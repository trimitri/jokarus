"""Test the `websockets` package."""

import asyncio

import websockets

URL = 'ws://menlo_b:8000'
SILENT_URL = 'ws://echo.websocket.org'


async def open_and_wait():
    _ = await websockets.connect(URL)
    while True:
        await asyncio.sleep(3)
        print("Sleeping.")

if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(open_and_wait())
