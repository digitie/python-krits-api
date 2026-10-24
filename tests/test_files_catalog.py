"""공개 일반 첨부 목록의 기간·ID·DOM 경로·무인증 계약을 검증한다."""

import asyncio
from datetime import date, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from krits import KritsClient, KritsRateLimitError, KritsSchemaError
from krits.client import _date_range, _open_file_catalog
from krits.parse import open_data_ids, parse_open_data, parse_weak_files


def fixture(name):
    return json.loads((Path(__file__).parent / 'fixtures' / ('files-'+name+'.json')).read_text(encoding='utf8'))


def anchors(kind):
    return [{'id': x['fileId'], 'name': x['fileStreNm'],
             'href': f"/opendata/fileDownload/{kind}/{x['workingDirectory']}/{x['fileStreNm']}"}
            for x in fixture(kind)['body']['data']['fileVOList']]


@pytest.mark.parametrize('kind', ['traffic', 'event', 'vms'])
def test_observed_file_rows_and_dom_agree(kind):
    d = fixture(kind);items = parse_open_data(d, kind, anchors(kind))
    assert len(items) == 2 and items[0].attachment_id == '0'
    assert items[0].file_id == d['body']['data']['fileVOList'][0]['fileId']
    assert items[0].size_bytes > 0 and items[0].name.endswith('.zip')
    assert items[0].download_url.startswith('https://www.its.go.kr/opendata/fileDownload/')
    d['body']['data']['fileVOList'] = []
    assert parse_open_data(d, kind, []) == ()


@pytest.mark.parametrize('field,value', [('fileId', 1), ('fileSeq', -1), ('fileSeq', True),
                                        ('fileSize', '1024'), ('fileSize', None), ('dataType', 'vms'),
                                        ('workingDirectory', '../2026'), ('fileStreNm', '../a.zip')])
def test_bad_file_fields(field, value):
    d = fixture('event');d['body']['data']['fileVOList'][0][field] = value
    with pytest.raises(KritsSchemaError): parse_open_data(d, 'event', anchors('event'))


@pytest.mark.parametrize('mutate', [
    lambda d: d.pop('header'), lambda d: d['header'].update(state='ERROR'),
    lambda d: d['body']['data'].pop('fileVOList'),
    lambda d: d['body']['data'].update(fileVOList=None),
    lambda d: d['body']['data']['fileVOList'].append(d['body']['data']['fileVOList'][0]),
])
def test_bad_envelope_or_duplicate_ids(mutate):
    d = fixture('event');mutate(d)
    with pytest.raises(KritsSchemaError): open_data_ids(d)


@pytest.mark.parametrize('field,value', [('id', 'other'), ('name', 'other.zip'),
    ('href', 'https://other.invalid/a.zip'), ('href', '//www.its.go.kr/a.zip'),
    ('href', '/opendata/fileDownload/event/2026/../a.zip'),
    ('href', '/opendata/fileDownload/event/2026/%2e%2e.zip'),
    ('href', '/opendata/fileDownload/event/2026/20261023.zip?token=1'),
    ('href', '/opendata/fileDownload/vms/2026/20261023.zip')])
def test_dom_mismatch_or_unsafe_path(field, value):
    links = anchors('event');links[0][field] = value
    with pytest.raises(KritsSchemaError): parse_open_data(fixture('event'), 'event', links)


def test_missing_anchors_are_not_partial_success():
    with pytest.raises(KritsSchemaError): parse_open_data(fixture('event'), 'event', [])


def test_static_weak_duplicates_have_no_invented_ids_size_or_dates():
    items = parse_weak_files(fixture('weak'))
    assert len(items) == 2
    assert all(x.file_id is None and x.attachment_id is None and x.size_bytes is None for x in items)
    assert items[0].name == '행정안전부_상습 결빙구간.csv'


@pytest.mark.parametrize('value', [[], None, [{'href': '/file/opendata/weakSections/a.csv', 'name': ''}],
    [{'href': '/file/opendata/weakSections/a.csv', 'name': None}],
    [{'href': '/file/opendata/weakSections/a.csv', 'name': 'a'}, {'href': '/file/opendata/weakSections/a.csv', 'name': 'b'}],
    [{'href': '/file/opendata/weakSections/../a.csv', 'name': 'a'}]])
def test_static_missing_changed_or_unsafe_dom(value):
    with pytest.raises(KritsSchemaError): parse_weak_files(value)


@pytest.mark.parametrize('start,end', [(date(2025,1,1), date(2026,1,1)),
                                      (date(2023,3,1), date(2024,2,29)),
                                      (date(1,1,1), date(1,1,1))])
def test_calendar_year_boundary(start, end):
    assert _date_range(start, end) == (start.isoformat(), end.isoformat())


@pytest.mark.parametrize('start,end', [(None,None), ('2026-01-01',date(2026,1,1)),
    (datetime(2026,1,1),date(2026,1,1)), (date(2026,1,2),date(2026,1,1)),
    (date(2023,2,28),date(2024,2,29)), (date(2024,12,31),date(2026,1,1))])
def test_invalid_date_range(start, end):
    with pytest.raises(ValueError): _date_range(start, end)


@pytest.fixture
def file_browser(browser, monkeypatch):
    p = browser.page;p.on = Mock();p.remove_listener = Mock();p.wait_for_function = AsyncMock()
    p.wait_for_load_state = AsyncMock()
    async def goto(url, **kwargs):
        p.url = url
        return SimpleNamespace(status=200)
    p.goto.side_effect = goto
    loc = SimpleNamespace(count=AsyncMock(return_value=1), click=AsyncMock(), fill=AsyncMock(),
                          wait_for=AsyncMock(), evaluate_all=AsyncMock(return_value=anchors('event')))
    loc.first = loc
    p.locator.side_effect = lambda s: SimpleNamespace(count=AsyncMock(return_value=0)) if ':visible' in s else loc
    action = AsyncMock(return_value=fixture('event'))
    monkeypatch.setattr('krits.client._action_json', action)
    return SimpleNamespace(page=p, loc=loc, action=action)


async def test_date_search_uses_ui_and_preserves_scope(file_browser):
    b = file_browser
    async with KritsClient() as c:
        result = await c.list_data_files('event', start_date=date(2026,10,22), end_date=date(2026,10,23))
    assert result.scope == {'service':'event','kind':'date_range','start_date':'2026-10-22','end_date':'2026-10-23'}
    assert not result.complete and len(result.items) == 2
    assert b.action.call_count == 1
    assert b.page.goto.call_args.args[0].endswith('?service=event')
    await b.action.call_args_list[0].args[2]()
    b.loc.click.assert_awaited_once()
    assert b.loc.fill.await_args_list[0].args == ('2026.10.22',)
    assert b.page.on.call_args_list[0].args == b.page.remove_listener.call_args_list[-1].args


async def test_static_files_do_not_send_date_query(file_browser):
    b = file_browser;b.loc.evaluate_all.return_value = fixture('weak')
    async with KritsClient() as c: result = await c.list_data_files('weakSection')
    assert len(result.items) == 2 and result.scope['kind'] == 'static'
    b.action.assert_not_awaited()


@pytest.mark.parametrize('kind,kwargs', [('unknown', {}), ('traffic', {}),
    ('weakSection', {'start_date':date(2026,1,1)}), ('event', {'start_date':date(2026,1,2),'end_date':date(2026,1,1)})])
async def test_bad_query_does_not_open_browser(browser, kind, kwargs):
    async with KritsClient() as c:
        with pytest.raises(ValueError): await c.list_data_files(kind, **kwargs)
    browser.manager.start.assert_not_awaited()


@pytest.mark.parametrize('status,payload,error', [(200, fixture('event'), None),
    (429, {}, KritsRateLimitError), (200, {}, KritsSchemaError)])
async def test_initial_catalog_responses_are_checked_and_listener_removed(file_browser, status, payload, error):
    b = file_browser
    endpoint = '/opendata/getTestDataFileList'
    async def loaded(_state):
        observe = b.page.on.call_args.args[1]
        observe(SimpleNamespace(url='https://other.invalid/'))
        observe(SimpleNamespace(url='https://www.its.go.kr'+endpoint, status=status,
                                text=AsyncMock(return_value=json.dumps(payload))))
    b.page.wait_for_load_state.side_effect = loaded
    call = _open_file_catalog(b.page, 'https://www.its.go.kr/opendata/opendataList?service=event', endpoint)
    if error:
        with pytest.raises(error): await call
    else:
        await call
    assert b.page.on.call_args.args == b.page.remove_listener.call_args.args
