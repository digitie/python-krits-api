"""실제 공개 화면에서 CCTV·우회·도시간 메타데이터를 검증한다."""

import os
import pytest
from krits import KritsClient

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
