"""실제 Chromium과 ITS에서 키 없는 패키지 경계를 검증한다."""

import os
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
import pytest

from krits import KritsClient, KritsClosedError, KritsNetworkError

pytestmark = pytest.mark.live


async def test_owned_browser_keyless_public_page_and_close():
    client = KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"), timeout=60)
    async with client:
        result = await client.get_page_snapshot()
        assert result.source_url == "https://www.its.go.kr/opendata/intro"
        assert "오픈데이터" in result.title
        assert result.collected_at.tzinfo is not None
        print(f"공개 페이지 접근 성공: {result.source_url}, {result.collected_at.isoformat()}")
    with pytest.raises(KritsClosedError):
        await client.get_page_snapshot()


async def test_injected_context_remains_usable_after_client_closes():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"),
        )
        try:
            context = await browser.new_context(service_workers="block")
            try:
                original_pages = len(context.pages)
                async with KritsClient(browser_context=context, timeout=60) as client:
                    snapshot = await client.get_page_snapshot("nodelink")
                    assert "노드링크" in snapshot.title
                    assert len(context.pages) == original_pages + 1
                assert len(context.pages) == original_pages
                extra = await context.new_page()
                await extra.close()
                assert browser.is_connected()
            finally:
                await context.close()
        finally:
            await browser.close()


async def test_redirect_each_hop_is_filtered_before_network(monkeypatch):
    """실제 Chromium이 차단 대상 redirect를 서버에 전송하지 않는지 확인한다."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/forbidden")
            elif self.path == "/allowed-start":
                self.send_response(302)
                self.send_header("Location", "/ok")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            # Chromium 버전별 암묵적 /favicon.ico 요청이 redirect 검증을 흔들지 않게 한다.
            self.wfile.write(b"<!doctype html><link rel='icon' href='data:,'>")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    authority = f"localhost:{server.server_port}"
    monkeypatch.setattr(
        "krits._browser._allowed_resource",
        lambda url, kind: urlsplit(url).netloc == authority and kind.lower() == "document",
    )
    try:
        async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE")) as client:
            with pytest.raises(KritsNetworkError):
                async with client._browser.operation() as page:
                    await page.goto(f"http://{authority}/start")
            async with client._browser.operation() as page:
                response = await page.goto(f"http://{authority}/allowed-start")
                assert response.status == 200
        assert received == ["/start", "/allowed-start", "/ok"]
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await asyncio.to_thread(worker.join)
