"""다운로드 입력·CDP 경계·길이와 오류 응답 회귀."""

import asyncio
import base64
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from krits import FileAttachment, FileStore, KritsClient, KritsClosedError, KritsIntegrityError
from krits.exceptions import KritsAccessError, KritsNetworkError, KritsRateLimitError
from krits.files import _headers, validate_attachment
from playwright.async_api import Error as PlaywrightError


@pytest.fixture
def attachment():
    return FileAttachment('nodelink','001','1','내역서.csv',
                          'https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_001/1',None,{})


@pytest.mark.parametrize('url',[
    'https://www.its.go.kr.evil/opendata/nodelinkFileSDownload/DF_001/1',
    'https://www.its.go.kr:9443/opendata/nodelinkFileSDownload/DF_001/1',
    'http://www.its.go.kr/opendata/nodelinkFileSDownload/DF_001/1',
    'https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_001/1?key=x',
    'https://www.its.go.kr/opendata/nodelinkFileSDownload/../1',
    'https://www.its.go.kr/map/traffic',
])
def test_bad_download_url(attachment,url):
    with pytest.raises(ValueError):validate_attachment(replace(attachment,download_url=url),100)


@pytest.mark.parametrize('maximum',[0,-1,True,1.2])
def test_bad_maximum(attachment,maximum):
    with pytest.raises(ValueError):validate_attachment(attachment,maximum)


@pytest.mark.parametrize('field,value',[
    ('file_id',1),('attachment_id',''),('service',''),('name','x'*4097),
    ('size_bytes',True),('size_bytes',-1),
])
def test_bad_attachment(attachment,field,value):
    with pytest.raises(ValueError):validate_attachment(replace(attachment,**{field:value}),100)


def test_declared_over_maximum(attachment):
    with pytest.raises(KritsIntegrityError):validate_attachment(replace(attachment,size_bytes=101),100)


@pytest.mark.parametrize('status,error',[(401,KritsAccessError),(403,KritsAccessError),(429,KritsRateLimitError),
                                        (302,KritsAccessError),(500,KritsNetworkError),(None,KritsNetworkError)])
def test_response_status(attachment,status,error):
    with pytest.raises(error):_headers({'responseStatusCode':status},attachment,100)


@pytest.mark.parametrize('headers',[
    [('Content-Type','text/html')],[('Content-Type','application/json')],[('Content-Encoding','gzip')],
    [('Content-Length','-1')],[('Content-Length','101')],[('Content-Length','3'),('Content-Length','3')],
])
def test_bad_response_headers(attachment,headers):
    with pytest.raises(KritsIntegrityError):
        _headers({'responseStatusCode':200,'responseHeaders':[{'name':k,'value':v} for k,v in headers]},attachment,100)


async def simulate(browser,attachment,*,chunks=(b'a,b\n1,2\n',),status=200,headers=(),error=None):
    async def goto(url,**_kwargs):
        if url=='about:blank':return
        callback=browser.session.on.call_args.args[1]
        await callback({'requestId':'1','resourceType':'Document','request':{'url':url,'headers':{}}})
        await callback({'requestId':'1','resourceType':'Document','request':{'url':url},'responseStatusCode':status,
                        'responseHeaders':[{'name':k,'value':v} for k,v in headers]})
    index=0
    async def send(method,params=None):
        nonlocal index
        if method=='Fetch.takeResponseBodyAsStream':return {'stream':'stream'}
        if method=='IO.read':
            if error:raise error
            chunk=chunks[index];index+=1
            return {'data':base64.b64encode(chunk).decode(),'base64Encoded':True,'eof':index==len(chunks)}
        return {}
    browser.page.goto=AsyncMock(side_effect=goto);browser.session.send=AsyncMock(side_effect=send)


async def test_download_reuse_refresh_and_close_tracking(browser,tmp_path,attachment):
    await simulate(browser,attachment)
    store=FileStore(tmp_path)
    async with KritsClient() as client:
        first=await client.download_file(attachment,store)
        assert first.size_bytes==8 and first.path.read_bytes()==b'a,b\n1,2\n'
        requests=browser.page.goto.await_count
        assert await client.download_file(attachment,store)==first
        assert browser.page.goto.await_count==requests
        await simulate(browser,attachment,chunks=(b'new',))
        second=await client.download_file(attachment,store,refresh=True)
        assert second.sha256!=first.sha256 and len(await store.versions(attachment))==2
        assert not list((tmp_path/'staging').iterdir()) and not client._file_tasks
    with pytest.raises(KritsClosedError):await client.download_file(attachment,store)


@pytest.mark.parametrize('chunks,headers',[
    ((b'<ht',b'ml>login'),()),((b'\xef\xbb\xbf {"error":1}',),()),
    ((b'',),()),((b'1234',),[('Content-Length','5')]),((b'x'*65537,),()),
])
async def test_bad_body_cleans_temp_without_manifest(browser,tmp_path,attachment,chunks,headers):
    await simulate(browser,attachment,chunks=chunks,headers=headers)
    async with KritsClient() as client:
        with pytest.raises(KritsIntegrityError):await client.download_file(attachment,FileStore(tmp_path))
    assert not list((tmp_path/'staging').iterdir()) and not (tmp_path/'manifests').exists()


async def test_download_input_before_browser_or_disk(browser,tmp_path,attachment):
    async with KritsClient() as client:
        with pytest.raises(ValueError):await client.download_file(attachment,FileStore(tmp_path),refresh=1)
        with pytest.raises(ValueError):await client.download_file(attachment,None)
    browser.manager.start.assert_not_awaited();assert list(tmp_path.iterdir())==[]


async def test_download_limit_and_declared_header_mismatch(browser,tmp_path,attachment):
    await simulate(browser,attachment,chunks=(b'x'*101,))
    async with KritsClient() as client:
        with pytest.raises(KritsIntegrityError):await client.download_file(attachment,FileStore(tmp_path),max_bytes=100)
    with pytest.raises(KritsIntegrityError):
        _headers({'responseStatusCode':200,'responseHeaders':[{'name':'Content-Length','value':'5'}]},
                 replace(attachment,size_bytes=4),100)


async def test_download_stream_error_preserves_old_version(browser,tmp_path,attachment):
    await simulate(browser,attachment)
    store=FileStore(tmp_path)
    async with KritsClient() as client:
        old=await client.download_file(attachment,store)
        await simulate(browser,attachment,error=PlaywrightError('disconnected'))
        with pytest.raises(KritsNetworkError):await client.download_file(attachment,store,refresh=True)
        assert await store.verify(old)==old
        with pytest.raises(KritsIntegrityError):await client.download_file(attachment,store,max_bytes=1)
    assert not list((tmp_path/'staging').iterdir())


async def test_client_close_waits_download_even_if_repeatedly_cancelled(browser,tmp_path,attachment,monkeypatch):
    started=asyncio.Event();release=asyncio.Event()
    async def download(*_args,**_kwargs):started.set();await release.wait();return 'result'
    monkeypatch.setattr('krits.client.download_file',download)
    client=KritsClient();task=asyncio.create_task(client.download_file(attachment,FileStore(tmp_path)))
    await started.wait();closing=asyncio.create_task(client.aclose());await asyncio.sleep(0)
    closing.cancel();await asyncio.sleep(0);closing.cancel();await asyncio.sleep(0)
    assert not closing.done()
    release.set();assert await task=='result'
    with pytest.raises(asyncio.CancelledError):await closing
    assert client._browser._closed


async def test_client_download_repeated_cancel_waits_cleanup(browser,tmp_path,attachment,monkeypatch):
    started=asyncio.Event();cleaning=asyncio.Event();release=asyncio.Event()
    async def download(*_args,**_kwargs):
        try:started.set();await asyncio.Event().wait()
        finally:cleaning.set();await release.wait()
    monkeypatch.setattr('krits.client.download_file',download)
    client=KritsClient();task=asyncio.create_task(client.download_file(attachment,FileStore(tmp_path)))
    await started.wait();task.cancel();await cleaning.wait();task.cancel();await asyncio.sleep(0)
    assert not task.done();release.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert not client._file_tasks;await client.aclose()


@pytest.mark.parametrize('data',[b'\xff\xfe<\x00h\x00t\x00m\x00l\x00>\x00',b'\xfe\xff\x00<\x00h'])
async def test_utf16_html_error_is_rejected(browser,tmp_path,attachment,data):
    await simulate(browser,attachment,chunks=(data,))
    async with KritsClient() as c:
        with pytest.raises(KritsIntegrityError):await c.download_file(attachment,FileStore(tmp_path))


async def test_refresh_revert_then_default_reuses_last_successful_observation(browser,tmp_path,attachment):
    store=FileStore(tmp_path)
    async with KritsClient() as c:
        await simulate(browser,attachment,chunks=(b'A',));a=await c.download_file(attachment,store)
        await simulate(browser,attachment,chunks=(b'B',));b=await c.download_file(attachment,store,refresh=True)
        assert a.sha256!=b.sha256
        await simulate(browser,attachment,chunks=(b'A',));assert await c.download_file(attachment,store,refresh=True)==a
        browser.page.goto.reset_mock()
        assert await c.download_file(attachment,store)==a
        browser.page.goto.assert_not_awaited()
        assert len(await store.versions(attachment))==2
