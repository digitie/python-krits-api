"""실제 Chromium과 ITS에서 키 없는 패키지 경계를 검증한다."""

import os

from playwright.async_api import async_playwright
import pytest

from krits import KritsClient, KritsClosedError

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
