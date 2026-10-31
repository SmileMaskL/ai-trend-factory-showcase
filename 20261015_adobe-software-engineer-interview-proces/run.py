#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEEN_FILE = DATA_DIR / "seen_ids.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

HN_ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

LOOKBACK_HOURS = 48
MAX_RESULTS_PER_QUERY = 50


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
        "ai_keywords": [
            "ai", "chatgpt", "copilot", "llm", "gpt", "claude",
            "gemini", "cursor", "generative ai"
        ],
        "interview_keywords": [
            "interview", "onsite", "technical interview",
            "coding interview", "hiring process", "whiteboard", "screen"
        ],
        "queries": [
            "software engineer interview",
            "interview process AI",
            "technical interview AI rules",
            "coding interview AI policy",
            "interview prep"
        ]
    }
    return load_json(WATCHLIST_FILE, default)


def fetch_hn_candidates(query):
    since_ts = int(time.time()) - LOOKBACK_HOURS * 3600
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": MAX_RESULTS_PER_QUERY,
    }
    url = HN_ALGOLIA_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[WARN] HN query failed for '{query}': {e}", file=sys.stderr)
        return []
    return data.get("hits", [])


def text_of(hit):
    parts = [hit.get("title") or "", hit.get("story_text") or ""]
    return " ".join(parts).lower()


def matches_signal(hit, watchlist):
    text = text_of(hit)
    has_interview = any(kw in text for kw in watchlist["interview_keywords"])
    has_ai = any(kw in text for kw in watchlist["ai_keywords"])
    return has_interview and has_ai


def build_message(hit):
    title = hit.get("title") or "(제목 없음)"
    object_id = hit.get("objectID")
    points = hit.get("points", 0)
    comments = hit.get("num_comments", 0)
    hn_url = f"https://news.ycombinator.com/item?id={object_id}"
    story_url = hit.get("url") or hn_url
    lines = [
        "🧭 <b>AI 면접 정책 레이더</b>",
        f"<b>{title}</b>",
        f"points={points} comments={comments}",
        f"기사: {story_url}",
        f"HN: {hn_url}",
    ]
    return "\n".join(lines)


def send_telegram_message(token, chat_id, text):
    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)

    watchlist = load_watchlist()
    seen = load_json(SEEN_FILE, {"ids": []})
    seen_ids = set(seen.get("ids", []))

    candidates = {}
    for query in watchlist["queries"]:
        for hit in fetch_hn_candidates(query):
            object_id = hit.get("objectID")
            if object_id and object_id not in candidates:
                candidates[object_id] = hit

    new_hits = []
    for object_id, hit in candidates.items():
        if object_id in seen_ids:
            continue
        if matches_signal(hit, watchlist):
            new_hits.append(hit)

    if not new_hits:
        print("[INFO] 새로운 AI 면접 정책 신호 없음. 종료.")
        return

    new_hits.sort(key=lambda h: h.get("created_at_i", 0))

    sent_count = 0
    for hit in new_hits:
        message = build_message(hit)
        try:
            send_telegram_message(token, chat_id, message)
            sent_count += 1
            seen_ids.add(hit.get("objectID"))
        except requests.RequestException as e:
            print(f"[WARN] 텔레그램 전송 실패: {e}", file=sys.stderr)

    seen["ids"] = list(seen_ids)[-2000:]
    save_json(SEEN_FILE, seen)

    print(f"[INFO] 신규 신호 {sent_count}건 전송 완료.")


if __name__ == "__main__":
    main()