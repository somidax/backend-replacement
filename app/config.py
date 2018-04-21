from os import environ

HTTP_PROVIDER_URL = environ.get("HTTP_PROVIDER_URL")
WS_PROVIDER_URL = environ.get("WS_PROVIDER_URL")

ED_CONTRACT_ADDR = '0x983293eb01740d9788bbdcfe3a29d1bf2fdfc47d'
with open('coinEstate.abi.json') as f:
    import json
    ED_CONTRACT_ABI = json.load(f)
ED_WS_SERVERS = [
  "wss://socket01.etherdelta.com/socket.io/?EIO=3&transport=websocket",
  "wss://socket02.etherdelta.com/socket.io/?EIO=3&transport=websocket",
  "wss://socket03.etherdelta.com/socket.io/?EIO=3&transport=websocket",
  "wss://socket04.etherdelta.com/socket.io/?EIO=3&transport=websocket",
  "wss://socket05.etherdelta.com/socket.io/?EIO=3&transport=websocket",
  "wss://socket06.etherdelta.com/socket.io/?EIO=3&transport=websocket",
]

POSTGRES_HOST = "postgres"
POSTGRES_DB = environ.get("POSTGRES_DB")
POSTGRES_USER = environ.get("POSTGRES_USER")
POSTGRES_PASSWORD = environ.get("POSTGRES_PASSWORD")

FRONTEND_CONFIG_FILE="https://raw.githubusercontent.com/somidax/coinEstate/master/config/main.json"
