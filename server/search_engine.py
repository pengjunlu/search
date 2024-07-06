import requests
import asyncio
import aiohttp
from typing import List, Dict, Optional
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from dataclasses import dataclass

class SessionPool:
    def __init__(self, max_size: int = 10, timeout: float = 300):
        self.max_size = max_size
        self.timeout = timeout
        self.pool: List[aiohttp.ClientSession] = []
        self.in_use: Dict[aiohttp.ClientSession, float] = {}
        self.lock = asyncio.Lock()

    async def get_session(self) -> aiohttp.ClientSession:
        async with self.lock:
            current_time = asyncio.get_event_loop().time()
            for session in self.pool:
                if session not in self.in_use or (current_time - self.in_use[session]) > self.timeout:
                    self.in_use[session] = current_time
                    return session
            
            if len(self.pool) < self.max_size:
                session = aiohttp.ClientSession()
                self.pool.append(session)
                self.in_use[session] = current_time
                return session
            
            while True:
                await asyncio.sleep(0.1)
                for session in self.pool:
                    if session not in self.in_use or \
                       (current_time - self.in_use[session]) > self.timeout:
                        self.in_use[session] = current_time
                        return session

    async def release_session(self, session: aiohttp.ClientSession):
        async with self.lock:
            if session in self.in_use:
                del self.in_use[session]


    async def close(self):
        async with self.lock:
            for session in self.pool:
                await session.close()
            self.pool.clear()
            self.in_use.clear()


@asynccontextmanager
async def get_session_from_pool(pool: SessionPool):
    session = await pool.get_session()
    try:
        yield session
    finally:
        await pool.release_session(session)


class SearxngSearchOptions:
    def __init__(self, categories: Optional[List[str]] = None, 
                 engines: Optional[List[str]] = None, 
                 language: Optional[str] = None, 
                 pageno: Optional[int] = None):
        self.categories = categories
        self.engines = engines
        self.language = language
        self.pageno = pageno


@dataclass
class SearxngSearchResult:
    title: str
    url: str
    img_src: Optional[str] = None
    thumbnail_src: Optional[str] = None
    thumbnail: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    iframe_src: Optional[str] = None


async def search_searxng(pool, searxng_url, query, opts):
    params = {'q': query, 'format': 'json'}
    
    if opts:
        if opts.categories:
            params['categories'] = ','.join(opts.categories)
        if opts.engines:
            params['engines'] = ','.join(opts.engines)
        if opts.language:
            params['language'] = opts.language
        if opts.pageno:
            params['pageno'] = opts.pageno
    
    async with get_session_from_pool(pool) as session:
        url = f'{searxng_url}/search?{urlencode(params)}'
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()

    results = [
        SearxngSearchResult(
            title=result['title'],
            url=result['url'],
            img_src=result.get('img_src'),
            thumbnail_src=result.get('thumbnail_src'),
            thumbnail=result.get('thumbnail'),
            content=result.get('content'),
            author=result.get('author'),
            iframe_src=result.get('iframe_src')
        )
        for result in data.get('results', [])
    ]
    # suggestions = data.get('suggestions', [])
    
    return {'query': query, 'results': results}
