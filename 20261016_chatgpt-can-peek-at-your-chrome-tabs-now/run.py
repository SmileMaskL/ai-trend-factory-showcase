#!/usr/bin/env python3
"""
AI 브라우저 에이전트 프라이버시 워치
-----------------------------------
ChatGPT Atlas, Copilot, Comet 등 "브라우저 탭/기록을 들여다보는 AI 에이전트" 기능이
퍼지는 흐름을, (1) 공식 브라우저 릴리스노트 RSS + (2) HackerNews 토론글에서
교차 감지해 새로운 신호가 있을 때만 텔레그램으로 알려주는 1회성 무인 스크립트.

- 비용 $0 (전부 인증 불필요한 공개 API/RSS)
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> 수집 -> 키워드 교차 필터 -> 중복제거 -> 알림 -> 종료
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
SEEN_PATH = os.path.join(DATA_DIR, "seen_ids.json")
WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist.json")

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
HTTP_TIMEOUT = 20
MAX_SEEN = 1500
MAX_ALERTS_PER_RUN = 20
HN_LOOKBACK_HOURS = 72


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"{os.path.basename(path)} 로드 실패, 기본값 사용: {e}")
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_watchlist():
    default = {
        "hn_queries": [
            "ChatGPT Atlas",
            "browser agent privacy",
            "AI browser extension permission",
            "agentic browser",
            "Comet browser AI",
            "Copilot browser tabs",
            "browser agent reads tabs",
            "AI reads browsing history",
        ],
        "rss_feeds": [
            {"name": "Chrome Releases", "url": "https://chromereleases.googleblog.com/feeds/posts/default"},
            {"name": "Chromium Blog", "url": "https://blog.chromium.org/feeds/posts/default"},
            {"name": "Microsoft Edge Dev Blog", "url": "https://blogs.windows.com/msedgedev/feed/"},
        ],
        "privacy_keywords": [
            "tab", "tabs", "browsing history", "clipboard", "screenshot",
            "screen read", "password", "autofill", "cookie", "permission",
            "read your", "access your", "personal data", "private data",
            "browser history",
        ],
        "ai_keywords": [
            "ai", "gpt", "chatgpt", "copilot", "gemini", "assistant",
            "agent", "atlas", "comet", "genai", "llm",
        ],
    }
    data = load_json(WATCHLIST_PATH, default)
    for key, val in default.items():
        data.setdefault(key, val)
    return data


def load_seen():
    data = load_json(SEEN_PATH, {"ids": []})
    return set(data.get("ids", []))


def save_seen(seen_set):
    ids = list(seen_set)
    if len(ids) > MAX_SEEN:
        ids = ids[-MAX_SEEN:]
    save_json(SEEN_PATH, {"ids": ids, "updated_at": datetime.now(timezone.utc).isoformat()})


def contains_any(text, terms):
    t = text.lower()
    return any(term in t for term in terms)


def fetch_hn_candidates(queries, privacy_keywords, since_dt):
    since_ts = int(since_dt.timestamp())
    results = []
    for query in queries:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since_ts}",
            "hitsPerPage": 30,
        }
        try:
            r = requests.get(HN_ALGOLIA_URL, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            hits = r.json().get("hits", [])
        except Exception as e:
            log(f"HN Algolia 요청 실패 (query={query}): {e}")
            continue

        for hit in hits:
            title = hit.get("title") or ""
            if not title:
                continue
            full_text = title + " " + (hit.get("story_text") or "")
            if not contains_any(full_text, privacy_keywords):
                continue

            story_id = hit.get("objectID")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            results.append({
                "id": f"hn:{story_id}",
                "source": "HackerNews",
                "title": title,
                "url": url,
                "points": hit.get("points", 0),
                "matched_query": query,
            })
    return results


def parse_feed(xml_bytes):
    def local(tag):
        return tag.split("}")[-1]

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        raise RuntimeError(f"XML 파싱 실패: {e}")

    entries = []
    for el in root.iter():
        if local(el.tag) in ("entry", "item"):
            entries.append(el)

    results = []
    for el in entries:
        title, link, guid, summary = "", "", "", ""
        for child in list(el):
            ctag = local(child.tag)
            if ctag == "title":
                title = (child.text or "").strip()
            elif ctag == "link":
                href = child.get("href")
                if href:
                    link = href
                elif child.text:
                    link = child.text.strip()
            elif ctag in ("summary", "description", "content"):
                summary = (child.text or "") + "".join(
                    (sub.text or "") for sub in child.iter() if sub is not child
                )
            elif ctag in ("id", "guid"):
                guid = (child.text or "").strip()
        results.append({
            "title": title,
            "link": link,
            "id": guid or link or title,
            "summary": summary,
        })
    return results


def fetch_rss_candidates(feeds, privacy_keywords, ai_keywords):
    results = []
    for feed in feeds:
        name = feed.get("name", feed.get("url", "RSS"))
        url = feed.get("url")
        if not url:
            continue
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0 (privacy-watch-bot)"})
            r.raise_for_status()
            entries = parse_feed(r.content)
        except Exception as e:
            log(f"RSS 요청/파싱 실패 ({name}): {e}")
            continue

        for entry in entries:
            text = f"{entry['title']} {entry['summary']}"
            if not contains_any(text, privacy_keywords):
                continue
            if not contains_any(text, ai_keywords):
                continue

            raw_id = entry["id"] or entry["link"] or entry["title"]
            short_hash = hashlib.md5(raw_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
            results.append({
                "id": f"rss:{name}:{short_hash}",
                "source": name,
                "title": entry["title"] or "(제목 없음)",
                "url": entry["link"] or url,
                "points": None,
                "matched_query": None,
            })
    return results


def chunk_message(lines, limit=3500):
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > limit and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"텔레그램 전송 실패 status={r.status_code} body={r.text[:300]}")


def escape_html(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_message_lines(items):
    lines = ["🕵️ <b>AI 브라우저 에이전트 프라이버시 워치</b>", "(탭/기록/클립보드를 읽는 AI 브라우저 기능 신규 신호)", ""]
    by_source = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    for source, its in by_source.items():
        lines.append(f"<b>[{escape_html(source)}]</b>")
        for item in its:
            title = escape_html(item["title"])
            extra = ""
            if item.get("points") is not None:
                extra = f" (👍{item['points']})"
            lines.append(f"• <a href=\"{item['url']}\">{title}</a>{extra}")
        lines.append("")
    return lines


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 설정되어 있지 않습니다.")
        sys.exit(1)

    watchlist = load_watchlist()
    now = datetime.now(timezone.utc)
    since_dt = now - timedelta(hours=HN_LOOKBACK_HOURS)

    log("HackerNews 수집 중...")
    hn_items = fetch_hn_candidates(
        watchlist["hn_queries"], watchlist["privacy_keywords"], since_dt
    )
    log(f"HackerNews 후보: {len(hn_items)}건")

    log("공식 브라우저 릴리스노트 RSS 수집 중...")
    rss_items = fetch_rss_candidates(
        watchlist["rss_feeds"], watchlist["privacy_keywords"], watchlist["ai_keywords"]
    )
    log(f"RSS 후보: {len(rss_items)}건")

    all_items = hn_items + rss_items

    seen = load_seen()
    new_items = [item for item in all_items if item["id"] not in seen]
    new_items.sort(key=lambda it: (it.get("points") or 0), reverse=True)
    new_items = new_items[:MAX_ALERTS_PER_RUN]
    log(f"신규 항목: {len(new_items)}건 (전체 {len(all_items)}건 중)")

    if not new_items:
        log("새로운 AI 브라우저 프라이버시 신호 없음. 알림 전송 안 함.")
        for item in all_items:
            seen.add(item["id"])
        save_seen(seen)
        return

    lines = build_message_lines(new_items)
    messages = chunk_message(lines)

    try:
        for msg in messages:
            send_telegram(token, chat_id, msg)
        log(f"텔레그램 전송 완료 ({len(messages)}개 메시지).")
    except Exception as e:
        log(f"텔레그램 전송 중 오류 발생: {e}")
        sys.exit(1)

    for item in all_items:
        seen.add(item["id"])
    save_seen(seen)
    log("완료.")


if __name__ == "__main__":
    main()