# Copyright @Jeff
#
# File contains a singleton class to hold all required service.

import asyncio
from dotenv import load_dotenv
from search_engine import SessionPool
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings

class Provider:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Provider, cls).__new__(cls)
            cls._instance._initialize_services()
        return cls._instance

    def load_prompts(self, prompt_paths):
        prompts = {}
        for k, v in prompt_paths.items():
            with open(v, 'r', encoding='utf-8') as file:
                prompts[k] = file.read()

        return prompts

    def _initialize_services(self):
        load_dotenv()

        # 1. initialize various configs.
        prompt_paths = {
            'qrewrite': '../prompt/rephrase_query.txt',
            'summarize': '../prompt/summarize.txt'
        }
        self._prompts = self.load_prompts(prompt_paths)

        # maintain search/embedding session pool
        self._search_pool = SessionPool(max_size=5)

        # comfig llm and embeddings.
        self._llm = ChatOpenAI(model='gpt-3.5-turbo')
        self._embeddings = OpenAIEmbeddings(model='text-embedding-3-small')


    def llm(self):
        return self._llm

    def embeddings(self):
        return self._embeddings

    def prompts(self):
        return self._prompts

    def search_pool(self):
        return self._search_pool

    def release(self):
        asyncio.create_task(self._search_pool.close())
