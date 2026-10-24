"""완료 캐시·진행 요청 공유·취소와 실패의 서버 재호출 경계를 검증한다."""

import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from krits import KritsClient,KritsClosedError,KritsRateLimitError,KritsSchemaError,DataSnapshot
from krits._cache import RequestCache,_copy


@pytest.mark.parametrize('ttl,entries',[(True,1),(-1,1),(float('nan'),1),(float('inf'),1),(1,True),(1,0),(1,1.5)])
def test_invalid_cache_configuration(ttl,entries):
    with pytest.raises(ValueError): RequestCache(ttl,entries)


async def test_cache_hit_expiry_clear_and_lru(monkeypatch):
    now=[10.0];monkeypatch.setattr('krits._cache.time.monotonic',lambda:now[0])
    cache=RequestCache(5,2);fetch=AsyncMock(return_value={'rows':[1]})
    a=await cache.get('a',fetch);a['rows'].append(9)
    assert await cache.get('a',fetch)=={'rows':[1]}
    await cache.get('b',fetch);await cache.get('a',fetch);await cache.get('c',fetch)
    assert list(cache._entries)==['a','c']
    await cache.get('b',fetch)
    assert fetch.await_count==4
    now[0]=20
    await cache.get('b',fetch);assert fetch.await_count==5
    cache.clear();await cache.get('b',fetch);assert fetch.await_count==6
    await cache.aclose()
    with pytest.raises(KritsClosedError): await cache.get('b',fetch)


async def test_same_flight_one_fetch_and_independent_results_with_cache_disabled():
    cache=RequestCache(0,2);started=asyncio.Event();release=asyncio.Event();count=0
    async def fetch():
        nonlocal count
        count+=1;started.set();await release.wait();return {'rows':[1]}
    a=asyncio.create_task(cache.get('same',fetch));await started.wait()
    b=asyncio.create_task(cache.get('same',fetch));await asyncio.sleep(0)
    release.set();first,second=await asyncio.gather(a,b)
    first['rows'].append(9);assert second=={'rows':[1]} and count==1
    await cache.get('same',fetch);assert count==2
    await cache.aclose()


async def test_one_cancelled_waiter_does_not_cancel_other_waiter():
    cache=RequestCache(1,2);started=asyncio.Event();release=asyncio.Event();fetch=AsyncMock()
    async def slow():started.set();await release.wait();return [1]
    fetch.side_effect=slow
    a=asyncio.create_task(cache.get('a',fetch));await started.wait()
    b=asyncio.create_task(cache.get('a',fetch));await asyncio.sleep(0)
    a.cancel()
    with pytest.raises(asyncio.CancelledError): await a
    release.set();assert await b==[1]
    fetch.assert_awaited_once();await cache.aclose()


async def test_last_waiter_repeated_cancel_finishes_fetch_cleanup():
    cache=RequestCache(1,2);started=asyncio.Event();cleaning=asyncio.Event();release=asyncio.Event()
    async def slow():
        try:started.set();await asyncio.Event().wait()
        finally:cleaning.set();await release.wait()
    a=asyncio.create_task(cache.get('a',slow));await started.wait();a.cancel();await cleaning.wait()
    a.cancel();await asyncio.sleep(0);assert not a.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):await a
    assert not cache._flights and not cache._entries
    await cache.aclose()


async def test_failure_shared_but_not_cached_or_retried():
    cache=RequestCache(15,2);started=asyncio.Event();release=asyncio.Event();count=0
    async def fail():
        nonlocal count
        count+=1;started.set();await release.wait();raise KritsSchemaError('오류')
    a=asyncio.create_task(cache.get('a',fail));await started.wait()
    b=asyncio.create_task(cache.get('a',fail));await asyncio.sleep(0);release.set()
    results=await asyncio.gather(a,b,return_exceptions=True)
    assert all(isinstance(r,KritsSchemaError) for r in results) and count==1
    with pytest.raises(KritsSchemaError):await cache.get('a',fail)
    assert count==2 and not cache._entries
    await cache.aclose()


async def test_clear_during_fetch_does_not_repopulate_cache():
    cache=RequestCache(15,2);started=asyncio.Event();release=asyncio.Event()
    async def fetch():started.set();await release.wait();return [1]
    task=asyncio.create_task(cache.get('a',fetch));await started.wait();cache.clear();release.set()
    assert await task==[1] and not cache._entries
    await cache.aclose()


async def test_close_waits_active_fetch_and_repeated_cancel_then_clears():
    cache=RequestCache(15,2);started=asyncio.Event();release=asyncio.Event()
    await cache.get('old',AsyncMock(return_value=[0]))
    async def fetch():started.set();await release.wait();return [1]
    task=asyncio.create_task(cache.get('a',fetch));await started.wait()
    closing=asyncio.create_task(cache.aclose());await asyncio.sleep(0);closing.cancel();await asyncio.sleep(0)
    closing.cancel();await asyncio.sleep(0);assert not closing.done()
    release.set();assert await task==[1]
    with pytest.raises(asyncio.CancelledError):await closing
    assert not cache._entries
    await cache.aclose();assert not cache._entries


def test_recursive_copy_error_is_explicit():
    class BadCopy:
        def __deepcopy__(self,_memo):raise RecursionError
    with pytest.raises(KritsSchemaError):_copy(BadCopy())


async def test_client_cache_normalizes_defaults_preserves_time_and_isolates_raw(browser,monkeypatch):
    raw={'id':'001'}
    value=DataSnapshot((raw,),'https://www.its.go.kr/map/outbreak',datetime.now(timezone.utc),{})
    fetch=AsyncMock(return_value=value)
    monkeypatch.setattr('krits.client.parse_events',lambda *_args:value.items)
    monkeypatch.setattr('krits.client._action_json',fetch)
    browser.page.goto=AsyncMock()
    async with KritsClient() as c:
        first=await c.get_events()
        second=await c.get_events(road_type=None)
        assert first.collected_at==second.collected_at and fetch.await_count==1
        first.items[0]['id']='changed'
        assert second.items[0]['id']=='001'
        c.clear_cache();await c.get_events();assert fetch.await_count==2
    with pytest.raises(KritsClosedError):await c.get_events()


async def test_unhashable_invalid_query_keeps_original_validation(browser):
    async with KritsClient() as c:
        with pytest.raises(ValueError):await c.search_cctvs([])
    browser.manager.start.assert_not_awaited()


async def test_cached_client_cannot_cross_loops(browser):
    c=KritsClient()
    c._browser._loop=object()
    with pytest.raises(RuntimeError):await c.get_events()


async def test_cached_success_never_hides_late_first_party_denial(browser,monkeypatch):
    fetch=AsyncMock(return_value={})
    monkeypatch.setattr('krits.client._action_json',fetch)
    monkeypatch.setattr('krits.client.parse_events',lambda *_args:())
    async with KritsClient() as c:
        await c.get_events()
        observe=browser.page.on.call_args.args[1]
        observe(SimpleNamespace(status=429,url='https://www.its.go.kr/asset',request=SimpleNamespace(resource_type='xhr')))
        await asyncio.sleep(0)
        with pytest.raises(KritsRateLimitError):await c.get_events()
        fetch.assert_awaited_once()
        assert not c._query_cache._entries
