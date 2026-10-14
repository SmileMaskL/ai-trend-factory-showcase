#!/usr/bin/env python3
"""
MCP & AI Agent OSS Radar
GitHub에서 최근 며칠간 활발히 업데이트된 MCP 서버 / AI 에이전트 스킬 / RAG 프레임워크
관련 오픈소스 저장소를 검색해서, 이전에 알림을 보낸 적 없는 것만 골라
텔레그램으로 보내는 1회성(하루 1번 실행 후 종료) 스크립트.

텔레그램 환경변수(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)는 실제 운영 파이프라인에서는
항상 설정되어 있지만, 어떤 실행 환경(예: 격리된 테스트/검증 실행)에서는 전달되지 않을 수
있다. 이 스크립트는 그런 경우에도 실패하지 않고, 텔레그램 전송 대신 콘솔(stdout)에
리포트를 출력하는 방식으로 항상 정상 종료하도록 설계되어 있다.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "data" / "seen_repos.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

GITHUB_API = "https://api.github.com/search/repositories"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

DEFAULT_QUERIES = [
    "mcp server model context protocol",
    "ai agent skills framework",
    "rag pipeline framework",
    "agentic rag toolkit",
    "llm agent orchestration",
]

MAX_RESULTS_PER_QUERY = 8
LOOKBACK_DAYS = 3
MAX_REPOS_IN_MESSAGE = 12


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
    data = load_json(WATCHLIST_FILE, {"queries": DEFAULT_QUERIES})
    return data.get("queries", DEFAULT_QUERIES)


def github_search(query, since_date, session):
    q = f"{query} pushed:>={since_date}"
    params = {
        "q": q,
        "sort": "stars",
        "order": "desc",
        "per_page": MAX_RESULTS_PER_QUERY,
    }
    headers = {"Accept": "application/vnd.github+json"}
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
        results.append({
            "full_name": item.get("full_name"),
            "html_url": item.get("html_url"),
            "description": (item.get("description") or "").strip(),
            "stargazers_count": item.get("stargazers_count", 0),
            "pushed_at": item.get("pushed_at"),
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
    return text.replace("<b>", "").replace("</b>", "").replace("<a href=\"", "").replace("\">", " ").replace("</a>", "")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    telegram_configured = bool(token and chat_id)
    if not telegram_configured:
        # 실제 운영 파이프라인에는 항상 설정되어 있는 값이지만, 이 값이 없다고 해서
        # 전체 실행을 실패로 만들면 안 된다. 콘솔 출력으로 대체하고 계속 진행한다.
        print(
            "[warn] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 없어 "
            "텔레그램 전송 대신 콘솔 출력으로 대체합니다.",
            file=sys.stderr,
        )

    queries = load_watchlist()
    seen = load_json(STATE_FILE, {})

    since_date = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    session = requests.Session()
    new_repos = []
    seen_in_this_run = set()

    for query in queries:
        results = github_search(query, since_date, session)
        time.sleep(2)  # GitHub 무인증 검색 API rate limit(10/min) 보호
        for repo in results:
            name = repo["full_name"]
            if not name or name in seen or name in seen_in_this_run:
                continue
            seen_in_this_run.add(name)
            new_repos.append(repo)

    new_repos.sort(key=lambda r: r["stargazers_count"], reverse=True)
    new_repos = new_repos[:MAX_REPOS_IN_MESSAGE]

    if not new_repos:
        print("[info] 새로운 MCP/에이전트/RAG OSS 저장소가 없습니다. 알림을 보내지 않습니다.")
        for name in seen_in_this_run:
            seen[name] = datetime.now(timezone.utc).isoformat()
        save_json(STATE_FILE, seen)
        return

    header = (
        f"🧭 <b>MCP & AI Agent OSS 레이더</b> "
        f"({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n"
        f"신규/급상승 저장소 {len(new_repos)}건\n"
    )
    lines = [header]
    for repo in new_repos:
        desc = repo["description"][:120] if repo["description"] else "(설명 없음)"
        line = (
            f"⭐ {repo['stargazers_count']} · "
            f"<a href=\"{repo['html_url']}\">{repo['full_name']}</a>\n{desc}"
        )
        lines.append(line)

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
            seen[repo["full_name"]] = datetime.now(timezone.utc).isoformat()
        for name in seen_in_this_run:
            seen.setdefault(name, datetime.now(timezone.utc).isoformat())
        save_json(STATE_FILE, seen)
        if telegram_configured:
            print(f"[info] {len(new_repos)}개 저장소를 텔레그램으로 전송 완료.")
        else:
            print(f"[info] {len(new_repos)}개 저장소를 콘솔에 출력 완료 (텔레그램 미설정).")
    else:
        print("[error] 일부 메시지 전송 실패. 상태 파일을 갱신하지 않습니다 (다음 실행에서 재시도).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()