"""실제 공개 예측 분기와 참고 XLSX를 키 없이 Chromium에서 검증한다."""

from datetime import date,timedelta
import os

import pytest

from krits import FileLimits,FileStore,KritsClient,inspect_file,read_xlsx

pytestmark=pytest.mark.live


async def test_live_forecast_date_hour_directions_and_link_raw():
    forecast_date=date.today()+timedelta(days=1)
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE")) as client:
        roads=await client.list_forecast_roads()
        assert roads.items and roads.scope["mode"]=="forecast"
        road=roads.items[0].road_number
        for direction in ("1","2"):
            sections=await client.list_forecast_sections(road,forecast_date=forecast_date,hour=12,direction=direction)
            assert sections.items and not sections.complete
            assert sections.scope["forecast_date"]==forecast_date.isoformat() and sections.scope["hour"]=="12"
            assert all(s.direction==direction and s.road_number==road for s in sections.items)
            print("예측 구간",sections.collected_at.isoformat(),road,direction,len(sections.items),
                  "집계 미제공",sum(s.main_speed_kmh is None for s in sections.items),flush=True)
            if direction=="1":
                first=sections.items[0]
                links=await client.get_forecast_links(road,first.section_id,first.detour_id,
                    forecast_date=forecast_date,hour=12,direction=direction)
                assert links.items and {l.route for l in links.items}=={"MAIN","DETOUR"}
                assert all(l.link_id==l.raw_info["LINK_ID"] and l.section_id==first.section_id for l in links.items)
                print("예측 상세",links.collected_at.isoformat(),len(links.items),
                      "원시 speed=1",sum(l.raw_speed==1 for l in links.items),flush=True)
        again=await client.list_forecast_roads()
        assert again.items==roads.items


@pytest.mark.parametrize("service",["fcTraffic","detectorInfo","vsl"])
async def test_live_reference_xlsx_discovery_download_inspect_read_reuse(service,request,tmp_path,monkeypatch):
    store=FileStore(request.config.getoption("--file-store") or tmp_path)
    limits=FileLimits(max_rows=100_000,max_table_bytes=64*1024**2)
    async with KritsClient(executable_path=os.getenv("KRITS_CHROMIUM_EXECUTABLE"),timeout=180) as client:
        catalog=await client.list_reference_files(service)
        assert catalog.items and not catalog.complete and catalog.scope["kind"]=="reference"
        for attachment in catalog.items:
            stored=await client.download_file(attachment,store,max_bytes=50*1024**2)
            report=await inspect_file(store,stored,limits=limits)
            table=await read_xlsx(store,stored,limits=limits)
            assert report.kind=="xlsx" and report.crc_checked and table.rows
            assert await store.verify(stored)==stored
            def no_network():
                raise AssertionError("참고 파일 재사용 중 Chromium operation이 발생했습니다")
            with monkeypatch.context() as patch:
                patch.setattr(client._browser,"operation",no_network)
                assert await client.download_file(attachment,store,max_bytes=50*1024**2)==stored
            print("참고 XLSX",service,attachment.name,stored.size_bytes,stored.sha256,
                  "시트",table.sheet_name,"행",len(table.rows),flush=True)
