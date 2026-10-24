"""실제 Chromium과 로컬 서버 카운터로 전송 예산·캐시·동일 조회 공유를 검증한다."""

import asyncio
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import os
import threading
import time
from urllib.parse import urlsplit

import pytest
from krits import AsyncTokenBucket,KritsClient,KritsAccessError,KritsRateLimitError

pytestmark=pytest.mark.live


@pytest.fixture
async def load_server(monkeypatch):
    requests=[];posts=[];status=[200,200]
    valid=(Path(__file__).parent/'fixtures/events.json').read_bytes()
    html=b'<!doctype html><link rel="icon" href="data:,"><title>ITS '+ '국가교통정보센터'.encode()+b'</title><script src="/asset.js"></script><div id="map"></div>'
    script=b"fetch('/map/getMarkers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body:{data:{type:'',keyword:''}}})});"
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path,time.monotonic()))
            self.send_response(status[1] if self.path=='/asset.js' else 200)
            self.send_header('Content-Type','text/javascript' if self.path=='/asset.js' else 'text/html; charset=utf-8')
            self.end_headers()
            try:self.wfile.write(script if self.path=='/asset.js' else html)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            requests.append((self.path,time.monotonic()));posts.append(status[0])
            self.send_response(status[0]);self.send_header('Content-Type','application/json')
            self.end_headers()
            try:self.wfile.write(valid if status[0]==200 else b'{}')
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def log_message(self,*_args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    authority=f'127.0.0.1:{server.server_port}'
    monkeypatch.setattr('krits.client.BASE_URL','http://'+authority)
    monkeypatch.setattr('krits._browser._allowed_resource',lambda url,kind:urlsplit(url).netloc==authority
                        and kind.lower() in {'document','script','stylesheet','xhr','fetch'})
    try:yield requests,posts,status
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();await asyncio.to_thread(thread.join)


async def test_real_wire_budget_is_shared_between_clients_and_includes_scripts(load_server):
    requests,posts,_status=load_server
    bucket=AsyncTokenBucket(2,capacity=1)
    options={'timeout':30,'rate_limiter':bucket,'executable_path':os.getenv('KRITS_CHROMIUM_EXECUTABLE')}
    async with KritsClient(**options) as a,KritsClient(**options) as b:
        result=await asyncio.gather(a.get_events(),b.get_events())
    assert all(r.items for r in result) and posts==[200,200]
    assert sum(path=='/asset.js' for path,_stamp in requests)==2
    intervals=[b[1]-a[1] for a,b in zip(requests,requests[1:])]
    assert len(intervals)>=5 and min(intervals)>=0.40
    print('공유 전송',len(requests),'최소 간격',round(min(intervals),3),'초')


async def test_real_same_query_one_post_cache_hit_zero_and_explicit_refresh(load_server):
    _requests,posts,_status=load_server
    async with KritsClient(timeout=30,max_rps=50,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        a,b=await asyncio.gather(c.get_events(),c.get_events(road_type=None))
        assert posts==[200] and a.collected_at==b.collected_at
        await c.get_events();assert posts==[200]
        c.clear_cache();await c.get_events();assert posts==[200,200]
    print('동일 조회 공유1회·캐시 적중0회·명시 재조회1회')


@pytest.mark.parametrize('status_code',[401,403,429])
async def test_denial_is_shared_once_without_retry_or_success_cache(load_server,status_code):
    _requests,posts,status=load_server;status[0]=status_code
    async with KritsClient(timeout=30,max_rps=50,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        results=await asyncio.gather(c.get_events(),c.get_events(),return_exceptions=True)
        expected=KritsRateLimitError if status_code==429 else KritsAccessError
        assert all(isinstance(r,expected) for r in results) and posts==[status_code]
        assert not c._query_cache._entries


@pytest.mark.parametrize('status_code',[401,403,429])
async def test_asset_denial_stops_before_data_post(load_server,status_code):
    requests,posts,status=load_server;status[1]=status_code
    async with KritsClient(timeout=15,max_rps=5,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        with pytest.raises(KritsRateLimitError if status_code==429 else KritsAccessError):
            await c.get_events()
    assert not posts and [path for path,_stamp in requests]==['/map/outbreak','/asset.js']
