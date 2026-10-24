"""키 없는 실제 Chromium에서 T003 공개 조회의 비어 있지 않은 계약을 검증한다."""

import math
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


@pytest.mark.parametrize("kind,direction", [("highway", "1"), ("highway", "2"), ("national", "3"), ("national", "4")])
async def test_live_road_catalog_and_traffic_both_directions(kind, direction):
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"), timeout=60) as client:
        roads = await client.list_roads(road_type=kind)
        assert roads.items
        road = roads.items[0]
        assert len(road.road_id) == 4 and road.name and road.road_number
        result = await client.get_traffic(road.road_id, road_type=kind, direction=direction)
        assert result.items
        assert result.scope == {"road_type": kind, "road_id": road.road_id, "direction": direction}
        assert result.complete is False and result.completeness_note
        assert result.collected_at.tzinfo is not None
        assert all(section.direction == direction and section.links for section in result.items)
        links = [link for section in result.items for link in section.links]
        assert all(isinstance(link.link_id, str) and link.link_id for link in links)
        assert any(link.speed_kmh is not None and math.isfinite(link.speed_kmh) for link in links)
        assert all(section.raw_info["COUNT"] == len(section.links) for section in result.items)
        assert any(link.path for link in links)
        assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for link in links for lon, lat in link.path)
        print(f"소통 live: {result.collected_at.isoformat()} {kind}/{road.road_id}/{direction}, "
              f"도로 {len(roads.items)}, 구간 {len(result.items)}, 링크 {len(links)}, 경로 제공 {sum(bool(link.path) for link in links)}/{len(links)}")


@pytest.mark.parametrize("kind", [None, "national"])
async def test_live_events_have_real_ids_scope_and_optional_messages(kind):
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"), timeout=60) as client:
        result = await client.get_events(road_type=kind)
    assert result.items
    assert result.source_url == "https://www.its.go.kr/map/outbreak"
    assert result.scope["excluded"] == "DISASTER"
    assert result.complete is False
    assert all(item.event_id and item.road_name and item.event_type_name for item in result.items)
    assert all(item.event_id == item.raw_info["outbrkId"] for item in result.items)
    if kind is not None:
        assert all(item.road_type == kind for item in result.items)
    print(f"돌발 live: {result.collected_at.isoformat()} {kind or 'all'}, {len(result.items)}건")


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_initial_event_denial_stops_without_refresh_in_real_chromium(monkeypatch, status):
    """초기 요청 거부 후 200을 주는 refresh 버튼이 있어도 추가 호출하지 않는다."""
    observed = []
    valid = (Path(__file__).parent / "fixtures" / "events.json").read_bytes()
    html = '''<!doctype html><title>돌발정보 | ITS 국가교통정보센터</title>
    <div id="map"></div><button onclick="refreshOutbreak()">새로고침</button>
    <script>
    function send(data) { return fetch('/map/getMarkers', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({body:{data}})}); }
    function refreshOutbreak() { return send({type:''}); }
    send({type:'',keyword:''});
    </script>'''.encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            initial = "keyword" in payload["body"]["data"]
            result = status if initial else 200
            observed.append(result)
            self.send_response(result)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"header":{"state":"ERROR"}}' if initial else valid)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    authority = f"127.0.0.1:{server.server_port}"
    monkeypatch.setattr("krits.client.BASE_URL", "http://" + authority)
    monkeypatch.setattr("krits._browser._allowed_resource", lambda url, kind: urlsplit(url).netloc == authority)
    error = KritsRateLimitError if status == 429 else KritsAccessError
    try:
        async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"), timeout=15) as client:
            with pytest.raises(error):
                await client.get_events()
        assert observed == [status]
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await asyncio.to_thread(worker.join)
