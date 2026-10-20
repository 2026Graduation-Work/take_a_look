"""Claude Code 훅(.claude/settings.json). CLAUDE.md, AGENTS.md는 '부탁'이라 어길 수 있어, 되돌리기 힘든 규칙 두 개만 훅으로 막는다.
종료 코드 2만 도구 실행을 막는다(1은 알림만). 막은 이유는 stderr로 Claude에게 간다.

- protect: .env 류(비밀키) 수정 금지. 템플릿 .env.example은 허용
- commit: git commit 전에 바뀐 블록의 빠른 검사(프론트 단위 테스트, 파이썬 ruff). 실패하면 커밋을 막는다
  pytest 전체와 build는 CI 필수 체크가 막으므로 여기서는 돌리지 않는다(커밋마다 수십 초가 늘어서)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def protect(tool_input: dict) -> str | None:
    name = Path(tool_input.get("file_path") or tool_input.get("notebook_path") or "").name
    if re.fullmatch(r"\.env(\..+)?", name) and name != ".env.example":
        return f"{name}는 비밀키 파일이라 Claude가 고치지 않아요. 바꿀 값은 사람이 직접 넣어 주세요."
    return None


def commit(tool_input: dict) -> str | None:
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", tool_input.get("command", "")):
        return None
    staged = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], cwd=ROOT,
                            capture_output=True, text=True).stdout.split()
    checks = []
    if any(path.startswith("frontend/") and path.endswith((".ts", ".tsx")) for path in staged):
        checks.append((["pnpm", "-s", "test:unit"], ROOT / "frontend"))
    python = [path for path in staged if path.endswith(".py")]
    if python:
        checks.append((["ruff", "check", *python], ROOT))
    for command, cwd in checks:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode:
            tail = (result.stdout + result.stderr).strip().splitlines()[-15:]
            return f"커밋 전 검사 실패({' '.join(command[:3])}). 고친 뒤 다시 커밋하세요.\n" + "\n".join(tail)
    return None


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    reason = {"protect": protect, "commit": commit}[sys.argv[1]](payload.get("tool_input", {}))
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
