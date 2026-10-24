"""CCTV·우회·도시간의 정상 빈 결과와 깨진 데이터 계약을 구분한다."""

from copy import deepcopy
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from krits import KritsClient, KritsRateLimitError, KritsSchemaError
from krits.client import _travel_widget
from krits.parse import parse_cctvs, parse_detour_roads, parse_detours, parse_origins, parse_travel_times


def fixture(name):
    return json.loads((Path(__file__).parent / 'fixtures' / (name + '.json')).read_text(encoding='utf8'))


def test_real_metadata_preserves_ids_and_units():
    cctv = parse_cctvs(fixture('cctv'))[0]
    assert cctv.cctv_id.startswith('000000') and cctv.route_id == '0010'
    detours = parse_detours(fixture('detour'), '1')
    assert len(detours) == 4 and {d.direction for d in detours} == {'1', '2'}
    assert detours[0].main_time_seconds == detours[0].raw['MAIN_PASNG_TIME']
    times = parse_travel_times(fixture('travel'), '대전')
    assert times[0].group_id == 'DJBS02' and times[0].minutes == 166
    assert parse_detour_roads([{'road_number': '1', 'name': '경부'}])[0].road_number == '1'
    assert parse_origins(['서울', '대전']) == ('서울', '대전')


def test_explicit_empty_arrays():
    assert parse_cctvs([]) == ()
    d = fixture('detour');d['body']['data']['SECTIONS'] = {'UPROAD': [], 'DOWNROAD': []}
    assert parse_detours(d, '1') == ()
    d = fixture('travel');d['body']['data']['COURSE'] = []
    assert parse_travel_times(d, '대전') == ()


@pytest.mark.parametrize('parser,args', [
    (parse_cctvs, (None,)), (parse_cctvs, ({},)), (parse_cctvs, ([{'cctvId': 1}],)),
    (parse_detour_roads, ([],)), (parse_detour_roads, ([{'road_number': 'x', 'name': 'a'}],)),
    (parse_detour_roads, ([{'road_number': '1', 'name': 'a'}] * 2,)),
    (parse_origins, ([],)), (parse_origins, (['서울', '서울'],)), (parse_origins, ([None],)),
    (parse_detours, ({}, '1')), (parse_travel_times, ({}, '대전')),
])
def test_bad_shapes(parser, args):
    with pytest.raises(KritsSchemaError): parser(*args)


@pytest.mark.parametrize('field,value', [('ROAD_NO', '2'), ('SCTN_TY_CODE', 'NH'), ('DRC_CODE', '2'),
                                        ('MLN_SCTN_ID', 1), ('DETU_ID', None), ('MAIN_PASNG_TIME', -1),
                                        ('DETOUR_PASNG_SPED', float('nan'))])
def test_detour_contract(field, value):
    d = fixture('detour');d['body']['data']['SECTIONS']['DOWNROAD'][0][field] = value
    with pytest.raises(KritsSchemaError): parse_detours(d, '1')


@pytest.mark.parametrize('field,value', [('BSPOTNM', '부산'), ('GRPID', 1), ('REQRETIME', None),
                                        ('REQRETIME', float('inf')), ('ESPOTNM', '')])
def test_travel_contract(field, value):
    d = fixture('travel');d['body']['data']['COURSE'][0][field] = value
    with pytest.raises(KritsSchemaError): parse_travel_times(d, '대전')


@pytest.mark.parametrize('name', ['cctv', 'detour', 'travel'])
def test_missing_fields_are_not_empty(name):
    d = fixture(name)
    if name == 'cctv':
        del d[0]['instlLcDc'];call = lambda: parse_cctvs(d)
    elif name == 'detour':
        del d['body']['data']['SECTIONS']['UPROAD'];call = lambda: parse_detours(d, '1')
    else:
        del d['body']['data']['COURSE'];call = lambda: parse_travel_times(d, '대전')
    with pytest.raises(KritsSchemaError): call()


@pytest.fixture
def more_browser(browser, monkeypatch):
    p = browser.page
    async def goto(url, **kwargs):
        p.url = url
        return SimpleNamespace(status=200)
    p.goto.side_effect = goto
    p.on = Mock();p.remove_listener = Mock()
    loc = SimpleNamespace(count=AsyncMock(return_value=1), wait_for=AsyncMock(),
                          evaluate_all=AsyncMock(), click=AsyncMock(), fill=AsyncMock(), select_option=AsyncMock())
    loc.first = loc;loc.locator = Mock(return_value=loc);loc.nth = Mock(return_value=loc)
    p.locator.side_effect = lambda s: SimpleNamespace(count=AsyncMock(return_value=0)) if ':visible' in s else loc
    action = AsyncMock()
    monkeypatch.setattr('krits.client._action_json', action)
    return SimpleNamespace(page=p, loc=loc, action=action)


async def test_cctv_query_and_scope(more_browser):
    b = more_browser;b.action.return_value = fixture('cctv')
    async with KritsClient() as c: result = await c.search_cctvs(' 서울 ')
    assert result.items and result.scope == {'keyword': '서울', 'content': 'metadata'}
    assert b.action.call_args.kwargs == {'flat_request': True}
    await b.action.call_args.args[2]()
    b.loc.fill.assert_awaited_once_with('서울');b.loc.click.assert_awaited_once()


async def test_detour_and_origin_catalog_queries(more_browser):
    b = more_browser
    async with KritsClient(max_rps=10000) as c:
        b.loc.evaluate_all.return_value = [{'road_number': '1', 'name': '경부'}]
        assert (await c.list_detour_roads()).items[0].road_number == '1'
        b.action.return_value = fixture('detour')
        result = await c.get_detours('1')
        assert result.scope['mode'] == 'current' and len(result.items) == 4
        await b.action.call_args.args[2]()
        with pytest.raises(ValueError): await c.get_detours('9999')
        b.loc.evaluate_all.return_value = ['서울', '대전']
        assert (await c.list_travel_origins()).items == ('서울', '대전')
        b.action.return_value = fixture('travel')
        result = await c.get_travel_times('대전')
        assert result.scope['origin'] == '대전'
        await b.action.call_args.args[2]()
        b.loc.select_option.assert_awaited_once_with('대전', force=True)
        with pytest.raises(ValueError): await c.get_travel_times('제주')


@pytest.mark.parametrize('method,arg', [('search_cctvs', ''), ('search_cctvs', 1), ('search_cctvs', 'a'*101),
                                      ('get_detours', 1), ('get_detours', 'a'),
                                      ('get_travel_times', ''), ('get_travel_times', 1)])
async def test_invalid_arguments_are_lazy(browser, method, arg):
    async with KritsClient() as c:
        with pytest.raises(ValueError): await getattr(c, method)(arg)
    browser.manager.start.assert_not_awaited()


@pytest.mark.parametrize('phase', ['initial', 'before_select', 'return', 'failure'])
async def test_widget_denial_guard_covers_navigation_selection_and_return(more_browser, phase):
    b = more_browser;b.loc.evaluate_all.return_value = ['서울', '대전']
    denied = SimpleNamespace(url='https://www.its.go.kr/map/getCityReqTimeByGroup', status=429)
    def deny(): b.page.on.call_args.args[1](denied)
    if phase == 'initial':
        async def initial(*_args, **_kwargs): deny()
        b.action.side_effect = initial
    with pytest.raises(KritsRateLimitError):
        async with _travel_widget(b.page) as (_select, _origins, check):
            if phase == 'before_select': deny();check()
            if phase == 'return': deny()
            if phase == 'failure': deny();raise KritsSchemaError('원래 실패')
    assert b.page.on.call_args.args == b.page.remove_listener.call_args.args


async def test_widget_cancel_is_preserved_and_observer_removed(more_browser):
    b = more_browser;b.loc.evaluate_all.return_value = ['서울']
    with pytest.raises(asyncio.CancelledError):
        async with _travel_widget(b.page): raise asyncio.CancelledError
    assert b.page.on.call_args.args == b.page.remove_listener.call_args.args


async def test_widget_initial_action_and_original_error(more_browser):
    b = more_browser;b.loc.evaluate_all.return_value = ['서울']
    with pytest.raises(KritsSchemaError):
        async with _travel_widget(b.page): raise KritsSchemaError('원래 오류')
    await b.action.call_args.args[2]()
    assert b.page.goto.call_args.args[0].endswith('/map/traffic')
