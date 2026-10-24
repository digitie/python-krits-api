"""노드링크 배포·첨부 ID와 과거 파일·관찰 차이를 검증한다."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from krits import KritsClient, KritsSchemaError, DataSnapshot, compare_nodelink_catalogs
from krits.parse import nodelink_dom_ids, parse_nodelink_releases


def fixture(name='nodelink'):
    return json.loads((Path(__file__).parent/'fixtures'/(name+'.json')).read_text(encoding='utf8'))


def snapshot(items, scope=None):
    return DataSnapshot(items, 'https://www.its.go.kr/nodelink/nodelinkRef', datetime.now(timezone.utc),
                        scope or {'service':'nodelink','start_date':'2025-10-24','end_date':'2026-10-24'})


def test_observed_ids_sizes_formats_and_optional_history():
    items = parse_nodelink_releases(fixture(), fixture('nodelink-links'))
    assert len(items)==3 and items[0].release_id=='221' and items[0].attachment_group_id=='DF_221'
    assert items[0].data_file.size_bytes is None and items[0].history_file.name=='내역서.csv'
    assert items[1].data_file.attachment_id=='5' and items[1].history_file.attachment_id=='6'
    assert items[1].data_file.file_id=='DF_211' and items[1].history_file.name.endswith('.xlsx')
    partial = parse_nodelink_releases(fixture('nodelink-partial'), fixture('nodelink-partial-links'))[0]
    assert partial.history_file is None and '전국 표준노드링크 자료가 아닌' in partial.description
    assert partial.data_file.raw['nodeFileMg']==0.19
    d = fixture();d['body']['data']['fileVOList']=[]
    assert nodelink_dom_ids(d)==() and parse_nodelink_releases(d,[])==()


@pytest.mark.parametrize('field,value', [('seq',1),('atchFileId',None),('nodeFileSeq',0),
    ('nodeFileSeq','x'),('nodeFileExtsnNm','../zip'),('nodeFileMg',-1),('nodeFileMg',True),
    ('nodeOrginlFileNm',None),('histFileSeq','0')])
def test_broken_release_metadata(field,value):
    d=fixture();d['body']['data']['fileVOList'][0][field]=value
    with pytest.raises(KritsSchemaError): parse_nodelink_releases(d,fixture('nodelink-links'))


@pytest.mark.parametrize('field', ['nodeFileSeq','histFileMg','nodeOrginlFileNm','histFileExtsnNm'])
def test_missing_field_is_not_optional_attachment(field):
    d=fixture();del d['body']['data']['fileVOList'][0][field]
    with pytest.raises(KritsSchemaError): nodelink_dom_ids(d)


@pytest.mark.parametrize('field', ['seq','atchFileId'])
def test_duplicate_release_or_attachment_group(field):
    d=fixture();rows=d['body']['data']['fileVOList'];rows[1][field]=rows[0][field]
    with pytest.raises(KritsSchemaError): nodelink_dom_ids(d)


def test_explicit_absence_inconsistent_metadata_and_no_files():
    d=fixture('nodelink-partial');row=d['body']['data']['fileVOList'][0]
    row['histFileMg']=False
    with pytest.raises(KritsSchemaError): nodelink_dom_ids(d)
    row['histFileMg']=None
    for key in ['nodeOrginlFileNm','nodeFileExtsnNm','nodeFileSeq','nodeFileMg']:row[key]=None
    with pytest.raises(KritsSchemaError): nodelink_dom_ids(d)


@pytest.mark.parametrize('field,value', [('id','NODE_DF_999'),('sequence','1'),('name','other.zip'),
    ('href','/opendata/nodelinkFileSDownload/DF_999/0'),
    ('href','https://other.invalid/a.zip'),('href','/opendata/nodelinkFileSDownload/DF_221/0?key=x')])
def test_changed_or_unsafe_dom(field,value):
    links=fixture('nodelink-links');links[0][field]=value
    with pytest.raises(KritsSchemaError): parse_nodelink_releases(fixture(),links)


def test_missing_dom_and_leading_zero_ids():
    with pytest.raises(KritsSchemaError): parse_nodelink_releases(fixture(),[])
    d=fixture('nodelink-partial');row=d['body']['data']['fileVOList'][0]
    row['seq']='000201';row['atchFileId']='other_group';row['nodeFileSeq']='005'
    links=fixture('nodelink-partial-links');links[0].update(id='NODE_other_group',sequence='005',href='/opendata/nodelinkFileSDownload/other_group/005')
    item=parse_nodelink_releases(d,links)[0]
    assert item.release_id=='000201' and item.attachment_group_id=='other_group' and item.data_file.attachment_id=='005'


def test_catalog_changes_preserve_history_and_ignore_position():
    original=parse_nodelink_releases(fixture(),fixture('nodelink-links'))
    newer=deepcopy(original)
    newer[1].raw['rowSeq']=99
    assert compare_nodelink_catalogs(snapshot(original),snapshot(newer)).changed_ids==()
    newer[1].raw['nodeStreFileNm']='replacement-file'
    changes=compare_nodelink_catalogs(snapshot(original[:2]),snapshot(newer[1:]))
    assert changes.added_ids==('210',) and changes.missing_ids==('221',) and changes.changed_ids==('211',)
    assert len(original)==3 and original[0].data_file
    edited=(replace(original[0],description='수정된 설명'),*original[1:])
    assert compare_nodelink_catalogs(snapshot(original),snapshot(edited)).changed_ids==('221',)
    with pytest.raises(ValueError): compare_nodelink_catalogs(snapshot(original),snapshot(original,{'start_date':'other'}))
    with pytest.raises(ValueError): compare_nodelink_catalogs(snapshot(original),replace(snapshot(original),source_url='other'))
    with pytest.raises(KritsSchemaError): compare_nodelink_catalogs(snapshot(original*2),snapshot(original))


@pytest.fixture
def node_browser(browser,monkeypatch):
    p=browser.page;p.on=Mock();p.remove_listener=Mock();p.wait_for_function=AsyncMock()
    p.wait_for_load_state=AsyncMock()
    async def goto(url,**_kwargs):
        p.url=url
        return SimpleNamespace(status=200)
    p.goto.side_effect=goto
    loc=SimpleNamespace(count=AsyncMock(return_value=1),fill=AsyncMock(),click=AsyncMock(),
                        evaluate_all=AsyncMock(return_value=fixture('nodelink-links')))
    p.locator.side_effect=lambda s:SimpleNamespace(count=AsyncMock(return_value=0)) if ':visible' in s else loc
    action=AsyncMock(return_value=fixture())
    monkeypatch.setattr('krits.client._action_json',action)
    return SimpleNamespace(page=p,loc=loc,action=action)


async def test_public_catalog_ui_scope_and_actual_ids(node_browser):
    b=node_browser
    async with KritsClient() as c:
        result=await c.list_nodelink_releases(start_date=date(2025,10,24),end_date=date(2026,10,24))
    assert len(result.items)==3 and not result.complete
    assert result.scope=={'service':'nodelink','start_date':'2025-10-24','end_date':'2026-10-24'}
    await b.action.call_args.args[2]()
    b.loc.click.assert_awaited_once()
    assert b.action.call_args.args[3]['workingDirectory']=='/nodeLink'


async def test_invalid_period_is_lazy(browser):
    async with KritsClient() as c:
        with pytest.raises(ValueError): await c.list_nodelink_releases(start_date=date(2024,1,1),end_date=date(2026,1,1))
    browser.manager.start.assert_not_awaited()
