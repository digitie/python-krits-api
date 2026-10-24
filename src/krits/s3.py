"""명시적 설정의 선택 S3 보관. MOIS SigV4 구조를 참고한 native async 전송."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import math
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

import httpx

from ._cache import _settle
from ._file_io import run_file_io
from ._ratelimit import AsyncTokenBucket
from .exceptions import KritsAccessError, KritsClosedError, KritsIntegrityError, KritsNetworkError, KritsRateLimitError
from .models import StoredFile
from .storage import CHUNK_SIZE, FileStore


@dataclass(frozen=True, slots=True)
class S3Config:
    """환경변수/기본 credential chain을 탐색하지 않는 명시적 S3 설정."""

    endpoint_url: str
    bucket: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    region: str = "us-east-1"
    prefix: str = "krits"
    session_token: str | None = field(default=None, repr=False)
    allow_http: bool = False

    def __post_init__(self) -> None:
        for value in (self.endpoint_url, self.bucket, self.access_key, self.secret_key, self.region, self.prefix):
            if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(ch) < 32 for ch in value):
                raise ValueError("S3 설정 문자열이 잘못됐습니다")
        endpoint = urlsplit(self.endpoint_url)
        if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username is not None
                or endpoint.password is not None or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
            raise ValueError("S3 endpoint는 인증정보/query/path 없는 origin이어야 합니다")
        if type(self.allow_http) is not bool or endpoint.scheme == "http" and not (
                self.allow_http and endpoint.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("S3는 HTTPS 또는 명시적으로 허용한 loopback HTTP여야 합니다")
        if (re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.bucket) is None
                or any(part in self.bucket for part in ("..", ".-", "-."))):
            raise ValueError("S3 bucket 이름이 잘못됐습니다")
        if re.fullmatch(r"[a-z0-9-]{1,64}", self.region) is None:
            raise ValueError("S3 region이 잘못됐습니다")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.access_key) is None:
            raise ValueError("S3 access_key 형식이 잘못됐습니다")
        if re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", self.prefix) is None:
            raise ValueError("S3 prefix는 안전한 상대 경로여야 합니다")
        if self.session_token is not None and (not isinstance(self.session_token, str) or not self.session_token
                or len(self.session_token) > 16384 or any(ord(ch) < 33 or ord(ch) > 126 for ch in self.session_token)):
            raise ValueError("S3 session_token이 잘못됐습니다")


@dataclass(frozen=True, slots=True)
class S3Object:
    """PUT 후 실제 GET 내용까지 해시 검증한 객체. ETag를 SHA-256으로 해석하지 않는다."""

    endpoint_url: str
    bucket: str
    key: str
    sha256: str
    size_bytes: int


def _sign(method: str, url: str, config: S3Config, payload_hash: str,
          headers: dict[str, str] | None = None, *, now: datetime | None = None) -> dict[str, str]:
    """MOIS SigV4 helper의 canonical header/HMAC 흐름. 전체 본문은 인자로 받지 않는다."""
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ"); date_stamp = timestamp.strftime("%Y%m%d")
    endpoint = urlsplit(url)
    request_headers = {"host": endpoint.netloc, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    request_headers.update({name.lower(): " ".join(value.split()) for name, value in (headers or {}).items()})
    if config.session_token is not None:
        request_headers["x-amz-security-token"] = config.session_token
    canonical_headers = "".join(f"{name}:{value}\n" for name, value in sorted(request_headers.items()))
    signed_headers = ";".join(sorted(request_headers))
    canonical = "\n".join([method, endpoint.path or "/", "", canonical_headers, signed_headers, payload_hash])
    scope = f"{date_stamp}/{config.region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signing_key = ("AWS4" + config.secret_key).encode()
    for value in (date_stamp, config.region, "s3", "aws4_request"):
        signing_key = hmac.new(signing_key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, to_sign.encode(), hashlib.sha256).hexdigest()
    request_headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={config.access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return request_headers


def _status(status: int) -> None:
    if status in (401, 403):
        raise KritsAccessError("S3 접근이 거부됐습니다")
    if status == 429:
        raise KritsRateLimitError("S3 호출 제한입니다")
    if status != 200:
        raise KritsNetworkError(f"S3 HTTP {status}")


def _read_chunk(path: Path, offset: int) -> bytes:
    with path.open("rb") as source:
        source.seek(offset)
        return source.read(CHUNK_SIZE)


async def _chunks(stored: StoredFile) -> AsyncIterator[bytes]:
    offset = 0; digest = hashlib.sha256()
    while offset < stored.size_bytes:
        chunk = await run_file_io(_read_chunk, stored.path, offset)
        if not chunk or offset + len(chunk) > stored.size_bytes:
            raise KritsIntegrityError("S3 전송 중 로컬 파일 길이가 바뀌었습니다")
        offset += len(chunk); digest.update(chunk)
        yield chunk
    if digest.hexdigest() != stored.sha256:
        raise KritsIntegrityError("S3 전송 중 로컬 파일 해시가 바뀌었습니다")


class S3Store:
    """명시한 endpoint/bucket의 원본 업로드·원격 해시 확인. bucket을 자동 생성하지 않는다."""

    def __init__(self, config: S3Config, *, timeout: float = 90, max_rps: float = 5,
                 rate_limiter: AsyncTokenBucket | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not isinstance(config, S3Config):
            raise ValueError("S3Config가 필요합니다")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout은 유한한 양수여야 합니다")
        self._config = config; self.timeout = timeout; self.rate_limiter = rate_limiter or AsyncTokenBucket(max_rps, capacity=1)
        self._transport = transport; self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock(); self._closed = False; self._closing = False

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("S3Store는 한 이벤트 루프에서 사용해야 합니다")
        self.rate_limiter._bind_loop()

    async def __aenter__(self) -> S3Store:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """진행 중 업로드/검증을 기다린 뒤 소유 HTTP client를 닫는다."""
        self._bind_loop(); self._closing = True
        async def close() -> None:
            async with self._lock:
                self._closed = True
                if self._client is not None:
                    await self._client.aclose()
                    self._client = None
        task = asyncio.create_task(close())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await _settle(task)
            raise

    async def put_file(self, store: FileStore, stored: StoredFile) -> S3Object:
        """로컬 재검증 → signed PUT → 실제 GET 크기/SHA-256 검증을 수행한다."""
        self._bind_loop()
        if self._closed or self._closing:
            raise KritsClosedError("종료된 S3Store입니다")
        try:
            async with asyncio.timeout(self.timeout):
                async with self._lock:
                    if self._closed:
                        raise KritsClosedError("종료된 S3Store입니다")
                    checked = await store.verify(stored)
                    key = f"{self._config.prefix}/objects/{checked.sha256[:2]}/{checked.sha256}"
                    path = "/" + "/".join(quote(part, safe="-_.~") for part in (self._config.bucket + "/" + key).split("/"))
                    url = self._config.endpoint_url.rstrip("/") + path
                    if self._client is None:
                        self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, trust_env=False, transport=self._transport)
                    await self.rate_limiter.acquire()
                    headers = _sign("PUT", url, self._config, checked.sha256,
                                    {"content-length": str(checked.size_bytes), "content-type": "application/octet-stream"})
                    async with self._client.stream("PUT", url, headers=headers, content=_chunks(checked), follow_redirects=False) as response:
                        _status(response.status_code)
                    await self.rate_limiter.acquire()
                    headers = _sign("GET", url, self._config, hashlib.sha256(b"").hexdigest(), {"accept-encoding": "identity"})
                    digest = hashlib.sha256(); received = 0
                    async with self._client.stream("GET", url, headers=headers, follow_redirects=False) as response:
                        _status(response.status_code)
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise KritsIntegrityError("S3 검증 응답의 전송 압축은 허용하지 않습니다")
                        length = response.headers.get("content-length")
                        if length is not None and (re.fullmatch(r"[0-9]{1,20}", length) is None or int(length) != checked.size_bytes):
                            raise KritsIntegrityError("S3 객체 선언 길이가 로컬 원본과 다릅니다")
                        async for chunk in response.aiter_raw(CHUNK_SIZE):
                            received += len(chunk)
                            if received > checked.size_bytes:
                                raise KritsIntegrityError("S3 객체 실제 길이가 로컬 원본보다 큽니다")
                            digest.update(chunk)
                    if received != checked.size_bytes or digest.hexdigest() != checked.sha256:
                        raise KritsIntegrityError("S3 객체 크기/SHA-256이 로컬 원본과 다릅니다")
                    await store.verify(stored)
                    return S3Object(self._config.endpoint_url, self._config.bucket, key, checked.sha256, checked.size_bytes)
        except (httpx.HTTPError, TimeoutError):
            raise KritsNetworkError("S3 전송/검증 통신 또는 시간 제한 실패") from None
        except OSError as exc:
            raise KritsIntegrityError("S3 전송 중 로컬 파일 읽기가 실패했습니다") from exc
