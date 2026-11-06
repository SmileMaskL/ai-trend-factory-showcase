#!/usr/bin/env python3
"""
Agent-Native Launch Radar
하루 1회 실행: Hacker News에서 "사람이 아니라 AI 에이전트가 직접 쓰도록 설계된
제품/서비스" (예: Agentitter - plain-text social network you use through your AI agent)
신규 등장 신호만 걸러서 텔레그램으로 다이제스트를 보내고 종료합니다.
무한 루프/서버 없음 - 1회성 실행 스크립트입니다.
"""
import os
import sys
import json
import time
import hashlib
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(BASE_DIR, "data", "seen_ids.json")
MAX_SEEN = 3000
LOOKBACK_HOURS = 48
HTTP_TIMEOUT = 15

# "사람용 UI가 아니라 AI 에이전트가 직접 사용하도록 설계됨"을 가리키는 신호 문구들.
# (단순히 "AI agent에 관한 글"이 아니라, "제품/서비스를 agent가 직접 쓴다"는 신호)
SIGNAL_PHRASES = [
    "through your ai agent",
    "through an ai agent",
    "via your ai agent",
    "via an ai agent",
    "use through your agent",
    "you use through your",
    "ai agent can use",
    "your ai agent can",
    "your agent can",
    "agents can join",
    "agent-native",
    "agent native",
    "agent-only",
    "agents, not humans",
    "not for humans",
    "no human ui",
    "no ui for humans",
    "plain-text social network",
    "plain text social network",
    "plain-text interface",
    "plain text interface",
    "plain-text protocol",
    "machine-readable only",
    "built for agents",
    "designed for ai agents",
    "for ai agents",
    "a social network for agents",
    "social network for ai agents",
    "interface for ai agents",
    "api for ai agents",
    "talk to my agent",
    "agent-to-agent",
    "agent to agent",
    "agent2agent",
]


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


def make_key(object_id, title):
    raw = (object_id or "") + "|" + (title or "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def find_matches(text):
    if not text:
        return []
    low = text.lower()
    return [p for p in SIGNAL_PHRASES if p in low]


def fetch_candidates():
    """HN Algolia 검색으로 'agent' 관련 최근 스토리를 모은 뒤,
    에이전트-네이티브 신호 문구가 매칭되는 것만 추린다."""
    since_ts = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    results = []
    seen_object_ids = set()

    for query in ["agent", "AI agent"]:
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{since_ts}",
                    "hitsPerPage": 200,
                },
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except requests.RequestException as e:
            print(f"[WARN] HN fetch failed for query '{query}': {e}", file=sys.stderr)
            continue

        for h in hits:
            object_id = h.get("objectID")
            if not object_id or object_id in seen_object_ids:
                continue
            seen_object_ids.add(object_id)

            title = h.get("title") or ""
            story_text = h.get("story_text") or ""
            combined = f"{title} {story_text}"

            matches = find_matches(combined)
            if not matches:
                continue

            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            target_url = h.get("url") or hn_url

            results.append({
                "object_id": object_id,
                "title": title,
                "url": target_url,
                "hn_url": hn_url,
                "points": h.get("points", 0) or 0,
                "comments": h.get("num_comments", 0) or 0,
                "created_at": h.get("created_at", ""),
                "matches": matches,
                "score": len(matches),
            })

    results.sort(key=lambda it: (it["score"], it["points"]), reverse=True)
    return results


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

    seen_data = load_json(SEEN_PATH, {"seen": []})
    seen_list = list(seen_data.get("seen", []))
    seen_set = set(seen_list)

    candidates = fetch_candidates()

    new_items = []
    for it in candidates:
        key = make_key(it["object_id"], it["title"])
        if key not in seen_set:
            seen_set.add(key)
            seen_list.append(key)
            new_items.append(it)

    if new_items:
        lines = [
            "\U0001F916 Agent-Native 제품 런칭 레이더",
            '"사람이 아니라 AI 에이전트가 직접 쓰는" 신규 제품/서비스 신호',
            f"신규 신호 {len(new_items)}건",
            "",
        ]
        for it in new_items[:15]:
            lines.append(f"- {it['title']}")
            lines.append(f"  {it['url']}")
            if it["url"] != it["hn_url"]:
                lines.append(f"  (HN: {it['hn_url']})")
            lines.append(
                f"  points={it['points']} comments={it['comments']} "
                f"matched=[{', '.join(it['matches'][:3])}]"
            )
            lines.append("")
        message = "\n".join(lines).strip()
        send_telegram(token, chat_id, message)
        print(f"[INFO] {len(new_items)}건 신규 신호 전송 완료.")
    else:
        print("[INFO] 신규 agent-native 신호 없음. 알림 생략.")

    if len(seen_list) > MAX_SEEN:
        seen_list = seen_list[-MAX_SEEN:]
    save_json(SEEN_PATH, {"seen": seen_list})


if __name__ == "__main__":
    main()