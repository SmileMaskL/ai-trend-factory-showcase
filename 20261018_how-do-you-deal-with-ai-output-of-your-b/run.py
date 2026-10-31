#!/usr/bin/env python3
"""
AI 말투 신호 레이더 (Hacker News)
--------------------------------
오늘의 트렌드 "How do you deal with AI Output of your boss?" (HN)에서 출발.
직장에서 상사/동료가 던지는 글이 "AI가 쓴 것 같다"는 판단은 결국 몇 가지
전형적인 말투(delve, furthermore, boilerplate 미괄식 결론, 과다한 em-dash 등)
에 근거하는 경우가 많다. 이 스크립트는 그런 "AI-tell 패턴"이 실제로
Hacker News 댓글/스토리 본문에 하루 동안 얼마나 섞여 있는지를 수치화하고,
7일 이동평균 대비 오늘 급등했는지를 텔레그램으로 알려주는 1회성 무인 스크립트.

- 데이터 소스: Hacker News 공식 Firebase API (https://github.com/HackerNews/API)
  - 인증/키 불필요, 무료, 레이트리밋 없음
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> Top 스토리 N개 + 각 스토리 댓글 일부 수집
  -> AI-tell 매칭 점수 계산 -> 7일 평균과 비교 -> 텔레그램 알림 -> 종료
  (서버/데몬 아님, 무한루프 없음)
"""

import html
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
HISTORY_FILE = DATA_DIR / "history.json"
CONFIG_FILE = BASE_DIR / "watchlist.json"

HN_TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

HTTP_TIMEOUT = 15
USER_AGENT = "ai-trend-factory-ai-tell-radar/1.0 (daily batch script; no auth)"
REQUEST_DELAY_SEC = 0.1
MAX_STORIES = 25
MAX_COMMENTS_PER_STORY = 4
MAX_HISTORY_DAYS = 30
SPIKE_RATIO = 1.5
MIN_BASELINE_DAYS = 3

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
        "ai_tell_phrases": [
            "delve into", "delve", "boilerplate", "furthermore", "moreover",
            "it's worth noting", "it is worth noting", "it is important to note",
            "in today's fast-paced world", "navigate the landscape",
            "unlock the potential", "harness the power", "robust solution",
            "seamless integration", "paradigm shift", "cutting-edge",
            "game-changer", "game changer", "leverage the power",
            "foster a", "ever-evolving", "testament to", "in conclusion",
            "to summarize", "overall, this", "as an ai language model",
            "as an ai, i", "i cannot provide", "i don't have personal",
            "plays a crucial role", "plays a vital role", "underscores the",
            "a myriad of", "a plethora of", "it's important to remember",
            "let's dive in", "let's break down", "at the end of the day",
        ],
        "em_dash_threshold": 3,
        "min_comment_length": 40,
    }
    cfg = load_json(CONFIG_FILE, default)
    cfg.setdefault("ai_tell_phrases", default["ai_tell_phrases"])
    cfg.setdefault("em_dash_threshold", default["em_dash_threshold"])
    cfg.setdefault("min_comment_length", default["min_comment_length"])
    return cfg


def clean_text(raw_html):
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = TAG_RE.sub(" ", text)
    return text


def fetch_json(url):
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        log(f"[warn] {url} 조회 실패: {e}")
        return None


def score_text(text, phrases, em_dash_threshold):
    lower = text.lower()
    matched = [p for p in phrases if p in lower]
    em_dash_count = text.count("—")
    if em_dash_count >= em_dash_threshold:
        matched.append(f"em-dash x{em_dash_count}")
    return matched


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


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("[error] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.")
        sys.exit(1)

    cfg = load_config()
    phrases = [p.lower() for p in cfg["ai_tell_phrases"]]
    em_dash_threshold = cfg["em_dash_threshold"]
    min_len = cfg["min_comment_length"]

    story_ids = fetch_json(HN_TOP_STORIES) or []
    story_ids = story_ids[:MAX_STORIES]
    log(f"Top 스토리 {len(story_ids)}건 대상으로 수집 시작")

    if not story_ids:
        log("[error] HN 스토리 목록을 가져오지 못했습니다. 종료.")
        sys.exit(1)

    total_comments = 0
    total_matches = 0
    flagged = []

    for sid in story_ids:
        story = fetch_json(HN_ITEM.format(id=sid))
        time.sleep(REQUEST_DELAY_SEC)
        if not story:
            continue
        story_title = story.get("title", "(제목 없음)")
        story_hn_url = f"https://news.ycombinator.com/item?id={sid}"
        kids = story.get("kids", [])[:MAX_COMMENTS_PER_STORY]

        for cid in kids:
            comment = fetch_json(HN_ITEM.format(id=cid))
            time.sleep(REQUEST_DELAY_SEC)
            if not comment or comment.get("deleted") or comment.get("dead"):
                continue
            text = clean_text(comment.get("text", ""))
            if len(text) < min_len:
                continue
            total_comments += 1
            matched = score_text(text, phrases, em_dash_threshold)
            if matched:
                total_matches += len(matched)
                flagged.append({
                    "score": len(matched),
                    "story_title": story_title,
                    "story_url": story_hn_url,
                    "excerpt": text[:140],
                    "matched": matched,
                })

    avg_score = round(total_matches / total_comments, 3) if total_comments else 0.0

    history = load_json(HISTORY_FILE, [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = [h for h in history if h.get("date") != today]

    baseline_entries = history[-7:]
    baseline_avg = (
        round(sum(h["avg_score"] for h in baseline_entries) / len(baseline_entries), 3)
        if len(baseline_entries) >= MIN_BASELINE_DAYS else None
    )

    is_spike = (
        baseline_avg is not None and baseline_avg > 0
        and avg_score >= baseline_avg * SPIKE_RATIO
    )

    history.append({
        "date": today,
        "total_comments": total_comments,
        "total_matches": total_matches,
        "avg_score": avg_score,
    })
    history = history[-MAX_HISTORY_DAYS:]

    flagged.sort(key=lambda f: f["score"], reverse=True)
    top_flagged = flagged[:5]

    trend_line = "데이터 누적 중(7일 미만, 기준선 없음)"
    if baseline_avg is not None:
        arrow = "🔺" if avg_score > baseline_avg else ("🔻" if avg_score < baseline_avg else "➡️")
        trend_line = f"{arrow} 7일 평균 {baseline_avg} -> 오늘 {avg_score}"

    lines = [
        "🕵️ <b>AI 말투 신호 레이더</b> (Hacker News)",
        "오늘의 트렌드: <i>How do you deal with AI Output of your boss?</i> (HN)",
        f"오늘 분석한 댓글 {total_comments}건 | AI-tell 매칭 {total_matches}건 "
        f"| 댓글당 평균 {avg_score}",
        trend_line,
    ]

    if is_spike:
        lines.insert(1, "🚨 <b>오늘 AI 말투 밀도 급등 감지!</b>")

    if top_flagged:
        lines.append("")
        lines.append("가장 'AI스러운' 댓글 Top 5:")
        for f in top_flagged:
            matched_str = ", ".join(f["matched"][:4])
            lines.append(
                f"  - [{f['score']}점] <a href=\"{html.escape(f['story_url'])}\">"
                f"{html.escape(f['story_title'][:50])}</a>"
            )
            lines.append(f"    · 패턴: {html.escape(matched_str)}")
            lines.append(f"    · \"{html.escape(f['excerpt'])}...\"")
    else:
        lines.append("")
        lines.append("오늘은 뚜렷한 AI 말투 신호 없음.")

    message = "\n".join(lines)

    ok = send_telegram(token, chat_id, message)
    if ok:
        save_json(HISTORY_FILE, history)
        log(f"[info] 텔레그램 전송 완료. 댓글 {total_comments}건 분석, 기록 저장.")
    else:
        log("[error] 텔레그램 전송 실패. history 갱신 안 함(다음 실행에서 재집계).")


if __name__ == "__main__":
    main()