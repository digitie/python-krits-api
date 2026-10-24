"""전체 노드링크 원문 ZIP을 한 번 전송하고 보관본을 재검증한다."""

from datetime import date, timedelta
import os
from pathlib import Path

import pytest

from krits import FileLimits, FileStore, KritsClient, inspect_file
from tools.installed_e2e import is_within

pytestmark = [pytest.mark.live, pytest.mark.large_file]


async def test_complete_nodelink_zip_download_crc_metadata_and_reuse(request, monkeypatch):
    root = request.config.getoption("--file-store")
    if not root:
        pytest.fail("--file-store에 저장소 밖의 재사용 가능한 경로를 지정해야 합니다")
    storage_root = Path(root).resolve()
    repository = Path(__file__).resolve().parents[1]
    if is_within(storage_root, repository):
        pytest.fail("전체 원본은 Git 저장소 밖에 보관해야 합니다")
    store = FileStore(storage_root)
    today = date.today()
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"), timeout=1200) as client:
        catalog = await client.list_nodelink_releases(start_date=today-timedelta(days=300), end_date=today)
        assert catalog.items and catalog.items[0].data_file is not None
        attachment = catalog.items[0].data_file
        assert attachment.name.lower().endswith("nodelinkdata.zip")
        first = await client.download_file(attachment, store)
        assert first.size_bytes > 0
        report = await inspect_file(store, first, limits=FileLimits(
            max_member_bytes=2 * 1024**3, max_total_bytes=6 * 1024**3))
        assert report.kind == "zip" and report.crc_checked and report.members
        assert any(member.name.lower().endswith(".shp") for member in report.members)
        assert any(member.name.lower().endswith(".dbf") for member in report.members)
        assert any(item.name.lower().endswith(".prj") and item.data for item in report.metadata)
        def unexpected_operation():
            raise AssertionError("검증된 보관본 재사용 중 Chromium operation이 발생했습니다")
        monkeypatch.setattr(client._browser, "operation", unexpected_operation)
        again = await client.download_file(attachment, store)
        assert first == again
        assert await store.verify(first) == first
        assert report.report_path and report.report_path.is_file()
    print("전체 ZIP", attachment.name, first.size_bytes, first.sha256,
          "항목", len(report.members), "해제총량", sum(m.size_bytes for m in report.members),
          "metadata", [(m.name, len(m.data)) for m in report.metadata], "재실행 전송0회", flush=True)
