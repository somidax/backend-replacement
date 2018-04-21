from app.lib.threaded_wrap_async import threaded_wrap_async
import asyncio
from datetime import datetime
import logging
from web3 import Web3, HTTPProvider

from ..app import App
from ..config import ED_CONTRACT_ADDR, ED_CONTRACT_ABI
from ..src.contract_event_utils import block_timestamp

huey = App().huey
logger = logging.getLogger("tasks.update_order")
logger.setLevel(logging.DEBUG)

@huey.task()
@threaded_wrap_async
async def update_order_by_signature(order_signature):
    """
    Updates the fill of a single order given its signature.
    Arguments:
    order_signature: Order signature as a 0x-prefixed hex string
    """
    logger.debug("Update order by signature={}".format(order_signature))
    order = await fetch_order_by_signature(order_signature)
    await update_order(order)
    return None

@huey.task()
@threaded_wrap_async
async def update_orders_by_maker_and_token(maker_addr, token_addr, block_number):
    """
    Updates the fill of one or more orders given order maker and a token. The
    token may be on either side of the transaction.
    Arguments:
    marker_addr: Ethereum address of the order maker as a 0x-prefixed hex string
    token_addr: Address of the token on either side of the order as a 0x-prefixed hex string
    block_number: Limit updates to orders that expire after `block_number`
    """
    logger.debug("Update orders by maker={} and token={}, expires >= {}".format(maker_addr, token_addr, block_number))
    affected_orders = await fetch_affected_orders(maker_addr, token_addr, block_number)
    if len(affected_orders) > 0:
        logger.debug("updating up to %i orders", len(affected_orders))
        for order in affected_orders:
            await update_order(order)
    else:
        logger.warn("No orders found for maker=%s and token=%s", maker_addr, token_addr)
    return None

SELECT_ORDER_STMT = """
    SELECT *
    FROM orders
    WHERE signature = $1
"""
async def fetch_order_by_signature(signature):
    async with App().db.acquire_connection() as conn:
        return await conn.fetchrow(SELECT_ORDER_STMT, Web3.toBytes(hexstr=signature))

FETCH_AFFECTED_ORDERS_STMT = """
    SELECT *
    FROM orders
    WHERE "user" = $1
        AND ("token_give" = $2 OR "token_get" = $2)
        AND "expires" >= $3
"""
async def fetch_affected_orders(order_maker, coin_addr, expiring_at):
    async with App().db.acquire_connection() as conn:
        return await conn.fetch(
            FETCH_AFFECTED_ORDERS_STMT,
            Web3.toBytes(hexstr=order_maker),
            Web3.toBytes(hexstr=coin_addr),
            expiring_at)

UPDATE_ORDER_FILL_STMT = """
    UPDATE "orders"
    SET "amount_fill" = GREATEST("amount_fill", $1),
        "state" = (CASE
                    WHEN "state" IN ('FILLED'::orderstate, 'CANCELED'::orderstate) THEN "state"
                    WHEN ("amount_get" <= GREATEST("amount_fill", $1)) THEN 'FILLED'::orderstate
                    ELSE 'OPEN'::orderstate END),
        "updated"  = $2
    WHERE "signature" = $3
"""
async def update_order(order):
    contract = App().web3.eth.contract(ED_CONTRACT_ADDR, abi=ED_CONTRACT_ABI)

    maker = Web3.toHex(order["user"])
    signature = Web3.toBytes(order["signature"])
    updated_at = datetime.fromtimestamp(block_timestamp(App().web3, "latest"), tz=None)

    amount_fill = contract.call().orderFills(maker, signature)

    update_args = (amount_fill, updated_at, signature)
    async with App().db.acquire_connection() as conn:
        await conn.execute(UPDATE_ORDER_FILL_STMT, *update_args)
    logger.info("updated order signature=%s fill=%i", Web3.toHex(signature), amount_fill)
