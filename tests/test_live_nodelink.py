"""실제 공개 자료실의 현재/과거 배포 및 ZIP·CSV·XLSX 첨부를 확인한다."""

from datetime import date,datetime,timedelta
import os
from zoneinfo import ZoneInfo
import pytest
from krits import KritsClient,compare_nodelink_catalogs

pytestmark=pytest.mark.live


@pytest.mark.parametrize('historic',[False,True])
async def test_live_nodelink_catalog(historic):
    end=datetime.now(ZoneInfo('Asia/Seoul')).date()
    start=end-timedelta(days=365)
    if historic:start,end=date(2025,1,1),date(2025,12,31)
    async with KritsClient(timeout=90,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        result=await c.list_nodelink_releases(start_date=start,end_date=end)
    assert result.items and not result.complete
    files=[f for row in result.items for f in [row.data_file,row.history_file] if f is not None]
    assert all(f.file_id and f.attachment_id and f.size_bytes is None for f in files)
    assert any(f.name.lower().endswith('.zip') for f in files)
    if historic:assert any(f.name.lower().endswith('.xlsx') for f in files)
    assert compare_nodelink_catalogs(result,result).changed_ids==()
    print('노드링크',result.collected_at.isoformat(),start,end,'배포',len(result.items),'첨부',len(files))


async def test_live_older_partial_release_can_have_no_history():
    async with KritsClient(timeout=90,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        result=await c.list_nodelink_releases(start_date=date(2024,1,1),end_date=date(2024,12,31))
    assert result.items and any(row.history_file is None for row in result.items)
    assert all(row.description for row in result.items)


async def test_live_explicit_empty_nodelink_period():
    today=datetime.now(ZoneInfo('Asia/Seoul')).date()+timedelta(days=10)
    async with KritsClient(timeout=90,executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as c:
        result=await c.list_nodelink_releases(start_date=today,end_date=today)
    assert result.items==() and not result.complete
