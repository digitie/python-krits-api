"""기본 테스트에서 live 네트워크 접근을 명시적으로 제외한다."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="실제 Chromium/ITS E2E 실행")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live"):
        marker = pytest.mark.skip(reason="--run-live를 지정해야 외부 네트워크를 사용합니다")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(marker)
