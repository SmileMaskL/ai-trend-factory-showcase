#!/usr/bin/env python3
"""
AI 런치 영상 툴 스파이크 레이더
------------------------------------------------
Hacker News(Algolia Search API, 무료/키 불필요)에서 주요 AI 영상 생성 툴
(Sora, Runway, Pika, Kling, Luma, Veo, HeyGen, Synthesia 등) 언급량을
매일 집계하고, 최근 7일 평균 대비 급증(스파이크)한 툴을 찾아
텔레그램으로 알려주는 1회성 스크립트.

- 외부 의존성: requests 만 사용 (표준 라이브러리 + requests)
- 매일 1회 실행되고 끝나는 구조 (데몬/서버 없음)
- 상태는 data/history.json 에 최근 14일치만 보관
"""

import os
import json
import time
import html
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")

HN_SEARCH_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"
HN_SEARCH = "https://hn.algolia.com/api/v1/search"
HEADERS = {"User-Agent": "ai-trend-factory-video-tool-spike-radar/1.0"}

DEFAULT_KEYWORDS = [
    "Sora", "Runway", "Pika Labs", "Kling AI", "Luma AI", "Veo 3",
    "HeyGen", "Synthesia", "Hailuo AI", "Seedance", "LTX Studio",
    "Higgsfield AI", "Vidu AI",
]

MAX_HISTORY_DAYS = 14
BASELINE_WINDOW_DAYS = 7
MIN_TODAY_COUNT = 2
MIN_SPIKE_RATIO = 1.5
TOP_N = 5


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {"daily_counts": {}}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"daily_counts": {}}


def save_history(history):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_keywords():
    env_kw = os.environ.get("AI_VIDEO_KEYWORDS", "").strip()
    if env_kw:
        return [k.strip() for k in env_kw.split(",") if k.strip()]
    return DEFAULT_KEYWORDS


def hn_count(keyword, since_ts):
    params = {
        "query": keyword,
        "tags": "(story,comment)",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": 0,
    }
    try:
        r = requests.get(HN_SEARCH_BY_DATE, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return int(r.json().get("nbHits", 0))
    except Exception as e:
        print(f"[WARN] count fetch failed for '{keyword}': {e}")
        return 0


def hn_top_example(keyword, since_ts):
    params = {
        "query": keyword,
        "tags": "story",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": 5,
    }
    try:
        r = requests.get(HN_SEARCH, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as e:
        print(f"[WARN] example fetch failed for '{keyword}': {e}")
        return None

    if not hits:
        return None

    hits.sort(key=lambda h: h.get("points") or 0, reverse=True)
    top = hits[0]
    title = top.get("title") or keyword
    object_id = top.get("objectID")
    url = top.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
    points = top.get("points") or 0
    return {"title": title, "url": url, "points": points}


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되어 있지 않습니다. "
              "메시지를 전송하지 않고 아래 내용만 출력합니다.\n")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            print(f"[ERROR] 텔레그램 전송 실패: {result}")
            return False
        return True
    except Exception as e:
        print(f"[ERROR] 텔레그램 전송 중 예외 발생: {e}")
        return False


def esc(s):
    return html.escape(str(s), quote=False)


def build_message(today_str, ranked, no_spike_fallback):
    lines = [f"🎬 <b>AI 런치 영상 툴 스파이크 레이더</b> ({today_str})"]

    if ranked:
        lines.append("\n최근 7일 평균 대비 언급량이 급증한 AI 영상 생성 툴:")
        for i, (kw, today_cnt, avg_prev, ratio, example) in enumerate(ranked, start=1):
            lines.append(
                f"\n{i}. <b>{esc(kw)}</b> — 오늘 {today_cnt}건 "
                f"(최근 평균 {avg_prev:.1f}건, x{ratio:.1f})"
            )
            if example:
                lines.append(
                    f'   └ <a href="{esc(example["url"])}">{esc(example["title"])}</a> '
                    f'({example["points"]}pt)'
                )
    else:
        lines.append("\n오늘은 임계치를 넘는 뚜렷한 스파이크가 없었습니다.")
        if no_spike_fallback:
            lines.append("\n참고용 — 오늘 언급량 상위 3개 툴:")
            for kw, cnt in no_spike_fallback:
                lines.append(f"  • {esc(kw)}: {cnt}건")

    lines.append(
        "\n📡 집계 기준: HN(Algolia) 최근 24h 언급 건수, "
        "직전 7일 평균 대비 1.5배 이상 & 오늘 2건 이상일 때 스파이크로 판정"
    )
    return "\n".join(lines)


def main():
    keywords = get_keywords()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    since_today_ts = int((now - timedelta(hours=24)).timestamp())

    history = load_history()
    daily_counts = history.setdefault("daily_counts", {})

    today_counts = {}
    for kw in keywords:
        cnt = hn_count(kw, since_today_ts)
        today_counts[kw] = cnt
        print(f"[INFO] '{kw}' 최근 24h 언급: {cnt}건")
        time.sleep(0.3)

    daily_counts[today_str] = today_counts

    all_dates_sorted = sorted(daily_counts.keys())
    if len(all_dates_sorted) > MAX_HISTORY_DAYS:
        for old_date in all_dates_sorted[:-MAX_HISTORY_DAYS]:
            del daily_counts[old_date]

    prev_dates = [d for d in sorted(daily_counts.keys()) if d != today_str][-BASELINE_WINDOW_DAYS:]

    spikes = []
    for kw in keywords:
        today_cnt = today_counts[kw]
        prev_vals = [daily_counts[d].get(kw, 0) for d in prev_dates]
        avg_prev = (sum(prev_vals) / len(prev_vals)) if prev_vals else 0.0
        ratio = (today_cnt + 1) / (avg_prev + 1)
        spikes.append((kw, today_cnt, avg_prev, ratio))

    qualifying = [s for s in spikes if s[1] >= MIN_TODAY_COUNT and s[3] >= MIN_SPIKE_RATIO]
    qualifying.sort(key=lambda s: s[3], reverse=True)
    top = qualifying[:TOP_N]

    ranked = []
    for kw, today_cnt, avg_prev, ratio in top:
        example = hn_top_example(kw, since_today_ts)
        ranked.append((kw, today_cnt, avg_prev, ratio, example))
        time.sleep(0.3)

    no_spike_fallback = None
    if not ranked:
        fallback_sorted = sorted(spikes, key=lambda s: s[1], reverse=True)[:3]
        no_spike_fallback = [(kw, cnt) for kw, cnt, _, _ in fallback_sorted if cnt > 0]

    message = build_message(today_str, ranked, no_spike_fallback)
    save_history(history)

    sent = send_telegram(message)
    print(f"[DONE] 텔레그램 전송 {'성공' if sent else '실패/스킵'}. 기록 저장 완료 → {HISTORY_PATH}")


if __name__ == "__main__":
    main()