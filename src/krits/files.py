"""Chromium CDP 스트림으로 공개 첨부를 제한된 청크로 보관한다."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import CDPSession, Error as PlaywrightError

from ._browser import BrowserSession, _intercept_request
from ._file_io import run_file_io
from .exceptions import KritsAccessError, KritsIntegrityError, KritsNetworkError, KritsRateLimitError
from .models import FileAttachment, StoredFile
from .storage import CHUNK_SIZE, FileStore, _metadata

DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
_PATH = re.compile(r"(?:/opendata/nodelinkFileSDownload/[A-Za-z0-9_-]+/[0-9]+|"
                   r"/opendata/fileDownload/(?:traffic|event|vms)/[0-9]{4}/[A-Za-z0-9_-]+\.[A-Za-z0-9]+|"
                   r"/file/opendata/weakSections/[A-Za-z0-9_-]+\.csv)")


def validate_attachment(attachment: FileAttachment, max_bytes: int) -> None:
    """다운로드 URL과 입력 크기를 네트워크 이전에 검증한다."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes는 양의 정수여야 합니다")
    if not isinstance(attachment, FileAttachment):
        raise ValueError("FileAttachment가 필요합니다")
    for value in (attachment.service, attachment.name, attachment.download_url):
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ValueError("첨부 문자열 필드가 잘못됐습니다")
    url = urlsplit(attachment.download_url)
    if (url.scheme != "https" or url.netloc != "www.its.go.kr" or url.query or url.fragment
            or _PATH.fullmatch(url.path) is None):
        raise ValueError("공개 ITS 첨부 URL만 다운로드할 수 있습니다")
    for identifier in (attachment.file_id, attachment.attachment_id):
        if identifier is not None and (not isinstance(identifier, str) or not identifier or len(identifier) > 4096):
            raise ValueError("첨부 식별자는 문자열이어야 합니다")
    size = attachment.size_bytes
    if size is not None and (type(size) is not int or size < 0):
        raise ValueError("첨부 바이트 수가 잘못됐습니다")
    if size is not None and size > max_bytes:
        raise KritsIntegrityError("발견된 첨부 크기가 다운로드 상한을 넘습니다")


def _headers(event: dict[str, Any], attachment: FileAttachment, max_bytes: int) -> tuple[str, int | None]:
    status = event.get("responseStatusCode")
    if status in (401, 403):
        raise KritsAccessError("공개 파일 접근이 거부됐습니다")
    if status == 429:
        raise KritsRateLimitError("공개 파일 호출 제한입니다")
    if isinstance(status, int) and 300 <= status < 400:
        raise KritsAccessError("파일 리디렉션은 따라가지 않습니다")
    if status != 200:
        raise KritsNetworkError(f"공개 파일 HTTP {status}")
    headers: dict[str, str] = {}
    for header in event.get("responseHeaders", []):
        key = header["name"].lower()
        if key in headers and key in {"content-length", "content-type", "content-encoding"}:
            raise KritsIntegrityError("파일 응답의 중요 헤더가 중복됐습니다")
        headers[key] = header["value"]
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type in {"text/html", "application/xhtml+xml", "application/json", "text/xml", "application/xml"}:
        raise KritsIntegrityError("첨부 대신 HTML/오류 응답을 받았습니다")
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise KritsIntegrityError("전송 압축 응답은 원문 길이 검증 계약을 지원하지 않습니다")
    length: int | None = None
    if "content-length" in headers:
        raw_length = headers["content-length"]
        if re.fullmatch(r"[0-9]{1,20}", raw_length) is None:
            raise KritsIntegrityError("Content-Length 형식이 잘못됐습니다")
        length = int(raw_length)
        if length > max_bytes or (attachment.size_bytes is not None and length != attachment.size_bytes):
            raise KritsIntegrityError("응답 길이가 상한 또는 발견 크기와 다릅니다")
    return content_type, length


def _append(path: Path, chunk: bytes) -> None:
    with path.open("ab") as output:
        output.write(chunk)


def _sync(path: Path) -> None:
    import os
    with path.open("ab") as output:
        output.flush(); os.fsync(output.fileno())


async def download_file(browser: BrowserSession, attachment: FileAttachment, store: FileStore,
                        *, max_bytes: int, refresh: bool) -> StoredFile:
    """재검증한 보관본을 재사용하거나 명시적으로 새 전송을 수행한다."""
    validate_attachment(attachment, max_bytes)
    await store.versions(attachment)
    current = await store.current(attachment)
    if not refresh and current is not None and _metadata(current.attachment) == _metadata(attachment):
        if current.size_bytes > max_bytes:
            raise KritsIntegrityError("보관본 크기가 명시한 상한을 넘습니다")
        return current
    temporary: list[Path] = []
    try:
        await run_file_io(lambda: temporary.append(store._temporary()))
        async with browser.operation() as page:
            await page.goto("about:blank")
            response: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

            async def handle(session: CDPSession, event: dict[str, Any]) -> None:
                try:
                    if "responseStatusCode" in event or "responseErrorReason" in event:
                        if event.get("responseStatusCode") in (401, 403, 429):
                            browser._denied_status = event["responseStatusCode"]
                        if not response.done():
                            response.set_result(event)
                    elif event["request"]["url"] != attachment.download_url:
                        await session.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})
                    else:
                        await _intercept_request(session, event, browser.rate_limiter,
                                                 lambda: browser._denied_status is not None, intercept_response=True)
                except Exception as exc:
                    if not response.done():
                        response.set_exception(exc)

            browser._request_handler = handle
            navigation = asyncio.create_task(page.goto(attachment.download_url))
            # 끝난 navigation 예외도 조회 대기 중 즉시 회수한다.
            navigation.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            stream: str | None = None
            try:
                event = await response
                content_type, expected_length = _headers(event, attachment, max_bytes)
                session = browser._cdp
                assert session is not None
                stream = (await session.send("Fetch.takeResponseBodyAsStream", {"requestId": event["requestId"]}))["stream"]
                digest = hashlib.sha256(); size = 0; prefix = b""
                while True:
                    data = await session.send("IO.read", {"handle": stream, "size": CHUNK_SIZE})
                    try:
                        chunk = base64.b64decode(data["data"], validate=True) if data.get("base64Encoded") else data["data"].encode("utf-8")
                    except (ValueError, binascii.Error) as exc:
                        raise KritsIntegrityError("Chromium 스트림 인코딩이 잘못됐습니다") from exc
                    if len(chunk) > CHUNK_SIZE:
                        raise KritsIntegrityError("Chromium 청크 크기 상한을 넘었습니다")
                    size += len(chunk)
                    if size > max_bytes:
                        raise KritsIntegrityError("실제 수신 바이트가 다운로드 상한을 넘었습니다")
                    prefix = (prefix + chunk)[:1024]
                    visible_prefix = prefix.lstrip(b"\xef\xbb\xbf\x00 \r\n\t").lower()
                    if prefix.startswith((b"\xff\xfe", b"\xfe\xff")):
                        visible_prefix = prefix.decode("utf-16", errors="ignore").lstrip().encode("utf-8")
                    if visible_prefix.startswith((b"<", b"{", b"[")):
                        raise KritsIntegrityError("첨부 본문이 HTML/JSON 오류 응답입니다")
                    digest.update(chunk)
                    if chunk:
                        await run_file_io(_append, temporary[0], chunk)
                    if data.get("eof"):
                        break
                if (size == 0 or (expected_length is not None and size != expected_length)
                        or (attachment.size_bytes is not None and size != attachment.size_bytes)):
                    raise KritsIntegrityError("실제 수신 길이가 비어 있거나 선언 길이와 다릅니다")
                await run_file_io(_sync, temporary[0])
            finally:
                # stream은 page 종료로도 회수된다. 반복 취소 정리는 BrowserSession이 보장한다.
                browser._request_handler = None
                await browser._dispose()
                await asyncio.gather(navigation, return_exceptions=True)
        return await run_file_io(store._publish, temporary[0], attachment, digest.hexdigest(), size, content_type)
    except PlaywrightError:
        raise KritsNetworkError("Chromium 파일 스트림 통신 실패") from None
    except OSError as exc:
        raise KritsIntegrityError("파일 staging 또는 원본/manifest 저장이 실패했습니다") from exc
    finally:
        if temporary:
            await run_file_io(temporary[0].unlink, missing_ok=True)
