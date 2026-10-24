"""실제 브라우저 없이 소유권·경쟁·취소·오류 경계를 검증한다."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from playwright.async_api import Error as PlaywrightError
import pytest

from krits import (
    AsyncTokenBucket, KritsAccessError, KritsClient, KritsClosedError,
    KritsNetworkError, KritsRateLimitError, KritsSchemaError,
)
from krits._browser import BASE_URL, _allowed_resource, _intercept_request


async def test_lazy_snapshot_and_owned_cleanup(browser):
    client = KritsClient()
    browser.manager.start.assert_not_awaited()
    async with client:
        browser.manager.start.assert_not_awaited()
        result = await client.get_page_snapshot()
        assert result.source_url == browser.page.url
        assert result.collected_at.utcoffset().total_seconds() == 0
        assert "ITS" in result.title
    for resource in (browser.page, browser.context, browser.engine):
        resource.close.assert_awaited_once()
    browser.playwright.stop.assert_awaited_once()
    await client.aclose()
    with pytest.raises(KritsClosedError):
        await client.get_page_snapshot()
    browser.page.goto.assert_awaited_once()


async def test_unused_client_close_has_no_browser(browser):
    client = KritsClient()
    await client.aclose()
    browser.manager.start.assert_not_awaited()


async def test_external_context_only_owns_new_page(browser):
    async with KritsClient(browser_context=browser.context) as client:
        await client.get_page_snapshot()
    browser.manager.start.assert_not_awaited()
    browser.context.close.assert_not_awaited()
    browser.page.close.assert_awaited_once()


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        KritsClient(timeout=timeout)


def test_external_context_excludes_launch_path(browser):
    with pytest.raises(ValueError):
        KritsClient(browser_context=browser.context, executable_path="chromium")


async def test_invalid_page_never_starts_browser(browser):
    async with KritsClient() as client:
        with pytest.raises(ValueError):
            await client.get_page_snapshot("https://untrusted.example/")
    browser.manager.start.assert_not_awaited()


@pytest.mark.parametrize("status,error", [
    (401, KritsAccessError), (403, KritsAccessError), (429, KritsRateLimitError),
    (404, KritsNetworkError), (500, KritsNetworkError),
])
async def test_http_errors_have_no_retries(browser, status, error):
    browser.page.goto.return_value.status = status
    async with KritsClient() as client:
        with pytest.raises(error):
            await client.get_page_snapshot()
    browser.page.goto.assert_awaited_once()
    browser.page.close.assert_awaited_once()


async def test_missing_response(browser):
    browser.page.goto.return_value = None
    async with KritsClient() as client:
        with pytest.raises(KritsNetworkError):
            await client.get_page_snapshot()


async def test_login_redirect_is_not_success(browser):
    browser.page.url = BASE_URL + "/user/login"
    async with KritsClient() as client:
        with pytest.raises(KritsAccessError):
            await client.get_page_snapshot()


async def test_schema_error_is_not_empty_result(browser):
    browser.page.title.return_value = "서비스 점검"
    async with KritsClient() as client:
        with pytest.raises(KritsSchemaError):
            await client.get_page_snapshot()


@pytest.mark.parametrize("title", ["보안 확인 | ITS 국가교통정보센터", "로그인 | ITS 국가교통정보센터"])
async def test_http_200_access_screen_is_rejected(browser, title):
    browser.page.title.return_value = title
    async with KritsClient() as client:
        with pytest.raises(KritsAccessError):
            await client.get_page_snapshot()


async def test_captcha_element_is_rejected(browser):
    browser.page.locator.return_value = SimpleNamespace(count=AsyncMock(return_value=1))
    browser.page.locator.side_effect = None
    async with KritsClient() as client:
        with pytest.raises(KritsAccessError):
            await client.get_page_snapshot()


async def test_missing_normal_container_is_schema_error(browser):
    browser.page.locator.side_effect = None
    browser.page.locator.return_value = SimpleNamespace(count=AsyncMock(return_value=0))
    async with KritsClient() as client:
        with pytest.raises(KritsSchemaError):
            await client.get_page_snapshot()


async def test_partial_initialization_failure_cleans_all_acquired_resources(browser):
    browser.context.new_page.side_effect = PlaywrightError("private session information")
    async with KritsClient() as client:
        with pytest.raises(KritsNetworkError) as error:
            await client.get_page_snapshot()
    assert "private" not in str(error.value)
    browser.context.close.assert_awaited_once()
    browser.engine.close.assert_awaited_once()
    browser.playwright.stop.assert_awaited_once()


async def test_launch_failure_stops_playwright(browser):
    browser.playwright.chromium.launch.side_effect = PlaywrightError("missing executable")
    async with KritsClient() as client:
        with pytest.raises(KritsNetworkError):
            await client.get_page_snapshot()
    browser.playwright.stop.assert_awaited_once()


async def test_timeout_is_bounded_and_cleans_resources(browser):
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    browser.page.goto.side_effect = stalled
    async with KritsClient(timeout=0.01) as client:
        with pytest.raises(KritsNetworkError):
            await client.get_page_snapshot()
    browser.page.close.assert_awaited_once()


async def test_cancelled_request_finishes_cleanup_even_when_cancelled_again(browser):
    started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stalled(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    async def slow_close():
        closing.set()
        await release.wait()

    browser.page.goto.side_effect = stalled
    browser.page.close.side_effect = slow_close
    client = KritsClient()
    task = asyncio.create_task(client.get_page_snapshot())
    await started.wait()
    task.cancel()
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    browser.context.close.assert_awaited_once()
    await client.aclose()


@pytest.mark.parametrize("stage", ["start", "launch", "context", "page"])
async def test_cancellation_during_resource_acquisition_waits_and_closes(browser, stage):
    started, release = asyncio.Event(), asyncio.Event()
    create, result = {
        "start": (browser.manager.start, browser.playwright),
        "launch": (browser.playwright.chromium.launch, browser.engine),
        "context": (browser.engine.new_context, browser.context),
        "page": (browser.context.new_page, browser.page),
    }[stage]

    async def delayed_creation(*args, **kwargs):
        started.set()
        await release.wait()
        return result

    create.side_effect = delayed_creation
    client = KritsClient()
    task = asyncio.create_task(client.get_page_snapshot())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    if stage != "start":
        browser.engine.close.assert_awaited_once()
    browser.playwright.stop.assert_awaited_once()
    if stage == "page":
        browser.page.close.assert_awaited_once()
    await client.aclose()


async def test_cancelled_acquisition_failure_preserves_cancellation(browser):
    started, release = asyncio.Event(), asyncio.Event()

    async def failed_creation(*args, **kwargs):
        started.set()
        await release.wait()
        raise PlaywrightError("creation failed")

    browser.context.new_page.side_effect = failed_creation
    client = KritsClient()
    task = asyncio.create_task(client.get_page_snapshot())
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    browser.context.close.assert_awaited_once()
    await client.aclose()


async def test_resource_acquisition_itself_can_be_cancelled(browser):
    browser.context.new_page.side_effect = asyncio.CancelledError()
    async with KritsClient() as client:
        with pytest.raises(asyncio.CancelledError):
            await client.get_page_snapshot()
    browser.context.close.assert_awaited_once()


async def test_cleanup_failure_attempts_remaining_resources(browser):
    client = KritsClient()
    await client.get_page_snapshot()
    browser.page.close.side_effect = PlaywrightError("failed close")
    with pytest.raises(KritsNetworkError):
        await client.aclose()
    browser.context.close.assert_awaited_once()
    browser.engine.close.assert_awaited_once()
    browser.playwright.stop.assert_awaited_once()


async def test_cleanup_error_does_not_hide_original_failure(browser):
    browser.page.title.return_value = "점검"
    browser.page.close.side_effect = PlaywrightError("failed close")
    client = KritsClient()
    with pytest.raises(KritsSchemaError):
        await client.get_page_snapshot()
    with pytest.raises(KritsClosedError):
        await client.get_page_snapshot()
    await client.aclose()


async def test_operations_and_close_are_serialized(browser):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_goto(*args, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(status=200)

    browser.page.goto.side_effect = slow_goto
    client = KritsClient(rate_limiter=AsyncTokenBucket(10000))
    first = asyncio.create_task(client.get_page_snapshot())
    await started.wait()
    second = asyncio.create_task(client.get_page_snapshot())
    closing = asyncio.create_task(client.aclose())
    await asyncio.sleep(0)
    assert browser.page.goto.await_count == 1
    assert not closing.done()
    release.set()
    await asyncio.gather(first, second, closing)
    assert browser.page.goto.await_count == 2
    browser.manager.start.assert_awaited_once()


async def test_wire_limiter_wait_respects_timeout_and_aborts_paused_request(browser):
    async def goto(url, **_kwargs):
        callback = browser.session.on.call_args.args[1]
        await callback({"requestId":"1", "request":{"url":url}, "resourceType":"Document"})
        return SimpleNamespace(status=200)

    browser.page.goto.side_effect = goto
    client = KritsClient(timeout=0.1, max_rps=0.01)
    await client.get_page_snapshot()
    with pytest.raises(KritsNetworkError, match="시간 제한"):
        await asyncio.wait_for(client.get_page_snapshot(), 1)
    browser.page.close.assert_awaited_once()
    await client.aclose()


async def test_lock_wait_timeout_does_not_close_other_operation_page(browser):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_goto(*args, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(status=200)

    browser.page.goto.side_effect = slow_goto
    client = KritsClient(timeout=10)
    first = asyncio.create_task(client.get_page_snapshot())
    await started.wait()
    client._browser.timeout = 0.01
    with pytest.raises(KritsNetworkError, match="시간 제한"):
        await asyncio.wait_for(client.get_page_snapshot(), 1)
    browser.page.close.assert_not_awaited()
    release.set()
    await first
    await client.aclose()


def test_client_cannot_cross_event_loops(browser):
    client = KritsClient()
    asyncio.run(client.aclose())
    with pytest.raises(RuntimeError, match="이벤트 루프"):
        asyncio.run(client.aclose())


@pytest.mark.parametrize("url,kind,allowed", [
    (BASE_URL + "/map/getMarkers", "xhr", True),
    (BASE_URL + "/js/map.js", "script", True),
    (BASE_URL + "/css/image.png", "image", False),
    ("https://external.example/map.js", "script", False),
    ("http://www.its.go.kr/map", "document", False),
    ("https://openapi.its.go.kr/trafficInfo", "fetch", False),
    ("https://www.its.go.kr:9443/tiles", "fetch", False),
])
async def test_resource_filter(url, kind, allowed):
    assert _allowed_resource(url, kind) is allowed
    session = SimpleNamespace(send=AsyncMock())
    await _intercept_request(session, {"requestId": "1", "request": {"url": url}, "resourceType": kind})
    assert session.send.call_args.args[0] == ("Fetch.continueRequest" if allowed else "Fetch.failRequest")


async def test_closed_cdp_session_does_not_leave_unhandled_exception():
    session = SimpleNamespace(send=AsyncMock(side_effect=PlaywrightError("closed")))
    await _intercept_request(session, {"requestId": "1", "request": {"url": BASE_URL}, "resourceType": "Document"})


async def test_cdp_handler_is_removed_and_session_detached_with_owned_page(browser):
    client = KritsClient()
    await client.get_page_snapshot()
    callback = browser.session.on.call_args.args[1]
    await callback({"requestId": "1", "request": {"url": BASE_URL}, "resourceType": "Document"})
    await client.aclose()
    browser.session.remove_listener.assert_called_once_with("Fetch.requestPaused", callback)
    browser.session.detach.assert_awaited_once()
    assert browser.context.close.await_count == 1


async def test_automatic_detach_on_closed_page_is_safe(browser):
    browser.session.detach.side_effect = PlaywrightError("already detached")
    async with KritsClient() as client:
        await client.get_page_snapshot()
    browser.context.close.assert_awaited_once()


async def test_paused_wire_waiters_cancel_before_page_close(browser):
    client=KritsClient(max_rps=0.01)
    await client.get_page_snapshot()
    callback=browser.session.on.call_args.args[1]
    event={"requestId":"1","request":{"url":BASE_URL},"resourceType":"Document"}
    await callback(event)
    waiting=callback({**event,"requestId":"2"})
    await asyncio.sleep(0)
    assert not waiting.done()
    await client.aclose()
    assert waiting.cancelled()
    browser.page.close.assert_awaited_once()


async def test_shared_bucket_loop_mismatch_fails_before_browser_start(browser):
    bucket=AsyncTokenBucket();bucket._loop=object()
    async with KritsClient(rate_limiter=bucket) as client:
        with pytest.raises(RuntimeError,match='single event loop'):await client.get_page_snapshot()
    browser.manager.start.assert_not_awaited()


async def test_blocked_resource_never_consumes_token():
    session=SimpleNamespace(send=AsyncMock());bucket=SimpleNamespace(acquire=AsyncMock())
    await _intercept_request(session,{"requestId":"1","request":{"url":"https://openapi.its.go.kr/a"},"resourceType":"Fetch"},bucket)
    bucket.acquire.assert_not_awaited()
    await _intercept_request(session,{"requestId":"2","request":{"url":BASE_URL},"resourceType":"Document"},bucket)
    bucket.acquire.assert_awaited_once()


async def test_denial_while_waiting_for_token_never_continues_request():
    blocked=[False]
    async def acquire():blocked[0]=True
    session=SimpleNamespace(send=AsyncMock());bucket=SimpleNamespace(acquire=AsyncMock(side_effect=acquire))
    event={"requestId":"1","request":{"url":BASE_URL},"resourceType":"Document"}
    await _intercept_request(session,event,bucket,lambda:blocked[0])
    assert session.send.call_args.args[0]=='Fetch.failRequest'
    await _intercept_request(session,event,bucket,lambda:True)
    bucket.acquire.assert_awaited_once()


@pytest.mark.parametrize('status,error',[(401,KritsAccessError),(403,KritsAccessError),(429,KritsRateLimitError)])
async def test_idle_asset_denial_is_not_ignored_on_next_operation(browser,status,error):
    async with KritsClient() as c:
        await c.get_page_snapshot()
        observe=browser.page.on.call_args.args[1]
        observe(SimpleNamespace(status=200,url=BASE_URL,request=SimpleNamespace(resource_type='document')))
        observe(SimpleNamespace(status=status,url=BASE_URL+'/css/main.css',request=SimpleNamespace(resource_type='stylesheet')))
        await asyncio.sleep(0)
        with pytest.raises(error):await c.get_page_snapshot()
    browser.context.close.assert_awaited_once()
