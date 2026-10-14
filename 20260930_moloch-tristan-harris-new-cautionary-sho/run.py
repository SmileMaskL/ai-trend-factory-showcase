#!/usr/bin/env python3
"""
Moloch Index — AI Race vs AI Safety 예측시장 신호
- Manifold Markets의 무료 공개 API(search-markets)에서 "AI 레이스/능력경쟁" 계열 질문과
  "AI 안전/규제/일시중단" 계열 질문의 실시간 확률(크라우드 예측)을 가져와
- 두 진영의 거래량 가중 평균 확률 차이를 하루 한 번 계산하고(Moloch Index),
- 전일 대비 지수 변화와 개별 시장의 급격한 확률 변동(무버)을 텔레그램으로 보고한 뒤 종료합니다.

의존성: 표준 라이브러리 + requests
API 키 불필요 (Manifold search-markets/market 엔드포인트는 읽기 전용 공개 API).
"""
import datetime
import html
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
HISTORY_PATH = BASE_DIR / "data" / "history.json"

API_BASE = "https://api.manifold.markets/v0"
USER_AGENT = "moloch-index-bot/1.0 (+https://manifold.markets)"
HTTP_TIMEOUT = 20
REQUEST_DELAY_SEC = 0.6
MARKETS_PER_TERM = 8
TOP_N_PER_BUCKET = 5
HISTORY_MAX_AGE_DAYS = 45
INDEX_HISTORY_MAX = 120
TELEGRAM_LIMIT = 3900

# 이 프로젝트의 핵심 해석: Moloch(다자간 경쟁 함정)는 "능력 경쟁이 안전보다 앞선다"는
# 크라우드 예측시장 확률로 근사할 수 있다는 아이디어.
BUCKETS = {
    "race": {
        "label": "🏁 AI 레이스(능력 경쟁)",
        "terms": [
            "AGI by",
            "superintelligence",
            "next frontier model",
            "AI capabilities",
            "GPT-5",
        ],
    },
    "safety": {
        "label": "🛡 AI 안전/제동",
        "terms": [
            "AI pause",
            "AI regulation",
            "AI moratorium",
            "AI safety",
            "existential risk AI",
        ],
    },
}

MOVE_THRESHOLD_PCT = float(os.environ.get("MOLOCH_MOVE_THRESHOLD_PCT", "4"))


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


# ---------------------------------------------------------------- Manifold API
def search_markets(term):
    resp = requests.get(
        f"{API_BASE}/search-markets",
        params={
            "term": term,
            "filter": "open",
            "contractType": "BINARY",
            "sort": "liquidity",
            "limit": MARKETS_PER_TERM,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"예상치 못한 응답 형식: {type(data)}")
    return data


def fetch_bucket_markets(bucket_key, bucket, errors):
    found = {}
    for term in bucket["terms"]:
        try:
            markets = search_markets(term)
        except (requests.RequestException, ValueError) as e:
            errors.append((f"{bucket_key}:{term}", str(e)))
            continue
        for m in markets:
            if m.get("isResolved"):
                continue
            if m.get("outcomeType") != "BINARY":
                continue
            prob = m.get("probability")
            mid = m.get("id")
            if prob is None or mid is None:
                continue
            volume = m.get("volume") or m.get("volume24Hours") or 0.0
            existing = found.get(mid)
            if existing is None or volume > existing["volume"]:
                found[mid] = {
                    "id": mid,
                    "question": m.get("question", "(제목 없음)"),
                    "url": m.get("url") or (f"https://manifold.markets/{m.get('creatorUsername','')}/{m.get('slug','')}"),
                    "prob": float(prob),
                    "volume": float(volume),
                    "bucket": bucket_key,
                }
        time.sleep(REQUEST_DELAY_SEC)
    return found


def weighted_avg_prob(markets):
    total_w = sum(m["volume"] for m in markets)
    if total_w <= 0:
        if not markets:
            return None
        return sum(m["prob"] for m in markets) / len(markets)
    return sum(m["prob"] * m["volume"] for m in markets) / total_w


# ---------------------------------------------------------------- 리포트
def fmt_pct(x):
    return f"{x * 100:.1f}%"


def market_line(m, prev_prob=None):
    delta = ""
    if prev_prob is not None:
        d = (m["prob"] - prev_prob) * 100
        if abs(d) >= 0.5:
            arrow = "🔺" if d > 0 else "🔻"
            delta = f" ({arrow}{abs(d):.1f}pt)"
    q = html.escape(m["question"])
    u = html.escape(m["url"], quote=True)
    return f'• <a href="{u}">{q}</a>: <b>{fmt_pct(m["prob"])}</b>{delta}'


def index_mood(index_pct):
    if index_pct >= 20:
        return "🔥 레이스 압도적 우세"
    if index_pct >= 5:
        return "⚠️ 레이스 쏠림"
    if index_pct > -5:
        return "⚖️ 팽팽한 균형"
    if index_pct > -20:
        return "🧯 안전 쪽 쏠림"
    return "🛡 안전 압도적 우세"


def build_report(today, bucket_top, bucket_avg, prev_probs, prev_index, movers, errors, total_terms_tried):
    lines = [f"<b>🧭 몰록 지수(Moloch Index)</b> — AI 레이스 vs 안전 예측시장 — {today.isoformat()}", ""]

    race_avg = bucket_avg.get("race")
    safety_avg = bucket_avg.get("safety")
    if race_avg is not None and safety_avg is not None:
        index_pct = (race_avg - safety_avg) * 100
        delta_str = ""
        if prev_index is not None:
            d = index_pct - prev_index
            if abs(d) >= 0.1:
                arrow = "🔺" if d > 0 else "🔻"
                delta_str = f" ({arrow}{abs(d):.1f}pt / 전회 대비)"
        lines.append(f"<b>지수: {index_pct:+.1f}</b>{delta_str}")
        lines.append(index_mood(index_pct))
        lines.append(f"(레이스 진영 평균 {fmt_pct(race_avg)} vs 안전 진영 평균 {fmt_pct(safety_avg)})")
    else:
        lines.append("⚠️ 두 진영 중 하나 이상의 데이터를 가져오지 못해 지수를 계산할 수 없습니다.")
    lines.append("")

    for key in ("race", "safety"):
        markets = bucket_top.get(key, [])
        if not markets:
            continue
        lines.append(f"<b>{BUCKETS[key]['label']}</b> (상위 {len(markets)}개)")
        for m in markets:
            lines.append(market_line(m, prev_probs.get(m["id"])))
        lines.append("")

    if movers:
        lines.append(f"<b>⚡ 급변동 (±{MOVE_THRESHOLD_PCT:.0f}pt 이상)</b>")
        for m, prev in movers:
            lines.append(market_line(m, prev))
        lines.append("")

    if errors:
        lines.append(f"<b>⚠️ 조회 실패 {len(errors)}/{total_terms_tried}개 검색어</b>")
        for label, err in errors[:8]:
            lines.append(f"• {html.escape(str(label))}: {html.escape(err[:150])}")
        lines.append("")

    lines.append("데이터 출처: manifold.markets (크라우드 예측시장, 실제 확정된 사실이 아닌 참고용 신호)")
    return "\n".join(lines).strip()


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
    today = datetime.date.today()
    history = load_json(HISTORY_PATH, {"markets": {}, "index_history": []})
    if not isinstance(history, dict):
        history = {"markets": {}, "index_history": []}
    history.setdefault("markets", {})
    history.setdefault("index_history", [])

    errors = []
    bucket_found = {}
    total_terms = sum(len(b["terms"]) for b in BUCKETS.values())
    for key, bucket in BUCKETS.items():
        bucket_found[key] = fetch_bucket_markets(key, bucket, errors)

    if not any(bucket_found.values()):
        report = (
            "<b>🧭 몰록 지수(Moloch Index)</b>\n\n⚠️ Manifold API에서 데이터를 전혀 가져오지 못했습니다.\n"
            + "\n".join(f"• {html.escape(str(l))}: {html.escape(e[:150])}" for l, e in errors[:10])
        )
        print(report.replace("<b>", "").replace("</b>", ""))
        send_telegram(report)
        return 1

    prev_probs = {mid: rec["prob"] for mid, rec in history["markets"].items()}
    prev_index = history["index_history"][-1]["index"] if history["index_history"] else None

    bucket_top = {}
    bucket_avg = {}
    movers = []
    now_iso = datetime.datetime.now().isoformat()

    for key, found in bucket_found.items():
        markets = sorted(found.values(), key=lambda m: -m["volume"])[:TOP_N_PER_BUCKET]
        bucket_top[key] = markets
        avg = weighted_avg_prob(markets)
        if avg is not None:
            bucket_avg[key] = avg

        for m in markets:
            prev = prev_probs.get(m["id"])
            if prev is not None and abs(m["prob"] - prev) * 100 >= MOVE_THRESHOLD_PCT:
                movers.append((m, prev))
            history["markets"][m["id"]] = {
                "question": m["question"],
                "url": m["url"],
                "bucket": key,
                "prob": m["prob"],
                "updated_at": now_iso,
            }

    cutoff = (datetime.datetime.now() - datetime.timedelta(days=HISTORY_MAX_AGE_DAYS)).isoformat()
    history["markets"] = {
        mid: rec for mid, rec in history["markets"].items()
        if rec.get("updated_at", "") >= cutoff
    }

    if "race" in bucket_avg and "safety" in bucket_avg:
        index_pct = (bucket_avg["race"] - bucket_avg["safety"]) * 100
        history["index_history"].append({"date": today.isoformat(), "index": index_pct})
        history["index_history"] = history["index_history"][-INDEX_HISTORY_MAX:]

    save_json_atomic(HISTORY_PATH, history)

    report = build_report(today, bucket_top, bucket_avg, prev_probs, prev_index, movers, errors, total_terms)
    print("\n" + report.replace("<b>", "").replace("</b>", "").replace("<a href=\"", "[").replace("\">", "] ").replace("</a>", "") + "\n")

    if not send_telegram(report):
        return 1
    print("[info] 텔레그램 전송 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())