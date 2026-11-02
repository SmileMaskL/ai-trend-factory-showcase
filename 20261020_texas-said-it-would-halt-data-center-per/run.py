#!/usr/bin/env python3
"""
Data Center Permit Policy-Gap Radar
하루 1회 실행: HN + Google News에서 "데이터센터 허가/모라토리엄/그리드" 관련
신규 신호를 모아 텔레그램으로 다이제스트 알림을 보내고 종료합니다.
무한 루프/서버 없음 - 1회성 실행 스크립트입니다.
"""
import os
import sys
import json
import time
import hashlib
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
SEEN_PATH = os.path.join(BASE_DIR, "data", "seen_ids.json")
MAX_SEEN = 3000
LOOKBACK_HOURS = 48
HTTP_TIMEOUT = 15


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_key(url, title):
    raw = (url or "") + "|" + (title or "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def matches_watchlist(text, watchlist):
    if not text:
        return False
    low = text.lower()
    has_topic = any(k.lower() in low for k in watchlist.get("topic_keywords", []))
    has_action = any(k.lower() in low for k in watchlist.get("action_keywords", []))
    return has_topic and has_action


def fetch_hn_items(watchlist):
    items = []
    since_ts = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    queries = ["data center permit", "data center moratorium", "data center grid"]
    for q in queries:
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": q,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{since_ts}",
                },
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            for h in hits:
                title = h.get("title") or ""
                url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
                if matches_watchlist(title, watchlist):
                    items.append({
                        "source": "HackerNews",
                        "title": title,
                        "url": url,
                        "extra": f"points={h.get('points', 0)} comments={h.get('num_comments', 0)}",
                    })
        except requests.RequestException as e:
            print(f"[WARN] HN fetch failed for query '{q}': {e}", file=sys.stderr)
    return items


def fetch_google_news_items(watchlist):
    items = []
    queries = [
        '"data center" (permit OR moratorium OR halt OR grid OR zoning)',
        '"data center" ("push ahead" OR "pushing ahead" OR override OR waiver)',
    ]
    for q in queries:
        try:
            encoded = urllib.parse.quote(q)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(
                url,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            for item in root.findall("./channel/item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                if matches_watchlist(title, watchlist):
                    items.append({
                        "source": "GoogleNews",
                        "title": title,
                        "url": link,
                        "extra": pub_date,
                    })
        except (requests.RequestException, ET.ParseError) as e:
            print(f"[WARN] Google News fetch failed for query '{q}': {e}", file=sys.stderr)
    return items


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    remaining = text
    chunks = []
    while remaining:
        chunks.append(remaining[:4000])
        remaining = remaining[4000:]
    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERROR] Telegram send failed: {e}", file=sys.stderr)
        time.sleep(0.5)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.", file=sys.stderr)
        sys.exit(1)

    watchlist = load_json(WATCHLIST_PATH, {"topic_keywords": [], "action_keywords": []})
    seen_data = load_json(SEEN_PATH, {"seen": []})
    seen_list = list(seen_data.get("seen", []))
    seen_set = set(seen_list)

    all_items = fetch_hn_items(watchlist) + fetch_google_news_items(watchlist)

    new_items = []
    for it in all_items:
        key = make_key(it["url"], it["title"])
        if key not in seen_set:
            seen_set.add(key)
            seen_list.append(key)
            new_items.append(it)

    if new_items:
        lines = [
            "\U0001F3D7\uFE0F 데이터센터 허가/그리드 정책-실행 괴리 레이더",
            f"신규 신호 {len(new_items)}건",
            "",
        ]
        for it in new_items[:15]:
            lines.append(f"[{it['source']}] {it['title']}")
            lines.append(it["url"])
            if it.get("extra"):
                lines.append(f"  ({it['extra']})")
            lines.append("")
        message = "\n".join(lines).strip()
        send_telegram(token, chat_id, message)
        print(f"[INFO] {len(new_items)}건 신규 신호 전송 완료.")
    else:
        print("[INFO] 신규 신호 없음. 알림 생략.")

    if len(seen_list) > MAX_SEEN:
        seen_list = seen_list[-MAX_SEEN:]
    save_json(SEEN_PATH, {"seen": seen_list})


if __name__ == "__main__":
    main()