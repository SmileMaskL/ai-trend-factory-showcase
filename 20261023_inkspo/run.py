#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 크리에이티브 툴 얼리시그널 레이더
Hacker News(Algolia API, 무료/무키)에서 "AI + 디자인/아트/크리에이티브" 키워드가
겹치면서 아직 포인트가 낮은(=아직 뜨지 않은) 신규 론칭 신호를 매일 1회 포착해
텔레그램으로 알려주는 무인 큐레이션 레이더.

- 외부 의존성: requests (이미 설치됨) + 표준 라이브러리만 사용
- 1회 실행 후 종료 (데몬/서버 아님)
- 자격증명: 기존 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수만 사용
"""

import json
import os
import re
import sys
import time
from html import escape
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
DATA_DIR = BASE_DIR / "data"
SEEN_PATH = DATA_DIR / "seen_ids.json"

HN_ALGOLIA_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
TELEGRAM_API_BASE = "https://api.telegram.org"

REQUEST_TIMEOUT = 15


def load_watchlist() -> dict:
    default = {
        "search_queries": ["AI"],
        "creative_keywords": [
            "design", "designer", "art", "illustration", "illustrator",
            "draw", "drawing", "sketch", "generative art", "creative",
            "logo", "poster", "graphic", "tattoo", "ink", "doodle",
            "paint", "painting", "canvas", "visual", "aesthetic",
            "image generator", "comic", "animation"
        ],
        "lookback_hours": 48,
        "max_points_for_early_signal": 20,
        "max_items_per_run": 5
    }
    if WATCHLIST_PATH.exists():
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            default.update(data)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def load_seen_ids() -> set:
    if SEEN_PATH.exists():
        try:
            with open(SEEN_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen_ids(seen: set) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = list(seen)[-2000:]
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


AI_WORD_RE = re.compile(r"\bai\b", re.IGNORECASE)


def looks_ai_related(title: str) -> bool:
    lowered = title.lower()
    if AI_WORD_RE.search(title):
        return True
    for kw in ("gpt", "llm", "chatgpt", "artificial intelligence", "machine learning"):
        if kw in lowered:
            return True
    return False


def matches_creative_keyword(title: str, keywords: list) -> str:
    lowered = title.lower()
    for kw in keywords:
        if kw.lower() in lowered:
            return kw
    return ""


def fetch_candidates(watchlist: dict) -> list:
    lookback_hours = watchlist.get("lookback_hours", 48)
    since_ts = int(time.time()) - lookback_hours * 3600
    queries = watchlist.get("search_queries", ["AI"])

    collected = {}
    for query in queries:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since_ts}",
            "hitsPerPage": 200,
        }
        try:
            resp = requests.get(HN_ALGOLIA_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except (requests.RequestException, ValueError) as e:
            print(f"[WARN] HN Algolia 조회 실패 (query={query}): {e}")
            continue

        for hit in hits:
            object_id = hit.get("objectID")
            if not object_id:
                continue
            collected[object_id] = hit

    return list(collected.values())


def build_message(items: list) -> str:
    lines = ["<b>🎨 AI 크리에이티브 툴 얼리시그널 레이더</b>", ""]
    for item in items:
        title = escape(item.get("title") or "(제목 없음)")
        points = item.get("points", 0)
        comments = item.get("num_comments", 0)
        story_url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}"
        hn_link = f"https://news.ycombinator.com/item?id={item.get('objectID')}"
        keyword = escape(item.get("_matched_keyword", ""))

        lines.append(f"• <b>{title}</b>")
        lines.append(f"  매칭 키워드: {keyword} | 포인트 {points} | 댓글 {comments}")
        lines.append(f"  <a href=\"{story_url}\">원문</a> | <a href=\"{hn_link}\">HN 토론</a>")
        lines.append("")

    lines.append("👉 아직 포인트가 낮은 초기 단계 신호입니다. 선점 큐레이션/소개 콘텐츠 기회로 활용하세요.")
    return "\n".join(lines)


def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[ERROR] 텔레그램 전송 실패: {e}")
        return False


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 설정되어 있지 않습니다.")
        return 1

    watchlist = load_watchlist()
    seen_ids = load_seen_ids()

    candidates = fetch_candidates(watchlist)
    print(f"[INFO] HN에서 조회된 후보: {len(candidates)}건")

    creative_keywords = watchlist.get("creative_keywords", [])
    max_points = watchlist.get("max_points_for_early_signal", 20)
    max_items = watchlist.get("max_items_per_run", 5)

    new_matches = []
    for hit in candidates:
        object_id = hit.get("objectID")
        title = hit.get("title") or ""
        points = hit.get("points") or 0

        if not object_id or object_id in seen_ids:
            continue
        if points > max_points:
            continue
        if not looks_ai_related(title):
            continue

        matched_kw = matches_creative_keyword(title, creative_keywords)
        if not matched_kw:
            continue

        hit["_matched_keyword"] = matched_kw
        new_matches.append(hit)

    new_matches.sort(key=lambda h: h.get("created_at_i", 0), reverse=True)
    new_matches = new_matches[:max_items]

    if not new_matches:
        print("[INFO] 신규 매칭 신호가 없습니다. 조용히 종료합니다.")
        return 0

    message = build_message(new_matches)
    sent = send_telegram_message(token, chat_id, message)

    if sent:
        for hit in new_matches:
            seen_ids.add(hit["objectID"])
        save_seen_ids(seen_ids)
        print(f"[INFO] {len(new_matches)}건 전송 완료.")
        return 0
    else:
        print("[ERROR] 전송 실패로 seen_ids를 갱신하지 않습니다 (다음 실행에서 재시도).")
        return 1


if __name__ == "__main__":
    sys.exit(main())