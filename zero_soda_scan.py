#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
식품안전나라 OpenAPI(C002: 식품(첨가물)품목제조보고 - 원재료)로
탄산음료 품목을 수집하고, 감미료 구성에 따라 티어를 매기는 스크립트.

의존성 없음 (표준 라이브러리만 사용). Python 3.8+

사용법
------
1) 필드 이름부터 확인 (반드시 이것부터 실행):
   python zero_soda_scan.py --key YOUR_KEY --mode probe

2) 제품명 키워드로 수집:
   python zero_soda_scan.py --key YOUR_KEY --mode search --keyword 제로

3) 여러 키워드 한번에:
   python zero_soda_scan.py --key YOUR_KEY --mode search \
       --keyword 제로 --keyword 사이다 --keyword 콜라 --keyword 스파클링

결과: zero_soda_result.csv (엑셀에서 열 수 있게 UTF-8 BOM)
      zero_soda_raw.json (원본 응답 보관용)
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://openapi.foodsafetykorea.go.kr/api"
SERVICE = "C002"          # 식품(첨가물)품목제조보고(원재료)
PAGE = 100                # 이 API는 1회 최대 100건
SLEEP = 0.3               # 호출 간격 (서버 부하/차단 방지)

# ── 감미료 사전 ────────────────────────────────────────────────
# 표기 흔들림(알룰로스/알룰로오스, 에리스리톨/에리스리트리톨 등)까지 커버
SWEETENERS = {
    "S": ["알룰로스", "알룰로오스", "D-알룰로스", "사이코스", "타가토스"],
    "A": ["스테비올배당체", "스테비아", "효소처리스테비아", "레바우디오",
          "리바우디오", "나한과", "모그로사이드", "감초추출물", "토마틴"],
    "B": ["수크랄로스", "아세설팜", "아스파탐", "사카린", "네오탐", "어드밴탐", "시클라메이트"],
    "C": ["에리스리톨", "에리스리트리톨", "에리트리톨", "자일리톨", "자일리트"],
    "D": ["말티톨", "소르비톨", "솔비톨", "락티톨", "만니톨", "이소말트", "환원물엿"],
    "SUGAR": ["설탕", "액상과당", "과당", "물엿", "포도당", "정백당", "결정과당",
              "농축과즙", "고과당", "올리고당", "벌꿀"],
}
TIER_ORDER = ["S", "A", "B", "C", "D", "SUGAR"]  # 뒤로 갈수록 나쁨


def classify(raw_text):
    """원재료 문자열 -> (최종티어, 발견된 감미료 목록)"""
    if not raw_text:
        return "?", []
    text = raw_text.replace(" ", "")
    found, tiers = [], set()
    for tier, words in SWEETENERS.items():
        for w in words:
            if w.replace(" ", "") in text:
                found.append(f"{w}({tier})")
                tiers.add(tier)
    if not tiers:
        return "무감미료?", []
    worst = max(tiers, key=lambda t: TIER_ORDER.index(t))
    if worst == "SUGAR":
        worst = "F(당류함유)"
    return worst, found


# ── API 호출 ──────────────────────────────────────────────────
def call(key, start, end, cond=None):
    """cond: dict 형태의 검색조건. 예: {'PRDLST_NM': '제로'}"""
    url = f"{BASE}/{key}/{SERVICE}/json/{start}/{end}"
    if cond:
        for k, v in cond.items():
            url += "/" + urllib.parse.quote(f"{k}={v}", safe="=")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def unwrap(payload):
    """{'C002': {'RESULT': {...}, 'total_count': '..', 'row': [...]}} 구조를 벗김"""
    body = payload.get(SERVICE)
    if body is None:
        # 인증 실패 등은 RESULT만 최상위에 오는 경우가 있음
        raise RuntimeError(f"예상과 다른 응답: {json.dumps(payload, ensure_ascii=False)[:400]}")
    result = body.get("RESULT", {})
    code = result.get("CODE", "")
    if code and not code.startswith("INFO-000"):
        raise RuntimeError(f"API 오류 {code}: {result.get('MSG')}")
    total = int(body.get("total_count", 0))
    return total, body.get("row", [])


# ── 모드별 동작 ────────────────────────────────────────────────
def probe(key):
    """필드명 확인용. 5건만 받아서 키와 샘플을 그대로 출력."""
    total, rows = unwrap(call(key, 1, 5))
    print(f"[probe] 전체 건수: {total:,}\n")
    if not rows:
        print("행이 없습니다. 키를 확인하세요.")
        return
    print("[probe] 필드 목록:")
    for k in rows[0].keys():
        print(f"  - {k}")
    print("\n[probe] 첫 행 전체:")
    print(json.dumps(rows[0], ensure_ascii=False, indent=2))
    print("\n※ 원재료가 담긴 필드명과 식품유형 필드명을 확인한 뒤,")
    print("   아래 FIELD_* 상수를 맞춰 수정하세요 (기본값이 안 맞을 수 있음).")


# 기본 추정 필드명 — probe 결과 보고 필요하면 여기만 고치면 됩니다
FIELD_NAME = ["PRDLST_NM", "PRDT_NM", "PRODUCT_NM"]      # 제품명
FIELD_RAW = ["RAWMTRL_NM", "RAWMTRL", "RAW_MTRL_NM"]      # 원재료
FIELD_TYPE = ["PRDLST_DCNM", "PRDLST_DC_NM", "PRDT_TYPE"]  # 식품유형
FIELD_MAKER = ["BSSH_NM", "MAKER_NM", "CMPNY_NM"]          # 업소명
FIELD_DATE = ["PRMS_DT", "RPT_DT", "PRDLST_REPORT_DE"]     # 보고일자


def pick(row, candidates):
    for c in candidates:
        if c in row and row[c]:
            return str(row[c])
    return ""


def search(key, keywords, only_carbonated, out_csv, out_json):
    seen, records, raw_all = set(), [], []

    for kw in keywords:
        print(f"\n=== 키워드 '{kw}' 수집 시작 ===")
        start = 1
        total = None
        while True:
            end = start + PAGE - 1
            try:
                payload = call(key, start, end, {"PRDLST_NM": kw})
                t, rows = unwrap(payload)
            except Exception as e:
                print(f"  ! {start}-{end} 실패: {e}")
                break
            if total is None:
                total = t
                print(f"  총 {total:,}건")
            raw_all.extend(rows)
            for row in rows:
                name = pick(row, FIELD_NAME)
                ftype = pick(row, FIELD_TYPE)
                raw = pick(row, FIELD_RAW)
                maker = pick(row, FIELD_MAKER)
                date = pick(row, FIELD_DATE)

                if only_carbonated and ftype and "탄산" not in ftype:
                    continue
                sig = (name, maker, raw[:80])
                if sig in seen:
                    continue
                seen.add(sig)

                tier, found = classify(raw)
                records.append({
                    "티어": tier,
                    "제품명": name,
                    "식품유형": ftype,
                    "업소명": maker,
                    "보고일자": date,
                    "감미료": " / ".join(found),
                    "원재료전문": raw,
                })
            print(f"  {min(end, total):,}/{total:,}")
            if end >= total or not rows:
                break
            start = end + 1
            time.sleep(SLEEP)

    records.sort(key=lambda r: (TIER_ORDER.index(r["티어"])
                                if r["티어"] in TIER_ORDER else 99,
                                r["제품명"]))

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()) if records else
                           ["티어", "제품명", "식품유형", "업소명", "보고일자", "감미료", "원재료전문"])
        w.writeheader()
        w.writerows(records)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(raw_all, f, ensure_ascii=False, indent=1)

    print(f"\n완료: {len(records):,}건 -> {out_csv}")
    counts = {}
    for r in records:
        counts[r["티어"]] = counts.get(r["티어"], 0) + 1
    print("티어 분포:", ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())))

    tops = [r for r in records if r["티어"] in ("S", "A", "무감미료?")]
    if tops:
        print(f"\n── S/A/무감미료 후보 {len(tops)}건 (상위 30) ──")
        for r in tops[:30]:
            print(f"  [{r['티어']}] {r['제품명']} / {r['업소명']} / {r['감미료']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, help="식품안전나라 인증키")
    p.add_argument("--mode", choices=["probe", "search"], default="probe")
    p.add_argument("--keyword", action="append", default=[],
                   help="제품명 검색어. 여러 번 지정 가능")
    p.add_argument("--all-types", action="store_true",
                   help="탄산음료 외 유형도 모두 포함")
    p.add_argument("--out", default="zero_soda_result.csv")
    args = p.parse_args()

    if args.mode == "probe":
        probe(args.key)
        return

    kws = args.keyword or ["제로"]
    search(args.key, kws, not args.all_types, args.out, "zero_soda_raw.json")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
