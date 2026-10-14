import os
import sys
import json
import time
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "seen_articles.json")
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")


def _load_env_file_fallback(path):
    """os.environ에 텔레그램 토큰이 없을 때만 쓰는 폴백.
    이 저장소의 run_daily.ps1이 이미 같은 경로(~/.config/ai-trend-factory.env)를
    텔레그램 토큰의 실제 출처로 사용 중인데, 이 스크립트를 실행하는 서브프로세스
    체인에는 그 값이 환경변수로 export되지 않아 os.environ.get()이 None을 반환하는
    것이 실패 원인이었다. 새 키가 필요한 게 아니라 이미 있는 토큰을 못 찾는 문제라서,
    같은 파일을 표준 라이브러리만으로 직접 읽어 보완한다."""
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    result[key] = value
    except OSError:
        pass
    return result


def _resolve_telegram_credentials():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return token, chat_id

    env_path = os.path.expanduser("~/.config/ai-trend-factory.env")
    fallback = _load_env_file_fallback(env_path)
    token = token or fallback.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or fallback.get("TELEGRAM_CHAT_ID")
    return token, chat_id


TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = _resolve_telegram_credentials()

MAX_ITEMS_PER_QUERY = 8
MAX_TOTAL_ITEMS = 20
SEEN_RETENTION_DAYS = 45
REQUEST_TIMEOUT = 15

DEFAULT_QUERIES = [
    "AI talent travel ban",
    "AI researcher visa restriction",
    "China AI talent travel restriction",
    "chip engineer export control talent",
    "AI scientist immigration crackdown",
    "brain drain AI researchers",
    "tech talent travel curbs",
    "AI talent family travel restriction",
]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_watchlist():
    wl = load_json(WATCHLIST_FILE, None)
    if wl and isinstance(wl.get("queries"), list) and wl["queries"]:
        return wl["queries"]
    return DEFAULT_QUERIES


def fetch_google_news_rss(query):
    url = (
        "https://news.google.com/rss/search?q="
        + quote(query + " when:7d")
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    resp = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AITalentWatch/1.0)"},
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items = []
    for item in root.findall(".//item")[:MAX_ITEMS_PER_QUERY]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        if title and link:
            items.append(
                {"title": title, "link": link, "pubDate": pub_date, "source": source}
            )
    return items


def hash_link(link):
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:20]


def prune_seen(seen):
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_RETENTION_DAYS)
    pruned = {}
    for k, v in seen.items():
        try:
            ts = datetime.fromisoformat(v)
        except Exception:
            continue
        if ts >= cutoff:
            pruned[k] = v
    return pruned


def escape_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def chunk_message(lines, max_len=3800):
    chunks = []
    current = ""
    for line in lines:
        candidate = (current + "\n\n" + line) if current else line
        if len(candidate) > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars are required.",
            file=sys.stderr,
        )
        sys.exit(1)

    queries = load_watchlist()
    seen = prune_seen(load_json(STATE_FILE, {}))

    collected = {}
    for q in queries:
        try:
            items = fetch_google_news_rss(q)
        except Exception as e:
            print(f"WARN: failed to fetch query '{q}': {e}", file=sys.stderr)
            continue

        for it in items:
            h = hash_link(it["link"])
            if h in seen:
                continue
            it["_hash"] = h
            collected.setdefault(h, it)

        time.sleep(1)

    new_items = list(collected.values())
    new_items.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    new_items = new_items[:MAX_TOTAL_ITEMS]

    now_iso = datetime.now(timezone.utc).isoformat()

    if not new_items:
        print("No new AI-talent policy articles found. Nothing sent.")
        save_json(STATE_FILE, seen)
        return

    lines = [f"<b>\U0001F6C2 AI 인재 정책/이동 제한 알림 \u2014 {len(new_items)}건</b>"]
    for it in new_items:
        title = escape_html(it["title"])
        source = escape_html(it["source"]) if it["source"] else ""
        line = f'\u2022 <a href="{it["link"]}">{title}</a>'
        if source:
            line += f"\n  ({source})"
        lines.append(line)

    chunks = chunk_message(lines)
    for i, chunk in enumerate(chunks):
        header = "" if i == 0 else f"(계속 {i + 1}/{len(chunks)})\n\n"
        send_telegram_message(header + chunk)
        time.sleep(1)

    for it in new_items:
        seen[it["_hash"]] = now_iso
    save_json(STATE_FILE, seen)

    print(f"Sent {len(new_items)} new items to Telegram across {len(chunks)} message(s).")


if __name__ == "__main__":
    main()