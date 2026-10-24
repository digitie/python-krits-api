"""저장소 Markdown의 상대 파일 링크가 실제 문서를 가리키는지 확인한다."""

from pathlib import Path
import re


def main() -> None:
    """외부 링크를 제외하고 로컬 문서 링크를 검사한다."""
    root = Path(__file__).resolve().parents[1]
    checked = 0
    for path in root.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            if not (path.parent / target).is_file():
                raise SystemExit(f"깨진 링크: {path.relative_to(root)} -> {target}")
            checked += 1
    print(f"로컬 문서 링크 {checked}건 통과")


if __name__ == "__main__":
    main()
