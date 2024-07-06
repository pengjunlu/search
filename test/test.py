import asyncio
import json
import web_search
from provider import Provider
from server import handle_connection

class MockWebSocket:
    def __init__(self, messages, raise_exception=False):
        self.messages = messages
        self.raise_exception = raise_exception

    async def __aiter__(self):
        for message in self.messages:
            if self.raise_exception:
                raise ConnectionClosed(1000, "Connection closed")
            yield message

    async def send(self, message):
        parsed_data = json.loads(message)
        if parsed_data['type'] == 'messageEnd':
            print()
        elif parsed_data['type'] == 'sources':
            #print(parsed_data['data'], end='', flush=True)
            #print()
            print(message)
        else:
            print(parsed_data['data'], end='', flush=True)

async def main():
    messages = [
        json.dumps({
            'type': 'message',
            'content': '世界上10个公认好看的女明星有谁？',
            'copilot': False,
            'focusMode':'webSearch',
            'history':[]
        }),
    ]
    ws = MockWebSocket(messages)

    provider = Provider()
    #1. test websocket process
    await handle_connection(ws, '/')

    #2. test runner name.
    #chain = web_search.create_retrieve_documents_chain(
    #    provider.search_pool(),
    #    provider.llm(),
    #    provider.embeddings()
    #)

    #async for event in chain.astream_events('hello world', version='v1'):
    #    print(event)

    provider.release()

if __name__ == "__main__":
    asyncio.run(main())
