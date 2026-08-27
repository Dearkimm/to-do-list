# -*- coding: utf-8 -*-
"""전일(정확히는 마지막 분석 이후) 대화를 claude -p 로 분석해 요약과 할 일 목록을 갱신한다."""
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import collect

# exe(frozen)로 실행되면 데이터는 exe 옆에 둔다
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).parent
TASKS_FILE = BASE / "tasks.json"
BRIEF_DIR = BASE / "briefings"
INBOX = BASE / "inbox"
LOG_DIR = BASE / "logs"
MODEL = "opus"


def find_claude():
    """PC마다 다른 Claude Code CLI 위치를 자동 탐색."""
    p = shutil.which("claude")
    if p:
        return p
    cand = Path.home() / ".local" / "bin" / "claude.exe"
    if cand.exists():
        return str(cand)
    raise RuntimeError("Claude Code CLI를 찾을 수 없습니다. "
                       "이 PC에 Claude Code 설치·로그인이 필요합니다.")
STATUSES = ("진행", "보류", "완료")
WEEKDAYS = "월화수목금토일"


def log(msg):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n"
    with open(LOG_DIR / f"analyze-{datetime.now():%Y%m}.log", "a", encoding="utf-8") as f:
        f.write(line)


def load_state():
    if TASKS_FILE.exists():
        state = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    else:
        state = {"last_run": None, "seq": 0, "tasks": []}
    state.setdefault("deleted", [])
    gone = [t for t in state["tasks"] if t["status"] == "삭제"]
    if gone:
        state["tasks"] = [t for t in state["tasks"] if t["status"] != "삭제"]
        state["deleted"] += [t["title"] for t in gone]
    return state


def save_state(state):
    tmp = TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(TASKS_FILE)


def read_inbox():
    docs, used = [], []
    total = 0
    for p in sorted(INBOX.glob("*")):
        if not p.is_file() or p.suffix.lower() not in (".txt", ".md"):
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")[:30000]
        except Exception:
            continue
        if total + len(body) > 60000:
            break
        docs.append(f"\n### 참고 문서: {p.name}\n{body}\n")
        used.append(p)
        total += len(body)
    return "".join(docs), used


def user_name():
    cfg = BASE / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get(
                "user_name", "사용자")
        except Exception:
            pass
    return "사용자"


def build_prompt(digest, inbox_text, tasks, deleted):
    now = datetime.now().astimezone()
    today = f"{now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]}) {now:%H:%M} 현재"
    task_lines = [
        f'- {t["id"]} [{t["status"]}] {t["title"]} (프로젝트: {t.get("project","")}, 기한: {t.get("due") or "없음"})'
        + (f' — 메모: {t["note"][:100]}' if t.get("note") else "")
        for t in tasks
    ]
    return f"""당신은 {user_name()}의 업무 비서다. 오늘은 {today}이다.
아래에 (1) 최근 Claude 작업 세션의 대화 발췌, (2) 참고 문서, (3) 현재 할 일 목록이 있다.

반드시 아래 형태의 JSON 객체 하나만 출력하라. 코드펜스, 설명, 다른 텍스트 일절 금지. 도구 사용 금지.
{{
 "briefing": "(플레인 텍스트 정리)",
 "new_tasks": [{{"title": "", "project": "", "due": "YYYY-MM-DD 또는 null", "note": ""}}],
 "updates": [{{"id": "T001", "status": "완료", "reason": ""}}]
}}

briefing 작성 형식(이모지·장식·과장 금지, 담백한 한국어):
[어제까지 한 일]
- 프로젝트별로 굵직한 것 위주 3~7줄
[오늘 할 일]
- 이어서 해야 할 일을 기한 임박 순으로
[기한·일정 언급]
- 대화나 문서에서 발견한 기한 문장의 요지와 환산한 날짜 (없으면 "새로 발견된 기한 없음")

규칙:
- new_tasks: 대화·문서에서 "~까지 해야 한다"류의 할 일과 기한을 찾아 추가한다. 추가 전에 반드시 현재 목록·삭제된 항목과 **의미를 비교**하여, 워딩이 달라도 같은 일이면 절대 추가하지 않는다. (예: "5차 쿼리 실행"과 "DB 쿼리 돌리기"는 같은 일) 애매하면 추가하지 않는 쪽을 택한다.
- new_tasks의 title은 20자 내외로 간결하게 핵심만 쓴다. 파일명·테이블명·배경 설명 등 세부사항은 전부 note에 넣는다.
- 상대적 기한("다음 주 수요일까지", "킥오프 전")은 오늘 날짜 기준 구체 날짜로 환산하고, 근거가 약하면 due를 null로 둔다.
- updates(완료 판정): 현재 할 일 목록의 **각 항목을 하나씩** 대화와 대조하여, 그 일이 실제로 수행된 근거가 있으면 status "완료"로 제안한다. Claude가 "~완료했습니다", "반영했습니다", "push했습니다", "수정했습니다"처럼 실행을 보고한 것, 사용자가 "됐다/끝났다"고 한 것, 결과물(파일·커밋·문서)이 만들어진 것은 모두 완료 근거다. 워딩이 달라도 같은 일이면 매칭한다. reason에는 근거 문장을 짧게 적는다. "완료" 이외의 status는 절대 제안하지 않는다.
- [어제까지 한 일]에 적은 내용이 기존 할 일과 같은 일이면 반드시 그 할 일을 updates로 완료 제안한다.
- 대화에서 이미 끝난 것으로 확인되는 일은 new_tasks에 넣지 않는다. (할 일이 아니라 이력이다)
- 새 할 일은 확실하지 않으면 만들어내지 않는다.

### 현재 할 일 목록
{chr(10).join(task_lines) if task_lines else "(비어 있음)"}

### 삭제된 항목 (다시 추가 금지)
{chr(10).join("- " + d for d in deleted) if deleted else "(없음)"}

### 최근 세션 대화 발췌
{digest if digest.strip() else "(기간 내 대화 없음)"}
{inbox_text}"""


FALLBACK_MODEL = "sonnet"   # 주 모델 과부하(529) 시 자동 대체
CLAUDE_TIMEOUT = 420        # 초. 재시도 포함 이 이상 걸리면 실패로 처리
LOCK_FILE = BASE / "analyze.lock"


def call_claude(prompt):
    # 헤드리스 실행엔 MCP 커넥터(Gmail·Notion 등)가 필요 없다 — 로딩 생략으로 속도·안정성 확보
    empty_mcp = BASE / "empty_mcp.json"
    if not empty_mcp.exists():
        empty_mcp.write_text('{"mcpServers":{}}', encoding="utf-8")
    cmd = [find_claude(), "-p", "--model", MODEL, "--fallback-model", FALLBACK_MODEL,
           "--strict-mcp-config", "--mcp-config", str(empty_mcp)]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=CLAUDE_TIMEOUT, cwd=str(BASE),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude 응답 없음 ({CLAUDE_TIMEOUT // 60}분 초과) — 서버 과부하 가능성, 잠시 후 다시 시도")
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()[-300:]
        if "529" in detail or "overloaded" in detail.lower():
            raise RuntimeError("Claude 서버 과부하(529) — 잠시 후 다시 시도")
        raise RuntimeError(f"claude -p 실패 (code {proc.returncode}): {detail[:300]}")
    return proc.stdout


def acquire_lock():
    """분석 중복 실행 방지. 10분 넘은 잠금은 죽은 것으로 보고 무시."""
    if LOCK_FILE.exists():
        age = datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
        if age < 600:
            return False
    LOCK_FILE.write_text(str(datetime.now()), encoding="utf-8")
    return True


def release_lock():
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


def parse_json(raw):
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("응답에서 JSON을 찾지 못함")
    return json.loads(raw[start : end + 1])


def merge(state, result):
    now = f"{datetime.now():%Y-%m-%d %H:%M}"
    by_id = {t["id"]: t for t in state["tasks"]}
    for upd in result.get("updates", []):
        t = by_id.get(upd.get("id"))
        # AI 제안은 진행/보류 → 완료 방향만 허용 (사용자가 정한 상태를 되돌리지 못하게)
        if t and upd.get("status") == "완료" and t["status"] in ("진행", "보류"):
            t["status"] = "완료"
            t["updated"] = now
            t["auto_note"] = f'자동 변경: {upd.get("reason", "")}'.strip()
    existing_titles = {t["title"] for t in state["tasks"]} | set(
        state.get("deleted", []))
    for nt in result.get("new_tasks", []):
        title = (nt.get("title") or "").strip()
        if not title or title in existing_titles:
            continue
        state["seq"] += 1
        state["tasks"].append({
            "id": f'T{state["seq"]:03d}',
            "title": title,
            "project": (nt.get("project") or "").strip(),
            "due": nt.get("due") or None,
            "note": (nt.get("note") or "").strip(),
            "status": "진행",
            "source": "auto",
            "created": now,
            "updated": now,
        })


def run(days=None, force=False):
    if not acquire_lock():
        log("건너뜀: 다른 분석이 진행 중")
        if force:
            raise RuntimeError("다른 분석이 진행 중입니다 — 잠시 후 다시 시도")
        return
    try:
        _run(days, force)
    finally:
        release_lock()


def _run(days, force):
    INBOX.mkdir(exist_ok=True)
    (INBOX / "processed").mkdir(exist_ok=True)
    state = load_state()
    now = datetime.now().astimezone()
    # 스케줄 실행 시: 직전 분석이 10분 이내면 진짜 중복이므로 건너뛴다 (수동 새로고침은 예외)
    # (새 대화가 없으면 아래에서 AI 호출 없이 끝나므로 이 이상 막을 필요가 없다)
    if not force and days is None and state["last_run"]:
        elapsed = (now - datetime.fromisoformat(state["last_run"])).total_seconds()
        if elapsed < 10 * 60:
            log(f"건너뜀: 마지막 분석 후 {int(elapsed // 60)}분")
            return
    if days is not None:
        since = now - timedelta(days=days)
    elif state["last_run"]:
        since = datetime.fromisoformat(state["last_run"]) - timedelta(hours=1)
    else:
        since = now - timedelta(days=1)
    log(f"분석 시작: {since:%Y-%m-%d %H:%M} 이후")

    digest = collect.build_digest(since)
    inbox_text, inbox_files = read_inbox()
    log(f"수집 완료: 발췌 {len(digest):,}자, 문서 {len(inbox_files)}건")

    # 새 대화도 문서도 없으면 AI 호출 없이 종료 (구독 사용량 절약)
    if not digest.strip() and not inbox_files:
        state["last_run"] = now.isoformat()
        save_state(state)
        log("새 내용 없음: AI 호출 생략")
        return

    raw = call_claude(build_prompt(digest, inbox_text, state["tasks"],
                                   state.get("deleted", [])))
    result = parse_json(raw)

    # AI 호출에 수 분이 걸리므로, 그 사이 사용자가 바꾼 상태를 잃지 않게
    # 디스크에서 최신 상태를 다시 읽은 뒤 병합한다
    state = load_state()
    merge(state, result)
    state["last_run"] = now.isoformat()
    save_state(state)

    briefing = result.get("briefing", "").strip()
    header = f"===== {now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]}) {now:%H:%M} 요약 =====\n\n"
    BRIEF_DIR.mkdir(exist_ok=True)
    (BRIEF_DIR / f"{now:%Y-%m-%d}.txt").write_text(header + briefing + "\n", encoding="utf-8")
    (BASE / "latest.txt").write_text(header + briefing + "\n", encoding="utf-8")

    for p in inbox_files:
        shutil.move(str(p), str(INBOX / "processed" / p.name))
    log(f'분석 완료: 신규 {len(result.get("new_tasks", []))}건, 갱신 {len(result.get("updates", []))}건')


if __name__ == "__main__":
    days = None
    if "--days" in sys.argv:
        days = float(sys.argv[sys.argv.index("--days") + 1])
    try:
        run(days)
    except Exception as e:
        log(f"오류: {e!r}")
        raise
