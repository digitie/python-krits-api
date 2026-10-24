"""실제 ITS 내역서의 CRC 검사와 제한된 XLSX/CSV 읽기."""

from datetime import date, timedelta
import os

import pytest

from krits import FileStore, KritsClient, inspect_file, read_csv, read_xlsx

pytestmark=pytest.mark.live


async def test_real_history_xlsx_crc_and_saved_values(tmp_path):
    async with KritsClient(executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as client:
        end=date.today();catalog=await client.list_nodelink_releases(start_date=end-timedelta(days=365),end_date=end)
        attachment=next(row.history_file for row in catalog.items
                        if row.history_file is not None and row.history_file.name.lower().endswith('.xlsx'))
        store=FileStore(tmp_path);stored=await client.download_file(attachment,store,max_bytes=10*1024*1024)
    report=await inspect_file(store,stored)
    table=await read_xlsx(store,stored)
    assert report.kind=='xlsx' and report.crc_checked and report.report_path.exists()
    assert table.rows and any(value for row in table.rows for value in row)
    assert all(value is None or isinstance(value,str) for row in table.rows for value in row)
    assert await store.verify(stored)==stored
    print('실제 XLSX',stored.size_bytes,len(report.members),table.sheet_name,len(table.rows))


async def test_real_history_csv_with_explicit_decoder(tmp_path):
    async with KritsClient(executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as client:
        end=date.today();catalog=await client.list_nodelink_releases(start_date=end-timedelta(days=365),end_date=end)
        attachment=next(row.history_file for row in catalog.items
                        if row.history_file is not None and row.history_file.name.lower().endswith('.csv'))
        store=FileStore(tmp_path);stored=await client.download_file(attachment,store,max_bytes=10*1024*1024)
    table=await read_csv(store,stored,encoding='cp949')
    assert len(table.rows)>=2 and table.encoding=='cp949'
    assert await store.verify(stored)==stored
    print('실제 CSV',stored.size_bytes,table.encoding,len(table.rows))
