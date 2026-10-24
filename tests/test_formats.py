"""ZIP 공격 경계와 원문 CSV/XLSX 선택 읽기."""

from dataclasses import replace
import hashlib
import io
import json
import stat
import struct
import zipfile

import pytest

from krits import FileAttachment, FileLimits, FileStore, KritsIntegrityError, inspect_file, read_csv, read_xlsx


def stored_file(tmp_path,data,name='file.zip'):
    store=FileStore(tmp_path);temporary=store._temporary();temporary.write_bytes(data)
    attachment=FileAttachment('nodelink','001','1',name,
        'https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_001/1',len(data),{})
    try:stored=store._publish(temporary,attachment,hashlib.sha256(data).hexdigest(),len(data),'application/octet-stream')
    finally:temporary.unlink(missing_ok=True)
    return store,stored


def archive_bytes(items,compression=zipfile.ZIP_STORED):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=compression) as archive:
        for name,data in items:archive.writestr(name,data)
    return output.getvalue()


async def test_zip_crc_sidecars_selected_csv_and_separate_report(tmp_path):
    data=archive_bytes([('data/values.csv','id,name\n001,서울\n'.encode()),('data/link.prj',b'raw CRS'),('data/link.cpg',b'CP949')])
    store,stored=stored_file(tmp_path,data);manifest=stored.manifest_path.read_bytes()
    result=await inspect_file(store,stored)
    assert result.kind=='zip' and result.crc_checked and len(result.members)==3
    assert [m.data for m in result.metadata]==[b'raw CRS',b'CP949']
    assert result.report_path.exists() and result.limits
    assert json.loads(result.report_path.read_text(encoding='utf-8'))['metadata'][0]['base64']=='cmF3IENSUw=='
    table=await read_csv(store,stored,member='data/values.csv',encoding='utf-8')
    assert table.rows==( ('id','name'),('001','서울') ) and table.row_numbers==(1,2)
    assert table.source_member=='data/values.csv' and stored.path.read_bytes()==data
    assert stored.manifest_path.read_bytes()==manifest


@pytest.mark.parametrize('name',['../file','/absolute','C:drive','a\\b','a//b','a/./b','a/../b'])
async def test_unsafe_zip_paths(tmp_path,name):
    data=archive_bytes([(name,b'abc')])
    if name=='a\\b':data=data.replace(b'a/b',b'a\\b')
    store,stored=stored_file(tmp_path,data)
    with pytest.raises(KritsIntegrityError):await inspect_file(store,stored)
    assert not (tmp_path/'inspections').exists()


@pytest.mark.parametrize('mode',['duplicate','symlink','bzip','crc','encrypted','nul','count','trailing','zip64'])
async def test_bad_archive_contract(tmp_path,mode):
    if mode=='duplicate':data=archive_bytes([('a',b'1'),('A',b'2')])
    elif mode=='symlink':
        info=zipfile.ZipInfo('link');info.external_attr=(stat.S_IFLNK|0o777)<<16
        data=archive_bytes([(info,b'target')])
    else:
        data=archive_bytes([('safe.txt',b'payload')],zipfile.ZIP_BZIP2 if mode=='bzip' else zipfile.ZIP_STORED)
        if mode=='crc':data=data.replace(b'payload',b'payloae',1)
        if mode=='nul':data=data.replace(b'safe.txt',b'\0afe.txt')
        if mode=='trailing':data+=b'junk'
        if mode in ('encrypted','count','zip64'):
            raw=bytearray(data);central=raw.find(b'PK\x01\x02');end=raw.rfind(b'PK\x05\x06')
            if mode=='encrypted':struct.pack_into('<H',raw,central+8,1)
            if mode=='count':struct.pack_into('<HH',raw,end+8,0,0)
            if mode=='zip64':struct.pack_into('<I',raw,end+12,0xffffffff)
            data=bytes(raw)
    store,stored=stored_file(tmp_path,data)
    with pytest.raises(KritsIntegrityError):await inspect_file(store,stored)


@pytest.mark.parametrize('limits',[
    FileLimits(max_archive_bytes=10),FileLimits(max_entries=1),FileLimits(max_directory_bytes=10),
    FileLimits(max_member_bytes=2),FileLimits(max_total_bytes=5),FileLimits(max_ratio=0.1),
    FileLimits(max_metadata_bytes=1),
])
async def test_zip_limits(tmp_path,limits):
    store,stored=stored_file(tmp_path,archive_bytes([('a.prj',b'abc'),('b',b'def')]))
    with pytest.raises(KritsIntegrityError):await inspect_file(store,stored,limits=limits)


async def test_ratio_bomb_and_large_sidecar(tmp_path):
    for index,items in enumerate([[('zeros',b'0'*100000)],[('a.cpg',b'x'*65537)]]):
        store,stored=stored_file(tmp_path/str(index),archive_bytes(items,zipfile.ZIP_DEFLATED))
        with pytest.raises(KritsIntegrityError):await inspect_file(store,stored,limits=FileLimits(max_ratio=10000) if index else FileLimits())


async def test_csv_explicit_encoding_bounds_and_source_immutability(tmp_path):
    data='id,이름\n001,서울\n'.encode('cp949');store,stored=stored_file(tmp_path,data,'file.csv')
    table=await read_csv(store,stored,encoding='cp949');assert table.rows[1]==('001','서울')
    report=await inspect_file(store,stored,encoding='cp949');assert report.table_rows==2 and not report.crc_checked
    with pytest.raises(ValueError):await inspect_file(store,stored)
    with pytest.raises(ValueError):await read_csv(store,stored,encoding='invalid-encoding')
    with pytest.raises(KritsIntegrityError):await read_csv(store,stored,encoding='utf-8')
    for limits in [FileLimits(max_rows=1),FileLimits(max_columns=1),FileLimits(max_field_chars=1),FileLimits(max_table_bytes=1)]:
        with pytest.raises(KritsIntegrityError):await read_csv(store,stored,encoding='cp949',limits=limits)
    assert stored.path.read_bytes()==data


def workbook_bytes(*,sheet=None,relationships=None,shared=None,workbook=None):
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    sheet=sheet or f'<worksheet xmlns="{ns}"><sheetData><row r="2"><c r="A2" t="s"><v>0</v></c><c r="C2"><f>SUM(1,2)</f><v>3</v></c></row></sheetData></worksheet>'
    relationships=relationships or f'<Relationships><Relationship Id="r1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    shared=shared or f'<sst xmlns="{ns}"><si><t>001</t></si></sst>'
    workbook=workbook or f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="내역" r:id="r1"/></sheets></workbook>'
    return archive_bytes([('[Content_Types].xml',b'content'),('xl/workbook.xml',workbook.encode()),
        ('xl/_rels/workbook.xml.rels',relationships.encode()),('xl/worksheets/sheet1.xml',sheet.encode()),('xl/sharedStrings.xml',shared.encode())])


async def test_xlsx_raw_values_formulas_and_original_row_numbers(tmp_path):
    store,stored=stored_file(tmp_path,workbook_bytes(),'file.xlsx')
    report=await inspect_file(store,stored);assert report.kind=='xlsx' and report.crc_checked
    table=await read_xlsx(store,stored,sheet_name='내역')
    assert table.rows==( ('001',None,'3'), ) and table.row_numbers==(2,)
    assert table.sheet_name=='내역' and table.encoding is None
    assert table.formulas[0].text=='SUM(1,2)' and table.formulas[0].column_number==3
    with pytest.raises(KritsIntegrityError):await read_xlsx(store,stored,sheet_name='missing')
    with pytest.raises(KritsIntegrityError):await read_xlsx(store,stored,limits=FileLimits(max_columns=2))
    with pytest.raises(KritsIntegrityError):await read_xlsx(store,stored,limits=FileLimits(max_table_bytes=1))


@pytest.mark.parametrize('content',[
    '<row r="bad"><c r="A1"><v>1</v></c></row>',
    '<row r="1"><c r="A2"><v>1</v></c></row>',
    '<row r="1"><c r="A1" t="s"><v>99</v></c></row>',
    '<row r="1"><c r="A1" t="unknown"><v>1</v></c></row>',
    '<row r="1"><c r="A1"/><c r="A1"/></row>',
    '<row r="1"/><row r="1"/>',
])
async def test_xlsx_malformed_cells(tmp_path,content):
    sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+content+'</sheetData></worksheet>'
    store,stored=stored_file(tmp_path,workbook_bytes(sheet=sheet))
    with pytest.raises(KritsIntegrityError):await read_xlsx(store,stored)


@pytest.mark.parametrize('relationship',[
    '<Relationships><Relationship Id="r1" TargetMode="External" Target="https://evil"/></Relationships>',
    '<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="../../outside"/></Relationships>',
])
async def test_xlsx_external_or_traversing_relationship(tmp_path,relationship):
    store,stored=stored_file(tmp_path,workbook_bytes(relationships=relationship))
    with pytest.raises(KritsIntegrityError):await read_xlsx(store,stored)


async def test_xlsx_dtd_is_forbidden(tmp_path):
    document='<!DOCTYPE workbook [<!ENTITY x "bad">]><workbook>&x;</workbook>'
    store,stored=stored_file(tmp_path,workbook_bytes(workbook=document))
    with pytest.raises(KritsIntegrityError):await read_xlsx(store,stored)


@pytest.mark.parametrize('kwargs',[{'max_rows':0},{'max_entries':True},{'max_ratio':float('inf')},{'max_ratio':False}])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):FileLimits(**kwargs)
