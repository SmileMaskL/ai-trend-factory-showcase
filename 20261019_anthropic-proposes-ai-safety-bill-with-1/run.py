#!/usr/bin/env python3
"""
AI 안전법안 구체성 레이더 (AI Safety Bill Concreteness Radar)
--------------------------------------------------------------
오늘의 트렌드: "Anthropic proposes AI safety bill with $1B / 50-death
threshold"(HN). 이 기사의 핵심은 "AI 규제 논의가 추상적 구호("위험하다",
"규제가 필요하다")에서 벗어나, 달러 금액·사망자 수 같은 구체적인 숫자
임계값으로 바뀌고 있다"는 점입니다.

이 프로젝트는 그 포인트를 그대로 측정 가능한 신호로 바꿉니다: Hacker News에서
AI 규제/안전법/책임 관련 키워드로 올라오는 글 + 댓글을 모아, 그 안에 "달러
금액", "사망/사상자 수", "퍼센트" 같은 서로 다른 유형의 구체적 숫자가 몇
종류나 동시에 등장하는지 스코어링합니다. 2종류 이상의 구체적 숫자가 함께
나오면("구체성 임계값 통과") "이 논의는 더 이상 말로만 하는 수준이 아니라
실제 입법/정책 디테일 단계로 넘어갔다"는 신호로 보고 텔레그램으로 알립니다.

- 데이터 소스: Hacker News Algolia Search API (https://hn.algolia.com/api) -
  인증 불필요, 무료, rate limit 넉넉함.
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> 키워드별 최근 글 수집 -> 댓글 텍스트까지 합쳐서
  숫자 패턴 분석 -> 구체성 임계값을 넘는 글만 텔레그램 알림 -> 종료
  (서버/데몬 아님)
"""

import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEEN_FILE = DATA_DIR / "seen_ids.json"
CONFIG_FILE = BASE_DIR / "watchlist.json"

HN_SEARCH_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"
HN_SEARCH = "https://hn.algolia.com/api/v1/search"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

HTTP_TIMEOUT = 15
USER_AGENT = "ai-trend-factory-ai-safety-bill-radar/1.0 (daily batch script; no auth)"
REQUEST_DELAY_SEC = 0.3
MAX_SEEN = 3000

MONEY_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:billion|million|trillion|bn|[bmt])\b",
    re.IGNORECASE,
)
DEATH_RE = re.compile(
    r"\b\d[\d,]*\s?-?\s?"
    r"(?:deaths?|killed|casualt(?:y|ies)|fatalit(?:y|ies)|people\s+(?:die|died|dying))\b",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
THRESHOLD_WORD_RE = re.compile(
    r"\b(threshold|liability cap|penalty|fine of|cap of|trigger|per\s+incident)\b",
    re.IGNORECASE,
)

TAG_RE = re.compile(r"<[^>]+>")


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"{path.name} 로드 실패, 기본값 사용: {e}")
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config():
    default = {
        "keywords": [
            "AI safety bill",
            "AI regulation",
            "AI liability",
            "AI safety act",
            "artificial intelligence bill",
            "AI moratorium",
            "AI safety legislation",
            "AI law",
        ],
        "lookback_hours": 72,
        "min_points": 1,
        "max_comments_per_story": 25,
        "max_stories_per_keyword": 10,
        "min_numeric_categories": 2,
    }
    cfg = load_json(CONFIG_FILE, default)
    for k, v in default.items():
        cfg.setdefault(k, v)
    return cfg


def strip_html(text):
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    return html_lib.unescape(text)


def hn_search_stories(keyword, since_ts, max_stories):
    params = {
        "query": keyword,
        "tags": "story",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": max_stories,
    }
    try:
        resp = requests.get(
            HN_SEARCH_BY_DATE,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log(f"[warn] HN 검색 실패 (keyword={keyword!r}): {e}")
        return []
    try:
        hits = resp.json().get("hits", [])
    except ValueError:
        return []
    return hits


def hn_fetch_comments_text(story_id, max_comments):
    params = {
        "tags": f"comment,story_{story_id}",
        "hitsPerPage": max_comments,
    }
    try:
        resp = requests.get(
            HN_SEARCH,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log(f"[warn] HN 댓글 조회 실패 (id={story_id}): {e}")
        return ""
    try:
        hits = resp.json().get("hits", [])
    except ValueError:
        return ""
    texts = [strip_html(h.get("comment_text") or "") for h in hits]
    return "\n".join(t for t in texts if t)


def analyze_text(text):
    money_matches = sorted(set(m.group(0).strip() for m in MONEY_RE.finditer(text)))
    death_matches = sorted(set(m.group(0).strip() for m in DEATH_RE.finditer(text)))
    percent_matches = sorted(set(m.group(0).strip() for m in PERCENT_RE.finditer(text)))
    threshold_words = sorted(set(m.group(0).strip() for m in THRESHOLD_WORD_RE.finditer(text)))

    numeric_categories = sum(
        1 for group in (money_matches, death_matches, percent_matches) if group
    )

    return {
        "money": money_matches,
        "death": death_matches,
        "percent": percent_matches,
        "threshold_words": threshold_words,
        "numeric_categories": numeric_categories,
    }


def send_telegram(token, chat_id, text):
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, data=payload, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        log(f"[error] Telegram 요청 예외: {e}")
        return False
    if resp.status_code != 200:
        log(f"[error] Telegram send failed: {resp.status_code} {resp.text}")
        return False
    return True


def build_message(qualifying):
    lines = [
        "⚖️ <b>AI 안전법안 구체성 레이더</b>",
        "오늘의 트렌드: <i>Anthropic AI safety bill ($1B / 50-death threshold)</i> (HN)",
        f"구체적 숫자 임계값(2종 이상)을 통과한 글 {len(qualifying)}건:",
        "",
    ]
    for item in qualifying:
        title = html_lib.escape(item["title"])
        url = item["url"]
        lines.append(f"• <a href=\"{url}\">{title}</a>")
        if item["money"]:
            lines.append(f"  💰 금액: {', '.join(item['money'][:4])}")
        if item["death"]:
            lines.append(f"  ⚠️ 사상자 수치: {', '.join(item['death'][:4])}")
        if item["percent"]:
            lines.append(f"  📊 비율: {', '.join(item['percent'][:4])}")
        if item["threshold_words"]:
            lines.append(f"  🔖 임계값 관련 표현: {', '.join(item['threshold_words'][:4])}")
        lines.append(f"  (points={item['points']}, comments={item['num_comments']})")
        lines.append("")
    return "\n".join(lines).strip()


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("[error] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.")
        sys.exit(1)

    cfg = load_config()
    keywords = cfg["keywords"]
    lookback_hours = cfg["lookback_hours"]
    min_points = cfg["min_points"]
    max_comments = cfg["max_comments_per_story"]
    max_per_keyword = cfg["max_stories_per_keyword"]
    min_numeric_categories = cfg["min_numeric_categories"]

    seen = set(load_json(SEEN_FILE, []))
    since_ts = int(time.time()) - lookback_hours * 3600

    collected = {}
    for kw in keywords:
        hits = hn_search_stories(kw, since_ts, max_per_keyword)
        time.sleep(REQUEST_DELAY_SEC)
        for h in hits:
            story_id = h.get("objectID")
            if not story_id or story_id in collected:
                continue
            if (h.get("points") or 0) < min_points:
                continue
            collected[story_id] = h

    log(f"키워드 {len(keywords)}개로 최근 {lookback_hours}시간 내 글 {len(collected)}건 수집")

    new_stories = {sid: h for sid, h in collected.items() if sid not in seen}

    if not new_stories:
        log("[info] 새로운 글 없음. 종료.")
        return

    qualifying = []
    all_processed_ids = []
    for story_id, h in new_stories.items():
        all_processed_ids.append(story_id)
        title = h.get("title") or ""
        story_url = h.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        story_text = strip_html(h.get("story_text") or "")

        comments_text = hn_fetch_comments_text(story_id, max_comments)
        time.sleep(REQUEST_DELAY_SEC)

        full_text = " ".join([title, story_text, comments_text])
        analysis = analyze_text(full_text)

        if analysis["numeric_categories"] >= min_numeric_categories:
            qualifying.append({
                "title": title,
                "url": story_url,
                "points": h.get("points") or 0,
                "num_comments": h.get("num_comments") or 0,
                "money": analysis["money"],
                "death": analysis["death"],
                "percent": analysis["percent"],
                "threshold_words": analysis["threshold_words"],
            })

    if not qualifying:
        log(f"[info] 신규 {len(new_stories)}건 분석했지만 구체성 임계값 통과 없음. seen만 갱신.")
        seen.update(all_processed_ids)
        save_json(SEEN_FILE, list(seen)[-MAX_SEEN:])
        return

    message = build_message(qualifying)
    ok = send_telegram(token, chat_id, message)
    if ok:
        seen.update(all_processed_ids)
        save_json(SEEN_FILE, list(seen)[-MAX_SEEN:])
        log(f"[info] 텔레그램 전송 완료. 구체성 통과 {len(qualifying)}건 / 전체 분석 {len(new_stories)}건.")
    else:
        log("[error] 텔레그램 전송 실패. seen 갱신 안 함(다음 실행에서 재시도).")


if __name__ == "__main__":
    main()