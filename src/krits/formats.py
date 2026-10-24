"""원본 보존형 ZIP/CSV/XLSX의 제한된 검사와 선택 읽기."""

from __future__ import annotations

import codecs
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import io
import math
from pathlib import Path, PurePosixPath
import re
import stat
import struct
from typing import BinaryIO, cast
from xml.etree.ElementTree import Element, ParseError
import zipfile

from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from ._file_io import run_file_io
from .exceptions import KritsIntegrityError
from .models import ArchiveMember, ArchiveMetadata, CellFormula, FileInspection, StoredFile, TableData
from .storage import CHUNK_SIZE, FileStore


@dataclass(frozen=True, slots=True)
class FileLimits:
    """검사/파싱 상한. 더 큰 원본을 처리할 때 소비자가 명시적으로 조정한다."""

    max_archive_bytes: int = 1024 * 1024 * 1024
    max_entries: int = 10_000
    max_directory_bytes: int = 8 * 1024 * 1024
    max_member_bytes: int = 512 * 1024 * 1024
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_ratio: float = 200
    max_metadata_bytes: int = 1024 * 1024
    max_table_bytes: int = 16 * 1024 * 1024
    max_rows: int = 10_000
    max_columns: int = 1024
    max_field_chars: int = 131_072

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name == "max_ratio":
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    raise ValueError("max_ratio는 유한한 양수여야 합니다")
                try:
                    if not math.isfinite(value):
                        raise ValueError("max_ratio는 유한한 양수여야 합니다")
                except OverflowError:
                    raise ValueError("max_ratio가 지원 범위를 넘었습니다") from None
            elif type(value) is not int or value <= 0:
                raise ValueError(f"{name}은 양의 정수여야 합니다")


def _fail(message: str) -> KritsIntegrityError:
    return KritsIntegrityError(message)


def _preflight(path: Path, limits: FileLimits) -> None:
    """ZipFile이 central directory 전체를 만들기 전에 크기·실제 항목 수를 제한한다."""
    size = path.stat().st_size
    if size > limits.max_archive_bytes:
        raise _fail("ZIP 원본 크기 상한을 넘었습니다")
    with path.open("rb") as source:
        source.seek(max(0, size - 65557)); tail = source.read(65557)
        position = tail.rfind(b"PK\x05\x06")
        if position < 0 or len(tail) - position < 22:
            raise _fail("ZIP EOCD가 없습니다")
        end = struct.unpack_from("<4s4H2IH", tail, position)
        if end[1] or end[2] or end[3] != end[4] or position + 22 + end[7] != len(tail):
            raise _fail("다중 디스크 또는 비정상 ZIP 종료 레코드입니다")
        count, directory_size, offset = end[4], end[5], end[6]
        if count == 65535 or directory_size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
            raise _fail("ZIP64 EOCD는 현재 검사 계약에서 지원하지 않습니다")
        if (count > limits.max_entries or directory_size > limits.max_directory_bytes
                or offset + directory_size != size - len(tail) + position):
            raise _fail("ZIP central directory 상한 또는 범위가 잘못됐습니다")
        source.seek(offset); directory_end = offset + directory_size; actual = 0
        while source.tell() < directory_end:
            header = source.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise _fail("ZIP central directory 항목이 손상됐습니다")
            lengths = struct.unpack_from("<3H", header, 28)
            actual += 1
            if actual > limits.max_entries or source.tell() + sum(lengths) > directory_end:
                raise _fail("ZIP 항목 수 또는 directory 길이가 상한을 넘었습니다")
            if lengths[0] > 4096:
                raise _fail("ZIP 멤버 이름 크기 상한을 넘었습니다")
            raw_name = source.read(lengths[0])
            encoding = "utf-8" if struct.unpack_from("<H", header, 8)[0] & 0x800 else "cp437"
            _safe_name(raw_name.decode(encoding))
            source.seek(lengths[1] + lengths[2], 1)
        if source.tell() != directory_end or actual != count:
            raise _fail("ZIP 선언/실제 항목 수가 다릅니다")


def _safe_name(name: str) -> None:
    parts = name.rstrip("/").split("/")
    if (not name or len(name) > 4096 or name.startswith("/") or "\\" in name or ":" in name
            or "\x00" in name or any(part in {"", ".", ".."} for part in parts)):
        raise _fail("ZIP 멤버 경로가 안전한 상대 경로가 아닙니다")


def _inspect_zip(stored: StoredFile, limits: FileLimits) -> FileInspection:
    _preflight(stored.path, limits)
    members: list[ArchiveMember] = []; metadata: list[ArchiveMetadata] = []
    names: set[str] = set(); total = 0; metadata_size = 0
    with zipfile.ZipFile(stored.path) as archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            raise _fail("ZIP 항목 수 상한을 넘었습니다")
        for item in infos:
            _safe_name(item.orig_filename)
            canonical = item.filename.casefold().rstrip("/")
            if canonical in names:
                raise _fail("ZIP 멤버 경로가 중복됐습니다")
            names.add(canonical)
            mode = stat.S_IFMT(item.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1:
                raise _fail("ZIP 링크/특수파일/암호화 항목은 허용하지 않습니다")
            if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise _fail("지원하지 않는 ZIP 압축 방식입니다")
            total += item.file_size
            if (item.file_size > limits.max_member_bytes or total > limits.max_total_bytes
                    or item.file_size / max(1, item.compress_size) > limits.max_ratio):
                raise _fail("ZIP 멤버/총 해제 크기 또는 압축비 상한을 넘었습니다")
            sidecar = PurePosixPath(item.filename).suffix.lower() in {".prj", ".cpg"}
            if sidecar and item.file_size > CHUNK_SIZE:
                raise _fail("ZIP prj/cpg 항목 크기 상한을 넘었습니다")
            raw = bytearray(); received = 0
            with archive.open(item) as source:
                while chunk := source.read(CHUNK_SIZE):
                    received += len(chunk)
                    if received > item.file_size or received > limits.max_member_bytes:
                        raise _fail("ZIP 실제 해제 크기가 선언/상한을 넘었습니다")
                    if sidecar:
                        raw.extend(chunk)
            if received != item.file_size or (item.is_dir() and received):
                raise _fail("ZIP 실제 해제 길이가 선언과 다릅니다")
            if sidecar:
                metadata_size += len(raw)
                if metadata_size > limits.max_metadata_bytes:
                    raise _fail("prj/cpg 원문 합계 상한을 넘었습니다")
                metadata.append(ArchiveMetadata(item.filename, bytes(raw)))
            members.append(ArchiveMember(item.filename, item.file_size, item.compress_size, item.CRC))
        is_xlsx = "[Content_Types].xml" in archive.namelist() and "xl/workbook.xml" in archive.namelist()
    return FileInspection(stored.sha256, "xlsx" if is_xlsx else "zip", datetime.now(timezone.utc),
                          True, tuple(members), tuple(metadata))


def _csv_table(source: BinaryIO, encoding: str, limits: FileLimits, member: str | None) -> TableData:
    canonical = codecs.lookup(encoding).name
    rows: list[tuple[str | None, ...]] = []
    with io.TextIOWrapper(source, encoding=canonical, errors="strict", newline="") as text:
        for row in csv.reader(text, strict=True):
            if len(rows) >= limits.max_rows or len(row) > limits.max_columns:
                raise _fail("CSV 행/열 상한을 넘었습니다")
            if any(len(value) > limits.max_field_chars for value in row):
                raise _fail("CSV 셀 길이 상한을 넘었습니다")
            rows.append(tuple(row))
    return TableData(tuple(rows), tuple(range(1, len(rows) + 1)), canonical, member)


_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rich_text(element: Element, limits: FileLimits) -> str:
    """본문 t/r만 읽고 별도 발음 주석 rPh를 셀 값에 합치지 않는다."""
    for node in element.iter():
        local = _local(node.tag)
        if local in {"t", "r", "si", "is"} and node.tag != "{" + _NS["x"] + "}" + local:
            raise _fail("XLSX 문자열 내부 namespace가 다릅니다")
    direct = element.findall("x:t", _NS); runs = element.findall("x:r", _NS)
    if len(direct) > 1 or direct and runs:
        raise _fail("XLSX 문자열 구조가 중복됐습니다")
    texts = direct[:]
    for run in runs:
        run_texts = run.findall("x:t", _NS)
        if len(run_texts) != 1:
            raise _fail("XLSX rich text의 필수 t가 없습니다")
        texts.extend(run_texts)
    value = "".join(item.text or "" for item in texts)
    if len(value) > limits.max_field_chars:
        raise _fail("XLSX 문자열 상한을 넘었습니다")
    return value


def _xml(archive: zipfile.ZipFile, name: str, limits: FileLimits) -> Element:
    info = archive.getinfo(name)
    if info.file_size > limits.max_table_bytes:
        raise _fail("XLSX XML 크기 상한을 넘었습니다")
    return cast(Element, fromstring(archive.read(info), forbid_dtd=True, forbid_entities=True, forbid_external=True))


def _column(cell: str, row: int, limits: FileLimits) -> int:
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", cell)
    if match is None or int(match[2]) != row:
        raise _fail("XLSX 셀 좌표와 행 번호가 다릅니다")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - 64
    if column > limits.max_columns:
        raise _fail("XLSX 열 상한을 넘었습니다")
    return column


def _xlsx_table(stored: StoredFile, limits: FileLimits, sheet_name: str | None) -> TableData:
    with zipfile.ZipFile(stored.path) as archive:
        workbook = _xml(archive, "xl/workbook.xml", limits)
        if workbook.tag != "{" + _NS["x"] + "}workbook":
            raise _fail("XLSX workbook namespace가 다릅니다")
        relationships = _xml(archive, "xl/_rels/workbook.xml.rels", limits)
        targets: dict[str, str] = {}
        for item in relationships:
            if item.get("TargetMode") == "External":
                raise _fail("외부 XLSX 관계는 허용하지 않습니다")
            if item.get("Type") == _REL + "/worksheet":
                target = item.attrib["Target"]
                # 실제 XLSX는 /xl/... 절대 package URI도 사용한다. 로컬 경로로 해석하지 않는다.
                path = target[1:] if target.startswith("/xl/") else "xl/" + target
                _safe_name(path)
                if item.attrib["Id"] in targets:
                    raise _fail("XLSX 관계 ID가 중복됐습니다")
                targets[item.attrib["Id"]] = path
        sheets = workbook.findall("x:sheets/x:sheet", _NS)
        if not sheets:
            raise _fail("XLSX worksheet가 없습니다")
        if len({item.get("name") for item in sheets}) != len(sheets):
            raise _fail("XLSX sheet 이름이 중복됐습니다")
        selected = next((item for item in sheets if item.get("name") == sheet_name), None) if sheet_name is not None else sheets[0]
        if selected is None:
            raise _fail("요청한 XLSX sheet가 없습니다")
        name = selected.attrib["name"]
        member = targets[selected.attrib["{" + _REL + "}id"]]
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = _xml(archive, "xl/sharedStrings.xml", limits)
            if strings.tag != "{" + _NS["x"] + "}sst":
                raise _fail("XLSX 공유 문자열 구조가 다릅니다")
            for item in strings:
                if _local(item.tag) == "si":
                    if item.tag != "{" + _NS["x"] + "}si":
                        raise _fail("XLSX 공유 문자열 namespace가 다릅니다")
                    shared.append(_rich_text(item, limits))
        sheet = _xml(archive, member, limits)
        if sheet.tag != "{" + _NS["x"] + "}worksheet":
            raise _fail("XLSX worksheet 구조가 다릅니다")
        containers = [item for item in sheet if _local(item.tag) == "sheetData"]
        if len(containers) != 1 or containers[0].tag != "{" + _NS["x"] + "}sheetData":
            raise _fail("XLSX 필수 sheetData 누락/중복/namespace 오류입니다")
        rows: list[tuple[str | None, ...]] = []; numbers: list[int] = []; formulas: list[CellFormula] = []
        for row in containers[0]:
            if row.tag != "{" + _NS["x"] + "}row":
                raise _fail("XLSX sheetData 내부 행 구조/namespace가 다릅니다")
            number = int(row.attrib["r"])
            if len(rows) >= limits.max_rows or number <= (numbers[-1] if numbers else 0) or number > 1048576:
                raise _fail("XLSX 행 상한 또는 행 순서가 잘못됐습니다")
            cells: list[str | None] = []
            for cell in row:
                if cell.tag == "{" + _NS["x"] + "}extLst":
                    continue
                if cell.tag != "{" + _NS["x"] + "}c":
                    raise _fail("XLSX 행 내부 셀 구조/namespace가 다릅니다")
                for field_name in ("v", "f", "is"):
                    fields = [item for item in cell if _local(item.tag) == field_name]
                    if len(fields) > 1 or any(item.tag != "{" + _NS["x"] + "}" + field_name for item in fields):
                        raise _fail("XLSX 셀 값/수식/문자열 namespace 또는 중복 오류입니다")
                column = _column(cell.attrib["r"], number, limits)
                if column <= len(cells):
                    raise _fail("XLSX 셀 순서/중복이 잘못됐습니다")
                cells.extend([None] * (column - len(cells)))
                kind = cell.get("t", "n"); value = cell.findtext("x:v", namespaces=_NS)
                if kind == "s":
                    if value is None or re.fullmatch(r"[0-9]+", value) is None or int(value) >= len(shared):
                        raise _fail("XLSX 공유 문자열 참조가 잘못됐습니다")
                    value = shared[int(value)]
                elif kind == "inlineStr":
                    inline = cell.find("x:is", _NS)
                    value = _rich_text(inline, limits) if inline is not None else None
                elif kind not in {"n", "b", "str", "e", "d"}:
                    raise _fail("지원하지 않는 XLSX 셀 형식입니다")
                formula = cell.find("x:f", _NS)
                if formula is not None:
                    if len(formula.text or "") > limits.max_field_chars:
                        raise _fail("XLSX 수식 길이 상한을 넘었습니다")
                    formulas.append(CellFormula(number, column, formula.text or ""))
                if value is not None and len(value) > limits.max_field_chars:
                    raise _fail("XLSX 셀 길이 상한을 넘었습니다")
                cells[-1] = value
            rows.append(tuple(cells)); numbers.append(number)
    return TableData(tuple(rows), tuple(numbers), None, member, name, tuple(formulas))


def _process(stored: StoredFile, limits: FileLimits, mode: str, encoding: str | None,
             member: str | None, sheet_name: str | None) -> tuple[FileInspection, TableData | None]:
    try:
        if stored.size_bytes > limits.max_archive_bytes:
            raise _fail("원본 검사 크기 상한을 넘었습니다")
        with stored.path.open("rb") as source:
            magic = source.read(4)
        is_zip = (zipfile.is_zipfile(stored.path) or magic in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}
                  or mode == "xlsx" or mode == "inspect" and stored.attachment.name.lower().endswith((".zip", ".xlsx")))
        report = _inspect_zip(stored, limits) if is_zip else FileInspection(
            stored.sha256, "csv", datetime.now(timezone.utc), False)
        table: TableData | None = None
        if mode == "xlsx":
            if report.kind != "xlsx":
                raise _fail("XLSX package가 아닙니다")
            try:
                table = _xlsx_table(stored, limits, sheet_name)
            except (ValueError, TypeError) as exc:
                raise _fail("XLSX 셀/행 값이 잘못됐습니다") from exc
        elif mode == "csv" or not is_zip:
            if encoding is None:
                raise ValueError("CSV encoding을 명시해야 합니다")
            if is_zip:
                if member is None:
                    raise ValueError("ZIP 안에서 읽을 CSV member를 명시해야 합니다")
                _safe_name(member)
                with zipfile.ZipFile(stored.path) as archive:
                    info = archive.getinfo(member)
                    if info.file_size > limits.max_table_bytes or info.is_dir():
                        raise _fail("선택 CSV 크기 상한 또는 종류가 잘못됐습니다")
                    with archive.open(info) as source:
                        table = _csv_table(cast(BinaryIO, source), encoding, limits, member)
            else:
                if member is not None or stored.size_bytes > limits.max_table_bytes:
                    raise _fail("일반 CSV의 member 또는 크기 상한이 잘못됐습니다")
                with stored.path.open("rb") as source:
                    table = _csv_table(source, encoding, limits, None)
        if table is not None:
            report = replace(report, encoding=table.encoding, selected_member=table.source_member, table_rows=len(table.rows))
        return report, table
    except (zipfile.BadZipFile, OSError, UnicodeError, csv.Error, ParseError, DefusedXmlException,
            KeyError, IndexError, OverflowError, NotImplementedError, struct.error) as exc:
        raise _fail("원본 ZIP/CSV/XLSX 형식 검사가 실패했습니다") from exc


async def _run(store: FileStore, stored: StoredFile, limits: FileLimits, mode: str,
               encoding: str | None = None, member: str | None = None,
               sheet_name: str | None = None) -> tuple[FileInspection, TableData | None]:
    if not isinstance(limits, FileLimits):
        raise ValueError("FileLimits가 필요합니다")
    if encoding is not None:
        try:
            codecs.lookup(encoding)
        except (LookupError, TypeError) as exc:
            raise ValueError("알 수 없는 CSV encoding입니다") from exc
    if member is not None and not isinstance(member, str) or sheet_name is not None and not isinstance(sheet_name, str):
        raise ValueError("member/sheet_name은 문자열이어야 합니다")
    verified = await store.verify(stored)
    report, table = await run_file_io(_process, verified, limits, mode, encoding, member, sheet_name)
    await store.verify(stored)
    report = replace(report, limits=tuple((name, getattr(limits, name)) for name in limits.__dataclass_fields__))
    report = await store._record_inspection(report)
    return report, table


async def inspect_file(store: FileStore, stored: StoredFile, *, limits: FileLimits = FileLimits(),
                       encoding: str | None = None) -> FileInspection:
    """ZIP 전체 CRC/경계 또는 명시한 encoding의 CSV를 검사하고 별도 보고서를 보관한다."""
    report, _table = await _run(store, stored, limits, "inspect", encoding)
    return report


async def read_csv(store: FileStore, stored: StoredFile, *, encoding: str, member: str | None = None,
                   limits: FileLimits = FileLimits()) -> TableData:
    """일반 CSV 또는 검증한 ZIP의 선택 CSV를 원문 문자열로 읽는다."""
    _report, table = await _run(store, stored, limits, "csv", encoding, member)
    assert table is not None
    return table


async def read_xlsx(store: FileStore, stored: StoredFile, *, sheet_name: str | None = None,
                    limits: FileLimits = FileLimits()) -> TableData:
    """선택 XLSX sheet의 저장 값과 수식 원문을 분리해 읽는다. 수식은 실행하지 않는다."""
    _report, table = await _run(store, stored, limits, "xlsx", sheet_name=sheet_name)
    assert table is not None
    return table
