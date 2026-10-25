"""실제 Chromium에서 예측 단계별 거부와 추가 조회 중단을 검증한다."""

import asyncio
from datetime import date,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

import pytest

from krits import KritsAccessError,KritsClient,KritsRateLimitError

pytestmark=pytest.mark.live


@pytest.mark.parametrize("stage",["roads","sections","links"])
@pytest.mark.parametrize("status",[401,403,429])
async def test_forecast_denial_stops_at_first_failed_stage(monkeypatch,stage,status):
    base=Path(__file__).parent/'fixtures'
    payloads={k:json.loads((base/f'forecast-{k}.json').read_text(encoding='utf8')) for k in ('roads','sections','links')}
    endpoints={'roads':'/map/getMainToDetourRoads','sections':'/map/getMainToDetourSectionsByRoad','links':'/map/getMainToDetourSection'}
    observed=[]
    roads=payloads['roads']['body']['data']['SECTIONS']['LIST']
    rows=''.join(f'<li class="dep1"><div class="title_box"><a class="title"><span class="road">{r["ROAD_NO"]}</span>{r["ROAD_NM"]}</a></div></li>' for r in roads)
    html=('''<!doctype html><title>우회도로 | ITS 국가교통정보센터</title><link rel="icon" href="data:,">
    <div id="map"></div><div class="fc_box">'''+rows+'''</div><script id="tmpl_route_list" type="text/plain">template</script>
    <input id="inp_fcDate"><button role="tab">예측정보</button><script>
    function initDateButton() {}
    window.jQuery=()=>({datepicker:(_action,key)=>{const d=new Date();if(key==='maxDate')d.setDate(d.getDate()+6);return d;}});
    function ajaxRequest(o){return fetch(o.url,{method:'POST',headers:{'Content-Type':'application/json'},body:o.data})
      .then(r=>r.json()).then(o.callBack);}
    ajaxRequest({url:'/map/getMainToDetourRoads',data:JSON.stringify({body:{data:{type:'fc',sctnTyCode:'EX'}}}),callBack:()=>{}});
    </script>''').encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers()
            try:self.wfile.write(html)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def do_POST(self):
            size=int(self.headers['Content-Length']);self.rfile.read(size)
            kind=next(k for k,v in endpoints.items() if self.path==v)
            observed.append(kind)
            response_status=status if kind==stage else 200
            self.send_response(response_status);self.send_header('Content-Type','application/json');self.end_headers()
            try:self.wfile.write(json.dumps(payloads[kind] if response_status==200 else {'header':{'state':'ERROR'}}).encode())
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

        def log_message(self,*_args):pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    authority=f'127.0.0.1:{server.server_port}'
    monkeypatch.setattr('krits.client.BASE_URL','http://'+authority)
    monkeypatch.setattr('krits._browser._allowed_resource',lambda url,kind:urlsplit(url).netloc==authority)
    error=KritsRateLimitError if status==429 else KritsAccessError
    try:
        async with KritsClient(executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE'),timeout=15) as client:
            with pytest.raises(error):
                await client.get_forecast_links('1','1','1',forecast_date=date.today()+timedelta(days=1),hour=12)
        assert observed==list(endpoints)[:list(endpoints).index(stage)+1]
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();worker.join(timeout=5)
