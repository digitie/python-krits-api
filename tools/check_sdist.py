"""빌드한 sdist를 저장소 밖에 풀어 문서와 네트워크 없는 전체 회귀를 검사한다."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="krits-sdist-") as directory:
        destination = Path(directory)
        with tarfile.open(args.archive.resolve(), "r:gz") as archive:
            archive.extractall(destination, filter="data")
        roots = list(destination.iterdir())
        assert len(roots) == 1 and roots[0].is_dir()
        project = roots[0]
        for required in ("tools/installed_e2e.py", "tools/check_docs.py", "tests/conftest.py",
                         "src/krits/py.typed", "README.md", "LICENSE", "NOTICE"):
            assert (project / required).is_file(), required
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(project / "src")
        subprocess.run([sys.executable, "tools/check_docs.py"], cwd=project, env=environment, check=True)
        subprocess.run([sys.executable, "-m", "pytest", "-m", "not live", "--cov=krits",
                        "--cov-fail-under=90"], cwd=project, env=environment, check=True)
        print("저장소 밖 sdist 문서·전체 오프라인 검증 통과", flush=True)


if __name__ == "__main__":
    main()
