"""명시적 opt-in의 실제 Chromium 첨부 전송과 보관본 재사용."""

from datetime import date, timedelta
import os

import pytest

from krits import FileStore, KritsClient

pytestmark = pytest.mark.live


async def test_real_nodelink_history_download_verify_and_reuse(tmp_path):
    async with KritsClient(executable_path=os.getenv('KRITS_CHROMIUM_EXECUTABLE')) as client:
        end=date.today();start=end-timedelta(days=300)
        releases=await client.list_nodelink_releases(start_date=start,end_date=end)
        attachment=next(item.history_file for item in reversed(releases.items) if item.history_file is not None)
        store=FileStore(tmp_path)
        stored=await client.download_file(attachment,store,max_bytes=10*1024*1024)
        assert stored.size_bytes>0 and stored.path.exists()
        assert await store.verify(stored)==stored
        assert await client.download_file(attachment,store,max_bytes=10*1024*1024)==stored
        assert len(await store.versions(attachment))==1
        print('실제 첨부',stored.collected_at.isoformat(),stored.size_bytes,stored.sha256,stored.attachment.name)
