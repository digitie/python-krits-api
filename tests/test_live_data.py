"""키 없는 실제 Chromium에서 T003 공개 조회의 비어 있지 않은 계약을 검증한다."""

import math
import os

import pytest

from krits import KritsClient

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
        print(f"소통 live: {result.collected_at.isoformat()} {kind}/{road.road_id}/{direction}, "
              f"도로 {len(roads.items)}, 구간 {len(result.items)}, 링크 {len(links)}")


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
