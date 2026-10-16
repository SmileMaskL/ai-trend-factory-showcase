#!/usr/bin/env python3
"""
AI-Compiler Convergence Watch
-----------------------------
"LLM이 컴파일러를 대체하는 게 아니라, LLM이 컴파일러/런타임을 '호출'하게 된다"는
트렌드가 실제로 어디에 착지하고 있는지를 두 군데에서 교차 관찰하는 1회성 무인 스크립트.

1) GitHub Releases Atom 피드(인증 불필요)로 LLVM/Triton/TVM/PyTorch/JAX 등
   주요 컴파일러·텐서 런타임 프로젝트의 "공식 릴리스 노트"에 LLM/에이전트 관련
   키워드가 등장하는 순간만 포착 (= 트렌드가 실제 코드베이스에 반영된 증거)
2) HackerNews Algolia 검색 API로 "compiler" + AI 키워드가 함께 언급된 신규 글만 포착
   (= 트렌드가 커뮤니티 담론에 등장한 증거)

두 신호 모두 "완전히 새 항목"일 때만 텔레그램으로 알리고, 없으면 조용히 종료한다.

- 비용 $0 (공개 API만 사용, 인증 불필요)
- 의존성: 표준 라이브러리 + requests
- 실행 모델: 한 번 실행 -> 수집 -> 필터 -> 중복제거 -> 알림(또는 콘솔 출력) -> 종료
"""

import json
import os
import sys
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEEN_PATH = DATA_DIR / "seen_items.json"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
MAX_SEEN = 500

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

DEFAULT_REPOS = [
    "llvm/llvm-project",
    "openai/triton",
    "apache/tvm",
    "pytorch/pytorch",
    "google/jax",
    "halide/Halide",
    "bytecodealliance/wasmtime",
    "microsoft/onnxruntime",
]

CONVERGENCE_TERMS = [
    "llm", "gpt", "agent", "agentic", "copilot", "genai", "generative ai",
    "language model", "autotun", "auto-tun", "nl2code", "natural language",
    "claude", "chatgpt", "ai-assisted", "ai assisted",
]

HN_AI_TERMS = [
    "llm", "gpt", "agent", "genai", "generative ai", "language model",
    "claude", "copilot", "neural", "autotun",
]

HN_QUERIES = ["AI compiler", "LLM compiler", "compiler agent"]

LOOKBACK_DAYS_HN = 3
HTTP_TIMEOUT = 20


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


def fetch_release_candidates(repos, seen_ids, session):
    """주요 컴파일러/런타임 프로젝트의 릴리스 노트 중, 아직 알린 적 없고
    'LLM이 컴파일러를 호출' 트렌드와 관련된 키워드가 포함된 것만 반환."""
    results = []
    for repo in repos:
        url = f"https://github.com/{repo}/releases.atom"
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "ai-compiler-convergence-watch"})
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

            full_text = f"{title} {content}".lower()
            if not any(term in full_text for term in CONVERGENCE_TERMS):
                continue

            results.append({
                "id": uid,
                "source": f"GitHub Release · {repo}",
                "title": title or repo,
                "url": link,
                "published": published,
            })
    return results


def is_ai_compiler_related(text):
    t = text.lower()
    return "compiler" in t and any(term in t for term in HN_AI_TERMS)


def fetch_hn_candidates(since_dt, seen_ids, session):
    since_ts = int(since_dt.timestamp())
    results = []
    seen_objids = set()
    for query in HN_QUERIES:
        params = {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{since_ts}",
            "hitsPerPage": 50,
        }
        try:
            r = session.get(HN_ALGOLIA_URL, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            hits = r.json().get("hits", [])
        except requests.RequestException as e:
            log(f"HN Algolia 요청 실패 (query={query}): {e}", err=True)
            continue

        for hit in hits:
            title = hit.get("title") or ""
            if not title:
                continue
            story_id = hit.get("objectID")
            if not story_id or story_id in seen_objids:
                continue
            uid = f"hn:{story_id}"
            if uid in seen_ids:
                continue

            full_text = title + " " + (hit.get("story_text") or "")
            if not is_ai_compiler_related(full_text):
                continue

            seen_objids.add(story_id)
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            results.append({
                "id": uid,
                "source": "HackerNews",
                "title": title,
                "url": url,
                "published": hit.get("created_at", ""),
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
    lines = ["🧩 <b>AI-컴파일러 수렴 신호 (AI-Compiler Convergence Watch)</b>", ""]
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

    now = datetime.now(timezone.utc)
    since_dt = now - timedelta(days=LOOKBACK_DAYS_HN)

    log(f"GitHub 릴리스 피드 수집 중... ({len(repos)}개 저장소)")
    release_items = fetch_release_candidates(repos, seen, session)
    log(f"릴리스 신규 후보: {len(release_items)}건")

    log("HackerNews 수집 중...")
    hn_items = fetch_hn_candidates(since_dt, seen, session)
    log(f"HackerNews 신규 후보: {len(hn_items)}건")

    new_items = release_items + hn_items

    if not new_items:
        log("새로운 AI-컴파일러 수렴 신호 없음. 알림 전송 안 함.")
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