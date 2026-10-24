"""실제 localhost HTTP의 독립 SigV4 검사·PUT/GET 객체 무결성 계약."""

import asyncio
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from krits import FileAttachment, FileStore, KritsIntegrityError
from krits.s3 import S3Config, S3Store

pytestmark=pytest.mark.live


@pytest.fixture
async def s3_server():
    objects={};requests=[];state={'corrupt':False}
    class Handler(BaseHTTPRequestHandler):
        def authorized(self,body):
            try:
                algorithm,fields=self.headers['Authorization'].split(' ',1)
                parts=dict(part.strip().split('=',1) for part in fields.split(','))
                credential=parts['Credential'].split('/');date,region,service,ending=credential[1:]
                assert algorithm=='AWS4-HMAC-SHA256' and credential[0]=='local-access'
                assert region=='us-east-1' and service=='s3' and ending=='aws4_request'
                names=parts['SignedHeaders'].split(';')
                canonical_headers=''.join(name+':'+ ' '.join(self.headers[name].split())+'\n' for name in names)
                payload=hashlib.sha256(body).hexdigest()
                assert self.headers['x-amz-content-sha256']==payload
                canonical='\n'.join([self.command,self.path,'',canonical_headers,parts['SignedHeaders'],payload])
                scope='/'.join(credential[1:])
                text='\n'.join([algorithm,self.headers['x-amz-date'],scope,hashlib.sha256(canonical.encode()).hexdigest()])
                key=b'AWS4local-secret'
                for value in (date,region,service,ending):key=hmac.digest(key,value.encode(),'sha256')
                return hmac.compare_digest(hmac.new(key,text.encode(),hashlib.sha256).hexdigest(),parts['Signature'])
            except (ValueError,KeyError,AssertionError,AttributeError):return False
        def respond(self,body,status=200):
            self.send_response(status);self.send_header('Content-Length',str(len(body)))
            self.send_header('ETag','not-sha256');self.end_headers();self.wfile.write(body)
        def do_PUT(self):
            body=self.rfile.read(int(self.headers['Content-Length']));allowed=self.authorized(body)
            requests.append(('PUT',self.path,allowed))
            if not allowed:self.respond(b'',403);return
            objects[self.path]=body;self.respond(b'')
        def do_GET(self):
            allowed=self.authorized(b'');requests.append(('GET',self.path,allowed))
            if not allowed:self.respond(b'',403);return
            body=objects[self.path]
            if state['corrupt']:body=b'z'*len(body)
            self.respond(body)
        def log_message(self,*_args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    endpoint=f'http://127.0.0.1:{server.server_port}'
    try:yield endpoint,objects,requests,state
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();await asyncio.to_thread(thread.join)


async def test_real_s3_signed_stream_get_hash_and_corruption(s3_server,tmp_path):
    endpoint,objects,requests,state=s3_server
    data=bytes(range(256))*513;store=FileStore(tmp_path);temporary=store._temporary();temporary.write_bytes(data)
    attachment=FileAttachment('nodelink','1','1','file.zip','https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_1/1',len(data),{})
    try:stored=store._publish(temporary,attachment,hashlib.sha256(data).hexdigest(),len(data),'application/octet-stream')
    finally:temporary.unlink()
    config=S3Config(endpoint,'test-bucket','local-access','local-secret',allow_http=True)
    async with S3Store(config,max_rps=5) as remote:
        result=await remote.put_file(store,stored)
        assert objects['/test-bucket/'+result.key]==data and result.sha256==stored.sha256
        assert [method for method,_path,_allowed in requests]==['PUT','GET'] and all(allowed for _method,_path,allowed in requests)
        state['corrupt']=True
        with pytest.raises(KritsIntegrityError):await remote.put_file(store,stored)
    assert len(requests)==4 and await store.verify(stored)==stored
    print('실제 HTTP S3 계약',len(data),'bytes',len(requests),'전송·독립서명·GET 손상검출')
