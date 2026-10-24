"""내용 해시 기반 원본과 첨부별 불변 manifest. 파일명은 저장 경로로 쓰지 않는다."""

from __future__ import annotations

import base64
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

from ._file_io import run_file_io
from .exceptions import KritsIntegrityError
from .models import FileAttachment, FileInspection, StoredFile

CHUNK_SIZE = 64 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")


def _metadata(attachment: FileAttachment) -> dict[str, Any]:
    # raw에는 브라우저/세션성 필드를 넣을 수 있으므로 manifest에 복사하지 않는다.
    return {"service": attachment.service, "file_id": attachment.file_id,
            "attachment_id": attachment.attachment_id, "name": attachment.name,
            "download_url": attachment.download_url, "size_bytes": attachment.size_bytes}


def _identity(attachment: FileAttachment) -> str:
    value = [attachment.service, attachment.file_id, attachment.attachment_id, attachment.download_url]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


class FileStore:
    """명시한 로컬 root의 원본/manifest 관리. 생성자는 파일·네트워크 I/O를 하지 않는다."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()

    def _path(self, *parts: str, mkdir: bool = False) -> Path:
        root = self.root.resolve()
        path = root.joinpath(*parts)
        for candidate in (path, *path.parents):
            if candidate == root:
                break
            if candidate.is_symlink():
                raise KritsIntegrityError("보관 경로에 심볼릭 링크가 있습니다")
        if not path.resolve().is_relative_to(root):
            raise KritsIntegrityError("보관 경로가 root를 벗어났습니다")
        if mkdir:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _object(self, sha256: str) -> Path:
        if _HASH.fullmatch(sha256) is None:
            raise KritsIntegrityError("manifest SHA-256 형식이 잘못됐습니다")
        return self._path("objects", sha256[:2], sha256)

    def _read(self, manifest: Path, expected_identity: str | None = None) -> StoredFile:
        try:
            if manifest.stat().st_size > 64 * 1024:
                raise KritsIntegrityError("manifest 크기 상한을 넘었습니다")
            with manifest.open("r", encoding="utf-8") as source:
                data = json.load(source)
            if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("status") != "verified":
                raise ValueError
            attachment_data = data["attachment"]
            if not isinstance(attachment_data, dict) or set(attachment_data) != {
                    "service", "file_id", "attachment_id", "name", "download_url", "size_bytes"}:
                raise ValueError
            for name in ("service", "name", "download_url"):
                if not isinstance(attachment_data[name], str) or not attachment_data[name]:
                    raise ValueError
            for name in ("file_id", "attachment_id"):
                if attachment_data[name] is not None and not isinstance(attachment_data[name], str):
                    raise ValueError
            declared = attachment_data["size_bytes"]
            if declared is not None and (type(declared) is not int or declared < 0):
                raise ValueError
            attachment = FileAttachment(**attachment_data, raw={})
            identity = _identity(attachment)
            if expected_identity is not None and identity != expected_identity:
                raise ValueError
            sha = data["sha256"]
            if not isinstance(sha, str) or manifest != self._path("manifests", identity, sha + ".json"):
                raise ValueError
            size = data["size_bytes"]
            timestamp = datetime.fromisoformat(data["collected_at"])
            content_type = data["content_type"]
            if (type(size) is not int or size <= 0 or timestamp.tzinfo is None
                    or not isinstance(content_type, str) or (declared is not None and size != declared)):
                raise ValueError
            original = self._object(sha)
            if _digest(original) != (sha, size):
                raise KritsIntegrityError("보관 원본의 크기/SHA-256이 manifest와 다릅니다")
            return StoredFile(attachment, original, manifest, sha, size, timestamp, content_type)
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise KritsIntegrityError("manifest 또는 보관 원본을 검증할 수 없습니다") from exc

    async def verify(self, stored: StoredFile) -> StoredFile:
        """manifest와 원본을 다시 읽어 해시·크기·식별자를 검증한다."""
        expected = self._path("manifests", _identity(stored.attachment), stored.sha256 + ".json")
        if stored.manifest_path != expected or stored.path != self._object(stored.sha256):
            raise KritsIntegrityError("보관본 경로가 이 저장소의 경로와 다릅니다")
        return await run_file_io(self._read, expected, _identity(stored.attachment))

    def _versions(self, attachment: FileAttachment) -> tuple[StoredFile, ...]:
        identity = _identity(attachment)
        directory = self._path("manifests", identity)
        if not directory.exists():
            return ()
        manifests: list[StoredFile] = []
        for entry in directory.iterdir():
            if len(manifests) >= 10_000:
                raise KritsIntegrityError("첨부별 manifest 개수 상한을 넘었습니다")
            if entry.is_symlink() or not entry.is_file() or re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) is None:
                raise KritsIntegrityError("알 수 없는 manifest 경로입니다")
            manifests.append(self._read(entry, identity))
        return tuple(sorted(manifests, key=lambda value: (value.collected_at, value.sha256)))

    async def versions(self, attachment: FileAttachment) -> tuple[StoredFile, ...]:
        """첨부의 모든 보관 버전을 재검증한다. 날짜만으로 이전 파일을 삭제하지 않는다."""
        try:
            return await run_file_io(self._versions, attachment)
        except OSError as exc:
            raise KritsIntegrityError("보관 버전 목록을 읽을 수 없습니다") from exc

    def _current(self, attachment: FileAttachment) -> StoredFile | None:
        identity = _identity(attachment)
        pointer = self._path("current", identity + ".json")
        if not pointer.exists():
            return None
        try:
            if pointer.stat().st_size > 64 * 1024:
                raise ValueError
            with pointer.open(encoding="utf-8") as source:
                data = json.load(source)
            if (not isinstance(data, dict) or data.get("schema_version") != 1
                    or data.get("identity") != identity or not isinstance(data.get("sha256"), str)
                    or _HASH.fullmatch(data["sha256"]) is None
                    or datetime.fromisoformat(data["observed_at"]).tzinfo is None):
                raise ValueError
            return self._read(self._path("manifests", identity, data["sha256"] + ".json"), identity)
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise KritsIntegrityError("마지막 성공 관찰 포인터를 검증할 수 없습니다") from exc

    async def current(self, attachment: FileAttachment) -> StoredFile | None:
        """마지막 성공 전송을 공개한 버전을 재검증한다. 없으면 추정 선택하지 않는다."""
        return await run_file_io(self._current, attachment)

    def _select(self, identity: str, sha256: str) -> None:
        self._path("current", mkdir=True)
        pointer = self._path("current", identity + ".json")
        staging = self._path("staging", mkdir=True)
        descriptor, name = tempfile.mkstemp(prefix="current-", suffix=".part", dir=staging)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({"schema_version": 1, "identity": identity, "sha256": sha256,
                           "observed_at": datetime.now(timezone.utc).isoformat()}, output)
                output.flush(); os.fsync(output.fileno())
            for attempt in range(20):
                try:
                    os.replace(temporary, pointer)
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    # Windows의 동시 경로 조회/읽기 handle은 짧게 rename을 막을 수 있다.
                    # 네트워크 재시도가 아니며 worker 안에서 최대190ms만 기다린다.
                    time.sleep(0.01)
        finally:
            temporary.unlink(missing_ok=True)

    def _temporary(self) -> Path:
        directory = self._path("staging", mkdir=True)
        descriptor, name = tempfile.mkstemp(prefix="download-", suffix=".part", dir=directory)
        os.close(descriptor)
        return Path(name)

    async def _record_inspection(self, report: FileInspection) -> FileInspection:
        def publish() -> FileInspection:
            self._object(report.sha256)
            data = asdict(report)
            data.pop("report_path")
            data["inspected_at"] = report.inspected_at.isoformat()
            data["metadata"] = [{"name": item.name, "base64": base64.b64encode(item.data).decode("ascii")}
                                for item in report.metadata]
            raw = json.dumps({"schema_version": 1, **data}, ensure_ascii=False).encode("utf-8")
            if len(raw) > 16 * 1024 * 1024:
                raise KritsIntegrityError("형식 검사 보고서 크기 상한을 넘었습니다")
            fingerprint = hashlib.sha256(raw).hexdigest()
            directory = self._path("inspections", report.sha256, mkdir=True)
            destination = self._path("inspections", report.sha256, fingerprint + ".json")
            staging = self._path("staging", mkdir=True)
            descriptor, name = tempfile.mkstemp(prefix="inspection-", suffix=".part", dir=staging)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    if _digest(destination) != (fingerprint, len(raw)):
                        raise KritsIntegrityError("기존 형식 검사 보고서가 손상됐습니다") from None
            finally:
                temporary.unlink(missing_ok=True)
            return replace(report, report_path=directory / destination.name)
        try:
            return await run_file_io(publish)
        except OSError as exc:
            raise KritsIntegrityError("형식 검사 보고서를 저장할 수 없습니다") from exc

    def _publish(self, temporary: Path, attachment: FileAttachment, sha256: str,
                 size: int, content_type: str) -> StoredFile:
        if temporary.parent != self._path("staging") or temporary.is_symlink():
            raise KritsIntegrityError("임시파일 경로가 잘못됐습니다")
        if _digest(temporary) != (sha256, size) or size <= 0:
            raise KritsIntegrityError("공개 전 임시파일 해시/크기가 다릅니다")
        original = self._object(sha256)
        self._path("objects", sha256[:2], mkdir=True)
        try:
            os.link(temporary, original)
        except FileExistsError:
            if _digest(original) != (sha256, size):
                raise KritsIntegrityError("동일 해시 경로의 기존 원본이 손상됐습니다") from None
        identity = _identity(attachment)
        directory = self._path("manifests", identity, mkdir=True)
        manifest = directory / (sha256 + ".json")
        if manifest.exists():
            stored = self._read(manifest, identity)
            self._select(identity, sha256)
            return stored
        record = {"schema_version": 1, "status": "verified", "sha256": sha256,
                  "size_bytes": size, "collected_at": datetime.now(timezone.utc).isoformat(),
                  "content_type": content_type, "format_validation": "not_checked",
                  "attachment": _metadata(attachment)}
        descriptor, name = tempfile.mkstemp(prefix="manifest-", suffix=".part", dir=self._path("staging"))
        temporary_manifest = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(record, output, ensure_ascii=False); output.flush(); os.fsync(output.fileno())
            try:
                os.link(temporary_manifest, manifest)
            except FileExistsError:
                pass  # 다른 저장소 인스턴스가 먼저 공개했으면 그 manifest를 재검증한다.
        finally:
            temporary_manifest.unlink(missing_ok=True)
        stored = self._read(manifest, identity)
        self._select(identity, sha256)
        return stored
