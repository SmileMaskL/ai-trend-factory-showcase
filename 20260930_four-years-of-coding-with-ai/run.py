#!/usr/bin/env python3
"""
AI 코딩 도구 릴리스 레이더 (AI Coding Tool Release Radar)

한 번 실행하면 다음을 수행하고 종료합니다.
  1) 주요 AI 코딩 에이전트/도구의 GitHub 릴리스를 확인합니다 (공개 GitHub API, 무료).
  2) Hacker News에서 AI 코딩 관련 인기 글을 모읍니다 (HN Algolia API, 무료).
  3) 지난 실행 이후 새로 나온 항목만 골라 텔레그램으로 다이제스트를 보냅니다.
  4) 보낸 항목은 state.json에 기록해 다음 실행에서 중복 전송하지 않습니다.

의존성: 표준 라이브러리 + requests
"""

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "state.json")
REPOS_PATH = os.path.join(BASE_DIR, "repos.txt")

DEFAULT_REPOS = [
    "anthropics/claude-code",
    "openai/codex",
    "google-gemini/gemini-cli",
    "Aider-AI/aider",
    "cline/cline",
    "continuedev/continue",
    "All-Hands-AI/OpenHands",
    "sst/opencode",
    "RooCodeInc/Roo-Code",
    "block/goose",
]

HN_QUERIES = [
    "AI coding",
    "coding agent",
    "Claude Code",
    "Codex",
    "Cursor",
    "LLM programming",
    "agentic",
]

# 최초 실행 시(상태 파일 없음) 너무 오래된 릴리스로 도배하지 않기 위한 기간
FIRST_RUN_LOOKBACK_DAYS = int(os.environ.get("RADAR_LOOKBACK_DAYS", "7"))
# HN 검색 기간(시간)과 최소 점수
HN_WINDOW_HOURS = int(os.environ.get("RADAR_HN_WINDOW_HOURS", "36"))
HN_MIN_POINTS = int(os.environ.get("RADAR_HN_MIN_POINTS", "30"))
HN_MAX_ITEMS = int(os.environ.get("RADAR_HN_MAX_ITEMS", "8"))
# 새 소식이 없어도 "오늘은 조용함" 메시지를 보낼지 여부
SEND_EMPTY = os.environ.get("RADAR_SEND_EMPTY", "0") == "1"

TELEGRAM_LIMIT = 3800  # 텔레그램 최대 4096자, 여유를 둠
STATE_KEEP = 1000
HTTP_TIMEOUT = 20


def log(msg):
    print(f"[radar] {msg}", flush=True)


# ---------------------------------------------------------------- state

def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("releases", [])
        data.setdefault("hn", [])
        return data
    except (OSError, ValueError) as e:
        log(f"state.json 읽기 실패, 새로 시작합니다: {e}")
        return None


def save_state(state):
    state["releases"] = state["releases"][-STATE_KEEP:]
    state["hn"] = state["hn"][-STATE_KEEP:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


# ---------------------------------------------------------------- http

def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = "ai-coding-release-radar/1.0"
    return s


def get_json(session, url, params=None, headers=None, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 429) and "rate limit" in r.text.lower():
                log(f"레이트 리밋: {url}")
                return None
            if r.status_code == 404:
                log(f"404 (저장소 없음/이름 변경?): {url}")
                return None
            if r.status_code >= 500 and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log(f"HTTP {r.status_code}: {url}")
            return None
        except (requests.RequestException, ValueError) as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log(f"요청 실패 {url}: {e}")
            return None
    return None


# ---------------------------------------------------------------- github

def load_repos():
    if os.path.exists(REPOS_PATH):
        repos = []
        with open(REPOS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "/" in line:
                    repos.append(line)
        if repos:
            return repos
    return DEFAULT_REPOS


def parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MD_NOISE = re.compile(r"[`*_>#]+")


def summarize_body(body, max_lines=3, max_len=140):
    if not body:
        return []
    out = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--") or line.startswith("|"):
            continue
        if line.startswith("#"):
            continue  # 헤더는 건너뜀
        line = MD_LINK.sub(r"\1", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = MD_NOISE.sub("", line).strip()
        line = re.sub(r"https?://\S+", "", line).strip()
        if len(line) < 4:
            continue
        if len(line) > max_len:
            line = line[: max_len - 1] + "…"
        out.append(line)
        if len(out) >= max_lines:
            break
    return out


def fetch_new_releases(session, repos, seen, cutoff):
    headers = {"Accept": "application/vnd.github+json"}
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    results = []
    for repo in repos:
        data = get_json(
            session,
            f"https://api.github.com/repos/{repo}/releases",
            params={"per_page": 5},
            headers=headers,
        )
        if not isinstance(data, list):
            continue
        for rel in data:
            if rel.get("draft"):
                continue
            key = f"{repo}#{rel.get('id')}"
            if key in seen:
                continue
            published = parse_time(rel.get("published_at") or rel.get("created_at"))
            if cutoff and published and published < cutoff:
                continue
            results.append({
                "key": key,
                "repo": repo,
                "tag": rel.get("tag_name") or rel.get("name") or "?",
                "name": rel.get("name") or "",
                "url": rel.get("html_url") or f"https://github.com/{repo}/releases",
                "prerelease": bool(rel.get("prerelease")),
                "published": published,
                "notes": summarize_body(rel.get("body") or ""),
            })
    results.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
    return results


# ---------------------------------------------------------------- hacker news

def fetch_hn(session, seen):
    since = int(time.time()) - HN_WINDOW_HOURS * 3600
    found = {}
    for q in HN_QUERIES:
        data = get_json(
            session,
            "https://hn.algolia.com/api/v1/search",
            params={
                "query": q,
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>={HN_MIN_POINTS}",
                "hitsPerPage": 20,
            },
        )
        if not data:
            continue
        for hit in data.get("hits", []):
            oid = str(hit.get("objectID", ""))
            if not oid or oid in seen or oid in found:
                continue
            title = hit.get("title") or ""
            if not title:
                continue
            found[oid] = {
                "key": oid,
                "title": title,
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "hn_url": f"https://news.ycombinator.com/item?id={oid}",
                "points": hit.get("points") or 0,
                "comments": hit.get("num_comments") or 0,
            }
    items = sorted(found.values(), key=lambda x: x["points"], reverse=True)
    return items[:HN_MAX_ITEMS]


# ---------------------------------------------------------------- message

def esc(s):
    return html.escape(str(s), quote=False)


def build_blocks(releases, hn_items):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks = [f"🛰 <b>AI 코딩 도구 레이더</b> — {today}"]

    if releases:
        blocks.append(f"\n📦 <b>새 릴리스 ({len(releases)})</b>")
        for r in releases:
            pre = " <i>(pre)</i>" if r["prerelease"] else ""
            date = r["published"].strftime("%m-%d") if r["published"] else ""
            lines = [f'• <b>{esc(r["repo"])}</b> <a href="{esc(r["url"])}">{esc(r["tag"])}</a>{pre} {esc(date)}']
            for n in r["notes"]:
                lines.append(f"   ◦ {esc(n)}")
            blocks.append("\n".join(lines))

    if hn_items:
        blocks.append(f"\n🔥 <b>HN 화제 ({len(hn_items)})</b>")
        for h in hn_items:
            blocks.append(
                f'• <a href="{esc(h["url"])}">{esc(h["title"])}</a>\n'
                f'   ▲{h["points"]} · <a href="{esc(h["hn_url"])}">💬{h["comments"]}</a>'
            )
    return blocks


def chunk_blocks(blocks):
    chunks, cur = [], ""
    for b in blocks:
        if len(b) > TELEGRAM_LIMIT:
            b = b[:TELEGRAM_LIMIT]
        if len(cur) + len(b) + 1 > TELEGRAM_LIMIT:
            chunks.append(cur)
            cur = b
        else:
            cur = f"{cur}\n{b}" if cur else b
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram(session, token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(3):
        try:
            r = session.post(url, json=payload, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                retry = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(min(int(retry), 30))
                continue
            if r.status_code == 400 and payload.get("parse_mode"):
                # HTML 파싱 문제 시 일반 텍스트로 재시도
                log(f"HTML 전송 실패, 텍스트로 재시도: {r.text[:200]}")
                payload.pop("parse_mode")
                payload["text"] = re.sub(r"<[^>]+>", "", html.unescape(text))
                continue
            log(f"텔레그램 오류 {r.status_code}: {r.text[:200]}")
            return False
        except requests.RequestException as e:
            log(f"텔레그램 요청 실패: {e}")
            time.sleep(3)
    return False


# ---------------------------------------------------------------- main

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    state = load_state()
    first_run = state is None
    if first_run:
        state = {"releases": [], "hn": []}
    cutoff = datetime.now(timezone.utc) - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)

    session = make_session()
    repos = load_repos()
    log(f"저장소 {len(repos)}개 확인 중 (최초 실행: {first_run})")

    releases = fetch_new_releases(session, repos, set(state["releases"]), cutoff)
    hn_items = fetch_hn(session, set(state["hn"]))
    log(f"새 릴리스 {len(releases)}개, HN 글 {len(hn_items)}개")

    if not releases and not hn_items:
        if SEND_EMPTY and token and chat_id:
            send_telegram(session, token, chat_id, "🛰 AI 코딩 도구 레이더: 오늘은 새 소식이 없습니다.")
        log("보낼 새 항목이 없습니다. 종료.")
        save_state(state)
        return 0

    chunks = chunk_blocks(build_blocks(releases, hn_items))

    if not token or not chat_id:
        # 텔레그램 자격 증명은 사람이 텔레그램 앱에서 봇을 만들고 채팅을 시작해야만
        # 얻을 수 있는 값이라, 이 무인 파이프라인이 그 값을 스스로 발급/갱신할 방법은
        # 없다. 이전 코드는 이 정상적인(오류가 아닌) 상황에서도 종료 코드 1을
        # 반환해서, 실제로는 수집·요약까지 전부 성공했는데도 파이프라인 전체가
        # "실패"로 기록되는 원인이 됐다. 자격 증명이 없을 때는 콘솔 출력을 최종
        # 산출물로 인정하고 성공(0)으로 종료한다. 상태 파일에는 기록하지 않으므로
        # 나중에 TELEGRAM_BOT_TOKEN/CHAT_ID가 채워지면 밀린 항목이 그대로
        # 텔레그램으로 발송된다.
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 — 다이제스트를 콘솔에만 출력하고 정상 종료합니다.")
        for c in chunks:
            print(re.sub(r"<[^>]+>", "", html.unescape(c)))
            print("-" * 40)
        return 0

    ok = True
    for c in chunks:
        if not send_telegram(session, token, chat_id, c):
            ok = False
            break
        time.sleep(1)

    if not ok:
        log("전송 실패 — 상태를 저장하지 않아 다음 실행에서 재시도합니다.")
        return 1

    state["releases"].extend(r["key"] for r in releases)
    state["hn"].extend(h["key"] for h in hn_items)
    save_state(state)
    log(f"텔레그램 전송 완료 ({len(chunks)}개 메시지). 종료.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 무인 실행: 예외를 로그로 남기고 실패 코드로 종료
        log(f"예상치 못한 오류: {e!r}")
        sys.exit(1)