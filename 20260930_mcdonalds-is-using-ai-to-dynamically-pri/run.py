#!/usr/bin/env python3
"""
Dynamic Price Watchdog
- watchlist.json에 등록된 상품의 오늘 가격을 한 번 수집하고
- data/history.json에 누적한 뒤
- 가격 변동 / 90일 최저가 / 목표가 도달 / '가격이 자주 바뀌는 상품'을 텔레그램으로 알리고 종료합니다.

의존성: 표준 라이브러리 + requests
"""
import datetime
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
HTTP_TIMEOUT = 20
REQUEST_DELAY_SEC = 1.5          # 사이트/Steam API 부하를 줄이기 위한 요청 간격
MAX_POINTS = 365                 # 상품당 보관하는 일별 가격 기록 수
LOW_WINDOW_DAYS = 90             # "N일 최저가" 판단 기간
VOLATILITY_WINDOW_DAYS = 30      # "자주 바뀌는 가격" 판단 기간
VOLATILITY_MIN_CHANGES = 3       # 이 기간 내 이 횟수 이상 바뀌면 '동적 가격' 후보로 표시
PRICE_EPSILON = 0.005
TELEGRAM_LIMIT = 3900
ZERO_DECIMAL_CURRENCIES = {"KRW", "JPY", "VND", "IDR", "CLP", "HUF", "ISK"}


# ---------------------------------------------------------------- 파일 I/O
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}")
        try:
            os.replace(path, backup)
            print(f"[warn] {path.name} 파싱 실패({e}) -> {backup.name}로 백업하고 새로 시작합니다.")
        except OSError:
            print(f"[warn] {path.name} 파싱 실패({e})")
        return default


def save_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 가격 파싱 유틸
def parse_number(raw):
    """'$1,299.00', '1.299,00 €', '₩21,500', '9.99' 같은 문자열을 float로."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = re.sub(r"[^\d.,]", "", str(raw))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def price_from_jsonld(text):
    pattern = r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    for m in re.finditer(pattern, text, re.S | re.I):
        raw = m.group(1).strip()
        data = None
        for candidate in (raw, html.unescape(raw)):
            try:
                data = json.loads(candidate)
                break
            except (json.JSONDecodeError, ValueError):
                continue
        if data is None:
            continue
        for node in _walk(data):
            for key in ("price", "lowPrice"):
                val = node.get(key)
                if isinstance(val, (dict, list)) or val in (None, ""):
                    continue
                num = parse_number(val)
                if num is not None:
                    return num, node.get("priceCurrency")
    return None, None


_ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


def _attrs(tag):
    return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3))
            for m in _ATTR_RE.finditer(tag)}


def price_from_meta(text):
    price, currency = None, None
    for tag in re.findall(r"<meta\b[^>]*>", text, re.I):
        a = _attrs(tag)
        key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        content = a.get("content")
        if content is None:
            continue
        if key in ("product:price:amount", "og:price:amount", "price") and price is None:
            price = parse_number(content)
        elif key in ("product:price:currency", "og:price:currency", "pricecurrency") and currency is None:
            currency = content.strip()
    if price is None:
        # <span itemprop="price" content="12.34"> 같은 microdata
        for tag in re.findall(r"<[a-z]+\b[^>]*itemprop=[\"']price[\"'][^>]*>", text, re.I):
            a = _attrs(tag)
            if a.get("content"):
                price = parse_number(a["content"])
                if price is not None:
                    break
    return price, currency


def title_from_html(text):
    for tag in re.findall(r"<meta\b[^>]*>", text, re.I):
        a = _attrs(tag)
        if (a.get("property") or "").lower() == "og:title" and a.get("content"):
            return a["content"].strip()
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    if m:
        return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return None


# ---------------------------------------------------------------- 수집기
def fetch_steam(item):
    appid = str(item["appid"])
    cc = str(item.get("cc", "us")).lower()
    resp = requests.get(
        "https://store.steampowered.com/api/appdetails",
        params={"appids": appid, "cc": cc, "l": "english", "filters": "basic,price_overview"},
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json() or {}
    payload = body.get(appid) or {}
    if not payload.get("success"):
        raise ValueError(f"Steam appid {appid} 조회 실패(존재하지 않거나 지역 제한)")
    data = payload.get("data") or {}
    if isinstance(data, list):
        data = {}
    name = item.get("name") or data.get("name") or f"Steam {appid}"
    po = data.get("price_overview")
    if po:
        price = po["final"] / 100.0
        regular = po.get("initial", po["final"]) / 100.0
        discount = int(po.get("discount_percent", 0))
        currency = po.get("currency", "")
    elif data.get("is_free"):
        price, regular, discount, currency = 0.0, 0.0, 0, ""
    else:
        raise ValueError(f"Steam appid {appid}: {cc.upper()} 지역 가격 정보 없음")
    return {
        "name": f"{name} [{cc.upper()}]",
        "price": price,
        "regular": regular,
        "discount": discount,
        "currency": currency,
        "link": f"https://store.steampowered.com/app/{appid}/",
    }


def fetch_url(item):
    url = item["url"]
    resp = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": item.get("accept_language", "en-US,en;q=0.8,ko;q=0.6"),
        },
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.text
    price, currency = None, None
    regex = item.get("price_regex")
    if regex:
        m = re.search(regex, text, re.S)
        if m:
            price = parse_number(m.group(1) if m.groups() else m.group(0))
    if price is None:
        price, currency = price_from_jsonld(text)
    if price is None:
        price, currency = price_from_meta(text)
    if price is None:
        raise ValueError("페이지에서 가격을 찾지 못함 (JSON-LD/meta 없음 → price_regex 지정 필요)")
    return {
        "name": item.get("name") or title_from_html(text) or url,
        "price": price,
        "regular": None,
        "discount": None,
        "currency": item.get("currency") or currency or "",
        "link": url,
    }


FETCHERS = {"steam": fetch_steam, "url": fetch_url}


def item_key(item):
    if item.get("id"):
        return str(item["id"])
    kind = item.get("type", "url")
    if kind == "steam":
        return f"steam:{item['appid']}:{str(item.get('cc', 'us')).lower()}"
    return f"url:{item['url']}"


def item_label(item):
    return item.get("name") or item.get("url") or f"steam:{item.get('appid')}"


# ---------------------------------------------------------------- 분석
def process_item(item, history, today):
    kind = item.get("type", "url")
    if kind not in FETCHERS:
        raise ValueError(f"알 수 없는 type: {kind}")
    snap = FETCHERS[kind](item)
    key = item_key(item)

    rec = history.setdefault(key, {"points": []})
    rec["name"] = snap["name"]
    rec["currency"] = snap["currency"]
    rec["link"] = snap["link"]

    today_s = today.isoformat()
    prior = [p for p in rec.get("points", []) if p.get("t") and p["t"] < today_s]
    points = prior + [{"t": today_s, "p": snap["price"], "r": snap["regular"], "d": snap["discount"]}]
    rec["points"] = points[-MAX_POINTS:]

    prev = prior[-1] if prior else None
    low_start = (today - datetime.timedelta(days=LOW_WINDOW_DAYS)).isoformat()
    window_prices = [p["p"] for p in prior if p["t"] >= low_start]

    vol_start = (today - datetime.timedelta(days=VOLATILITY_WINDOW_DAYS)).isoformat()
    seq = [p["p"] for p in rec["points"] if p["t"] >= vol_start]
    change_count = sum(1 for a, b in zip(seq, seq[1:]) if abs(a - b) >= PRICE_EPSILON)

    price = snap["price"]
    changed = prev is not None and abs(price - prev["p"]) >= PRICE_EPSILON
    pct = None
    if changed and prev["p"] > 0:
        pct = (price - prev["p"]) / prev["p"] * 100.0
    new_low = bool(window_prices) and price < min(window_prices) - PRICE_EPSILON
    target = item.get("target_price")
    target_hit = target is not None and price <= float(target)

    return {
        "key": key,
        "name": snap["name"],
        "link": snap["link"],
        "currency": snap["currency"],
        "price": price,
        "discount": snap["discount"],
        "prev": prev["p"] if prev else None,
        "is_new": prev is None,
        "changed": changed,
        "pct": pct,
        "new_low": new_low,
        "window_low": min(window_prices + [price]),
        "window_high": max(window_prices + [price]),
        "target": target,
        "target_hit": target_hit,
        "change_count": change_count,
        "days_tracked": len(rec["points"]),
    }


# ---------------------------------------------------------------- 리포트
def fmt_money(value, currency):
    if value is None:
        return "-"
    cur = (currency or "").upper()
    if value == 0:
        return "무료"
    if cur in ZERO_DECIMAL_CURRENCIES:
        return f"{value:,.0f} {cur}".strip()
    return f"{value:,.2f} {cur}".strip()


def link(r):
    return f'<a href="{html.escape(r["link"], quote=True)}">{html.escape(r["name"])}</a>'


def build_report(results, errors, today, total):
    lines = [f"<b>💸 동적 가격 워치독</b> — {today.isoformat()}", ""]
    notify = False

    changed = [r for r in results if r["changed"]]
    changed.sort(key=lambda r: (r["pct"] if r["pct"] is not None else 0))
    if changed:
        notify = True
        lines.append("<b>가격 변동</b>")
        for r in changed:
            arrow = "🔻" if r["price"] < r["prev"] else "🔺"
            pct = f" ({r['pct']:+.1f}%)" if r["pct"] is not None else ""
            extra = []
            if r["new_low"]:
                extra.append(f"🏆 {LOW_WINDOW_DAYS}일 최저")
            if r["discount"]:
                extra.append(f"할인 {r['discount']}%")
            tail = f" · {' · '.join(extra)}" if extra else ""
            lines.append(
                f"{arrow} {link(r)}\n    {fmt_money(r['prev'], r['currency'])} → "
                f"<b>{fmt_money(r['price'], r['currency'])}</b>{pct}{tail}"
            )
        lines.append("")

    hits = [r for r in results if r["target_hit"]]
    if hits:
        notify = True
        lines.append("<b>🎯 목표가 도달</b>")
        for r in hits:
            lines.append(
                f"• {link(r)}: <b>{fmt_money(r['price'], r['currency'])}</b> "
                f"(목표 {fmt_money(float(r['target']), r['currency'])})"
            )
        lines.append("")

    new = [r for r in results if r["is_new"]]
    if new:
        notify = True
        lines.append(f"<b>🆕 기준가 등록 ({len(new)}개)</b>")
        for r in new:
            lines.append(f"• {link(r)}: {fmt_money(r['price'], r['currency'])}")
        lines.append("")

    volatile = [r for r in results if r["change_count"] >= VOLATILITY_MIN_CHANGES]
    if volatile:
        volatile.sort(key=lambda r: -r["change_count"])
        lines.append(f"<b>⚡ 가격이 자주 바뀌는 상품 (최근 {VOLATILITY_WINDOW_DAYS}일)</b>")
        for r in volatile[:10]:
            lines.append(
                f"• {link(r)}: {r['change_count']}회 변경 · 범위 "
                f"{fmt_money(r['window_low'], r['currency'])} ~ {fmt_money(r['window_high'], r['currency'])}"
            )
        lines.append("")

    always = os.environ.get("PRICE_WATCH_ALWAYS_NOTIFY", "").strip().lower() in ("1", "true", "yes")
    if always and not notify:
        notify = True
        lines.append("변동 없음. 현재 가격:")
        for r in results:
            lines.append(f"• {link(r)}: {fmt_money(r['price'], r['currency'])}")
        lines.append("")

    if errors and (notify or not results):
        notify = True
        lines.append(f"<b>⚠️ 수집 실패 {len(errors)}/{total}</b>")
        for label, err in errors[:10]:
            lines.append(f"• {html.escape(str(label))}: {html.escape(err[:200])}")
        lines.append("")

    lines.append(f"추적 중 {len(results)}/{total}개 · 변동 {len(changed)}개")
    return "\n".join(lines).strip(), notify


# ---------------------------------------------------------------- 텔레그램
def split_message(text, limit=TELEGRAM_LIMIT):
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[warn] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 → 콘솔 출력만 하고 전송은 생략합니다.")
        return True
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_message(text):
        for attempt in range(3):
            try:
                resp = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=HTTP_TIMEOUT,
                )
            except requests.RequestException as e:
                print(f"[error] 텔레그램 요청 실패: {str(e).replace(token, '***')}")
                time.sleep(2)
                continue
            if resp.status_code == 429:
                try:
                    wait = int(resp.json().get("parameters", {}).get("retry_after", 5))
                except ValueError:
                    wait = 5
                time.sleep(min(wait, 60))
                continue
            if resp.ok:
                break
            print(f"[error] 텔레그램 응답 {resp.status_code}: {resp.text[:300]}")
            return False
        else:
            return False
        time.sleep(0.5)
    return True


# ---------------------------------------------------------------- main
def main():
    watch = load_json(WATCHLIST_PATH, None)
    if watch is None:
        print(f"[error] {WATCHLIST_PATH.name} 이 없습니다. README를 참고해 만들어 주세요.")
        return 1
    items = watch.get("items", []) if isinstance(watch, dict) else watch
    items = [i for i in items if isinstance(i, dict) and i.get("enabled", True)]
    if not items:
        print("[info] 활성화된 감시 항목이 없습니다. 종료합니다.")
        return 0

    today = datetime.date.today()
    history = load_json(HISTORY_PATH, {})
    if not isinstance(history, dict):
        history = {}

    results, errors = [], []
    for idx, item in enumerate(items):
        if idx:
            time.sleep(REQUEST_DELAY_SEC)
        try:
            r = process_item(item, history, today)
            results.append(r)
            print(f"[ok] {r['name']}: {fmt_money(r['price'], r['currency'])}"
                  f"{' (변동)' if r['changed'] else ''}")
        except Exception as e:  # 한 항목 실패가 전체 실행을 멈추지 않도록
            msg = f"{type(e).__name__}: {e}"
            errors.append((item_label(item), msg))
            print(f"[fail] {item_label(item)}: {msg}")

    if results:
        save_json_atomic(HISTORY_PATH, history)

    report, notify = build_report(results, errors, today, len(items))
    print("\n" + re.sub(r"<[^>]+>", "", report) + "\n")

    if notify:
        if not send_telegram(report):
            return 1
        print("[info] 텔레그램 전송 완료")
    else:
        print("[info] 알릴 변동 없음 → 전송 생략")

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())