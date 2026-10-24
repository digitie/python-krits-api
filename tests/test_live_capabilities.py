"""공개 지도 VMS/재난구역의 실제 Chromium 계약을 검증한다."""

import os
import pytest

from krits import KritsClient, list_capabilities

pytestmark = pytest.mark.live


async def test_live_vms_messages_and_cached_second_read():
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE")) as client:
        result = await client.get_vms()
        again = await client.get_vms()
        client.clear_cache()
        fresh = await client.get_vms()
    assert result.items and result == again
    assert fresh.items and fresh.collected_at >= result.collected_at
    assert not result.complete and result.scope == {"layer": "VMS", "time": "current"}
    assert len({v.vms_id for v in result.items}) == len(result.items)
    assert any(v.message for v in result.items)
    assert all(v.vms_id == v.raw_info["vmsId"] for v in result.items)
    print("VMS", result.collected_at.isoformat(), len(result.items))


async def test_live_current_disaster_zone_contract():
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE")) as client:
        result = await client.get_disaster_zones()
    assert not result.complete and result.scope["group"] == "DISASTER"
    assert all(v.disaster_id and v.title and v.zone_type_name for v in result.items)
    assert all(v.disaster_id == v.raw_info["dangerId"] for v in result.items)
    assert len(list_capabilities()) == 12
    print("재난구역", result.collected_at.isoformat(), len(result.items), "현재 구역만, 빈 결과 가능")
