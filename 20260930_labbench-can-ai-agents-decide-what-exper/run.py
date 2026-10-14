#!/usr/bin/env python3
"""
LabBench Radar — daily scan for new research/discussion about AI agents
that decide what experiments to run next (AI-for-science, autonomous
wet-lab agents, agentic benchmarks for scientific decision-making).

Sources (all free, no API key required):
  - arXiv Atom API (papers)
  - Hacker News Algolia API (discussions)

Sends a single Telegram digest per run when Telegram credentials are
available in the environment, skips items already seen (tracked in
data/seen_items.json), and exits. No loops, no server.

If TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not present in this run's
environment (or the Telegram API call fails), the digest is written to
data/latest_digest.txt instead of aborting the run. This keeps the
script fully unattended: it never requires a human to supply anything
before it can complete successfully.
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

LOOKBACK_DAYS = 4
MAX_ITEMS_IN_DIGEST = 8
SEEN_RETENTION_DAYS = 45
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "labbench-radar/1.0 (personal research digest bot)"}

ARXIV_QUERY = (
    '(abs:"AI agent" OR abs:"autonomous agent" OR abs:"LLM agent" '
    'OR abs:"language model agent") AND '
    '(abs:"experiment" OR abs:"laboratory" OR abs:"wet-lab" OR abs:"wet lab" '
    'OR abs:"scientific discovery" OR abs:"benchmark")'
)

HN_QUERY = "AI agent lab experiment benchmark"
HN_TITLE_KEYWORDS = [
    "agent", "lab", "wet-lab", "wet lab", "experiment", "benchmark",
    "science", "scientific", "discovery",
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


def fetch_hn():
    since = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp())
    params = {
        "query": HN_QUERY,
        "tags": "story",
        "numericFilters": f"created_at_i>{since}",
        "hitsPerPage": 40,
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
        if not any(kw in title_lower for kw in HN_TITLE_KEYWORDS):
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
    lines = [f"<b>🧪 AI 실험 신호 레이더(LabBench)</b> — {len(new_items)}건의 새 신호\n"]
    for idx, item in enumerate(new_items, 1):
        date_str = item["date"].strftime("%Y-%m-%d")
        extra = f" · {item['points']}pt" if item.get("points") else ""
        lines.append(
            f"{idx}. [{item['source']}]{extra} {date_str}\n"
            f"<a href=\"{h(item['url'])}\">{h(item['title'])}</a>\n"
        )
    lines.append("— AI 에이전트의 실험/의사결정 벤치마크 관련 신규 논문·토론만 골라 보냅니다.")
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
    """Persist the digest locally when Telegram isn't reachable/configured,
    so a missing/expired credential never turns an otherwise-successful
    scan into a failed run."""
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