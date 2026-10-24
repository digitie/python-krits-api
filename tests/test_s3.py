"""명시적 S3 설정·공식 SigV4 벡터·스트림 무결성·자원 회귀."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest

from krits import FileAttachment, FileStore, KritsClosedError, KritsIntegrityError
from krits.exceptions import KritsAccessError, KritsNetworkError, KritsRateLimitError
from krits.s3 import S3Config, S3Store, _chunks, _sign


@pytest.fixture
def stored(tmp_path):
    store=FileStore(tmp_path);data=b'x'*131073
    temp=store._temporary();temp.write_bytes(data)
    attachment=FileAttachment('nodelink','1','1','file.csv','https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_1/1',len(data),{})
    try:value=store._publish(temp,attachment,hashlib.sha256(data).hexdigest(),len(data),'text/csv')
    finally:temp.unlink()
    return store,value


def config(**kwargs):
    return S3Config(**{'endpoint_url':'https://storage.example','bucket':'test-bucket',
                       'access_key':'test-access','secret_key':'test-secret',**kwargs})


class ByteStream(httpx.AsyncByteStream):
    def __init__(self,data):self.data=data;self.closed=False
    async def __aiter__(self):
        for offset in range(0,len(self.data),32768):yield self.data[offset:offset+32768]
    async def aclose(self):self.closed=True


@pytest.mark.parametrize('kwargs',[
    {'endpoint_url':'http://storage.example'},{'endpoint_url':'http://127.0.0.1'},
    {'endpoint_url':'https://user:password@storage.example'}, {'endpoint_url':'https://storage.example/path'},
    {'endpoint_url':'https://storage.example?token=x'}, {'endpoint_url':'ftp://storage.example'},
    {'bucket':'../outside'}, {'bucket':'ab'}, {'bucket':'bad..bucket'},{'prefix':'../x'},
    {'region':'bad/region'}, {'access_key':''}, {'secret_key':'x\n'}, {'session_token':''}, {'allow_http':1},
    {'access_key':'bad key'}, {'access_key':'한글'}, {'session_token':'한글'},
])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):config(**kwargs)


def test_config_repr_hides_credentials_and_http_is_explicit_loopback():
    value=config(endpoint_url='http://127.0.0.1:9000',allow_http=True,session_token='test-token')
    assert all(secret not in repr(value) for secret in ('test-access','test-secret','test-token'))
    with pytest.raises(ValueError):config(endpoint_url='http://remote.example',allow_http=True)


def test_official_aws_s3_sigv4_get_vector():
    # AWS 문서의 공개 예제 자격정보이며 실계정 비밀값이 아니다.
    value=config(endpoint_url='https://examplebucket.s3.amazonaws.com',bucket='examplebucket',
                 access_key='AKIAIOSFODNN7EXAMPLE',secret_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')
    headers=_sign('GET','https://examplebucket.s3.amazonaws.com/test.txt',value,hashlib.sha256(b'').hexdigest(),
                  {'Range':'bytes=0-9'},now=datetime(2013,5,24,tzinfo=timezone.utc))
    assert headers['authorization'].endswith('Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41')


async def test_put_then_get_hash_verification_and_lazy_owned_close(stored):
    store,value=stored;requests=[];remote=[];responses=[]
    async def handler(request):
        requests.append(request)
        if request.method=='PUT':
            remote.append(await request.aread());return httpx.Response(200,stream=ByteStream(b''))
        stream=ByteStream(remote[-1]);responses.append(stream)
        return httpx.Response(200,headers={'Content-Length':str(value.size_bytes),'ETag':'not-a-sha256'},stream=stream)
    s3=S3Store(config(session_token='test-token'),max_rps=1000,transport=httpx.MockTransport(handler))
    assert s3._client is None
    async with s3:
        result=await s3.put_file(store,value)
        assert result.sha256==value.sha256 and result.key.endswith(value.sha256)
        assert remote==[value.path.read_bytes()]
        assert [request.method for request in requests]==['PUT','GET']
        assert requests[0].headers['x-amz-content-sha256']==value.sha256
        assert requests[0].headers['x-amz-security-token']=='test-token'
        assert responses[0].closed
    assert s3._client is None
    with pytest.raises(KritsClosedError):await s3.put_file(store,value)
    await s3.aclose()


@pytest.mark.parametrize('status,error',[(401,KritsAccessError),(403,KritsAccessError),(429,KritsRateLimitError),
                                        (302,KritsNetworkError),(500,KritsNetworkError)])
async def test_s3_status_no_redirect_no_retry(stored,status,error):
    store,value=stored;requests=[]
    def handler(request):requests.append(request);return httpx.Response(status,headers={'Location':'https://other.example/'},stream=ByteStream(b''))
    async with S3Store(config(),transport=httpx.MockTransport(handler)) as s3:
        with pytest.raises(error):await s3.put_file(store,value)
    assert len(requests)==1


@pytest.mark.parametrize('mode',['sha','long','short','length','encoding'])
async def test_remote_mismatch_is_not_accepted_as_etag_success(stored,mode):
    store,value=stored;streams=[]
    async def handler(request):
        if request.method=='PUT':await request.aread();return httpx.Response(200,stream=ByteStream(b''))
        raw=value.path.read_bytes();headers={'ETag':value.sha256}
        if mode=='sha':raw=b'z'*len(raw)
        if mode=='long':raw+=b'x'
        if mode=='short':raw=raw[:-1]
        if mode=='length':headers['Content-Length']='1'
        if mode=='encoding':headers['Content-Encoding']='gzip'
        stream=ByteStream(raw);streams.append(stream);return httpx.Response(200,headers=headers,stream=stream)
    async with S3Store(config(),max_rps=1000,transport=httpx.MockTransport(handler)) as s3:
        with pytest.raises(KritsIntegrityError):await s3.put_file(store,value)
    assert streams[0].closed


async def test_local_corruption_never_sends_and_chunk_boundaries(stored):
    store,value=stored;chunks=[chunk async for chunk in _chunks(value)]
    assert max(map(len,chunks))==65536 and len(chunks)==3
    value.path.write_bytes(b'broken')
    handler=AsyncMock()
    async with S3Store(config(),transport=httpx.MockTransport(handler)) as s3:
        with pytest.raises(KritsIntegrityError):await s3.put_file(store,value)
        assert s3._client is None
    handler.assert_not_awaited()
    with pytest.raises(KritsIntegrityError):[chunk async for chunk in _chunks(value)]


async def test_chunk_hash_mismatch(stored):
    _store,value=stored;value.path.write_bytes(b'y'*value.size_bytes)
    with pytest.raises(KritsIntegrityError):[chunk async for chunk in _chunks(value)]


async def test_s3_network_timeout_and_cancellation_close_stream(stored):
    store,value=stored;started=asyncio.Event();release=asyncio.Event()
    async def handler(request):started.set();await release.wait();raise httpx.ConnectError('test')
    async with S3Store(config(),timeout=.02,transport=httpx.MockTransport(handler)) as s3:
        with pytest.raises(KritsNetworkError):await s3.put_file(store,value)
    async with S3Store(config(),transport=httpx.MockTransport(handler)) as s3:
        task=asyncio.create_task(s3.put_file(store,value));await started.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task


def test_constructor_validation():
    with pytest.raises(ValueError):S3Store(None)
    with pytest.raises(ValueError):S3Store(config(),timeout=0)


async def test_cross_loop_rejected_before_network():
    s3=S3Store(config());s3._loop=object()
    with pytest.raises(RuntimeError):await s3.put_file(None,None)


async def test_close_repeated_cancel_while_waiting_active_put_completes_owned_cleanup(stored):
    store,value=stored;started=asyncio.Event();release=asyncio.Event()
    async def handler(request):
        if request.method=='PUT':
            await request.aread();started.set();await release.wait()
            return httpx.Response(200,stream=ByteStream(b''))
        return httpx.Response(200,stream=ByteStream(value.path.read_bytes()))
    s3=S3Store(config(),max_rps=1000,transport=httpx.MockTransport(handler))
    put=asyncio.create_task(s3.put_file(store,value));await started.wait();owned=s3._client
    close=asyncio.create_task(s3.aclose());await asyncio.sleep(0);close.cancel();await asyncio.sleep(0)
    close.cancel();await asyncio.sleep(0)
    assert not close.done() and not owned.is_closed
    with pytest.raises(KritsClosedError):await s3.put_file(store,value)
    release.set();assert (await put).sha256==value.sha256
    with pytest.raises(asyncio.CancelledError):await close
    assert s3._closed and owned.is_closed and s3._client is None
