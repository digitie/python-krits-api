"""실제 Chromium으로 파일 목록과 DOM 첨부만 확인한다. 대용량 전송은 하지 않는다."""

from datetime import datetime, timedelta
import os
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import pytest
from krits import KritsAccessError, KritsClient, KritsRateLimitError

pytestmark = pytest.mark.live


@pytest.mark.parametrize('kind', ['traffic', 'event', 'vms', 'weakSection'])
async def test_live_public_file_catalog(kind):
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    kwargs = {} if kind == 'weakSection' else {'start_date': today-timedelta(days=3), 'end_date': today}
    async with KritsClient(timeout=90, executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        result = await c.list_data_files(kind, **kwargs)
    assert result.items and not result.complete and result.scope['service'] == kind
    assert all(x.name and x.download_url.startswith('https://www.its.go.kr/') for x in result.items)
    if kind == 'weakSection':
        assert all(x.size_bytes is None and x.file_id is None for x in result.items)
    else:
        assert all(x.file_id and x.attachment_id is not None and x.size_bytes > 0 for x in result.items)
    print('파일 목록', result.collected_at.isoformat(), kind, len(result.items), [x.name for x in result.items])


async def test_live_empty_period_is_explicit_empty_array():
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    async with KritsClient(timeout=90, executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        result = await c.list_data_files('event', start_date=today+timedelta(days=10), end_date=today+timedelta(days=10))
    assert result.items == () and not result.complete


@pytest.mark.parametrize('initial_status', [None, 401, 403, 429])
async def test_initial_file_request_is_optional_but_denial_stops_search(monkeypatch, initial_status):
    """초기 요청 없음은 허용하고 초기 거부 뒤 기간 조회 재시도는 막는다."""
    observed = []
    valid = (Path(__file__).parent / 'fixtures' / 'files-event.json').read_bytes()
    html = '''<!doctype html><title>ITS 국가교통정보센터</title><h2 id="moveData">Data File</h2>
    <input id="inp_trafficDate"><input id="inp_trafficDate_endDate">
    <input type="submit" value="조회" onclick="pages.getDataFile(this)"><div id="data_file_list_result"></div>
    <script>const pages={getDataFile:()=>send(false)};
    async function send(initial) {
      const r=await fetch('/opendata/getTestDataFileList',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({body:{data:{searchType:-1,workingDirectory:'event',
      startDate:initial?'initial':document.querySelector('#inp_trafficDate').value.replaceAll('.','-'),
      endDate:initial?'initial':document.querySelector('#inp_trafficDate_endDate').value.replaceAll('.','-')}}})});
      if(r.status!==200)return;const d=await r.json();
      document.querySelector('#data_file_list_result').innerHTML=d.body.data.fileVOList.map(x=>
      `<a id="${x.fileId}" title="${x.fileStreNm}" href="/opendata/fileDownload/event/${x.workingDirectory}/${x.fileStreNm}">파일</a>`).join('');
    }
    INITIAL
    </script>'''.replace('INITIAL', 'send(true);' if initial_status is not None else '').encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers();self.wfile.write(html)

        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))['body']['data']
            status=initial_status if data['startDate']=='initial' else 200
            observed.append(status)
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.end_headers();self.wfile.write(valid if status==200 else b'{}')

        def log_message(self,*_args):
            pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    authority=f'127.0.0.1:{server.server_port}'
    monkeypatch.setattr('krits.client.BASE_URL','http://'+authority)
    monkeypatch.setattr('krits._browser._allowed_resource',lambda url,kind:urlsplit(url).netloc==authority)
    try:
        async with KritsClient(timeout=15,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
            kwargs={'start_date':datetime(2026,10,22).date(),'end_date':datetime(2026,10,23).date()}
            if initial_status is None:
                result=await c.list_data_files('event',**kwargs)
                assert len(result.items)==2
            else:
                with pytest.raises(KritsRateLimitError if initial_status==429 else KritsAccessError):
                    await c.list_data_files('event',**kwargs)
        assert observed==[200 if initial_status is None else initial_status]
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();await asyncio.to_thread(thread.join)
