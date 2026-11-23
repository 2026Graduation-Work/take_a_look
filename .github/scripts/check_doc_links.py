"""Check Markdown links in tracked files.

Fails when a relative link points to a missing file, or when a Markdown file
under docs/ is not linked from docs/README.md.

    python .github/scripts/check_doc_links.py
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
CODE_FENCE = re.compile(r"```.*?```", re.S)


def tracked_markdown() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.splitlines() if (ROOT / p).exists()]


def link_targets(md: Path) -> list[str]:
    text = CODE_FENCE.sub("", md.read_text(encoding="utf-8"))
    return [m.group(1) for m in LINK.finditer(text)]


def is_external(target: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target)) or target.startswith("#")


def resolve(md: Path, target: str) -> Path:
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return (ROOT / path.lstrip("/")) if path.startswith("/") else (md.parent / path)


def main() -> int:
    broken = []
    for md in tracked_markdown():
        for target in link_targets(md):
            if is_external(target):
                continue
            if not resolve(md, target).exists():
                broken.append(f"{md.relative_to(ROOT)}: {target}")

    index = ROOT / "docs/README.md"
    indexed = {resolve(index, t).resolve() for t in link_targets(index) if not is_external(t)}
    unindexed = [
        str(md.relative_to(ROOT))
        for md in tracked_markdown()
        if md.is_relative_to(ROOT / "docs") and md != index and md.resolve() not in indexed
    ]

    for line in broken:
        print(f"broken link  {line}")
    for path in unindexed:
        print(f"not in docs/README.md  {path}")
    print(f"{len(broken)} broken links, {len(unindexed)} unindexed docs")
    return 1 if broken or unindexed else 0


if __name__ == "__main__":
    sys.exit(main())
