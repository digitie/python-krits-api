"""실제 공개 화면에서 CCTV·우회·도시간 메타데이터를 검증한다."""

import os
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import pytest
from krits import KritsAccessError, KritsClient, KritsRateLimitError

pytestmark = pytest.mark.live


async def test_live_cctv_metadata():
    async with KritsClient(timeout=60, executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        result = await c.search_cctvs('서울')
    assert result.items and not result.complete
    assert all(x.cctv_id and x.name for x in result.items)
    assert result.scope['content'] == 'metadata'
    print('CCTV', result.collected_at.isoformat(), len(result.items))


async def test_live_detour_catalog_and_both_directions():
    async with KritsClient(timeout=60, executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        roads = await c.list_detour_roads()
        result = await c.get_detours(roads.items[0].road_number)
    assert result.items and {d.direction for d in result.items} == {'1', '2'}
    assert all(d.section_id and d.detour_id and d.main_time_seconds >= 0 for d in result.items)
    print('우회', result.collected_at.isoformat(), len(roads.items), len(result.items))


@pytest.mark.parametrize('origin', ['서울', '대전'])
async def test_live_travel_times(origin):
    async with KritsClient(timeout=60, executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        origins = await c.list_travel_origins()
        result = await c.get_travel_times(origin)
        async with c._browser.operation() as page:
            await page.locator('.region_list li:not(:first-child)').first.wait_for(state='attached')
            rendered = await page.locator('.region_list').inner_text()
    assert origin in origins.items and result.items and not result.complete
    for item in result.items:
        assert item.origin == origin and item.group_id and item.destination in rendered
        hours, minutes = divmod(int(item.minutes), 60)
        assert f'{minutes}분' in rendered or minutes == 0
        if hours: assert f'{hours}시간' in rendered
    print('도시간', result.collected_at.isoformat(), origin, len(result.items))


@pytest.mark.parametrize('status', [401, 403, 429])
@pytest.mark.parametrize('method', ['get_travel_times', 'list_travel_origins'])
async def test_initial_widget_denial_never_selects_again(monkeypatch, status, method):
    """초기 거부 후 change에는 정상 자료를 주더라도 추가 요청 없이 중단한다."""
    observed = []
    valid = (Path(__file__).parent / 'fixtures' / 'travel.json').read_bytes()
    html = '''<!doctype html><title>ITS 국가교통정보센터</title><div id="map"></div>
    <div class="region_list"><div class="select"><select onchange="send(this.value)">
    <option value="서울">서울</option><option value="대전">대전</option></select></div></div>
    <script>function send(city) {return fetch('/map/getCityReqTimeByGroup', {method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({body:{data:{grpIds:city}}})});}
    send('서울');</script>'''.encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers();self.wfile.write(html)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            code = status if data['body']['data']['grpIds'] == '서울' else 200
            observed.append(code)
            self.send_response(code);self.send_header('Content-Type', 'application/json')
            self.end_headers();self.wfile.write(b'{}' if code != 200 else valid)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    authority = f'127.0.0.1:{server.server_port}'
    monkeypatch.setattr('krits.client.BASE_URL', 'http://' + authority)
    monkeypatch.setattr('krits._browser._allowed_resource', lambda url, kind: urlsplit(url).netloc == authority)
    try:
        async with KritsClient(timeout=15, executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
            with pytest.raises(KritsRateLimitError if status == 429 else KritsAccessError):
                await getattr(c, method)(*(['대전'] if method == 'get_travel_times' else []))
        assert observed == [status]
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();await asyncio.to_thread(thread.join)
