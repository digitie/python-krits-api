"""localhost 실제 Chromium의 파일 전송 오류/취소/제한 회귀."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
from urllib.parse import urlsplit

import pytest

from krits import FileAttachment, FileStore, KritsClient, KritsIntegrityError
from krits.exceptions import KritsAccessError, KritsNetworkError, KritsRateLimitError

pytestmark=pytest.mark.live


@pytest.fixture
async def file_server(monkeypatch):
    state={'status':200,'body':b'\x00\xff\x80test\r\n','length':None,'headers':{},'slow':False}
    seen=[];started=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(state['status']);self.send_header('Content-Type','application/octet-stream')
            if state['length'] is not None:self.send_header('Content-Length',str(state['length']))
            for key,value in state['headers'].items():self.send_header(key,value)
            self.end_headers()
            try:
                self.wfile.write(state['body']);self.wfile.flush();started.set()
                if state['slow']:
                    release.wait(20);self.wfile.write(b'end');self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        def log_message(self,*_args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    authority=f'127.0.0.1:{server.server_port}'
    # 공개 입력 URL 검사는 오프라인에서 검증한다. 이 회귀만 localhost로 origin을 바꾼다.
    monkeypatch.setattr('krits.files.validate_attachment',lambda *_args:None)
    monkeypatch.setattr('krits.client.validate_attachment',lambda *_args:None)
    monkeypatch.setattr('krits._browser._allowed_resource',lambda url,_kind:urlsplit(url).netloc==authority)
    attachment=FileAttachment('nodelink','1','1','file.csv',f'http://{authority}/file',None,{})
    try:yield state,seen,started,release,attachment
    finally:
        release.set();await asyncio.to_thread(server.shutdown);server.server_close();await asyncio.to_thread(thread.join)


def client():
    return KritsClient(timeout=10,max_rps=5,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE'))


async def test_real_binary_stream_without_content_length_and_reuse(file_server,tmp_path):
    state,seen,_started,_release,attachment=file_server;store=FileStore(tmp_path)
    async with client() as c:
        stored=await c.download_file(attachment,store,max_bytes=100)
        assert stored.path.read_bytes()==state['body']
        assert await c.download_file(attachment,store,max_bytes=100)==stored and seen==['/file']
    assert not list((tmp_path/'staging').iterdir())


@pytest.mark.parametrize('status,error',[(401,KritsAccessError),(403,KritsAccessError),
                                        (429,KritsRateLimitError),(302,KritsAccessError),(500,KritsNetworkError)])
async def test_real_status_does_not_retry_or_follow(file_server,tmp_path,status,error):
    state,seen,_started,_release,attachment=file_server
    state['status']=status;state['headers']={'Location':'/should-not-follow'}
    async with client() as c:
        with pytest.raises(error):await c.download_file(attachment,FileStore(tmp_path))
    assert seen==['/file'] and not (tmp_path/'manifests').exists()
    assert not list((tmp_path/'staging').iterdir())


@pytest.mark.parametrize('mode',['declared_limit','actual_limit','html','truncated'])
async def test_real_invalid_transfer_keeps_no_manifest(file_server,tmp_path,mode):
    state,seen,_started,_release,attachment=file_server
    if mode=='declared_limit':state['length']=1000
    if mode=='actual_limit':state['body']=b'x'*1000
    if mode=='html':state['body']=b'<html>login</html>'
    if mode=='truncated':state['length']=20
    async with client() as c:
        with pytest.raises((KritsIntegrityError,KritsNetworkError)):
            await c.download_file(attachment,FileStore(tmp_path),max_bytes=100)
    assert seen==['/file'] and not (tmp_path/'manifests').exists()
    assert not list((tmp_path/'staging').iterdir())


async def test_real_download_cancel_and_close_wait_for_cleanup(file_server,tmp_path):
    state,seen,started,release,attachment=file_server
    state['slow']=True;state['body']=b'x'*65536
    c=client();task=asyncio.create_task(c.download_file(attachment,FileStore(tmp_path)))
    try:
        assert await asyncio.to_thread(started.wait,5)
        task.cancel();await asyncio.sleep(0);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        await c.aclose()
        assert not c._file_tasks and c._browser._page is None
        assert not list((tmp_path/'staging').iterdir()) and not (tmp_path/'manifests').exists()
    finally:
        release.set();await c.aclose()
