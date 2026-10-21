#!/usr/bin/env python3
"""
LLM Serving Breaking-Change Radar
----------------------------------
"에이전트가 서빙(serving) 경험에서 스스로 개선할 수 있는가"를 다루는 오늘의 트렌드
(ServeLearnBench)는 결국 "LLM을 실제 운영 환경에서 서빙하는 인프라"가 계속 변하고
있다는 전제를 깔고 있다. 그 인프라(서빙 엔진 / 주요 SDK)가 실제로 무엇을, 언제
깨뜨리는지(breaking change, deprecation, sunset)를 사람이 매번 릴리스 노트를
읽지 않아도 알 수 있게, 공식 GitHub Releases 피드만으로 매일 1회 교차 관찰한다.

- 비용 $0 (GitHub Releases Atom 피드, 인증 불필요, 공개 API만 사용)
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> 수집 -> 키워드 필터 -> 중복제거 -> 알림(또는 콘솔 출력) -> 종료
- "요약/큐레이션"이 아니라 "운영 리스크 알림 필터": 평소엔 조용하고,
  실제로 breaking change/deprecation 키워드가 release note에 등장할 때만 울린다.
"""

import json
import os
import sys
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEEN_PATH = DATA_DIR / "seen_items.json"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
MAX_SEEN = 500

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
HTTP_TIMEOUT = 20

DEFAULT_REPOS = [
    "vllm-project/vllm",
    "huggingface/text-generation-inference",
    "sgl-project/sglang",
    "ollama/ollama",
    "ggerganov/llama.cpp",
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
    "BerriAI/litellm",
]

BREAKING_TERMS = [
    "deprecat",
    "breaking change",
    "breaking-change",
    "⚠️",
    "removed support",
    "remove support",
    "no longer support",
    "sunset",
    "incompatible",
    "backward incompatible",
    "backwards incompatible",
    "migration guide",
    "migration required",
    "drop support",
    "dropped support",
    "end of life",
    "end-of-life",
]


def log(msg, err=False):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, file=sys.stderr if err else sys.stdout)


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"{path.name} 로드 실패, 기본값 사용: {e}", err=True)
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_seen():
    data = load_json(SEEN_PATH, {"ids": []})
    return set(data.get("ids", []))


def save_seen(seen_set):
    ids = list(seen_set)
    if len(ids) > MAX_SEEN:
        ids = ids[-MAX_SEEN:]
    save_json(SEEN_PATH, {"ids": ids, "updated_at": datetime.now(timezone.utc).isoformat()})


def load_watchlist():
    data = load_json(WATCHLIST_PATH, {"repos": DEFAULT_REPOS})
    repos = data.get("repos", DEFAULT_REPOS)
    return repos if repos else DEFAULT_REPOS


def matched_terms(text):
    t = text.lower()
    return [term for term in BREAKING_TERMS if term in t]


def fetch_breaking_candidates(repos, seen_ids, session):
    """주요 LLM 서빙 엔진/SDK의 공식 릴리스 노트 중, 아직 알린 적 없고
    breaking change/deprecation 키워드가 포함된 것만 반환."""
    results = []
    for repo in repos:
        url = f"https://github.com/{repo}/releases.atom"
        try:
            r = session.get(
                url,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": "llm-serving-breaking-change-radar"},
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"릴리스 피드 요청 실패 ({repo}): {e}", err=True)
            continue

        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            log(f"릴리스 피드 파싱 실패 ({repo}): {e}", err=True)
            continue

        for entry in root.findall("a:entry", ATOM_NS):
            entry_id = entry.findtext("a:id", default="", namespaces=ATOM_NS)
            if not entry_id:
                continue
            uid = f"gh:{entry_id}"
            if uid in seen_ids:
                continue

            title = (entry.findtext("a:title", default="", namespaces=ATOM_NS) or "").strip()
            content = entry.findtext("a:content", default="", namespaces=ATOM_NS) or ""
            published = entry.findtext("a:updated", default="", namespaces=ATOM_NS) or ""
            link_el = entry.find("a:link", ATOM_NS)
            link = link_el.get("href") if link_el is not None else f"https://github.com/{repo}/releases"

            full_text = f"{title} {content}"
            terms = matched_terms(full_text)
            if not terms:
                continue

            results.append({
                "id": uid,
                "source": repo,
                "title": title or repo,
                "url": link,
                "published": published,
                "terms": terms,
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


def build_message_lines(items):
    lines = ["🚨 <b>LLM 서빙 엔진/SDK Breaking Change 레이더</b>", ""]
    by_source = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    for source, its in by_source.items():
        lines.append(f"<b>[{html.escape(source)}]</b>")
        for item in its:
            title = html.escape(item["title"])
            terms = ", ".join(sorted(set(item["terms"])))
            lines.append(f"• <a href=\"{item['url']}\">{title}</a>")
            lines.append(f"  └ 감지 키워드: {html.escape(terms)}")
        lines.append("")
    return lines


def strip_html(text):
    return (
        text.replace("<b>", "").replace("</b>", "")
        .replace("<a href=\"", "").replace("\">", " ").replace("</a>", "")
    )


def send_telegram_message(text, token, chat_id):
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        log(f"텔레그램 전송 실패 status={r.status_code} body={r.text[:300]}", err=True)
        return False
    return True


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    telegram_configured = bool(token and chat_id)
    if not telegram_configured:
        log(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 없어 "
            "텔레그램 전송 대신 콘솔 출력으로 대체합니다.",
            err=True,
        )

    repos = load_watchlist()
    seen = load_seen()
    session = requests.Session()

    log(f"GitHub 릴리스 피드 수집 중... ({len(repos)}개 저장소)")
    new_items = fetch_breaking_candidates(repos, seen, session)
    log(f"Breaking change 신규 후보: {len(new_items)}건")

    if not new_items:
        log("새로운 breaking change/deprecation 신호 없음. 알림 전송 안 함.")
        return

    lines = build_message_lines(new_items)
    messages = chunk_message(lines)

    if telegram_configured:
        all_sent = True
        for msg in messages:
            ok = send_telegram_message(msg, token, chat_id)
            all_sent = all_sent and ok
        if not all_sent:
            log("일부 메시지 전송 실패. 상태 파일을 갱신하지 않습니다 (다음 실행에서 재시도).", err=True)
            sys.exit(1)
        log(f"텔레그램 전송 완료 ({len(messages)}개 메시지, {len(new_items)}건).")
    else:
        for msg in messages:
            print(strip_html(msg))
            print("---")
        log(f"콘솔 출력 완료 ({len(new_items)}건, 텔레그램 미설정).")

    for item in new_items:
        seen.add(item["id"])
    save_seen(seen)
    log("완료.")


if __name__ == "__main__":
    main()