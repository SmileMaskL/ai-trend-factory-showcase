#!/usr/bin/env python3
"""
게임 디컴파일/리버스엔지니어링 OSS + AI 포팅 커뮤니티 신호 레이더

오늘의 트렌드(Xbox가 게임 디컴파일/에뮬레이션 실험을 공식 수용)에서 착안.
- GitHub: 최근 며칠간 활발히 업데이트된 "게임 디컴파일 / ROM 해킹 / 게임 보존" 오픈소스 저장소를 검색
- HN(Algolia): 최근 며칠간 올라온 "게임 디컴파일 / 에뮬레이션 / AI 포팅" 관련 토론 스토리를 검색
두 신호를 합쳐, 이전에 알림을 보낸 적 없는 것만 골라 텔레그램으로 전송하는
1회성(하루 1번 실행 후 종료) 스크립트.

텔레그램 환경변수(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)가 없는 격리 실행 환경에서도
실패하지 않고 콘솔(stdout)에 리포트를 출력하는 방식으로 항상 정상 종료한다.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "data" / "seen.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

GITHUB_API = "https://api.github.com/search/repositories"
HN_API = "https://hn.algolia.com/api/v1/search_by_date"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

DEFAULT_GITHUB_QUERIES = [
    "decomp game in:name,description",
    "topic:decompilation topic:game",
    "topic:rom-hacking",
    "topic:game-preservation",
    "topic:reverse-engineering topic:retro-gaming",
]

DEFAULT_HN_QUERIES = [
    "game decompilation",
    "console emulation",
    "ROM hacking",
    "game preservation",
    "reverse engineering game",
    "AI game port",
]

GITHUB_LOOKBACK_DAYS = 3
HN_LOOKBACK_HOURS = 72
MAX_RESULTS_PER_QUERY = 8
MAX_GITHUB_IN_MESSAGE = 8
MAX_HN_IN_MESSAGE = 8
MIN_STARS = 2


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_watchlist():
    default = {
        "github_queries": DEFAULT_GITHUB_QUERIES,
        "hn_queries": DEFAULT_HN_QUERIES,
    }
    data = load_json(WATCHLIST_FILE, default)
    return (
        data.get("github_queries", DEFAULT_GITHUB_QUERIES),
        data.get("hn_queries", DEFAULT_HN_QUERIES),
    )


def github_search(query, since_date, session):
    q = f"{query} pushed:>={since_date}"
    params = {
        "q": q,
        "sort": "updated",
        "order": "desc",
        "per_page": MAX_RESULTS_PER_QUERY,
    }
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "game-decomp-radar-bot"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = session.get(GITHUB_API, params=params, headers=headers, timeout=20)
    except requests.RequestException as e:
        print(f"[warn] GitHub 요청 실패 (query={query!r}): {e}", file=sys.stderr)
        return []

    if resp.status_code == 403:
        print(f"[warn] GitHub API rate limit 도달 (query={query!r})", file=sys.stderr)
        return []
    if resp.status_code != 200:
        print(f"[warn] GitHub API 오류 {resp.status_code} (query={query!r})", file=sys.stderr)
        return []

    items = resp.json().get("items", [])
    results = []
    for item in items:
        stars = item.get("stargazers_count", 0)
        if stars < MIN_STARS:
            continue
        results.append({
            "full_name": item.get("full_name"),
            "html_url": item.get("html_url"),
            "description": (item.get("description") or "").strip(),
            "stargazers_count": stars,
            "pushed_at": item.get("pushed_at"),
        })
    return results


def hn_search(query, since_ts, session):
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": MAX_RESULTS_PER_QUERY,
    }
    try:
        resp = session.get(HN_API, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[warn] HN 검색 실패 (query={query!r}): {e}", file=sys.stderr)
        return []

    hits = resp.json().get("hits", [])
    results = []
    for hit in hits:
        obj_id = hit.get("objectID")
        if not obj_id:
            continue
        results.append({
            "objectID": obj_id,
            "title": hit.get("title") or "(제목 없음)",
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={obj_id}",
            "points": hit.get("points", 0),
            "num_comments": hit.get("num_comments", 0),
            "matched_query": query,
        })
    return results


def send_telegram_message(text, token, chat_id):
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, data=payload, timeout=20)
    if resp.status_code != 200:
        print(f"[error] 텔레그램 전송 실패: {resp.status_code} {resp.text}", file=sys.stderr)
        return False
    return True


def chunk_text(lines, max_len=3500):
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def strip_html(text):
    return (
        text.replace("<b>", "")
        .replace("</b>", "")
        .replace("<a href=\"", "")
        .replace("\">", " ")
        .replace("</a>", "")
    )


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    telegram_configured = bool(token and chat_id)
    if not telegram_configured:
        print(
            "[warn] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 없어 "
            "텔레그램 전송 대신 콘솔 출력으로 대체합니다.",
            file=sys.stderr,
        )

    github_queries, hn_queries = load_watchlist()
    seen = load_json(STATE_FILE, {"github": {}, "hn": {}})
    seen.setdefault("github", {})
    seen.setdefault("hn", {})

    session = requests.Session()

    since_date = (datetime.now(timezone.utc) - timedelta(days=GITHUB_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    new_repos = []
    seen_repos_this_run = set()
    for query in github_queries:
        results = github_search(query, since_date, session)
        time.sleep(2)  # GitHub 무인증 검색 API rate limit(10/min) 보호
        for repo in results:
            name = repo["full_name"]
            if not name or name in seen["github"] or name in seen_repos_this_run:
                continue
            seen_repos_this_run.add(name)
            new_repos.append(repo)
    new_repos.sort(key=lambda r: r["stargazers_count"], reverse=True)
    new_repos = new_repos[:MAX_GITHUB_IN_MESSAGE]

    since_ts = int((datetime.now(timezone.utc) - timedelta(hours=HN_LOOKBACK_HOURS)).timestamp())
    new_stories = []
    seen_stories_this_run = set()
    for query in hn_queries:
        results = hn_search(query, since_ts, session)
        for hit in results:
            obj_id = hit["objectID"]
            if obj_id in seen["hn"] or obj_id in seen_stories_this_run:
                continue
            seen_stories_this_run.add(obj_id)
            new_stories.append(hit)
    new_stories.sort(key=lambda h: h["points"], reverse=True)
    new_stories = new_stories[:MAX_HN_IN_MESSAGE]

    if not new_repos and not new_stories:
        print("[info] 새로운 게임 디컴파일/에뮬레이션 신호가 없습니다. 알림을 보내지 않습니다.")
        for name in seen_repos_this_run:
            seen["github"].setdefault(name, datetime.now(timezone.utc).isoformat())
        for obj_id in seen_stories_this_run:
            seen["hn"].setdefault(obj_id, datetime.now(timezone.utc).isoformat())
        save_json(STATE_FILE, seen)
        return

    header = (
        f"🕹️ <b>게임 디컴파일 & AI 포팅 레이더</b> "
        f"({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n"
        f"신규 OSS {len(new_repos)}건 · 신규 토론 {len(new_stories)}건\n"
    )
    lines = [header]

    if new_repos:
        lines.append("— 📦 <b>신규/업데이트된 디컴파일·보존 저장소</b> —")
        for repo in new_repos:
            desc = repo["description"][:120] if repo["description"] else "(설명 없음)"
            lines.append(
                f"⭐ {repo['stargazers_count']} · "
                f"<a href=\"{repo['html_url']}\">{repo['full_name']}</a>\n{desc}"
            )

    if new_stories:
        lines.append("— 💬 <b>신규 커뮤니티 토론</b> —")
        for hit in new_stories:
            lines.append(
                f"👍 {hit['points']} 💬 {hit['num_comments']} · "
                f"<a href=\"{hit['url']}\">{hit['title']}</a>\n검색어: {hit['matched_query']}"
            )

    chunks = chunk_text(lines)
    all_sent = True

    if telegram_configured:
        for chunk in chunks:
            ok = send_telegram_message(chunk, token, chat_id)
            all_sent = all_sent and ok
            time.sleep(1)
    else:
        for chunk in chunks:
            print(strip_html(chunk))
            print("---")

    if all_sent:
        for repo in new_repos:
            seen["github"][repo["full_name"]] = datetime.now(timezone.utc).isoformat()
        for name in seen_repos_this_run:
            seen["github"].setdefault(name, datetime.now(timezone.utc).isoformat())
        for hit in new_stories:
            seen["hn"][hit["objectID"]] = datetime.now(timezone.utc).isoformat()
        for obj_id in seen_stories_this_run:
            seen["hn"].setdefault(obj_id, datetime.now(timezone.utc).isoformat())
        save_json(STATE_FILE, seen)
        if telegram_configured:
            print(f"[info] 저장소 {len(new_repos)}건, 토론 {len(new_stories)}건을 텔레그램으로 전송 완료.")
        else:
            print(f"[info] 저장소 {len(new_repos)}건, 토론 {len(new_stories)}건을 콘솔에 출력 완료 (텔레그램 미설정).")
    else:
        print("[error] 일부 메시지 전송 실패. 상태 파일을 갱신하지 않습니다 (다음 실행에서 재시도).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()