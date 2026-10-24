"""키 없이 공개 ITS 화면과 자료실을 실제 Chromium에서 검증한다."""

import asyncio
from datetime import datetime, timezone
import json
import os

from playwright.async_api import async_playwright


async def main() -> None:
    """세션 원문 없이 페이지 상태·제목·첨부 수만 출력한다."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=os.environ.get("KRITS_CHROMIUM_EXECUTABLE") or None,
        )
        try:
            page = await browser.new_page()
            print(json.dumps({"started_at": datetime.now(timezone.utc).isoformat(),
                              "chromium": browser.version}))
            for service in ("traffic", "event", "cctv", "fcTraffic", "detectorInfo",
                            "vms", "safeDriving", "vsl", "weakSection", "nodelink",
                            "dangerousCarInfo", "disaster"):
                url = "https://www.its.go.kr/opendata/opendataList?service=" + service
                response = await page.goto(url, wait_until="networkidle", timeout=45000)
                if response is None or response.status != 200 or page.url != url:
                    raise RuntimeError(f"공개 사양 페이지 접근 실패: {service}")
                if await page.locator("#moveApi, #moveData").count() == 0:
                    raise RuntimeError(f"사양 컨테이너 누락: {service}")
                print(json.dumps({"service": service, "status": response.status}))
            url = "https://www.its.go.kr/nodelink/nodelinkRef"
            async with page.expect_response(
                lambda r: r.url.endswith("/opendata/getNodeLinkDataFileList")
            ) as pending:
                response = await page.goto(url, wait_until="networkidle", timeout=45000)
            payload_response = await pending.value
            payload = await payload_response.json()
            rows = payload["body"]["data"]["fileVOList"]
            if payload["header"]["state"] != "OK" or not isinstance(rows, list) or not rows:
                raise RuntimeError("노드링크 목록 계약 실패")
            await page.locator("a.down[href*='/opendata/nodelinkFileSDownload/']").first.wait_for()
            count = await page.locator("a.down[href*='/opendata/nodelinkFileSDownload/']").count()
            if count != len(rows) * 2:
                raise RuntimeError("목록과 첨부 DOM 수 불일치")
            print(json.dumps({"source_url": url, "releases": len(rows),
                              "attachments": count, "latest_id": rows[0]["seq"]}))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
