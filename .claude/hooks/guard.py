"""Claude Code 훅. CLAUDE.md, AGENTS.md는 '부탁'이라 어길 수 있어, 되돌리기 힘든 규칙 두 개만 훅으로 막는다.
종료 코드 2만 도구 실행을 막는다(1은 알림만). 막은 이유는 stderr로 Claude에게 간다.

- protect: .env 류(비밀키) 읽기, 수정 금지. 템플릿 .env.example은 허용(권한 deny glob으로는 이 예외를 못 만든다, #10)
- push: 강제 push(--force, -f, --force-with-lease, +refspec)와 원격 삭제 push(--delete, -d, :브랜치) 금지. bash -c, eval로 감싼 실행 자리도 본다. 커밋 메시지, echo 안 글자는 보지 않는다. main은 Ruleset이 막지만 다른 브랜치는 뚫려 있다
- commit: git commit 전에 바뀐 영역의 빠른 검사만 돌린다. 느린 검사(전체 테스트, build)는 CI 필수 체크에 맡긴다

새 프로젝트에서는 아래 CHECKS만 고친다: (바뀐 파일 조건, 명령, 실행 폴더)
"""
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (조건 함수, 명령, 실행 폴더). 조건은 바뀐 파일 목록을 받아 True면 실행한다.
CHECKS = [
    (lambda files: any(f.startswith("frontend/") and f.endswith((".ts", ".tsx")) for f in files),
     ["pnpm", "-s", "test:unit"], "frontend"),
    (lambda files: any(f.endswith(".py") for f in files),
     ["ruff", "check", "."], "."),
]


def protect(tool_input: dict, tool_name: str = "") -> str | None:
    name = Path(tool_input.get("file_path", "")).name
    if not re.fullmatch(r"\.env(\..+)?", name) or name == ".env.example":
        return None
    if tool_name == "Read":
        return f"{name}는 비밀키 파일이라 Claude가 읽지 않아요. 필요한 변수 이름은 .env.example에 적어 주세요."
    return f"{name}는 비밀키 파일이라 Claude가 고치지 않아요. 바꿀 값은 사람이 직접 넣어 주세요."


FORCE = re.compile(r"--force(-with-lease(=.*)?)?|-[a-zA-Z]*f[a-zA-Z]*|\+.+")
DELETE = re.compile(r"--delete|-[a-zA-Z]*d[a-zA-Z]*|:.+")


SHELLS = {"bash", "sh", "zsh", "dash"}


def commands(text: str) -> list[list[str]]:
    """셸 명령 줄을 ; & | 줄바꿈으로 나눈 단어 목록들. 따옴표 안 글자는 나누지 않는다."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|\n")
    lexer.whitespace, lexer.whitespace_split = " \t\r", True
    try:
        words = list(lexer)
    except ValueError:  # 따옴표가 안 닫힘. 따옴표를 지우고 본다(막는 쪽으로 틀린다)
        words = re.sub(r"[\"']", " ", re.sub(r"[;&|\n]", " ; ", text)).split()
    out = [[]]
    for word in words:
        if set(word) <= set(";&|\n"):
            out.append([])
        else:
            out[-1].append(word)
    return [c for c in out if c]


def inner(words: list[str]) -> list[str]:
    """셸이 실행할 문자열만 고른다: bash -c "..."(-lc 등 c가 든 짧은 옵션의 다음 인자), eval 뒤 인자."""
    found = []
    for i, word in enumerate(words):
        if word == "eval":
            found.append(" ".join(words[i + 1:]))
        elif Path(word).name in SHELLS:
            for j in range(i + 1, len(words) - 1):
                if not words[j].startswith("-") or words[j].startswith("--"):
                    break
                if "c" in words[j]:
                    found.append(words[j + 1])
                    break
    return found


def push(tool_input: dict, depth: int = 0) -> str | None:
    for words in commands(tool_input.get("command", "")):
        for text in inner(words) if depth < 3 else []:
            if reason := push({"command": text}, depth + 1):
                return reason
        if "git" not in words or "push" not in words[words.index("git"):]:
            continue
        args = words[words.index("push", words.index("git")) + 1:]
        if any(FORCE.fullmatch(a) for a in args):
            return "강제 push는 막아 둡니다. 원격 기록을 지울 수 있어요. 꼭 필요하면 사람이 직접 실행해 주세요."
        if any(DELETE.fullmatch(a) for a in args):
            return ("원격 브랜치 삭제 push는 막아 둡니다. 머지 후 삭제는 gh pr merge --delete-branch로 하고, "
                    "그 밖의 삭제는 사람이 직접 실행해 주세요.")
    return None


def commit(tool_input: dict) -> str | None:
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", tool_input.get("command", "")):
        return None
    # shortcut: 커밋에 안 들어갈 변경도 검사한다. `git add -A && git commit`은 훅 시점에 스테이징 전이라 작업 트리 전체를 본다
    status = subprocess.run(["git", "status", "--porcelain", "--no-renames", "-uall", "-z"], cwd=ROOT, check=False,
                            capture_output=True, text=True).stdout
    changed = [entry[3:] for entry in status.split("\0") if entry]
    for condition, command, folder in CHECKS:
        cwd = ROOT / folder
        if not condition(changed) or not cwd.exists():
            continue
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
        if result.returncode:
            tail = (result.stdout + result.stderr).strip().splitlines()[-15:]
            return f"커밋 전 검사 실패({' '.join(command[:3])}). 고친 뒤 다시 커밋하세요.\n" + "\n".join(tail)
    return None


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    check, tool_input = sys.argv[1], payload.get("tool_input", {})
    if check == "protect":
        reason = protect(tool_input, payload.get("tool_name", ""))
    else:
        reason = {"push": push, "commit": commit}[check](tool_input)
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
