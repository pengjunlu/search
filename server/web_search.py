import asyncio
import langchain
import numpy as np
import os
import json

from langchain.schema import Document
from contextlib import asynccontextmanager
from datetime import datetime
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableParallel, RunnableLambda, RunnableBranch, RunnablePassthrough, RunnableSequence
from search_engine import SessionPool, SearxngSearchOptions, search_searxng


class EventEmitter:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.done = asyncio.Event()

    def emit(self, event, data=None):
        # prevent new messages once done.
        if self.done.is_set(): return

        self.queue.put_nowait((event, data))
        if event == 'end': self.done.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.done.is_set() and self.queue.empty():
            raise StopAsyncIteration

        event, data = await self.queue.get()
        return event, data

    def __call__(self, timeout=None):
        return TimeoutEventEmitter(self, timeout)


class TimeoutEventEmitter:
    def __init__(self, emitter, timeout):
        self.emitter = emitter
        self.timeout = timeout

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            if self.timeout is not None:
                result = await asyncio.wait_for(
                    self.emitter.__anext__(),
                    timeout=self.timeout
                )
            else:
                result = await self.emitter.__anext__()
            return result

        except asyncio.TimeoutError:
            # add 'end' messages into the queue.
            self.emitter.emit('end')

            # return timeout message to caller.
            return ('error', {'data':'Timeout', 'key':'CHAIN_ERROR'})

        except StopAsyncIteration:
            raise


def create_query_rewrite_chain(llm, prompts, parser):
    # input: {'query': query, 'chat_history':history}
    prompt = ChatPromptTemplate.from_messages([
        ('system', prompts['qrewrite']),
        MessagesPlaceholder(variable_name='chat_history'),
        ('user', '{query}')
    ])

    return prompt | llm | parser


def create_retrieve_documents_chain(search_pool, llm, embeddings):
    #1. get _search function with query as input.
    #   input: query
    #   output: {query: query, results: [SearxngSearchResult]}
    async def _search(query):
        searxng_url = os.getenv('SEARXNG_URL')
        opts = SearxngSearchOptions(language='en')
        response = await search_searxng(search_pool, searxng_url, query, opts)

        documents = []
        for result in response['results']:
            doc = Document(
                page_content = result.content,
                metadata={
                    'url' : result.url,
                    'title': result.title,
                    **({'img_src': result.img_src}
                       if hasattr(result, 'img_src') and result.img_src is not None
                       else {})
                }
            )
            documents.append(doc)

        return {'query': query, 'results': documents}


    #2. get _embedding function with query and docs as input.
    #   input: {query, [SearxngSearchResult]}
    #   output: [SearxngSearchResult].
    async def _rerank_docs(inputs):
        query = inputs['query']
        docs = inputs['results']

        docs_with_content = [
            doc
            for doc in docs
            if doc.page_content and len(doc.page_content) > 0
        ]
        if len(docs_with_content) == 0: return []

        #2.1 compute embeddings.
        docs_content = [doc.page_content for doc in docs_with_content]
        all_texts = [query] + docs_content
        embed = await embeddings.aembed_documents(all_texts)

        query_embed = embed[0]
        doc_embeds = embed[1:]

        #2.2 compute query and docs similarity
        def compute_similarity(vec1, vec2):
            return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

        similarity = [{
                'index': i,
                'similarity': compute_similarity(query_embed, doc_embed)
            }
            for i, doc_embed in enumerate(doc_embeds)
        ]

        #2.3 rerank based on similarity.
        sorted_docs = sorted(similarity, key=lambda x: x['similarity'], reverse=True)
        filtered_docs = [
            docs_with_content[sim['index']]
            for sim in sorted_docs
            if sim['similarity'] > 0.5
        ][:15]

        return filtered_docs

    #3. organize documents as 'index: doc\n' format.
    #   input: [SearxngSearchResult]
    #   output: format string
    async def process_docs(docs) :
        processed_docs = '\n'.join(
            f'{index+1}. {doc.page_content}'
            for index, doc in enumerate(docs)
        )
        return processed_docs

    return RunnableLambda(_search).with_config(run_name='Search') | \
           RunnableLambda(_rerank_docs).with_config(run_name='RetrieveDocuments') | \
           RunnableLambda(process_docs).with_config(run_name='Process')


def create_sensitive_chain():
    return RunnableLambda(lambda x: f'No support for sensitive query {x}')


def create_summarize_chain(llm, parser, prompts):
    # input: {'query': query, 'chat_history':history, 'context':process_docs}
    prompt = ChatPromptTemplate.from_messages([
        ('system', prompts['summarize']),
        MessagesPlaceholder(variable_name='chat_history'),
        ('user', '{query}')
    ])

    return (prompt | llm | parser).with_config(run_name = 'Summarize')
 

def create_workflow_chain(prompts, llm, embeddings, parser, search_pool):
    qrewrite_chain = create_query_rewrite_chain(llm, prompts, parser)
    retrieve_chain = create_retrieve_documents_chain(search_pool, llm, embeddings)
    summarize_chain = create_summarize_chain(llm, parser, prompts)
    sensitive_chain = create_sensitive_chain()

    async def get_context(x):
        if x['qresult'] == 'not_needed':
            return ''
        return await retrieve_chain.ainvoke(x['qresult'])

    context_chain = RunnableBranch(
        (lambda x: x['qresult'] == 'not_needed', lambda _: ''),
        RunnableSequence(
            RunnableLambda(lambda x: x['qresult']),
            retrieve_chain,
        )
    )

    initial_chain = RunnableParallel(
        query=lambda x: x['query'],
        chat_history=lambda x: x['chat_history'],
        qresult=qrewrite_chain
    ).with_config(run_name='InitialChain')

    branch_chain = RunnableBranch(
        (lambda x: x['qresult'] == 'sensitive', sensitive_chain),
        RunnablePassthrough.assign( context=context_chain ) | summarize_chain
    )

    final_chain = initial_chain | branch_chain

    return final_chain


async def run_web_search(emitter, stream):
    async for event in stream:
        if event['event'] == 'on_chain_end' and \
           event['name'] == 'RetrieveDocuments':
           emitter.emit(
               'data',
               {'type': 'sources', 'data': event['data']['input']['results']}
           )
            
        if event['event'] == 'on_chain_stream' and \
           event['name'] == 'Summarize':
           emitter.emit(
               'data',
               {'type': 'response', 'data': event['data']['chunk']}
           )
            
        if event['event'] == 'on_chain_end' and \
           event['name'] == 'Summarize':
           emitter.emit('end', {'type': 'end', 'data': {}})


async def web_search(query, history, llm, embeddings, prompts, parser, search_pool):
    main_chain = create_workflow_chain(
        prompts,
        llm,
        embeddings,
        parser,
        search_pool
    )

    emitter = EventEmitter()
    async def execute_search():
        try:
            request = {'query': query, 'chat_history': history}
            stream = main_chain.astream_events(request, version="v1")
            await run_web_search(emitter, stream)
        except Exception as e:
            emitter.emit('error', {'data': f'{str(e)}'})
        finally:
            emitter.emit('end')
    asyncio.create_task(execute_search())

    return emitter
