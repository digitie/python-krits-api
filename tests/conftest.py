"""기본 테스트에서 live 네트워크 접근을 명시적으로 제외한다."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from krits._browser import BASE_URL


@pytest.fixture
def browser(monkeypatch):
    """기본 테스트가 외부 네트워크·실제 브라우저를 시작하지 못하도록 경계를 모의한다."""
    page = SimpleNamespace(
        close=AsyncMock(), set_default_timeout=Mock(),
        goto=AsyncMock(return_value=SimpleNamespace(status=200)),
        title=AsyncMock(return_value="오픈데이터 | ITS 국가교통정보센터"),
        url=BASE_URL + "/opendata/intro",
        on=Mock(), remove_listener=Mock(),
    )
    page.locator = Mock(side_effect=lambda selector: SimpleNamespace(
        count=AsyncMock(return_value=0 if ":visible" in selector else 1)))
    session = SimpleNamespace(send=AsyncMock(), on=Mock(), remove_listener=Mock(), detach=AsyncMock())
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock(),
                              new_cdp_session=AsyncMock(return_value=session))
    engine = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=engine)),
                                 stop=AsyncMock())
    manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
    monkeypatch.setattr("krits._browser.async_playwright", lambda: manager)
    return SimpleNamespace(page=page, context=context, engine=engine, playwright=playwright,
                           manager=manager, session=session)


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="실제 Chromium/ITS E2E 실행")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live"):
        marker = pytest.mark.skip(reason="--run-live를 지정해야 외부 네트워크를 사용합니다")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(marker)
