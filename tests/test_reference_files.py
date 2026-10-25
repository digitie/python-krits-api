"""정적 참고 데이터의 실제 DOM 발견·누락·경로·캐시 계약을 검사한다."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from krits import KritsClient, KritsSchemaError
from krits._references import REFERENCE_PATHS
from krits.files import validate_attachment
from krits.parse import parse_reference_files


def rows(service):
    return [{"href":path,"name":path.rsplit('/',1)[-1]} for path in REFERENCE_PATHS[service]]


@pytest.mark.parametrize("service", ["fcTraffic","detectorInfo","vsl"])
def test_reference_file_ids_and_sizes_are_not_inferred(service):
    files = parse_reference_files(rows(service),service)
    assert len(files) == len(REFERENCE_PATHS[service])
    for item in files:
        assert item.file_id is None and item.attachment_id is None and item.size_bytes is None
        assert item.service == service and item.raw == {"kind":"reference"}
        validate_attachment(item,50*1024**2)
    assert parse_reference_files(rows(service)*2,service) == files


@pytest.mark.parametrize("value", [None,{},[],[{"name":"test.xlsx","href":"/file/opendata/vsl/unknown.xlsx"}],
    [{"name":"test.hwp","href":"/file/opendata/vsl/highwayVSLStatus.xlsx"}],
    [{"name":None,"href":"/file/opendata/vsl/highwayVSLStatus.xlsx"}]])
def test_missing_or_changed_reference_files_are_not_empty(value):
    with pytest.raises(KritsSchemaError):parse_reference_files(value,"vsl")


def test_duplicate_with_different_display_name_is_schema_error():
    value=rows("vsl");value.append(dict(value[0],name="renamed.xlsx"))
    with pytest.raises(KritsSchemaError):parse_reference_files(value,"vsl")


@pytest.mark.parametrize("url", [
    "https://www.its.go.kr/file/opendata/vsl/unknown.xlsx",
    "https://www.its.go.kr/file/opendata/vsl/highwayVSLStatus.xlsx?extra=1",
    "https://www.its.go.kr/file/opendata/vsl/highwayVSLStatus.xlsx#part",
    "http://www.its.go.kr/file/opendata/vsl/highwayVSLStatus.xlsx",
    "https://other.invalid/file/opendata/vsl/highwayVSLStatus.xlsx",
    "https://www.its.go.kr/file/opendata/vsl/vsl_api.hwp",
])
def test_reference_download_allowlist_is_exact(url):
    item=parse_reference_files(rows("vsl"),"vsl")[0]
    with pytest.raises(ValueError):validate_attachment(replace(item,download_url=url),50*1024**2)


@pytest.mark.parametrize("service", ["traffic","safeDriving","dangerousCarInfo",None,[],123])
async def test_reference_invalid_service_does_not_start_browser(browser,service):
    async with KritsClient() as client:
        with pytest.raises(ValueError):await client.list_reference_files(service)
    browser.manager.start.assert_not_awaited()


async def test_reference_client_uses_dom_and_cache(browser,monkeypatch):
    visit=AsyncMock();monkeypatch.setattr("krits.client._visit_page",visit)
    browser.page.locator.side_effect=None
    browser.page.locator.return_value=SimpleNamespace(evaluate_all=AsyncMock(return_value=rows("vsl")))
    async with KritsClient() as client:
        first=await client.list_reference_files("vsl");second=await client.list_reference_files("vsl")
    assert first==second and first is not second and first.scope["edition"]=="not_provided"
    assert not first.complete and len(first.items)==2
    visit.assert_awaited_once()
    assert visit.call_args.args[1].endswith("service=vsl") and visit.call_args.args[2]=="#moveApi"
