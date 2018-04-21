from datetime import datetime
import logging
from pprint import pprint
from web3 import Web3

from ..app import App
from app.src.contract_event_utils import block_timestamp
from app.src.order_enums import OrderSource, OrderState
from app.src.order_hash import make_order_hash
from app.src.utils import coerce_to_int, parse_insert_status
from ..tasks.update_order import update_orders_by_maker_and_token

ZERO_ADDR = "0x0000000000000000000000000000000000000000"

logger = logging.getLogger("contract_event_recorders")
logger.setLevel(logging.DEBUG)

async def process_trade(contract, event_name, event):
    logger.debug("received trade txid=%s", event["transactionHash"])
    did_insert = await record_trade(contract, event_name, event)

    if did_insert:
        logger.info("recorded trade txid=%s, logidx=%i",
                    event["transactionHash"],
                    coerce_to_int(event["logIndex"]))

        ##
        # Dispatch a background job to update potentially affected orders
        block_number = coerce_to_int(event["blockNumber"])
        # Order maker side is recorded in `get`
        order_maker = event["args"]["get"]
        if event["args"]["tokenGive"] != ZERO_ADDR:
            coin_addr = event["args"]["tokenGive"]
        else:
            coin_addr = event["args"]["tokenGet"]
        update_orders_by_maker_and_token(order_maker, coin_addr, block_number)
    else:
        logger.debug("duplicate trade txid=%s", event["transactionHash"])


INSERT_TRADE_STMT = """
    INSERT INTO trades
    (
        "block_number", "transaction_hash", "log_index",
        "token_give", "amount_give", "token_get", "amount_get",
        "addr_give", "addr_get", "date"
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ON CONFLICT ON CONSTRAINT index_trades_on_event_identifier DO NOTHING;
"""
async def record_trade(contract, event_name, event):
    block_number = coerce_to_int(event["blockNumber"])
    log_index = coerce_to_int(event["logIndex"])
    date = datetime.fromtimestamp(block_timestamp(App().web3, event["blockNumber"]), tz=None)

    insert_args = (
        block_number,
        Web3.toBytes(hexstr=event["transactionHash"]),
        log_index,
        Web3.toBytes(hexstr=event["args"]["tokenGive"]),
        event["args"]["amountGive"],
        Web3.toBytes(hexstr=event["args"]["tokenGet"]),
        event["args"]["amountGet"],
        Web3.toBytes(hexstr=event["args"]["give"]),
        Web3.toBytes(hexstr=event["args"]["get"]),
        date
    )

    async with App().db.acquire_connection() as connection:
        insert_retval = await connection.execute(INSERT_TRADE_STMT, *insert_args)
        _, _, did_insert = parse_insert_status(insert_retval)

    if did_insert:
        logger.debug("recorded trade txid=%s, logidx=%i", event["transactionHash"], log_index)

    return bool(did_insert)

async def record_deposit(contract, event_name, event):
    did_insert = await record_transfer("DEPOSIT", event)
    if did_insert:
        enqueue_order_update_for_transfer(event)
        logger.info("recorded deposit txid=%s, logidx=%i", event["transactionHash"], coerce_to_int(event["logIndex"]))
    return did_insert

async def record_withdraw(contract, event_name, event):
    did_insert = await record_transfer("WITHDRAW", event)
    if did_insert:
        enqueue_order_update_for_transfer(event)
        logger.info("recorded withdraw txid=%s, logidx=%i", event["transactionHash"], coerce_to_int(event["logIndex"]))
    return did_insert

INSERT_TRANSFER_STMT = """
    INSERT INTO transfers
    (
        "block_number", "transaction_hash", "log_index",
        "direction", "token", "user", "amount", "balance_after", "date"
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT ON CONSTRAINT index_transfers_on_event_identifier DO NOTHING;
"""
async def record_transfer(transfer_direction, event):
    block_number = coerce_to_int(event["blockNumber"])
    log_index = coerce_to_int(event["logIndex"])
    date = datetime.fromtimestamp(block_timestamp(App().web3, block_number), tz=None)

    insert_args = (
        block_number,
        Web3.toBytes(hexstr=event["transactionHash"]),
        log_index,
        transfer_direction,
        Web3.toBytes(hexstr=event["args"]["token"]),
        Web3.toBytes(hexstr=event["args"]["user"]),
        event["args"]["amount"],
        event["args"]["balance"],
        date
    )

    async with App().db.acquire_connection() as connection:
        insert_retval = await connection.execute(INSERT_TRANSFER_STMT, *insert_args)
        _, _, did_insert = parse_insert_status(insert_retval)

    return bool(did_insert)

def enqueue_order_update_for_transfer(event):
    """
    Enqueues a task to update orders' fill / available volume when a
    Deposit/Withdraw event occurs.
    """
    user_addr = event["args"]["user"]
    token_addr = event["args"]["token"]
    block_number = coerce_to_int(event["blockNumber"])

    update_orders_by_maker_and_token(user_addr, token_addr, block_number)

UPSERT_CANCELED_ORDER_STMT = """
    INSERT INTO orders
    (
        "source", "signature",
        "token_give", "amount_give", "token_get", "amount_get",
        "expires", "nonce", "user", "state", "v", "r", "s", "date",
        "amount_fill", "updated"
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
    ON CONFLICT ON CONSTRAINT index_orders_on_signature
        DO UPDATE SET
            "state" = $10, "amount_fill" = $15, "updated" = $16
            WHERE "orders"."signature" = $2
                AND "orders"."state" = 'OPEN'::orderstate
"""
async def record_cancel(contract, event_name, event):
    order = event["args"]
    order_maker = order["user"]
    signature = make_order_hash(order)
    date = datetime.fromtimestamp(block_timestamp(App().web3, event["blockNumber"]), tz=None)
    if "r" in order and order["r"] is not None:
        source = OrderSource.OFFCHAIN
    else:
        source = OrderSource.ONCHANIN

    upsert_args = (
        source.name,
        Web3.toBytes(hexstr=signature),
        Web3.toBytes(hexstr=order["tokenGive"]),
        order["amountGive"],
        Web3.toBytes(hexstr=order["tokenGet"]),
        order["amountGet"],
        order["expires"],
        order["nonce"],
        Web3.toBytes(hexstr=order["user"]),
        OrderState.CANCELED.name,
        int(order["v"]),
        Web3.toBytes(text=order["r"]),
        Web3.toBytes(text=order["s"]),
        date,
        order["amountGet"], # Contract updates orderFills to amountGet when trade is cancelled
        date
    )

    async with App().db.acquire_connection() as connection:
        upsert_retval = await connection.execute(UPSERT_CANCELED_ORDER_STMT, *upsert_args)
        _, _, did_upsert = parse_insert_status(upsert_retval)

    if did_upsert:
        logger.debug("recorded order cancel signature=%s", signature)

    return bool(did_upsert)
