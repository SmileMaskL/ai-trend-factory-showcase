#!/usr/bin/env python3
"""
AI Agent Security Incident Radar
---------------------------------
HackerNews + NVD(CVE)에서 "AI/LLM 에이전트" 관련 보안 사고·취약점만 교차 필터링해
새로운 항목이 있을 때만 텔레그램으로 알려주는 1회성 무인 스크립트.

- 비용 $0 (공개 API만 사용, 인증 불필요)
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> 수집 -> 필터 -> 중복제거 -> 알림 -> 종료
"""

import json
import os
import sys
import html
from datetime import datetime, timedelta, timezone

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
SEEN_PATH = os.path.join(DATA_DIR, "seen_items.json")
MAX_SEEN = 1000

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

AGENT_TERMS = [
    "ai agent", "ai-agent", "autonomous agent", "llm agent",
    "agentic", "multi-agent",
]
AI_HINT_TERMS = [
    "ai", "llm", "gpt", "autonomous", "genai", "chatbot", "assistant",
    "openai", "anthropic", "claude", "copilot", "agentic",
]
SEC_TERMS_HN = [
    "vulnerab", "exploit", "breach", "incident", "attack", "hijack",
    "injection", "backdoor", "rce", "compromise", "malicious", "leak",
    "jailbreak", "hack", "cve", "flaw",
]

HTTP_TIMEOUT = 20


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return set()
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("ids", []))
    except Exception as e:
        log(f"seen_items.json 로드 실패, 빈 세트로 시작: {e}")
        return set()


def save_seen(seen_set):
    os.makedirs(DATA_DIR, exist_ok=True)
    ids = list(seen_set)
    if len(ids) > MAX_SEEN:
        ids = ids[-MAX_SEEN:]
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "updated_at": datetime.now(timezone.utc).isoformat()}, f, ensure_ascii=False, indent=2)


def is_agent_related(text):
    t = text.lower()
    if any(term in t for term in AGENT_TERMS):
        return True
    if "agent" in t and any(hint in t for hint in AI_HINT_TERMS):
        return True
    return False


def fetch_hn_candidates(since_dt):
    since_ts = int(since_dt.timestamp())
    results = []
    for query in ["AI agent", "LLM agent", "agentic"]:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since_ts}",
            "hitsPerPage": 50,
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
            if not is_agent_related(full_text):
                continue
            if not any(term in full_text.lower() for term in SEC_TERMS_HN):
                continue

            story_id = hit.get("objectID")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            results.append({
                "id": f"hn:{story_id}",
                "source": "HackerNews",
                "title": title,
                "url": url,
                "published": hit.get("created_at", ""),
            })
    return results


def fetch_nvd_candidates(since_dt, until_dt):
    fmt = "%Y-%m-%dT%H:%M:%S.000"
    params = {
        "keywordSearch": "agent",
        "pubStartDate": since_dt.strftime(fmt),
        "pubEndDate": until_dt.strftime(fmt),
        "resultsPerPage": 100,
    }
    try:
        r = requests.get(NVD_URL, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"NVD API 요청 실패: {e}")
        return []

    results = []
    for vuln in data.get("vulnerabilities", []):
        cve = vuln.get("cve", {})
        cve_id = cve.get("id", "")
        descriptions = cve.get("descriptions", [])
        desc_en = ""
        for d in descriptions:
            if d.get("lang") == "en":
                desc_en = d.get("value", "")
                break
        if not desc_en or not is_agent_related(desc_en):
            continue

        severity = "UNKNOWN"
        metrics = cve.get("metrics", {})
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if key in metrics and metrics[key]:
                severity = metrics[key][0].get("cvssData", {}).get("baseSeverity", "UNKNOWN")
                break

        results.append({
            "id": f"nvd:{cve_id}",
            "source": "NVD",
            "title": f"{cve_id} ({severity}) - {desc_en[:140]}",
            "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            "published": cve.get("published", ""),
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


def build_message_lines(items):
    lines = ["🛡️ <b>AI 에이전트 보안 사고 레이더</b>", ""]
    by_source = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    for source, its in by_source.items():
        lines.append(f"<b>[{html.escape(source)}]</b>")
        for item in its:
            title = html.escape(item["title"])
            lines.append(f"• <a href=\"{item['url']}\">{title}</a>")
        lines.append("")
    return lines


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 설정되어 있지 않습니다.")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    since_dt = now - timedelta(days=2)

    log("HackerNews 수집 중...")
    hn_items = fetch_hn_candidates(since_dt)
    log(f"HackerNews 후보: {len(hn_items)}건")

    log("NVD(CVE) 수집 중...")
    nvd_items = fetch_nvd_candidates(since_dt, now)
    log(f"NVD 후보: {len(nvd_items)}건")

    all_items = hn_items + nvd_items

    seen = load_seen()
    new_items = [item for item in all_items if item["id"] not in seen]
    log(f"신규 항목: {len(new_items)}건 (전체 {len(all_items)}건 중)")

    if not new_items:
        log("새로운 AI 에이전트 보안 사고 없음. 알림 전송 안 함.")
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