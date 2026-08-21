# -*- coding: utf-8 -*-
"""Claude Code 세션 JSONL에서 사람/Claude 대화 텍스트만 추출하는 수집기."""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
SKIP_TOKENS = ("claude-briefing",)  # 이 도구 자신의 헤드리스 세션은 제외
# 설치 폴더명이 달라도 자기 세션을 걸러내도록 자기 경로 토큰도 계산
if getattr(sys, "frozen", False):
    _SELF_DIR = Path(sys.executable).parent
else:
    _SELF_DIR = Path(__file__).parent
_SELF_TOKEN = re.sub(r"[^A-Za-z0-9]", "-", str(_SELF_DIR))
MAX_USER_CHARS = 3000
MAX_ASSIST_CHARS = 1500
MAX_TOTAL_CHARS = 150_000


def _local(ts_str):
    """ISO(Z) 타임스탬프 → 로컬(KST) datetime."""
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone()
    except Exception:
        return None


def _texts_from_content(content):
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(block.get("text", ""))
    return out


def _keep_user_text(t):
    t = t.strip()
    if not t or t.startswith("<") or t.startswith("Caveat:"):
        return False
    return True


def iter_session_messages(jsonl_path, since=None, until=None):
    """(ts, role, text, cwd) 목록을 시간순으로 돌려준다."""
    date_keys = None
    if since is not None:
        days = (datetime.now().astimezone() - since).days + 3
        date_keys = tuple(
            (since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(max(days, 1) + 1)
        )
    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if date_keys and not any(k in line for k in date_keys):
                continue
            if '"type":"user"' not in line and '"type":"assistant"' not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("isSidechain"):
                continue
            typ = obj.get("type")
            ts = _local(obj.get("timestamp", ""))
            if ts is None:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            msg = obj.get("message") or {}
            cwd = obj.get("cwd", "")
            if typ == "user":
                if (obj.get("origin") or {}).get("kind") not in ("human", None):
                    continue
                for t in _texts_from_content(msg.get("content")):
                    if _keep_user_text(t):
                        yield ts, "사용자", t[:MAX_USER_CHARS], cwd
            elif typ == "assistant":
                joined = "\n".join(_texts_from_content(msg.get("content"))).strip()
                if joined:
                    yield ts, "Claude", joined[:MAX_ASSIST_CHARS], cwd


def _session_files():
    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        if any(tok in proj_dir.name for tok in SKIP_TOKENS) \
                or proj_dir.name == _SELF_TOKEN:
            continue
        for p in sorted(proj_dir.glob("*.jsonl")):
            yield p


def build_digest(since, until=None):
    """기간 내 모든 세션 대화를 하나의 텍스트로 묶는다."""
    sessions = []
    for p in _session_files():
        mtime = datetime.fromtimestamp(p.stat().st_mtime).astimezone()
        if mtime < since:  # 기간 내 수정이 없으면 통째로 스킵
            continue
        msgs = list(iter_session_messages(p, since=since, until=until))
        if msgs:
            sessions.append((msgs[0][0], p.stem[:8], msgs))
    sessions.sort(key=lambda s: s[0])

    # (헤더, 본문) 블록을 만들고, 한도 초과 시 오래된 쪽부터 잘라 최신 대화를 보존한다
    blocks = []
    for first_ts, sid, msgs in sessions:
        proj = Path(msgs[0][3]).name or "(작업 폴더 미상)"
        header = f"\n### 세션 {first_ts:%Y-%m-%d %H:%M} 시작 | 폴더: {proj} | id {sid}\n"
        entries = [f"[{role} {ts:%m-%d %H:%M}] {text}\n" for ts, role, text, _ in msgs]
        blocks.append([header, entries])

    total = sum(len(h) + sum(len(e) for e in ent) for h, ent in blocks)
    truncated = total > MAX_TOTAL_CHARS
    while total > MAX_TOTAL_CHARS and blocks:
        header, entries = blocks[0]
        if entries:
            total -= len(entries.pop(0))
        else:
            total -= len(header)
            blocks.pop(0)

    parts = ["(용량 한도로 오래된 대화 일부는 생략됨)\n"] if truncated else []
    for header, entries in blocks:
        if entries:
            parts.append(header)
            parts.extend(entries)
    return "".join(parts)


def search(keyword, max_hits=200):
    """전체 세션에서 키워드가 든 대화만 찾는다(LLM 미사용, 무료)."""
    kw = keyword.lower()
    hits = []
    for p in _session_files():
        # 원시 라인 프리필터: 키워드 없는 파일/라인은 파싱하지 않는다
        found_raw = False
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if kw in line.lower():
                    found_raw = True
                    break
        if not found_raw:
            continue
        for ts, role, text, cwd in iter_session_messages(p):
            if kw in text.lower():
                proj = Path(cwd).name if cwd else ""
                snippet = text.replace("\n", " ")
                i = snippet.lower().find(kw)
                start = max(0, i - 80)
                hits.append((ts, proj, role, snippet[start:start + 240]))
                if len(hits) >= max_hits:
                    return sorted(hits)
    return sorted(hits)


if __name__ == "__main__":
    days = 1
    if "--days" in sys.argv:
        days = float(sys.argv[sys.argv.index("--days") + 1])
    if "--search" in sys.argv:
        kw = sys.argv[sys.argv.index("--search") + 1]
        for ts, proj, role, snip in search(kw):
            print(f"{ts:%Y-%m-%d %H:%M} [{proj}] {role}: {snip}")
    else:
        since = datetime.now().astimezone() - timedelta(days=days)
        sys.stdout.reconfigure(encoding="utf-8")
        print(build_digest(since))
