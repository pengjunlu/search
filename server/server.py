# Copyright @Jeff
#
# File continas web server logic to expose search api.

import asyncio
import websockets
import web_search

from provider import Provider
from message_handler import MessageHandler

async def handle_connection(websocket, path):
    try:
        async for message in websocket:
            provider = Provider()
            handler = MessageHandler(websocket, provider, web_search.web_search)
            await handler.handle_message(message)

    except websockets.ConnectionClosed:
        print("client disconnected")

    finally:
        pass

async def main():
    # initialize it here to avoid low speed for first visit.
    provider = Provider()

    server = await websockets.serve(handle_connection, "localhost", 3001)
    print("WebSocket server started on ws://localhost:3001")
    await server.wait_closed()

    # close all the resources.
    await provider.release()

if __name__ == "__main__":
    asyncio.run(main())
