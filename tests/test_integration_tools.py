"""설치본 검증이 실제 추가 전송과 경로 별칭을 놓치지 않는지 확인한다."""

from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from krits import FileAttachment
from tools.installed_e2e import is_within, reuse_file


def test_external_directory_guard_handles_inside_outside_and_extended_alias(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    assert is_within(root, root)
    assert is_within(root / "new-store", root)
    assert not is_within(tmp_path / "external", root)
    if os.name == "nt":
        alias = Path("\\\\?\\" + str(root)).resolve()
        assert alias.samefile(root)
        assert is_within(alias, root)
        assert is_within(alias / "new-store", root)


@pytest.mark.parametrize("mode", ["match", "changed", "missing", "unexpected_network"])
async def test_reuse_check_requires_same_metadata_and_zero_browser_operations(mode):
    attachment = FileAttachment("nodelink", "001", "01", "original.zip",
                                "https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_001/01", None, {})
    stored = SimpleNamespace(attachment=attachment)
    store = SimpleNamespace(current=AsyncMock(return_value=None if mode == "missing" else stored))
    original = Mock()
    client = SimpleNamespace(_browser=SimpleNamespace(operation=original))

    async def download(*_args, **_kwargs):
        if mode == "unexpected_network":
            client._browser.operation()
        return stored

    client.download_file = AsyncMock(side_effect=download)
    query = replace(attachment, name="renamed.zip") if mode == "changed" else attachment
    if mode == "match":
        assert await reuse_file(client, store, query) == stored
    else:
        with pytest.raises(AssertionError):
            await reuse_file(client, store, query)
    if mode in ("changed", "missing"):
        client.download_file.assert_not_awaited()
    assert client._browser.operation is original
    original.assert_not_called()
