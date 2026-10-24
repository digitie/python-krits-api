"""원본/manifest 무결성과 취소 안전한 파일 작업 회귀."""

import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import threading

import pytest

from krits import FileAttachment, FileStore, KritsIntegrityError
from krits._file_io import run_file_io


@pytest.fixture
def attachment():
    return FileAttachment('nodelink','001','01','../표시용.csv',
                          'https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_001/01',None,{'secret':'omit'})


def publish(store,attachment,data=b'a,b\n1,2\n'):
    path=store._temporary()
    try:
        path.write_bytes(data)
        return store._publish(path,attachment,hashlib.sha256(data).hexdigest(),len(data),'text/csv')
    finally:path.unlink(missing_ok=True)


async def test_store_lazy_publish_reuse_history_and_reverify(tmp_path,attachment):
    root=tmp_path/'new';store=FileStore(root);assert not root.exists()
    assert await store.versions(attachment)==()
    first=publish(store,attachment);again=publish(store,attachment)
    assert first==again and first.path.read_bytes()==b'a,b\n1,2\n'
    assert first.path.name==first.sha256 and first.path.is_relative_to(root)
    assert first.attachment.raw=={} and 'secret' not in first.manifest_path.read_text(encoding='utf-8')
    second=publish(store,attachment,b'new')
    assert [s.sha256 for s in await store.versions(attachment)]==[first.sha256,second.sha256]
    assert await store.verify(first)==first
    assert first.path.exists() and second.path.exists()
    assert json.loads(first.manifest_path.read_text(encoding='utf-8'))['format_validation']=='not_checked'


async def test_reverify_detects_corrupt_object_and_preserves_other_version(tmp_path,attachment):
    store=FileStore(tmp_path);first=publish(store,attachment);second=publish(store,attachment,b'new')
    first.path.write_bytes(b'broken')
    with pytest.raises(KritsIntegrityError):await store.verify(first)
    with pytest.raises(KritsIntegrityError):await store.versions(attachment)
    assert await store.verify(second)==second
    with pytest.raises(KritsIntegrityError):publish(store,attachment)


@pytest.mark.parametrize('change',[
    {'schema_version':2},{'status':'pending'},{'sha256':'../x'}, {'size_bytes':True},
    {'size_bytes':0},{'collected_at':'2026-01-01T00:00:00'},{'content_type':5},
    {'attachment':{}},{'attachment':{'service':True}}, {'collected_at':'invalid'},
])
async def test_manifest_invalid_contract(tmp_path,attachment,change):
    store=FileStore(tmp_path);stored=publish(store,attachment)
    record=json.loads(stored.manifest_path.read_text(encoding='utf-8'));record.update(change)
    stored.manifest_path.write_text(json.dumps(record))
    with pytest.raises(KritsIntegrityError):await store.verify(stored)


@pytest.mark.parametrize('field,value',[
    ('service',''),('name',False),('download_url',None),('file_id',123),('attachment_id',False),
    ('size_bytes',False),('size_bytes',-1),('size_bytes',999),
])
async def test_manifest_attachment_types(tmp_path,attachment,field,value):
    store=FileStore(tmp_path);stored=publish(store,attachment)
    record=json.loads(stored.manifest_path.read_text(encoding='utf-8'));record['attachment'][field]=value
    stored.manifest_path.write_text(json.dumps(record))
    with pytest.raises(KritsIntegrityError):await store.verify(stored)


async def test_manifest_file_errors_and_wrong_store_paths(tmp_path,attachment):
    store=FileStore(tmp_path);stored=publish(store,attachment)
    with pytest.raises(KritsIntegrityError):await store.verify(replace(stored,path=tmp_path/'else'))
    with pytest.raises(KritsIntegrityError):store._object('../x')
    stored.manifest_path.write_bytes(b'x'*(65537))
    with pytest.raises(KritsIntegrityError):await store.verify(stored)
    stored.manifest_path.unlink()
    with pytest.raises(KritsIntegrityError):await store.verify(stored)
    (stored.manifest_path.parent/'unexpected').write_text('x')
    with pytest.raises(KritsIntegrityError):await store.versions(attachment)


def test_publish_rejects_tampered_temp_and_outside_path(tmp_path,attachment):
    store=FileStore(tmp_path/'store');outside=tmp_path/'outside';outside.write_bytes(b'abc')
    with pytest.raises(KritsIntegrityError):store._publish(outside,attachment,'0'*64,3,'')
    temp=store._temporary();temp.write_bytes(b'abc')
    with pytest.raises(KritsIntegrityError):store._publish(temp,attachment,'0'*64,3,'')
    temp.unlink()


async def test_store_instances_publish_same_version_concurrently(tmp_path,attachment):
    a=FileStore(tmp_path);b=FileStore(tmp_path)
    first,second=await asyncio.gather(asyncio.to_thread(publish,a,attachment),asyncio.to_thread(publish,b,attachment))
    assert first==second and len(await a.versions(attachment))==1


async def test_file_io_repeated_cancellation_waits_worker_completion():
    started=threading.Event();release=threading.Event();finished=[]
    def operation():started.set();release.wait();finished.append(True)
    task=asyncio.create_task(run_file_io(operation))
    await asyncio.to_thread(started.wait);task.cancel();await asyncio.sleep(0);task.cancel();await asyncio.sleep(0)
    assert not task.done();release.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert finished==[True]


async def test_file_io_cancelled_worker_error_is_retrieved():
    started=threading.Event();release=threading.Event()
    def operation():started.set();release.wait();raise OSError('test')
    task=asyncio.create_task(run_file_io(operation));await asyncio.to_thread(started.wait)
    task.cancel();release.set()
    with pytest.raises(asyncio.CancelledError):await task


async def test_reverted_content_selects_last_observed_hash_without_changing_first_manifest(tmp_path,attachment):
    store=FileStore(tmp_path)
    assert await store.current(attachment) is None
    first=publish(store,attachment,b'A');second=publish(store,attachment,b'B')
    assert await store.current(attachment)==second
    reverted=publish(store,attachment,b'A')
    assert reverted==first and await store.current(attachment)==first
    assert len(await store.versions(attachment))==2


async def test_manifest_publish_is_invisible_to_other_reader_until_complete(tmp_path,attachment,monkeypatch):
    store=FileStore(tmp_path);first=publish(store,attachment,b'A')
    started=threading.Event();release=threading.Event();link=os.link
    def delayed(source,destination,*args,**kwargs):
        if Path(destination).parent.parent.name=='manifests':started.set();release.wait(5)
        return link(source,destination,*args,**kwargs)
    monkeypatch.setattr('krits.storage.os.link',delayed)
    job=asyncio.create_task(asyncio.to_thread(publish,store,attachment,b'B'))
    try:
        assert await asyncio.to_thread(started.wait,5)
        observer=FileStore(tmp_path)
        assert await observer.versions(attachment)==(first,)
        assert await observer.current(attachment)==first
        assert all(path.suffix=='.json' for path in first.manifest_path.parent.iterdir())
    finally:release.set()
    second=await job
    assert len(await store.versions(attachment))==2 and await store.current(attachment)==second
    (tmp_path/'staging'/'interrupted-manifest.part').write_bytes(b'partial')
    assert len(await store.versions(attachment))==2


async def test_invalid_current_pointer_is_not_silently_ignored(tmp_path,attachment):
    store=FileStore(tmp_path);publish(store,attachment)
    pointer=next((tmp_path/'current').iterdir());pointer.write_text('{}')
    with pytest.raises(KritsIntegrityError):await store.current(attachment)
