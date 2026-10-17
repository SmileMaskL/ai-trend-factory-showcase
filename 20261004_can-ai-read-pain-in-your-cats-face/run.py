#!/usr/bin/env python3
"""
Animal Pain-AI Radar
---------------------
"Can AI read pain in your cat's face?" 트렌드에서 출발한 무인 레이더.

이 프로젝트는 "오늘의 기사 하나"를 요약하는 게 아니라, 그 기사가 속한 더 큰 흐름 —
"컴퓨터 비전으로 반려동물/가축의 표정에서 통증·고통을 읽어내는 AI"(Feline Grimace
Scale류 연구, 수의학 AI, 동물 복지 AI) — 이 실제로 연구·커뮤니티에서 얼마나
새로 등장하고 있는지를 매일 한 번 교차 관찰합니다.

소스 (모두 무료, 인증 불필요):
  1) arXiv Atom API — "animal pain / grimace scale / facial action unit" +
     "animal/veterinary/cat/dog/livestock" 조합의 신규 논문
  2) Hacker News Algolia API — "pet/animal/veterinary" + "AI" 조합의 신규 토론

새 항목이 있을 때만 텔레그램으로 알리고, 없으면 조용히 종료합니다.
텔레그램 자격증명이 없으면 data/latest_digest.txt에 기록하는 것으로 대체합니다
(= 사람 개입 없이도 항상 "성공"으로 끝나는 무인 실행).

- 비용 $0 (공개 API만 사용)
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> 수집 -> 필터 -> 중복제거 -> 알림(또는 파일 기록) -> 종료
"""

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import escape as h

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
SEEN_PATH = os.path.join(DATA_DIR, "seen_items.json")
DIGEST_FALLBACK_PATH = os.path.join(DATA_DIR, "latest_digest.txt")

ARXIV_API = "http://export.arxiv.org/api/query"
HN_API = "https://hn.algolia.com/api/v1/search_by_date"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

LOOKBACK_DAYS = 5
MAX_ITEMS_IN_DIGEST = 8
SEEN_RETENTION_DAYS = 60
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "animal-pain-ai-radar/1.0 (personal research digest bot)"}

ARXIV_QUERY = (
    '(abs:"grimace scale" OR abs:"animal pain" OR abs:"pain face" OR '
    'abs:"facial action unit" OR abs:"pain assessment") AND '
    '(abs:"animal" OR abs:"veterinary" OR abs:"livestock" OR abs:"cat" OR '
    'abs:"dog" OR abs:"pet")'
)

HN_QUERY = "pet animal veterinary AI pain welfare"

ANIMAL_TERMS = [
    "pet", "cat", "cats", "dog", "dogs", "animal", "veterinary", "vet ",
    "livestock", "farm animal", "horse", "equine",
]
AI_TERMS = [
    "ai", "machine learning", "computer vision", "deep learning",
    "neural network", "model", "algorithm",
]
WELFARE_TERMS = [
    "pain", "grimace", "welfare", "emotion", "stress", "suffering",
    "health", "diagnos",
]


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return {}
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen(seen):
    os.makedirs(DATA_DIR, exist_ok=True)
    cutoff = time.time() - SEEN_RETENTION_DAYS * 86400
    pruned = {k: v for k, v in seen.items() if v.get("ts", 0) >= cutoff}
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def fetch_arxiv():
    params = {
        "search_query": ARXIV_QUERY,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": 25,
    }
    try:
        resp = requests.get(ARXIV_API, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        log(f"arXiv fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        log(f"arXiv parse failed: {e}")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    items = []

    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        id_el = entry.find("atom:id", ns)
        published_el = entry.find("atom:published", ns)
        if title_el is None or id_el is None or published_el is None:
            continue

        try:
            published = datetime.strptime(published_el.text.strip(), "%Y-%m-%dT%H:%M:%SZ")
            published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if published < cutoff:
            continue

        raw_id = id_el.text.strip()
        short_id = raw_id.split("/abs/")[-1]
        short_id = re.sub(r"v\d+$", "", short_id)
        title = " ".join(title_el.text.split())

        items.append({
            "uid": f"arxiv:{short_id}",
            "source": "arXiv",
            "title": title,
            "url": raw_id,
            "date": published,
        })

    return items


def is_relevant_hn_title(title_lower):
    has_animal = any(term in title_lower for term in ANIMAL_TERMS)
    has_ai = any(term in title_lower for term in AI_TERMS)
    has_welfare = any(term in title_lower for term in WELFARE_TERMS)
    return has_animal and (has_ai or has_welfare)


def fetch_hn():
    since = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp())
    params = {
        "query": HN_QUERY,
        "tags": "story",
        "numericFilters": f"created_at_i>{since}",
        "hitsPerPage": 50,
    }
    try:
        resp = requests.get(HN_API, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        log(f"HN fetch failed: {e}")
        return []

    try:
        data = resp.json()
    except ValueError as e:
        log(f"HN parse failed: {e}")
        return []

    items = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        title_lower = title.lower()
        if not is_relevant_hn_title(title_lower):
            continue

        object_id = hit.get("objectID")
        if not object_id:
            continue

        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        try:
            date = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
        except (KeyError, TypeError, ValueError):
            date = datetime.now(timezone.utc)

        items.append({
            "uid": f"hn:{object_id}",
            "source": "HN",
            "title": title,
            "url": url,
            "date": date,
            "points": hit.get("points", 0),
        })

    return items


def build_message(new_items):
    lines = [f"<b>🐾 동물 통증 AI 레이더</b> — {len(new_items)}건의 새 신호\n"]
    for idx, item in enumerate(new_items, 1):
        date_str = item["date"].strftime("%Y-%m-%d")
        extra = f" · {item['points']}pt" if item.get("points") else ""
        lines.append(
            f"{idx}. [{item['source']}]{extra} {date_str}\n"
            f"<a href=\"{h(item['url'])}\">{h(item['title'])}</a>\n"
        )
    lines.append(
        "— '고양이/동물 표정에서 통증을 읽는 AI' 흐름과 관련된 신규 논문·토론만 골라 보냅니다."
    )
    return "\n".join(lines)


def send_telegram(text, token, chat_id):
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def write_digest_fallback(message):
    """텔레그램 자격증명이 없거나 전송이 실패해도, 수집 결과를 로컬 파일에
    남겨서 무인 실행이 실패로 끝나지 않도록 한다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    plain_text = re.sub(r"<[^>]+>", "", message)
    with open(DIGEST_FALLBACK_PATH, "w", encoding="utf-8") as f:
        f.write(plain_text)
    log(f"Digest written to {DIGEST_FALLBACK_PATH} instead of Telegram.")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    telegram_configured = bool(token and chat_id)

    if not telegram_configured:
        log(
            "WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not present in this run's "
            "environment. Continuing without Telegram; the digest will be saved to "
            f"{DIGEST_FALLBACK_PATH} instead."
        )

    seen = load_seen()

    log("Fetching arXiv...")
    arxiv_items = fetch_arxiv()
    log(f"  -> {len(arxiv_items)} candidate(s) within lookback window")

    log("Fetching Hacker News...")
    hn_items = fetch_hn()
    log(f"  -> {len(hn_items)} candidate(s) within lookback window")

    all_items = arxiv_items + hn_items

    fresh_new_items = [it for it in all_items if it["uid"] not in seen]

    for item in fresh_new_items:
        seen[item["uid"]] = {"ts": time.time(), "title": item["title"]}

    fresh_new_items.sort(key=lambda x: x["date"], reverse=True)
    fresh_new_items = fresh_new_items[:MAX_ITEMS_IN_DIGEST]

    if not fresh_new_items:
        log("No new items today. Skipping digest.")
        save_seen(seen)
        return

    message = build_message(fresh_new_items)

    if telegram_configured:
        try:
            send_telegram(message, token, chat_id)
            log(f"Sent digest with {len(fresh_new_items)} item(s) via Telegram.")
        except requests.RequestException as e:
            log(f"WARNING: Telegram send failed ({e}); falling back to local file.")
            write_digest_fallback(message)
    else:
        write_digest_fallback(message)

    save_seen(seen)


if __name__ == "__main__":
    main()