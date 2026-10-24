"""저장소 소스 대신 별도 설치한 wheel의 공개 기능을 실제 Chromium으로 검증한다."""

import argparse
import asyncio
from datetime import date, timedelta
import importlib.metadata
import json
from pathlib import Path
import site
import sys


def arguments():
    """네트워크 실행과 설치 경로·원본 보관소를 명시적으로 받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--file-store", type=Path, required=True)
    parser.add_argument("--chromium", required=True)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--run-large-files", action="store_true")
    parser.add_argument("--history-encoding", help="CSV 내역서의 확인된 인코딩(추정/자동 fallback 없음)")
    return parser.parse_args()


async def run(args):
    """각 공개 기능을 한 번 호출하고 작은 내역서·선택 전체 ZIP의 보관본을 검증한다."""
    import krits
    from krits import FileLimits, FileStore, KritsClient, inspect_file, read_csv, read_xlsx

    imported = Path(krits.__file__).resolve()
    assert imported.is_relative_to(args.package_root), (imported, args.package_root)
    distribution = importlib.metadata.distribution("python-krits-api")
    assert Path(distribution.locate_file("krits")).resolve() == args.package_root / "krits"
    store = FileStore(args.file_store)
    end = date.today()
    summary = {"package": str(imported), "version": distribution.version}
    async with KritsClient(executable_path=args.chromium) as client:
        page = await client.get_page_snapshot()
        assert "ITS" in page.title
        roads = await client.list_roads()
        traffic = await client.get_traffic(roads.items[0].road_id)
        events = await client.get_events()
        cctvs = await client.search_cctvs("서울")
        detour_roads = await client.list_detour_roads()
        detours = await client.get_detours(detour_roads.items[0].road_number)
        origins = await client.list_travel_origins()
        travel = await client.get_travel_times(origins.items[0])
        vms = await client.get_vms()
        disasters = await client.get_disaster_zones()
        weak = await client.list_data_files("weakSection")
        period = await client.list_data_files("event", start_date=end-timedelta(days=3), end_date=end)
        releases = await client.list_nodelink_releases(start_date=end-timedelta(days=300), end_date=end)
        for name, result in (("roads", roads), ("traffic", traffic), ("events", events), ("cctvs", cctvs),
                             ("detours", detours), ("travel", travel), ("vms", vms), ("weak", weak),
                             ("period", period), ("releases", releases)):
            assert result.items and result.source_url and result.collected_at.tzinfo and not result.complete, name
            summary[name] = len(result.items)
        summary["disaster_zones"] = len(disasters.items)
        assert disasters.scope["group"] == "DISASTER" and not disasters.complete
        assert len(krits.list_capabilities()) == 12
        attachment = releases.items[0].history_file
        assert attachment is not None
        small = await client.download_file(attachment, store, max_bytes=10*1024**2)
        if attachment.name.lower().endswith(".csv"):
            assert args.history_encoding, "CSV는 --history-encoding으로 확인된 인코딩을 지정해야 합니다"
            table = await read_csv(store, small, encoding=args.history_encoding)
            report = await inspect_file(store, small, encoding=args.history_encoding)
        else:
            table = await read_xlsx(store, small)
            report = await inspect_file(store, small)
        assert table.rows and report.report_path
        assert await store.verify(small) == small
        assert await client.download_file(attachment, store, max_bytes=10*1024**2) == small
        summary["history"] = {"bytes": small.size_bytes, "sha256": small.sha256, "rows": len(table.rows)}
        if args.run_large_files:
            attachment = releases.items[0].data_file
            assert attachment is not None and attachment.name.lower().endswith("nodelinkdata.zip")
            before = await store.current(attachment)
            assert before is not None, "전체 ZIP은 pytest --run-large-files로 한 번 수집한 뒤 재사용합니다"
            large = await client.download_file(attachment, store)
            assert large == before
            report = await inspect_file(store, large, limits=FileLimits(
                max_member_bytes=2*1024**3, max_total_bytes=6*1024**3))
            assert report.crc_checked and report.members and report.metadata
            summary["zip_reused"] = {"bytes": large.size_bytes, "sha256": large.sha256, "members": len(report.members)}
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main():
    args = arguments()
    args.package_root = args.package_root.resolve()
    args.file_store = args.file_store.resolve()
    repository = Path(__file__).resolve().parents[1]
    if args.package_root.is_relative_to(repository) or args.file_store.is_relative_to(repository):
        raise SystemExit("설치 경로와 원본 보관소는 Git 저장소 밖에 지정해야 합니다")
    if not (args.package_root / "krits" / "__init__.py").is_file():
        raise SystemExit("--package-root에 wheel을 먼저 pip --target 설치해야 합니다")
    # -I에서 사용자 site의 .pth는 처리하지 않는다. 명시 설치본을 앞에 두고 의존 패키지만 찾는다.
    sys.path.insert(0, str(args.package_root))
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.append(user_site)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
