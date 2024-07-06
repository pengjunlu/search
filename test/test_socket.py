import asyncio
import websockets
import json

async def test_websocket_server():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        # 测试消息1
        message1 = {
            'type': 'message',
            'content': 'hello',
            'copilot': False,
            'focusMode': 'webSearch',
            'history': []
        }
        await send_and_receive(websocket, message1)

        # 测试消息2
        message2 = {
            'type': 'message',
            'content': '世界上10个公认好看的女明星有谁？',
            'copilot': False,
            'focusMode': 'webSearch',
            'history': []
        }
        await send_and_receive(websocket, message2)

async def send_and_receive(websocket, message):
    print(f"Sending message: {message['content']}")
    await websocket.send(json.dumps(message))
    
    while True:
        response = await websocket.recv()
        parsed_response = json.loads(response)
        
        if parsed_response['type'] == 'messageEnd':
            break
        elif parsed_response['type'] == 'sources':
            print(f"{parsed_response['data']}")
        else:
            print(f"{parsed_response['data']}", end='', flush=True)
    
    print("\n" + "-"*50)

async def main():
    try:
        await test_websocket_server()
    except websockets.exceptions.ConnectionClosedError:
        print("Connection to the server was closed unexpectedly.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
