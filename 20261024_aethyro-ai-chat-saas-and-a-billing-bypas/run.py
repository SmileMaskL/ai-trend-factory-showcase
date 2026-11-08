import os
import re
import sys
import json
import html
import requests
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
SEEN_IDS_PATH = os.path.join(DATA_DIR, "seen_ids.json")

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


def load_watchlist():
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_seen_ids():
    if not os.path.exists(SEEN_IDS_PATH):
        return set()
    try:
        with open(SEEN_IDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen_ids(seen_ids):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


def contains_keyword(text, keyword):
    if not text:
        return False
    if re.match(r"^[A-Za-z0-9 ]+$", keyword):
        pattern = r"\b" + re.escape(keyword) + r"\b"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return keyword.lower() in text.lower()


def search_hn(query, hits_per_page, since_timestamp):
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": hits_per_page,
        "numericFilters": f"created_at_i>{since_timestamp}",
    }
    try:
        resp = requests.get(HN_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("hits", [])
    except requests.RequestException as e:
        print(f"[WARN] HN search failed for query='{query}': {e}", file=sys.stderr)
        return []


def find_matches(watchlist):
    billing_terms = watchlist.get("billing_terms", [])
    security_terms = watchlist.get("security_terms", [])
    lookback_days = watchlist.get("lookback_days", 3)
    hits_per_term = watchlist.get("hits_per_term", 20)

    since_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    since_ts = int(since_dt.timestamp())

    matches = {}

    for term in security_terms:
        hits = search_hn(term, hits_per_term, since_ts)
        for hit in hits:
            object_id = hit.get("objectID")
            title = hit.get("title") or ""
            if not object_id or not title:
                continue

            matched_billing_term = next(
                (b for b in billing_terms if contains_keyword(title, b)), None
            )
            if not matched_billing_term:
                continue

            if object_id in matches:
                continue

            matches[object_id] = {
                "id": object_id,
                "title": title,
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
                "hn_link": f"https://news.ycombinator.com/item?id={object_id}",
                "points": hit.get("points", 0) or 0,
                "num_comments": hit.get("num_comments", 0) or 0,
                "billing_term": matched_billing_term,
                "security_term": term,
            }

    return list(matches.values())


def build_message(new_matches, low_signal_threshold):
    lines = [
        "<b>🧨 SaaS 빌링 취약점 디스클로저 레이더</b>",
        f"신규 매칭 {len(new_matches)}건 (결제/구독 키워드 × 보안 디스클로저 키워드)",
        "",
    ]
    for m in sorted(new_matches, key=lambda x: x["points"]):
        title = html.escape(m["title"])
        early_tag = " 🐣 얼리시그널" if m["points"] <= low_signal_threshold else ""
        lines.append(f"• <b>{title}</b>{early_tag}")
        lines.append(f"  매칭: {html.escape(m['billing_term'])} + {html.escape(m['security_term'])}")
        lines.append(f"  points={m['points']} comments={m['num_comments']}")
        lines.append(f"  {m['url']}")
        lines.append(f"  (HN: {m['hn_link']})")
        lines.append("")
    return "\n".join(lines).strip()


def send_telegram_message(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, data=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[ERROR] 텔레그램 전송 실패: {e}", file=sys.stderr)
        return False


def main():
    watchlist = load_watchlist()
    seen_ids = load_seen_ids()
    low_signal_threshold = watchlist.get("low_signal_threshold", 5)

    all_matches = find_matches(watchlist)
    new_matches = [m for m in all_matches if m["id"] not in seen_ids]

    if not new_matches:
        print(f"[{datetime.now().isoformat()}] 신규 매칭 없음. 종료합니다.")
        return

    message = build_message(new_matches, low_signal_threshold)
    sent = send_telegram_message(message)

    if sent:
        seen_ids.update(m["id"] for m in new_matches)
        save_seen_ids(seen_ids)
        print(f"[{datetime.now().isoformat()}] 신규 매칭 {len(new_matches)}건 전송 완료.")
    else:
        print(f"[{datetime.now().isoformat()}] 전송 실패로 seen_ids 갱신하지 않음.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()