import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEEN_FILE = DATA_DIR / "seen_ids.json"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

LOOKBACK_HOURS = 48
MAX_RESULTS_PER_QUERY = 20
MAX_ALERTS = 15


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_watchlist():
    default = {
        "queries": [
            "OpenAI pricing",
            "OpenAI subscription",
            "ChatGPT subscription",
            "ChatGPT pricing",
            "Anthropic pricing",
            "Claude subscription",
            "xAI subscription",
            "Grok subscription",
            "Google AI pricing",
            "Gemini subscription",
            "Perplexity pricing",
            "Perplexity subscription",
            "Midjourney price",
            "GitHub Copilot pricing",
            "Cursor pricing",
        ]
    }
    data = load_json(WATCHLIST_FILE, default)
    return data.get("queries", default["queries"])


def search_hn(query, since_ts):
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": MAX_RESULTS_PER_QUERY,
    }
    try:
        resp = requests.get(HN_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("hits", [])
    except requests.RequestException as exc:
        print(f"[warn] HN search failed for '{query}': {exc}", file=sys.stderr)
        return []


def build_message(item):
    title = item.get("title") or "(제목 없음)"
    url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}"
    points = item.get("points", 0)
    comments = item.get("num_comments", 0)
    matched = item.get("_matched_query", "")
    return (
        f"💳 <b>AI 구독/가격 변경 신호</b>\n"
        f"{title}\n"
        f"🔗 {url}\n"
        f"👍 {points} | 💬 {comments} | 검색어: {matched}"
    )


def send_telegram(token, chat_id, text):
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload, timeout=15)
    if resp.status_code != 200:
        print(f"[error] Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)
        return False
    return True


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[error] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.", file=sys.stderr)
        sys.exit(1)

    seen = load_json(SEEN_FILE, [])
    seen_set = set(seen)

    since_ts = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    queries = load_watchlist()

    candidates = {}
    for q in queries:
        hits = search_hn(q, since_ts)
        for hit in hits:
            obj_id = hit.get("objectID")
            if not obj_id or obj_id in seen_set:
                continue
            if obj_id not in candidates:
                hit["_matched_query"] = q
                candidates[obj_id] = hit

    new_items = sorted(candidates.values(), key=lambda h: h.get("points", 0), reverse=True)[:MAX_ALERTS]

    if not new_items:
        print("[info] 새로운 AI 구독/가격 변경 신호 없음. 종료.")
        save_json(SEEN_FILE, list(seen_set)[-2000:])
        return

    sent_ids = []
    for item in new_items:
        message = build_message(item)
        ok = send_telegram(token, chat_id, message)
        if ok:
            sent_ids.append(item["objectID"])
        time.sleep(1)

    seen_set.update(sent_ids)
    save_json(SEEN_FILE, list(seen_set)[-2000:])
    print(f"[info] {len(sent_ids)}건 전송 완료.")


if __name__ == "__main__":
    main()