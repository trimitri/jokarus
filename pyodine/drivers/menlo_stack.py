"""An interface wrapper to the Menlo stack websocket.

This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.
"""

import logging     # DEBUG, INFO, WARN, ERROR etc.
import asyncio     # Native python module, needed for websockets.
import websockets

async def hello_menlo():
    async with websockets.connect('ws://menlostack:8000') as ws:
        reply = await ws.recv()
        print(reply)

asyncio.get_event_loop().run_until_complete(hello_menlo())
