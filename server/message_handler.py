# Copyright @Jeff
#
# file continas the logic to handle websocket request and response.
# The input message contains:
#
# type(string): currently only message support
# content(string): user query
# copilot: boolean;
# focusMode(string): currently only webSearch support
# history(Array<[string, string]>): history.


import asyncio
import json
import random
import string
import traceback
import uuid
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser

class MessageHandler:
    def __init__(self, websocket, provider, handle_func):
        self.ws = websocket
        self.llm = provider.llm() 
        self.embeddings = provider.embeddings()
        self.prompts = provider.prompts()
        self.search_pool = provider.search_pool()
        self.handle_func = handle_func


    def document_to_dict(self, doc):
        metadata = {
            'title': doc.metadata.get('title', ''),
            'url': doc.metadata.get('url', ''),
        }
    
        if 'img_src' in doc.metadata:
            metadata['img_src'] = doc.metadata['img_src']
    
        return {
            'pageContent': doc.page_content,
            'metadata': metadata
        }


    def transform_documents(self, documents):
        return [self.document_to_dict(doc) for doc in documents]


    async def handle_message(self, message):
        try:
            parsed_message = json.loads(message)
            message_id = str(uuid.uuid4())[:7]

            if not parsed_message.get('content'):
                error = json.dumps({
                    'type': 'error',
                    'data': 'Invalid message format',
                    'key': 'INVALID_FORMAT',
                })
                await self.ws.send(error)
                return

            if parsed_message['type'] != 'message':
                error = json.dumps({
                    'type': 'error',
                    'data': 'Invalid message type',
                    'key': 'INVALID_MESSAGE_TYPE',
                })
                await self.ws.send(error)
                return

            if parsed_message['focusMode'] != 'webSearch':
                error = json.dumps({
                    'type': 'error',
                    'data': 'Invalid focus mode',
                    'key': 'INVALID_FOCUS_MODE',
                })
                await self.ws.send(error)
                return


            history = [
                HumanMessage(content=msg[1])
                if msg[0] == 'human' else AIMessage(content=msg[1])
                for msg in parsed_message['history']
            ]

            emitter = await self.handle_func(
                parsed_message['content'],
                history,
                self.llm,
                self.embeddings,
                self.prompts,
                StrOutputParser(),
                self.search_pool
            )

            await self.process_emit_event(emitter, message_id)

        except Exception as err:
            traceback.print_exc()
            error = json.dumps({
                'type': 'error',
                'data': 'Invalid message format',
                'key': 'INVALID_FORMAT',
            })
            await self.ws.send(error)


    async def process_emit_event(self, emitter, message_id):
        async for event, data in emitter(timeout=60):
            # end message.
            if event == 'end':
                await self.ws.send(json.dumps({
                    'type': 'messageEnd',
                    'messageId': message_id
                }))
                continue

            # error message.
            if event == 'error':
                await self.ws.send(json.dumps({
                    'type': 'error',
                    'data': data['data'],
                    'key':'CHAIN_ERROR'
                }))
                continue
                
            # data message.
            if data['type'] == 'response':
                await self.ws.send(json.dumps({
                    'type': 'message',
                    'data': data['data'],
                    'messageId': message_id,
                }))
            elif data['type'] == 'sources':
                await self.ws.send(json.dumps({
                    'type': 'sources',
                    'data': self.transform_documents(data['data']),
                    'messageId': message_id,
                }, ensure_ascii=False, default=str))
