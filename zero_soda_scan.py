#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
식품안전나라 OpenAPI(C002: 식품(첨가물)품목제조보고 - 원재료)로
탄산음료·탄산수 품목을 전수 수집하고, 감미료 구성에 따라 티어를 매기는 스크립트.
공공데이터포털 표준데이터(15100066, 인증키 불필요)로 열량·당류를 조인한다.

의존성 없음 (표준 라이브러리만 사용). Python 3.8+

사용법
------
1) 필드 이름부터 확인 (반드시 이것부터 실행):
   python zero_soda_scan.py --mode probe

2) 전수 수집 (기본: 탄산음료 + 탄산수):
   python zero_soda_scan.py --mode collect

3) 영양(열량·당류) 조인 — 인증키 불필요:
   python zero_soda_scan.py --mode nutrition

4) 산출 (오프라인, API 호출 없음):
   python zero_soda_scan.py --mode build

5) 1~4를 순서대로 한번에:
   python zero_soda_scan.py --mode run

6) 특정 제품만 콘솔에서 조회:
   python zero_soda_scan.py --mode build --find 밀키스제로

7) 이전 스냅샷과 비교 (신제품/배합변경/단종 탐지):
   python zero_soda_scan.py --mode diff --diff-against zero_soda_raw.20260101.json

인증키: --key 인자, FOOD_API_KEY 환경변수, 또는 .env 파일(FOOD_API_KEY=... 혹은 API=...)
        중 하나로 넘긴다. build/nutrition/diff 모드는 키가 필요 없다.

결과: zero_soda_result.csv     (엑셀에서 열 수 있게 UTF-8 BOM)
      zero_soda_report.html    (검색·필터·정렬 가능한 단일 파일 리포트)
      zero_soda_raw.json       (C002 원본 응답 보관용)
      zero_soda_nutrition.json (영양DB 조인 캐시)
"""

import argparse
import csv
import collections
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://openapi.foodsafetykorea.go.kr/api"
SERVICE = "C002"          # 식품(첨가물)품목제조보고(원재료)
PAGE = 100                # 이 API는 1회 최대 100건
SLEEP = 0.3               # 호출 간격 (서버 부하/차단 방지)

ENV_FILE = ".env"
KEY_NAMES = ("FOOD_API_KEY", "API")   # 앞에 있는 이름이 우선
UA = "Mozilla/5.0"

DEFAULT_TYPES = ["탄산음료", "탄산수"]
DEFAULT_RAW = "zero_soda_raw.json"
DEFAULT_NUTRITION_CACHE = "zero_soda_nutrition.json"
DEFAULT_OUT_CSV = "zero_soda_result.csv"
DEFAULT_OUT_HTML = "zero_soda_report.html"
DEFAULT_DOCS_HTML = os.path.join("docs", "index.html")
PAGE_URL = "https://zero-drinks-tier.vercel.app/"   # Vercel 배포 주소 (canonical/OG용)
GA_ID = "G-8QMBBJ4EXD"   # Google Analytics 4 측정 ID. 빈 문자열로 두면 태그를 넣지 않는다

# 파비콘 32x32 PNG. 데이터 URI 로 심어 로컬 단일 파일에서도 뜨게 하고 추가 요청을 없앤다.
# 원본은 249x249 RGBA. docs/favicon.ico(16/32/48) 와 docs/apple-touch-icon.png(180) 은 별도 파일.
_FAVICON_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAFpUlEQVR42rWXa4xVVxmGn2/tfeYGUygog6XDCCJMhRbamDZRWn5YCBUs1VYx3toCsaGkUUMxauKlISEpptDERGvSH6YhxhojP9SkMQZp2kZLa1GL006AOh1gBjjM5cycOTNz9l7r9cc5c2CGuUJdf/bOztprve93eb/vM0ni/7g0/jc5sADn48l+7kkGGAhDRDg8Yk5UR31cMyMANgWY+Gp0wjDOF3OsffuHZH0fNWQohGFuq2viyKofUeUyUN43UzCaGkBpY19a4GzSDSa8UopKaB/OMqSUajKESZhOBeLKvW6ijQ6j2jJEZjiLiIiodpkKC1fmbxMwm+6KJwuegFDZLR4RytcYkMpjWMVikbkZX+4mAzA2bGSQBpgdGc+1DnLg7UGiKodkKA3sv7OGLY21eEFkH4AFroQgUyl3rIT62KXAyS6D6jKNQTjeFdjSOHNXxDNPJqiNwcUQxyWIaQw1I7THkxWz6wUwgqF0UBAEjIADRAiiomfORlnBPjgLWJnISP67K50E5kDD+OMv4oZzEGWQT1D9TcQrHwCLrg2AYbhRTKySG6M4ugh8L3bmGGYBzGEhJeTOoRWfxTK1V6jMDC0w1q2RiUiXDytpRRlMpg7MVwAwhXTHU7EvEVVZeEoX5ovCF1Ms48BAw4FCostoTaCAFOAqzZypCwwiHPk0T+IShoPx6LKYz99cQ+MsRxC09Xua5jrkHS4UIXjI1F5/GhrgzJFL8qydvZJ9TV/BKWbdR0YH1CcbSs/g52B3bse/8weivo5SXFwzAANnRl/SzxMNmzmw9BvE5UgeKib8+eibtLZ1Ymas+vhiNqy7AxfFqOE2mL8cf/wQuvhO2Y1hsgAbvbyCJOm9wkXx6kPadep5SVLqvSTpzX+3as2Gx8XiTeLD94oF62Uf3aS7H9ytU/89KykoBMn7RFJByrbID/WVTw8a89I5YQXJ+QJr62/h2SWPkAYPBu1nL7D50af4Z2s7mZoqbr29meZVHyPOZHjlWAv379hLb24AKeBczIHnX+JEz2xcdT0haHxZmsgC/8mf0Wu970qShtNEkrRjz0Gx6D7VrPiC9v/itxoeLqo/X9C3f/KcqpY/IBZt1I+feaH0f2ubWHivtj6+b5QFx1rgKgAVICGMenb35NR418Oypk26+6E9o/YmSaIV674pW7xZt27YJe+9tj15UPGSz6mu+UG9/lbLWBBTu8BZSdMVSvndcrKdC905FAKf+fQaJJGkKWnqieOYe+5aiVJPe0eWru4cvf0DpLk8he5+sl19EzaF8XRrYLa7jyTx4IzGhfMxM8xKQiXBooXzwGCwmNBxsYenv/cIYajImtXLWX/PHUgiity19QMAxcRX3uMxB5lB7AxMmEEuX2D1J5Zy+FdPTasrmlYnMKu2CleqvuQHi5fLr4EkCsNJqS44Y94Ns5DEy3/7F6ff7+BcZ/b6pBigadEC6mqqyPcXONHahpnhfcDMiCOj5eQZwJh7wywWzJ/D1l37OP3eOTzG3DmzOfri00gquW0mFnDOIYnmZY0sa7oJF0f88cgbXOrqpboqQ1Um5t1T7bz89xMYxqdub6a3b4A/HXmDf7z0c/bu/jq5/sL1NSQ+BOI4ZudX7+OxJ58l25Pn/h17+da2LRSLCft/+XsKxRQpsH3reppubmBpYwM7v/8z2juy1NWNX5IDYNOdDUtKJh7+zjMc+s1foCoDoazxkYMkYc8TX2L/D7YDcOS1t3jl9RZOnHyfzmwvr/7up4QgnLPK/DPlbHh1LBgvHNzN6luWcOjwUTov5XDOWNwwj8e+tpFtX95IkFAI/PrwX+nu6efM+S6+u/OLlbFvrBzbtU7HIQQuXOzGzLGwYd6IrFd6xzT1nG47x4IP3ciNc+vHnQADnJ8xAAHee+JodK33PowrNCNgnXNX+r4ynv8Pb2BgPPFP7vkAAAAASUVORK5CYII="
_FAVICON_HTML = (
    '<link rel="icon" type="image/png" sizes="32x32" href="data:image/png;base64,' + _FAVICON_B64 + '">\n'
    '<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">'
)


# ── 감미료 사전 ────────────────────────────────────────────────
# 표기 흔들림(알룰로스/알룰로오스, 에리스리톨/에리스리트리톨 등)까지 커버
SWEETENERS = {
    "S": ["알룰로스", "알룰로오스", "D-알룰로스", "사이코스", "타가토스"],
    "A": ["스테비올배당체", "스테비아", "효소처리스테비아", "레바우디오",
          "리바우디오", "나한과", "모그로사이드", "감초추출물", "토마틴"],
    "B": ["수크랄로스", "아세설팜", "아스파탐", "사카린", "네오탐", "어드밴탐", "시클라메이트"],
    "C": ["에리스리톨", "에리스리트리톨", "에리트리톨", "자일리톨", "자일리트"],
    "D": ["말티톨", "소르비톨", "솔비톨", "락티톨", "만니톨", "이소말트", "환원물엿"],
    "SUGAR": ["설탕", "백설탕", "자당", "액상과당", "과당", "물엿", "포도당", "정백당",
              "결정과당", "농축과즙", "고과당", "올리고당", "벌꿀"],
}
TIER_ORDER = ["S", "A", "B", "C", "D", "SUGAR"]            # 뒤로 갈수록 나쁨
TIER_RANK = {"무감미료": 0, "S": 1, "A": 2, "B": 3, "C": 4, "D": 5, "F": 6, "?": 7}
NEGATIONS = ["설탕무첨가", "당류무첨가", "무설탕", "무가당", "제로슈가"]
_TOKENS = sorted(((w, t) for t, ws in SWEETENERS.items() for w in ws),
                  key=lambda x: -len(x[0]))                # 긴 표기 우선

CAFFEINE_TOKENS = ("무수카페인", "카페인")
ASPARTAME_TOKENS = ("아스파탐",)
ZERO_TOKEN = re.compile(r"제로|ZERO|0\s*kcal", re.IGNORECASE)

# 음료가 아닌 식품유형 — PRDLST_DCNM=탄산수 조건의 부분일치로 딸려온다
NON_BEVERAGE_TYPES = {"탄산수소나트륨"}


# 감미료를 가릴 수 있는 '뭉뚱그린' 원재료 표기. 이런 항목만 있고 감미료가
# 하나도 탐지되지 않으면 무감미료가 아니라 '확인 불가'로 본다.
# (코카콜라 제로의 신고 원재료는 식품첨가물혼합제제뿐이다 — 2026-08-10 실측)
OPAQUE_TOKENS = ("식품첨가물혼합제제", "혼합제제", "식품첨가물", "음료베이스",
                 "혼합음료", "기타가공품", "기타농산가공품", "당류가공품")
# 원재료 토큰 완전일치 집합. '맥아추출물분말'·'맥아시럽'(착향 첨가물)과 구분하려면
# 부분일치가 아니라 완전일치여야 한다.
ALCOHOL_ING_EXACT = {
    "맥아", "맥아즙", "홉", "알코올", "알콜", "주정",
    "탁주", "약주", "청주", "일반증류주", "증류주",
}
ALCOHOL_ING_PREFIX = ("호프", "홉추출", "맥아(")
ALCOHOL_ING_SUBSTR = ("위스키", "럼주", "보드카")

# 제품명 신호. '에일'(→진저에일)·'럼'(→플럼) 같은 부분문자열 함정을 피해
# 단독 토큰으로 쓰지 않는다. 아래 목록은 오탐 0으로 실측 검증됨.
ALCOHOL_NAME = re.compile(
    r"논알콜|논알코올|넌알콜|넌 알콜|무알콜|무알코올|non[- ]?alcohol|"
    r"맥주|beer|라거|lager|스타우트|IPA|페일에일|몰트드링크|밀맥|낫맥|"
    r"하이볼|막걸리|와인|소주|위스키|사케|칵테일|NAB",
    re.I,
)


def is_alcoholic(name, raw_text):
    """무알콜 맥주·논알콜 주류맛 음료 판정. 대체당 티어 대상이 아니므로 배제한다."""
    if ALCOHOL_NAME.search(name or ""):
        return True
    for part in (raw_text or "").split(","):
        p = part.strip().replace(" ", "")
        if p in ALCOHOL_ING_EXACT:
            return True
        if p.startswith(ALCOHOL_ING_PREFIX):
            return True
        if any(s in p for s in ALCOHOL_ING_SUBSTR):
            return True
    return False


def split_ingredients(raw_text):
    """괄호 depth 0의 쉼표로만 분할. '구연산(결정), 비타민C' 같은 표기 보호."""
    parts, buf, depth = [], [], 0
    for ch in raw_text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.replace(" ", "") for p in parts if p.strip()]


def classify(raw_text):
    """원재료 문자열 -> {'tier','combo','hits'}   hits: [{'표기','티어','순번'}]"""
    if not raw_text or not raw_text.strip():
        return {"tier": "?", "combo": "-", "hits": []}
    parts = split_ingredients(raw_text)
    text = raw_text.replace(" ", "")
    for neg in NEGATIONS:                        # 길이 보존 마스킹
        text = text.replace(neg, "\x00" * len(neg))
    hits, tiers = [], set()
    for w, tier in _TOKENS:                       # 긴 표기부터
        if w not in text:
            continue
        text = text.replace(w, "\x00" * len(w))   # 소비 → 짧은 표기 재매칭 차단
        seq = next((i + 1 for i, p in enumerate(parts) if w in p), 0)
        hits.append({"표기": w, "티어": tier, "순번": seq})
        tiers.add(tier)
    if not tiers:
        # 감미료가 '없는' 것과 '안 보이는' 것은 다르다. 코카콜라 제로처럼
        # 원재료가 식품첨가물혼합제제로 뭉뚱그려진 제품을 무감미료로 표시하면
        # 사실과 다르므로, 불투명 원재료가 있으면 판정을 보류한다.
        if any(o in p for p in parts for o in OPAQUE_TOKENS):
            return {"tier": "?", "combo": "-", "hits": []}
        return {"tier": "무감미료", "combo": "-", "hits": []}
    hits.sort(key=lambda h: (TIER_ORDER.index(h["티어"]), h["순번"]))
    label = lambda t: "F" if t == "SUGAR" else t
    worst = label(max(tiers, key=TIER_ORDER.index))
    combo = "+".join(label(t) for t in TIER_ORDER if t in tiers)
    return {"tier": worst, "combo": combo, "hits": hits}


# ── API 호출 ──────────────────────────────────────────────────
class ApiError(RuntimeError):
    """서버가 명시적으로 거부한 요청. 재시도해도 소용없음."""


def load_key(cli_key):
    if cli_key:
        return cli_key
    for name in KEY_NAMES:
        v = os.environ.get(name)
        if v:
            return v.strip()
    if os.path.exists(ENV_FILE):
        pairs = {}
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                pairs[k.strip()] = v.strip().strip('"').strip("'")
        for name in KEY_NAMES:
            if pairs.get(name):
                return pairs[name]
    raise SystemExit(
        "인증키를 찾을 수 없습니다. --key 로 넘기거나 FOOD_API_KEY 환경변수 "
        "또는 .env 파일에 FOOD_API_KEY=... 를 설정하세요."
    )


def _get_json(url, timeout=30, retries=3, headers=None):
    last = None
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise ApiError(f"HTTP {e.code} {e.reason}")
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        else:
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                m = re.search(r"alert\('([^']*)'\)", body)
                raise ApiError(m.group(1) if m else
                               "JSON이 아닌 응답: " + body.strip()[:200])
        time.sleep(2 ** attempt)
    raise ApiError(f"요청 실패: {last}")


def call(key, start, end, cond=None, service=SERVICE):
    """cond: dict 형태의 검색조건. 예: {'PRDLST_DCNM': '탄산음료'}"""
    url = f"{BASE}/{key}/{service}/json/{start}/{end}"
    if cond:
        for k, v in cond.items():
            url += "/" + urllib.parse.quote(f"{k}={v}", safe="=")
    return _get_json(url)


def unwrap(payload, service=SERVICE):
    """{'C002': {'RESULT': {...}, 'total_count': '..', 'row': [...]}} 구조를 벗김"""
    body = payload.get(service)
    if body is None:
        raise ApiError(f"예상과 다른 응답: {json.dumps(payload, ensure_ascii=False)[:400]}")
    result = body.get("RESULT", {})
    code = result.get("CODE", "")
    if code == "INFO-200":          # 해당하는 데이터가 없습니다 - 오류가 아니다
        return 0, []
    if code and not code.startswith("INFO-000"):
        raise ApiError(f"API 오류 {code}: {result.get('MSG')}")
    total = int(body.get("total_count", 0))
    return total, body.get("row", [])


# ── 필드명 ────────────────────────────────────────────────────
# probe로 전부 검증됨 (2026-08-07). 새 환경에서 응답이 다르면 후보를 추가한다.
FIELD_NAME = ["PRDLST_NM", "PRDT_NM", "PRODUCT_NM"]         # 제품명
FIELD_RAW = ["RAWMTRL_NM", "RAWMTRL", "RAW_MTRL_NM"]        # 원재료
FIELD_TYPE = ["PRDLST_DCNM", "PRDLST_DC_NM", "PRDT_TYPE"]   # 식품유형
FIELD_MAKER = ["BSSH_NM", "MAKER_NM", "CMPNY_NM"]           # 업소명
FIELD_DATE = ["PRMS_DT", "RPT_DT", "PRDLST_REPORT_DE"]      # 보고일자
FIELD_CHNG = ["CHNG_DT"]                                     # 변경일자
FIELD_REPORT_NO = ["PRDLST_REPORT_NO"]                       # 품목제조보고번호


def pick(row, candidates):
    for c in candidates:
        if c in row and row[c]:
            return str(row[c])
    return ""


# ── probe ─────────────────────────────────────────────────────
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


# ── Step 1: collect ──────────────────────────────────────────
def fetch_all(key, types):
    """식품유형별 전수 수집. (rows, counts) 반환. 파일에 쓰지 않는다."""
    rows = []
    counts = {}
    for t in types:
        print(f"\n=== 식품유형 '{t}' 수집 시작 ===")
        start = 1
        total = None
        type_rows = []
        while True:
            end = start + PAGE - 1
            try:
                payload = call(key, start, end, {"PRDLST_DCNM": t})
                total_now, page_rows = unwrap(payload)
            except ApiError as e:
                print(f"  ! {start}-{end} 실패: {e}")
                break
            if total is None:
                total = total_now
                print(f"  총 {total:,}건")
            type_rows.extend(page_rows)
            print(f"  {min(end, total):,}/{total:,}")
            if end >= total or not page_rows:
                break
            start = end + 1
            time.sleep(SLEEP)
        rows.extend(type_rows)
        counts[t] = len(type_rows)
    return rows, counts


def sort_rows(rows):
    """보고번호 기준 안정 정렬. API 응답 순서가 흔들려도 git diff가 최소가 된다."""
    return sorted(rows, key=lambda r: (pick(r, FIELD_REPORT_NO), pick(r, FIELD_NAME)))


def write_raw(rows, types, path, fetched_at=None):
    data = {
        "fetched_at": fetched_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "types": types,
        "rows": sort_rows(rows),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def collect(key, types, out_raw):
    rows, counts = fetch_all(key, types)
    write_raw(rows, types, out_raw)
    print(f"\n완료: 총 {len(rows):,}건 -> {out_raw}")
    for t, c in counts.items():
        print(f"  {t}: {c:,}건")


def load_raw_full(path):
    if not os.path.exists(path):
        raise SystemExit(f"원본 데이터 파일이 없습니다: {path} (먼저 --mode collect 실행)")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, []
    return data.get("rows", []), data.get("types", [])


def load_raw(path):
    return load_raw_full(path)[0]


# ── Step 2: nutrition ────────────────────────────────────────
NUTRI_URL = "https://www.data.go.kr/download/standard.json"
NUTRI_PK = "15100066"
NUTRI_TABLE = "tn_pubr_public_nutri_process_info_svc"
NUTRI_PER_PAGE = 10000
NUTRI_TOTAL_COUNT = 50000   # 엔드포인트가 요구하는 파라미터. 실제 반환 건수는 이보다 많을 수 있음(무시됨)
# 엔드포인트가 부분 컬럼 목록을 보내면 500을 반환한다 — 표준데이터 화면이 요청하는 전체 컬럼을 그대로 보낸다.
NUTRI_ALL_COLS = [
    "FOOD_CD", "FOOD_NM", "DATA_CD", "TYPE_NM", "FOOD_ORIGIN_CD", "FOOD_ORIGIN_NM",
    "FOOD_LV3_CD", "FOOD_LV3_NM", "FOOD_LV4_CD", "FOOD_LV4_NM", "FOOD_LV5_CD", "FOOD_LV5_NM",
    "FOOD_LV6_CD", "FOOD_LV6_NM", "FOOD_LV7_CD", "FOOD_LV7_NM", "NUT_CON_SRTR_QUA", "ENERC",
    "WATER", "PROT", "FATCE", "ASH", "CHOCDF", "SUGAR", "FIBTG", "CA", "FE", "P", "K", "NAT",
    "VITA_RAE", "RETOL", "CARTB", "THIA", "RIBF", "NIA", "VITC", "VITD", "CHOLE", "FASAT", "FATRN",
    "SRC_CD", "SRC_NM", "SERV_SIZE", "FOOD_SIZE", "ITEM_MNFTR_RPT_NO", "MFR_NM", "IMPT_NM",
    "DIST_NM", "IMPT_YN", "COO_CD", "COO_NM", "DATA_PROD_CD", "DATA_PROD_NM", "CRT_YMD", "CRTR_YMD",
]
# canonicalize()가 실제로 쓰는 부분만 캐시에 남겨 파일 크기를 줄인다.
NUTRI_KEEP = ["FOOD_NM", "NUT_CON_SRTR_QUA", "ENERC", "SUGAR", "FOOD_SIZE",
              "ITEM_MNFTR_RPT_NO", "MFR_NM", "FOOD_LV3_NM", "CRT_YMD"]
# 이 헤더 없이는 404/500을 반환한다 (브라우저 XHR과 동일한 조건 요구).
NUTRI_HEADERS = {
    "Referer": "https://www.data.go.kr/data/15100066/standard.do",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def fetch_nutrition(wanted_nos, cache_path, refresh):
    if not refresh and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        table = cache.get("rows", {})
        print(f"[nutrition] 캐시 사용: {cache_path} ({len(table):,}건)")
        return table

    table = {}
    page = 1
    while True:
        qs = urllib.parse.urlencode(
            [("publicDataPk", NUTRI_PK)]
            + [("colNmList", c) for c in NUTRI_ALL_COLS]
            + [("totalCount", str(NUTRI_TOTAL_COUNT)),
               ("svcTableNm", NUTRI_TABLE),
               ("perPage", str(NUTRI_PER_PAGE)),
               ("page", str(page))]
        )
        url = f"{NUTRI_URL}?{qs}"
        try:
            page_rows = _get_json(url, timeout=120, headers=NUTRI_HEADERS)
        except ApiError as e:
            print(f"영양 데이터 수집 실패: {e} — 열량/당류 없이 진행합니다")
            return {}
        if not page_rows:
            break
        for rec in page_rows:
            no = (rec.get("ITEM_MNFTR_RPT_NO") or "").strip()
            if no and no in wanted_nos:
                prev = table.get(no)
                if prev is None or (rec.get("CRT_YMD") or "") > (prev.get("CRT_YMD") or ""):
                    table[no] = {k: rec.get(k, "") for k in NUTRI_KEEP}
        if page % 10 == 0:
            print(f"  page {page} / 누적 매칭 {len(table):,}건")
        if len(page_rows) < NUTRI_PER_PAGE:
            break
        page += 1

    if wanted_nos:
        print(f"[nutrition] 보고번호 {len(wanted_nos):,}개 중 {len(table):,}개 매칭 "
              f"({len(table) / len(wanted_nos):.0%})")
    else:
        print("[nutrition] 대상 보고번호가 없습니다.")

    cache = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": f"{NUTRI_URL}?publicDataPk={NUTRI_PK}",
        "rows": table,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return table


def load_nutrition_cache(cache_path):
    """(rows, checked) 반환.

    checked = 표준데이터에서 '찾아본' 보고번호 전체. 영양DB에 없는 제품은
    rows에 남지 않으므로, checked를 따로 기록하지 않으면 매달 다시 전수
    조회하게 된다 (조회 대상 2,410건 중 매칭은 1,211건뿐).
    """
    if not os.path.exists(cache_path):
        return {}, set()
    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)
    rows = cache.get("rows", {})
    checked = set(cache.get("checked") or rows)
    return rows, checked


def write_nutrition_cache(table, checked, cache_path):
    cache = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": f"{NUTRI_URL}?publicDataPk={NUTRI_PK}",
        "checked": sorted(checked),
        "rows": dict(sorted(table.items())),
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)


def sync_nutrition(wanted_nos, cache_path):
    """증분 갱신. 아직 조회한 적 없는 보고번호가 있을 때만 표준데이터를 내려받는다.

    표준데이터는 보고번호 조건 검색을 지원하지 않아 전체를 훑어야 하므로
    (수십 페이지, 수 분 소요), 신규 제품이 없는 달에는 다운로드 자체를
    건너뛰는 것이 유일하면서 가장 큰 최적화다.
    반환: (table, downloaded)
    """
    rows, checked = load_nutrition_cache(cache_path)
    unseen = wanted_nos - checked
    stale = set(rows) - wanted_nos

    if not unseen:
        if stale:
            rows = {no: v for no, v in rows.items() if no in wanted_nos}
            write_nutrition_cache(rows, wanted_nos, cache_path)
            print(f"[nutrition] 신규 보고번호 없음 — 다운로드 생략, 단종 {len(stale):,}건 정리")
        else:
            print("[nutrition] 신규 보고번호 없음 — 다운로드 생략")
        return rows, False

    print(f"[nutrition] 미조회 보고번호 {len(unseen):,}건 — 표준데이터 전수 조회")
    fresh = fetch_nutrition(wanted_nos, cache_path, refresh=True)
    if not fresh:
        print("[nutrition] 조회 실패 — 기존 캐시를 유지합니다")
        return rows, False
    merged = {no: v for no, v in rows.items() if no in wanted_nos}
    merged.update(fresh)
    write_nutrition_cache(merged, wanted_nos, cache_path)
    return merged, True


def nutrition_mode(raw_path, cache_path, refresh):
    rows = load_raw(raw_path)
    wanted = {pick(r, FIELD_REPORT_NO).strip() for r in rows}
    wanted.discard("")
    fetch_nutrition(wanted, cache_path, refresh)


# ── Step 3: 생산중단 제품 걸러내기 (I2852) ───────────────────
# 단종된 제품을 현행처럼 보여주지 않기 위한 확인. 보고번호로 하나씩 물어본다.
#
# 왜 하나씩인가 - I2852 는 조건 없이 페이징하면 **1,000행에서 잘린다**
# (total_count 가 "1" 같은 엉뚱한 값으로 오고 1,001행부터는 빈 응답이다.
#  2026-08-10 실측). 전수 스캔이 불가능하니 개별 조회 외에 방법이 없다.
# 일일 호출 제한은 1,000회라 현행 제품 수(약 620개) 정도는 감당된다.
#
# I2570(유통바코드)·C005(바코드연계제품정보)는 쓰지 않는다. 2018년에 멈춘
# 자료라 커버리지가 1.3%(32/2,410)였고, 주는 제품명도 소매명이 아니라
# `동아오츠카 나랑드 사이다 250G x 6EA` 같은 도매 팩 단위 표기라 등록명보다
# 나빴다. 자세한 실측은 AGENTS.md 참고.
DEFAULT_ENRICH_CACHE = "zero_soda_enrich.json"
DEFAULT_LABEL_FILE = "zero_soda_label.json"
ENRICH_MAX_CALLS = 900   # 일일 제한 1,000회. 여유를 둔다


def fetch_discontinued(key, wanted, max_calls=ENRICH_MAX_CALLS):
    """보고번호별로 I2852 를 조회한다. (단종정보, 실제로 확인된 보고번호) 반환.

    실패한 번호는 `confirmed` 에 넣지 않는다. 넣으면 다음 실행에서 영영
    다시 묻지 않게 되어, 조회하지 못한 것이 '단종 아님'으로 굳어버린다.
    """
    found, confirmed = {}, set()
    todo = sorted(wanted)[:max_calls]
    if len(wanted) > max_calls:
        print(f"  ! 대상 {len(wanted):,}개가 호출 상한 {max_calls}회를 넘어 앞에서부터만 조회")
    for i, no in enumerate(todo, 1):
        try:
            _, rows = unwrap(call(key, 1, 5, {"PRDLST_REPORT_NO": no}, service="I2852"),
                             service="I2852")
        except ApiError as e:
            if "INFO-300" in str(e):
                # 일일 호출건수 초과. 더 두드려봐야 전부 실패하니 여기서 멈춘다.
                print(f"  ! 일일 호출 한도 초과 - {i - 1:,}개까지만 확인하고 중단합니다. "
                      f"내일 다시 실행하면 남은 것부터 이어서 조회합니다.")
                break
            print(f"  ! {no} 조회 실패: {e}")
            continue
        confirmed.add(no)
        for row in rows:
            end = str(row.get("END_DT", "")).strip()
            if end:
                found[no] = {"생산중단일": end}
                why = str(row.get("ARTCL_END_WHY", "")).strip()
                if why:
                    found[no]["사유"] = why
                break
        if i % 100 == 0 or i == len(todo):
            print(f"  [I2852] {i:,}/{len(todo):,} · 단종 {len(found):,}건")
        time.sleep(SLEEP)
    return found, confirmed


def write_enrich_cache(discontinued, checked, cache_path):
    """정렬해서 저장한다 - API 응답 순서가 흔들려도 git diff가 최소가 되도록.

    `checked` 를 함께 남긴다. 단종이 아닌 보고번호를 기록해 두지 않으면
    매달 전부 다시 물어보게 된다 (영양 캐시와 같은 이유).
    """
    data = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "discontinued": {k: discontinued[k] for k in sorted(discontinued)},
        "checked": sorted(checked),
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def load_enrich_cache(cache_path):
    """(discontinued, checked). 캐시가 없으면 비어 있다 - 보강은 선택 사항이다."""
    if not cache_path or not os.path.exists(cache_path):
        return {}, set()
    with open(cache_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("discontinued", {}), set(data.get("checked", []))


def load_labels(path=DEFAULT_LABEL_FILE):
    """제조사 공식몰의 고시·라벨에서 확인한 유통명. 품목제조보고번호로 조인한다.

    C002 의 제품명은 품목제조보고 등록명이라 유통명과 다르다 (`나랑드사이다` 대 실제
    판매명 `나랑드사이다 제로`). 라벨 사진에 품목제조보고번호가 함께 찍혀 있어
    이름 추측 없이 정확히 붙일 수 있다 - 실제로 12개 중 10개가 예상 레코드로 맞았다.

    **손으로 검증해 넣는 파일이다.** 자동 수집하지 말 것. 쇼핑몰 대부분이 크롤링을
    막고 있고(AGENTS.md 참고), 위키·블로그는 「작성 원칙」이 금지하는 출처다.
    """
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("labels", {})


def enrich_targets(rows, nutrition):
    """확인할 보고번호 = **실제로 게시되는 제품**의 현행 행 보고번호만.

    build 와 같은 순서로 걸러낸다. 원본 2,410행을 전부 물으면 일일 제한(1,000회)을
    그냥 넘긴다 - 실제로 넘겨서 INFO-300 을 받았다. 주류·비음료만 걸러도 1,646개라
    여전히 모자라므로, 제로 표기 없는 일반 음료까지 걸러 게시 대상만 남긴다.
    제품별 최신 보고번호 하나씩이면 충분하다 - 현행 보고가 살아 있으면 생산 중이다.
    """
    records = [r for r in canonicalize(rows, nutrition)
               if r["식품유형"] not in NON_BEVERAGE_TYPES
               and not is_alcoholic(r["제품명"], r["원재료전문"])]
    annotate(records)
    targets = set()
    for rec in records:
        if rec["티어"] in ("F", "무감미료") and rec["제로표기"] != "Y":
            continue
        no = rec["이력"][0]["보고번호"].strip()
        if no:
            targets.add(no)
    return targets


def enrich_mode(key, raw_path, cache_path, nutrition_path=DEFAULT_NUTRITION_CACHE,
                recheck=False):
    rows = load_raw(raw_path)
    nutrition = {}
    if os.path.exists(nutrition_path):
        with open(nutrition_path, encoding="utf-8") as f:
            nutrition = json.load(f).get("rows", {})
    wanted = enrich_targets(rows, nutrition)

    known, checked = load_enrich_cache(cache_path)
    todo = wanted if recheck else (wanted - checked)
    print(f"확인 대상 {len(wanted):,}개 중 미확인 {len(todo):,}개 조회 "
          f"(기확인 {len(checked & wanted):,}개 생략)")
    if not todo:
        return known, checked

    fresh, confirmed = fetch_discontinued(key, todo)
    if not confirmed:
        # 한 건도 확인하지 못했다 (대개 일일 호출 한도 초과). 캐시를 건드리지 않는다.
        print("[enrich] 확인된 건이 없어 캐시를 그대로 둡니다.")
        return known, checked
    merged = {k: v for k, v in known.items() if k in wanted}
    merged.update(fresh)
    now_checked = (checked & wanted) | confirmed
    write_enrich_cache(merged, now_checked, cache_path)
    print(f"\n[enrich] 생산중단 {len(merged):,}건 · 확인 완료 {len(now_checked):,}/{len(wanted):,}"
          f" -> {cache_path}")
    if len(now_checked) < len(wanted):
        print(f"[enrich] 남은 {len(wanted) - len(now_checked):,}개는 다음 실행에서 이어서 조회합니다.")
    return merged, now_checked


# ── Step 4: 제품 통합과 배합 이력 ────────────────────────────
def recency(row):
    return (max(pick(row, FIELD_DATE) or "", pick(row, FIELD_CHNG) or ""),
            pick(row, FIELD_REPORT_NO) or "")


CSV_FIELDS = ["티어", "조합", "제품명", "등록명", "식품유형", "업소명", "보고일자", "감미료",
              "열량", "기준량", "당류", "용량", "감미료미표기", "이력행수", "배합변경", "티어불일치",
              "원재료전문", "제로표기", "실측제로", "제로사칭", "카페인", "카페인수동", "아스파탐",
              "생산중단일", "표시원재료", "유통명출처", "일반판", "일반판티어"]


def _sugar_g(nut):
    """영양DB의 당류(g). 값이 없으면 None — '0'과 '데이터 없음'을 구분한다."""
    if not nut:
        return None
    try:
        return float(str(nut.get("SUGAR", "")).strip())
    except (TypeError, ValueError):
        return None


def resolve_by_nutrition(cls, nut):
    """원재료 표기만으로는 틀리는 두 경우를 영양 실측으로 바로잡는다.

    1) 당류 토큰이 잡혔는데 실제 당류가 0g
       레몬농축과즙·올리고당이 착향·미량으로 들어간 경우다. 나랑드사이다가
       레몬농축과즙 때문에 F로 떨어지던 것이 실제로는 0kcal/0g 제품이었다.
       -> 당류를 빼고 남은 감미료로 다시 판정한다.

    2) 감미료가 하나도 안 보이는데(원재료가 혼합제제로 뭉뚱그려짐) 실제 당류가 있음
       -> 당류가 있으니 F.

    반환: (tier, combo, 감미료미표기)
    """
    tier, combo, hits = cls["tier"], cls["combo"], cls["hits"]
    hidden = "Y" if tier == "?" else ""
    sugar = _sugar_g(nut)

    if tier == "?":
        # 확인 불가를 그대로 노출하면 쓰기 어려우므로 당류 실측으로 자리를 정한다.
        if sugar is not None and sugar > 0:
            return "F", "F", hidden
        return "무감미료", "-", hidden

    if tier == "F" and sugar == 0:
        rest = [h for h in hits if h["티어"] != "SUGAR"]
        if not rest:
            return "무감미료", "-", hidden
        worst = max({h["티어"] for h in rest}, key=TIER_ORDER.index)
        kept = {h["티어"] for h in rest}
        return worst, "+".join(t for t in TIER_ORDER if t in kept), hidden

    return tier, combo, hidden


def norm_name(name):
    """제품명 표기 정규화. 공백·하이픈·가운뎃점류·대소문자만 통일한다.

    `코카콜라 제로`/`코카·콜라 제로`/`코카●콜라 제로`/`코카 - 콜라 제로`는 같은
    제품이지만 C002에는 별개 행으로 등록되어 있다. 코카콜라 하나가 가운뎃점만
    U+00B7·U+2022·U+25CF 세 가지를 섞어 쓰므로 유사 기호를 한꺼번에 지운다.

    괄호 내용과 용량은 건드리지 않는다 - `콜앤비(트로피칼)`과
    `콜앤비(핑크 그레이프프룻)`은 서로 다른 제품이기 때문이다. 마침표·`&`·`+`도
    남긴다: `1.5 스파클링`처럼 의미가 있는 자리에 쓰인다.
    """
    return re.sub(r"[\s_\-\u2010-\u2015\u2212"
                  r"\u00b7\u2022\u2027\u2219\u22c5\u25cf\u25cb\u318d\u30fb]", "", name).upper()


_ODD_CHARS = re.compile(r"[^\w\s()]", re.UNICODE)


def display_name(names):
    """같은 제품의 표기 변형 중 가장 깔끔한 것을 대표로 고른다.

    코카콜라는 `코카콜라 제로`·`코카·콜라 제로`·`코카●콜라 제로`를 모두 신고해 두었다.
    최신 보고 행의 표기를 쓰면 `코카●콜라 제로`가 뽑히므로, 기호가 가장 적은 표기를
    우선하고 같으면 더 자주 쓰인 표기를 택한다.
    """
    freq = collections.Counter(names)
    return min(freq, key=lambda n: (len(_ODD_CHARS.findall(n)), -freq[n], len(n), n))


def canonicalize(rows, nutrition, discontinued=None, labels=None):
    discontinued = discontinued or {}
    labels = labels or {}
    # 1차: 등록명으로 묶는다.
    by_registered = {}
    for row in rows:
        name = pick(row, FIELD_NAME).strip()
        if not name:
            continue
        by_registered.setdefault(norm_name(name), []).append(row)

    # 2차: 한 행이라도 유통명이 확인되면 그룹 전체를 유통명으로 다시 묶는다.
    # 같은 제품이 등록명과 유통명 양쪽으로 신고돼 있으면(`나랑드사이다 그린애플` 과
    # `나랑드사이다 제로 그린애플`) 여기서 한 제품으로 합쳐진다. 1차 키를 바로
    # 유통명으로 잡으면, 공장 일부만 라벨에 실린 제품이 오히려 둘로 쪼개진다.
    groups = {}
    for key, group in by_registered.items():
        label = next((labels[n] for n in
                      (pick(r, FIELD_REPORT_NO).strip() for r in group) if n in labels), None)
        retail_key = norm_name(label["유통명"]) if label and label.get("유통명") else key
        groups.setdefault(retail_key, []).extend(group)

    records = []
    for group in groups.values():
        group.sort(key=recency, reverse=True)
        cur = group[0]
        registered = display_name([pick(r, FIELD_NAME).strip() for r in group])
        raw = pick(cur, FIELD_RAW)
        cls = classify(raw)

        makers = {pick(r, FIELD_MAKER) for r in group if pick(r, FIELD_MAKER)}
        maker = pick(cur, FIELD_MAKER)
        display_maker = f"{maker} 외 {len(makers) - 1}곳" if len(makers) > 1 else maker

        changed = any(pick(r, FIELD_RAW) != raw for r in group[1:])
        tiers = {classify(pick(r, FIELD_RAW))["tier"] for r in group}
        mismatch = "Y" if len(tiers) > 1 else ""

        nut = None
        for r in group:  # recency 순 — 현행 행부터 훑는다
            no = pick(r, FIELD_REPORT_NO).strip()
            if no and no in nutrition:
                nut = nutrition[no]
                break

        history = [{
            "보고일자": recency(r)[0],
            "보고번호": pick(r, FIELD_REPORT_NO),
            "원재료전문": pick(r, FIELD_RAW),
        } for r in group]

        # 현행(최신) 보고가 단종이면 단종. 구버전 보고번호만 끝난 제품은 현행 판매품이라
        # 건드리지 않는다. 확인 대상도 현행 행 하나뿐이다(enrich_targets 참고).
        end_dt = discontinued.get(pick(cur, FIELD_REPORT_NO).strip(), {}).get("생산중단일", "")
        nos = [pick(r, FIELD_REPORT_NO).strip() for r in group]

        # 공식몰 고시에서 확인된 유통명이 있으면 그걸 쓴다. 등록명은 따로 남긴다 -
        # 출처를 밝히지 않고 이름만 바꾸면 이 프로젝트의 근거 원칙이 깨진다.
        label = next((labels[n] for n in nos if n in labels), None)
        retail = (label or {}).get("유통명", "")

        # C002 원재료가 식품첨가물혼합제제로 가려져 감미료를 알 수 없는 제품은,
        # 고시에 실린 표시 원재료로 다시 판정한다. 코카콜라 제로가 '무감미료'(최상위)로
        # 표시되던 것이 이 경로로 바로잡힌다. 티어를 바꾸는 만큼 출처를 반드시 남긴다.
        label_raw = (label or {}).get("원재료", "")
        # 라벨 표시원재료는 C002 가 감미료를 하나도 못 짚었을 때만 덮어쓴다.
        # "?" 는 혼합제제로 가려진 경우, "무감미료" 는 신고서에 감미료가 없는 경우다.
        # 신고서의 '없음'보다 라벨의 '있음'이 더 구체적인 증거라 라벨을 따른다
        # (제로슈거 하이진저: C002 는 감미료 0건, 라벨은 알룰로스·수크랄로스·아세설팜).
        # C002 가 이미 감미료를 짚은 제품은 건드리지 않는다 - 정부 신고 데이터가 우선.
        if label_raw and cls["tier"] in ("?", "무감미료"):
            cls = classify(label_raw)

        tier, combo, hidden = resolve_by_nutrition(cls, nut)

        records.append({
            "티어": tier,
            "조합": combo,
            "제품명": retail or registered,
            "등록명": registered if retail and retail != registered else "",
            "유통명출처": (label or {}).get("출처", "") if (retail or label_raw) else "",
            "표시원재료": label_raw,
            # 신고 원재료가 혼합제제로 가려 카페인을 알 수 없는 제품에 한해 손으로 표시한다.
            # 유/무만 다루므로 원재료 전문 없이도 넣을 수 있다 (annotate 에서 적용).
            "_카페인수동": (label or {}).get("카페인", ""),
            "생산중단일": end_dt,
            "식품유형": pick(cur, FIELD_TYPE),
            "업소명": display_maker,
            "보고일자": recency(cur)[0],
            "감미료": " / ".join(f"{h['표기']}({h['티어']},{h['순번']})" for h in cls["hits"]),
            "열량": nut.get("ENERC", "") if nut else "",
            "기준량": nut.get("NUT_CON_SRTR_QUA", "") if nut else "",
            "당류": nut.get("SUGAR", "") if nut else "",
            "용량": nut.get("FOOD_SIZE", "") if nut else "",
            "감미료미표기": hidden,
            "이력행수": len(group),
            "배합변경": "Y" if changed else "",
            "티어불일치": mismatch,
            "원재료전문": raw,
            "_원본업소명": maker,      # 제조사 집계용 (annotate). CSV/HTML에는 안 씀
            "이력": history,          # HTML 배합 이력용. CSV에는 안 씀
        })
    return records


def kcal_per_100(rec):
    """100ml(g)당 열량. 영양DB의 기준량이 100이 아닌 제품이 있어 환산한다.

    값이 없으면 None - '0kcal'과 '데이터 없음'을 구분한다.
    """
    try:
        energy = float(str(rec.get("열량", "")).strip())
    except (TypeError, ValueError):
        return None
    qty = re.sub(r"[^\d.]", "", str(rec.get("기준량", "")))
    try:
        qty = float(qty) if qty else 100.0
    except ValueError:
        qty = 100.0
    return energy * 100.0 / qty if qty else None


# ── Step 4b: 파생 플래그와 제로↔일반판 짝 매칭 ─────────────────
def annotate(records):
    for rec in records:
        name = rec["제품명"]
        rec["제로표기"] = "Y" if ZERO_TOKEN.search(name) else "N"
        # 제로칼로리 표시 기준은 100ml당 4kcal 미만 (식약처 표시광고 기준).
        # 제품명이 아니라 실측 열량으로 판정하므로, 등록명에 '제로'가 없는
        # 나랑드사이다 같은 제품도 제로 음료로 잡힌다.
        k = kcal_per_100(rec)
        rec["실측제로"] = "" if k is None else ("Y" if k < 4.0 else "N")
        rec["제로사칭"] = "Y" if rec["제로표기"] == "Y" and rec["티어"] == "F" else ""
        # 고시에 실린 표시 원재료가 있으면 그걸로 판단한다. C002 원문이
        # 식품첨가물혼합제제로 뭉뚱그려진 제품은 카페인·아스파탐도 안 보인다.
        text = (rec.get("표시원재료") or rec["원재료전문"]).replace(" ", "")
        rec["카페인"] = "Y" if any(tok in text for tok in CAFFEINE_TOKENS) else ""
        # 원재료에서 못 짚었을 때만 수동 판정을 쓴다. 원재료에 카페인이 적혀 있으면 그게 우선.
        manual = rec.pop("_카페인수동", "")
        if manual and not rec["카페인"]:
            rec["카페인"] = "Y" if manual == "Y" else ""
            rec["카페인수동"] = "Y" if manual == "Y" else ""
        rec["아스파탐"] = "Y" if any(tok in text for tok in ASPARTAME_TOKENS) else ""
        rec["일반판"] = ""
        rec["일반판티어"] = ""

    groups = {}
    for rec in records:
        base = re.sub(r"\s+", "", ZERO_TOKEN.sub("", rec["제품명"]))
        groups.setdefault(base, []).append(rec)

    for base, group in groups.items():
        zeros = [r for r in group if r["제로표기"] == "Y"]
        normals = [r for r in group if r["제로표기"] == "N"]
        if not zeros or not normals:
            continue
        worst_normal = max(normals, key=lambda r: TIER_RANK.get(r["티어"], 99))
        for z in zeros:
            z["일반판"] = worst_normal["제품명"]
            z["일반판티어"] = worst_normal["티어"]

    # 제조사 집계 (제로 표기 제품만, 상위 15)
    maker_tiers = {}
    for rec in records:
        if rec["제로표기"] != "Y":
            continue
        maker = rec.get("_원본업소명") or rec["업소명"]
        maker_tiers.setdefault(maker, {})
        maker_tiers[maker][rec["티어"]] = maker_tiers[maker].get(rec["티어"], 0) + 1
    top_makers = sorted(maker_tiers.items(), key=lambda kv: -sum(kv[1].values()))[:15]

    return {"제조사": top_makers}


# 가시 FAQ 와 FAQPage LD 는 같은 원본에서 만든다. 글자가 어긋나면 스팸 판정 위험이
# 있어서, 화면 문구와 구조화 데이터를 절대 따로 쓰지 않는다.
_FAQ = [
    ("제로 음료 중 가장 나은 감미료는 무엇인가요?",
     "알룰로스와 타가토스입니다. 0.2~0.4 kcal/g 이고 식후 혈당을 오히려 낮춘다는 "
     "메타분석 결과가 있어 이 리포트에서 S 등급입니다. 다만 국내 탄산음료에서 알룰로스만 "
     "쓰는 제품은 드물고 대개 다른 감미료와 섞여 최종 등급이 내려갑니다."),
    ("코카콜라 제로에는 어떤 감미료가 들어가나요?",
     "아스파탐과 아세설팜칼륨입니다. 식약처 신고 원재료에는 '식품첨가물혼합제제'로만 "
     "적혀 있어 감미료가 보이지 않아, 판매처의 상품정보제공 고시 표시사항으로 확인해 "
     "출처와 함께 표시했습니다."),
    ("제로라고 적혀 있으면 칼로리가 정말 0인가요?",
     "아닙니다. 제로칼로리 표기 기준은 100mL당 4kcal 미만이라 소량의 열량과 당류가 "
     "있어도 적법하게 '제로'를 붙일 수 있습니다. 이 리포트는 제로를 표방하면서 신고 "
     "원재료에 당류가 있는 제품을 F 등급으로 따로 표시합니다."),
    ("에리스리톨은 피해야 하나요?",
     "혈당에는 무해하지만 혈소판 반응성·심혈관 사건과 연관된 관찰연구 신호가 있어 이 "
     "리포트에서 C 등급입니다. 인과관계는 확정되지 않았습니다. 스테비아 제품은 대부분 "
     "에리스리톨과 혼합되므로 원재료를 직접 확인해야 합니다."),
    ("이 데이터는 어디서 온 것인가요?",
     "식품의약품안전처 식품(첨가물)품목제조보고 원재료(C002)에서 제품명·업소명·원재료 "
     "전문을 수집하고, 품목제조보고번호로 공공데이터포털 전국통합식품영양성분정보"
     "(15100066)의 열량·당류를 조인했습니다. 추정으로 채우지 않으며 매월 갱신합니다."),
]


_GA_SNIPPET = """<script>
(function () {
  // 로컬로 연 산출물(file://, localhost)은 통계에서 제외한다
  if (location.protocol.indexOf('http') !== 0) return;
  var h = location.hostname;
  if (h === 'localhost' || h === '::1' || h.indexOf('127.') === 0) return;
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=__GA_ID__';
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { dataLayer.push(arguments); };
  gtag('js', new Date());
  gtag('config', '__GA_ID__');
})();
</script>"""


# ── Step 5: 단일 파일 HTML 리포트 ────────────────────────────
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제로 탄산음료 감미료 티어 리포트 | 식약처 원재료 데이터 기반 __TOTAL__개 제품 분석</title>
<meta name="description" content="국내 유통 제로·무당류 탄산음료 __TOTAL__개의 감미료 구성을 식약처 품목제조보고 원재료 데이터로 분석해 S~F 티어로 분류합니다. 알룰로스·스테비아·수크랄로스·아스파탐·에리스리톨 등 성분별 연구 근거와 제로 표기 사칭 여부까지 확인하세요.">
<meta name="robots" content="index, follow">
<meta name="naver-site-verification" content="a3a82e491e9f40e89ab9e12d3306aab7">
__FAVICON__
<link rel="canonical" href="__PAGE_URL__">
<meta property="og:type" content="website">
<meta property="og:locale" content="ko_KR">
<meta property="og:title" content="제로 탄산음료 감미료 티어 리포트">
<meta property="og:description" content="식약처 원재료 데이터로 분류한 국내 제로·무당류 탄산음료 __TOTAL__개의 감미료 티어(S~F). 알룰로스부터 아스파탐까지 성분별 근거를 확인하세요.">
<meta property="og:url" content="__PAGE_URL__">
<meta property="og:site_name" content="대체당 제로 음료 티어">
<meta property="og:image" content="__PAGE_URL__og-card.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="제로 탄산음료 감미료 티어 리포트">
<meta name="twitter:description" content="식약처 원재료 데이터로 분류한 국내 제로·무당류 탄산음료 __TOTAL__개의 감미료 티어(S~F).">
<meta name="twitter:image" content="__PAGE_URL__og-card.png">
__GA__
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "대체당 제로 음료 티어",
  "alternateName": "제로 탄산음료 감미료 티어 리포트",
  "description": "국내 유통 제로·무당류 탄산음료와 탄산수 __TOTAL__개 제품의 대체당(감미료) 구성을 식품의약품안전처 품목제조보고 원재료 전문으로 수집하고, 피어리뷰 메타분석 근거에 따라 S~F 티어로 분류한 데이터셋입니다. 알룰로스·스테비올배당체·수크랄로스·아스파탐·에리스리톨 등 감미료별 탐지 결과와 제로 표기 대비 실제 당류 포함 여부를 담고 있습니다.",
  "url": "__PAGE_URL__",
  "inLanguage": "ko",
  "dateModified": "__GENERATED_DATE__",
  "datePublished": "2026-08-09",
  "temporalCoverage": "2026-08-09/..",
  "measurementTechnique": "식품의약품안전처 품목제조보고 원재료 전문에서 감미료 표기를 탐지하고, 품목제조보고번호로 공공데이터포털 영양성분 표준데이터를 조인",
  "spatialCoverage": {"@type": "Place", "name": "대한민국"},

  "isAccessibleForFree": true,
  "keywords": ["제로음료", "대체당", "감미료", "알룰로스", "스테비아", "수크랄로스", "아스파탐", "에리스리톨", "탄산음료", "식품영양", "오픈데이터"],
  "variableMeasured": ["티어", "감미료 조합", "원재료 전문", "열량", "당류", "카페인 함유", "아스파탐 함유", "제로 표기 여부"],
  "creator": {"@type": "Person", "name": "gulf1324", "url": "https://github.com/gulf1324",
              "sameAs": ["https://github.com/gulf1324", "https://github.com/gulf1324/zero-drinks-tier"]},
  "publisher": {"@type": "Organization", "@id": "__PAGE_URL__#publisher", "name": "대체당 제로 음료 티어",
                "url": "__PAGE_URL__", "logo": "__PAGE_URL__apple-touch-icon.png",
                "sameAs": ["https://github.com/gulf1324/zero-drinks-tier"]},
  "sourceOrganization": {"@type": "GovernmentOrganization", "name": "식품의약품안전처", "url": "https://www.mfds.go.kr/"},
  "isBasedOn": [
    "https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=C002",
    "https://www.data.go.kr/data/15100066/standard.do"
  ],
  "creditText": "식품의약품안전처 식품(첨가물)품목제조보고(원재료), 공공데이터포털 전국통합식품영양성분정보",
  "sameAs": "https://github.com/gulf1324/zero-drinks-tier",
  "license": "https://github.com/gulf1324/zero-drinks-tier/blob/main/NOTICE.md",
  "distribution": [
    {"@type": "DataDownload", "encodingFormat": "text/html", "contentUrl": "__PAGE_URL__"},
    {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": "https://raw.githubusercontent.com/gulf1324/zero-drinks-tier/main/zero_soda_raw.json"},
    {"@type": "DataDownload", "encodingFormat": "text/markdown", "contentUrl": "__PAGE_URL__llms-full.txt"}
  ]
}
</script>
__FAQ_LD__
<style>
  :root{
    --bg:#f4f5f7; --surface:#fff; --border:#e4e7eb; --border-strong:#d3d8de;
    --text:#16191d; --muted:#6b7280; --muted-2:#8a919b;
    --accent:#2563eb; --accent-soft:#eef4ff; --danger:#c0262c; --danger-soft:#fdf4f4;
    --radius:10px; --radius-sm:7px; --pill:999px;
    --shadow-sm:0 1px 2px rgba(16,24,40,.05);
    --shadow:0 1px 3px rgba(16,24,40,.08), 0 1px 2px rgba(16,24,40,.04);
  }
  /* 티어 색의 단일 진원지 — 배지 점·배지 활성·표 칩·범례 칩이 모두 상속 */
  [data-tier="무감미료"]{--tc:#4caf50;--tf:#ffffff}
  [data-tier="S"]{--tc:#8bc34a;--tf:#14210a}
  [data-tier="A"]{--tc:#cddc39;--tf:#1f2408}
  [data-tier="B"]{--tc:#ffc107;--tf:#2b2000}
  [data-tier="C"]{--tc:#ff9800;--tf:#2b1800}
  [data-tier="D"]{--tc:#f4511e;--tf:#ffffff}
  [data-tier="F"]{--tc:#cc0000;--tf:#ffffff}
  [data-tier="?"]{--tc:#9aa1ab;--tf:#ffffff}

  *{box-sizing:border-box}
  body{margin:0;padding:20px 18px 44px;background:var(--bg);color:var(--text);font-size:13px;line-height:1.5;
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
       -webkit-font-smoothing:antialiased}
  .page{max-width:1320px;margin:0 auto}

  header{margin-bottom:14px}
  h1{font-size:22px;line-height:1.25;letter-spacing:-.01em;margin:0 0 5px;font-weight:700}
  .meta{color:var(--muted);font-size:12.5px;margin:0 0 12px}
  .meta-note{color:var(--muted-2);font-size:11.5px}

  .tier-chip{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:20px;padding:0 7px;
             border-radius:var(--radius-sm);font-size:11.5px;font-weight:700;white-space:nowrap;
             background:var(--tc,#9aa1ab);color:var(--tf,#fff)}

  .badges{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
  .badge{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--border-strong);background:var(--surface);
         border-radius:var(--pill);padding:5px 12px 5px 10px;font-size:12.5px;font-weight:600;color:var(--text);
         cursor:pointer;box-shadow:var(--shadow-sm);transition:background .12s,border-color .12s,box-shadow .12s}
  .badge:hover{border-color:#b9c0c9;box-shadow:var(--shadow)}
  .badge .dot{width:9px;height:9px;border-radius:50%;flex:none;background:var(--tc,#9aa1ab)}
  .badge .cnt{color:var(--muted);font-variant-numeric:tabular-nums}
  .badge.active{background:var(--tc,#4b5563);color:var(--tf,#fff);border-color:transparent;box-shadow:var(--shadow)}
  .badge.active .cnt{color:var(--tf,#fff);opacity:.7}
  .badge.active .dot{background:var(--tf,#fff);opacity:.85}
  .clear-tiers{border:1px solid var(--border-strong);background:var(--surface);border-radius:var(--pill);
               padding:5px 12px;font-size:12.5px;font-weight:600;color:var(--muted);cursor:pointer;box-shadow:var(--shadow-sm)}
  .clear-tiers:hover:not(:disabled){color:var(--text);border-color:#b9c0c9}
  .clear-tiers:disabled{opacity:.4;cursor:default;box-shadow:none}

  .warn{display:flex;gap:9px;align-items:flex-start;background:var(--danger-soft);border:1px solid #f0cdcd;
        border-left:4px solid var(--danger);border-radius:var(--radius-sm);padding:10px 13px;margin:0 0 12px;
        cursor:pointer;font-size:12.5px;color:#7d1d21;box-shadow:var(--shadow-sm)}
  .warn:hover{background:#fbebeb}
  .warn::before{content:"!";flex:none;width:16px;height:16px;border-radius:50%;background:var(--danger);color:#fff;
                font-size:11px;font-weight:700;line-height:16px;text-align:center;margin-top:1px}

  details.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
                margin:0 0 12px;box-shadow:var(--shadow-sm);font-size:12.5px}
  details.panel>summary{cursor:pointer;padding:10px 14px;font-weight:600;list-style:none;user-select:none;color:var(--text)}
  details.panel>summary::-webkit-details-marker{display:none}
  details.panel>summary::before{content:"\25B8";display:inline-block;margin-right:7px;color:var(--muted-2);
                                transition:transform .15s}
  details.panel[open]>summary::before{transform:rotate(90deg)}
  details.panel>summary:hover{background:#fafbfc;border-radius:var(--radius) var(--radius) 0 0}
  .panel-body{padding:2px 14px 12px}

  .tier-row{display:grid;grid-template-columns:30px 96px minmax(190px,1.1fr) minmax(240px,2fr);gap:10px;
            align-items:start;padding:7px 0;border-top:1px solid var(--border)}
  .tier-row:first-child{border-top:0}
  .tier-ing{color:var(--text)}
  .tier-why{color:var(--muted)}
  .tier-note{margin-top:10px;padding-top:9px;border-top:1px solid var(--border);color:var(--muted);font-size:12px}

  .maker-row{display:flex;align-items:center;gap:10px;margin:4px 0}
  .maker-name{width:230px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}
  .maker-bar{flex:1;height:14px;background:#eef0f2;border-radius:var(--radius-sm);overflow:hidden;display:flex}
  .maker-bar span{height:100%}

  /* ── 검색: 이 사이트의 주 진입 동선이라 가장 크고 먼저 온다 ── */
  .searchbar{background:var(--surface);border:1px solid var(--border);border-radius:14px;
             padding:13px 14px 11px;margin:0 0 11px;box-shadow:var(--shadow)}
  .searchfield{position:relative;display:flex;align-items:center}
  .s-icon{position:absolute;left:14px;width:18px;height:18px;fill:none;stroke:var(--muted-2);
          stroke-width:2;stroke-linecap:round;pointer-events:none}
  .searchfield:focus-within .s-icon{stroke:var(--accent)}
  input[type=search]{width:100%;padding:13px 42px 13px 42px;font-size:16px;font-family:inherit;
                     border:1.5px solid var(--border-strong);border-radius:var(--pill);
                     background:#fbfcfd;color:var(--text);outline:none;
                     -webkit-appearance:none;appearance:none}
  input[type=search]::-webkit-search-cancel-button{display:none}
  input[type=search]::placeholder{color:var(--muted-2)}
  input[type=search]:focus{border-color:var(--accent);background:#fff;
                           box-shadow:0 0 0 4px rgba(37,99,235,.13)}
  .s-clear{position:absolute;right:8px;width:26px;height:26px;border:0;border-radius:50%;
           background:#e8ebee;color:var(--muted);font-size:15px;line-height:1;cursor:pointer;
           display:flex;align-items:center;justify-content:center}
  .s-clear:hover{background:#dde1e5;color:var(--text)}
  .s-clear[hidden]{display:none}
  .searchmeta{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:9px 2px 0}
  .count-pill{color:var(--muted);font-size:12.5px;white-space:nowrap}
  .count-pill b{color:var(--accent);font-size:15px;font-variant-numeric:tabular-nums}
  .hint{color:var(--muted-2);font-size:11.5px}

  .toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:var(--surface);
           border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px;
           margin:0 0 12px;box-shadow:var(--shadow-sm)}
  .chks{display:flex;gap:7px;flex-wrap:wrap;align-items:center;min-width:0}
  .chk{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);background:#fbfcfd;
       border-radius:var(--pill);padding:5px 11px;font-size:12.5px;cursor:pointer;color:var(--muted);
       transition:background .12s,border-color .12s,color .12s}
  .chk:hover{border-color:var(--border-strong);color:var(--text)}
  .chk input{accent-color:var(--accent);margin:0;cursor:pointer}
  .chk:has(input:checked){background:var(--accent-soft);border-color:#bcd3fb;color:#12356e;font-weight:600}
  /* 정렬 컨트롤 — 데스크톱은 표 헤더 클릭으로 하므로 좁은 화면에서만 노출 */
  .sortsel{display:none;align-items:center;gap:6px;margin-left:auto;color:var(--muted);font-size:12px}
  .sortsel select{font-family:inherit;font-size:12.5px;padding:5px 8px;border-radius:var(--radius-sm);
                  border:1px solid var(--border-strong);background:#fbfcfd;color:var(--text)}
  .sortsel button{width:30px;height:28px;border:1px solid var(--border-strong);border-radius:var(--radius-sm);
                  background:#fbfcfd;color:var(--text);cursor:pointer;font-size:11px}

  .tablecard{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)}
  table{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px}
  th,td{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--border)}
  th{position:sticky;top:0;z-index:2;background:#f7f8fa;color:var(--muted);font-size:11.5px;font-weight:700;
     letter-spacing:.02em;white-space:nowrap;cursor:pointer;user-select:none;
     box-shadow:inset 0 -1px 0 var(--border-strong)}
  th:hover{color:var(--text);background:#f1f3f5}
  .th-unit{display:block;font-size:9px;font-weight:600;color:var(--muted-2);letter-spacing:0;margin-top:1px}
  th:first-child{border-top-left-radius:var(--radius)}
  th:last-child{border-top-right-radius:var(--radius)}
  th.sorted{color:var(--accent)}
  th.sorted::after{content:" " attr(data-dir);font-size:9px}
  tbody tr:last-child td{border-bottom:0}
  tr.row{cursor:pointer}
  tr.row:hover td{background:#f7f9fc}
  tr.fake-zero td:first-child{box-shadow:inset 3px 0 0 var(--danger)}
  tr.row.expanded td{background:#f4f8fd}
  tr.row.expanded:hover td{background:#eef4fb}
  tr.row.expanded td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
  tr.fake-zero.row.expanded td:first-child{box-shadow:inset 3px 0 0 var(--accent),inset 6px 0 0 var(--danger)}
  td.c-name .pname{font-weight:600}
  td.c-maker{color:var(--muted)}
  td.c-date,td.c-vol{white-space:nowrap;color:var(--muted);font-variant-numeric:tabular-nums}
  td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
  td.c-sweet{color:var(--muted);font-size:12px;max-width:280px}
  td.c-combo{white-space:nowrap}
  .combo-plus{color:var(--muted-2);margin:0 3px;font-size:11px}
  .na{color:#c3c8cf}
  .chip{display:inline-block;background:#eef0f2;color:var(--muted);border-radius:var(--pill);padding:1px 7px;
        font-size:10.5px;font-weight:600;margin-left:5px;vertical-align:1px}
  .chip.warn-chip{background:#fff4e5;color:#8a5300;cursor:help}
  .chip.ok-chip{background:#e8f5ec;color:#1c6b3c;cursor:help}
  tr.detail td{background:#f4f8fd;font-size:12px;padding:0}
  .detail-cell{width:0;min-width:100%}
  .detail-box{padding:11px 13px;border-left:3px solid var(--accent);white-space:pre-wrap;line-height:1.65;
              animation:detailIn .14s cubic-bezier(.16,1,.3,1)}
  .detail-raw{color:var(--text);margin-bottom:6px}
  .detail-box a{color:var(--accent)}
  .detail-box div{color:var(--muted)}
  @keyframes detailIn{from{opacity:0}to{opacity:1}}
  @media (prefers-reduced-motion: reduce){.detail-box{animation:none}}
  tr.empty td{text-align:center;padding:34px 10px;color:var(--muted);border-bottom:0}
  .pager{margin:14px 0 0;display:flex;flex-direction:column;align-items:center;gap:7px}
  .pager-btns{display:flex;gap:5px;flex-wrap:wrap;justify-content:center}
  .pg{min-width:34px;height:34px;padding:0 10px;border:1px solid var(--border-strong);
      background:var(--surface);border-radius:var(--radius-sm);font-family:inherit;font-size:12.5px;
      color:var(--text);cursor:pointer;box-shadow:var(--shadow-sm)}
  .pg:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
  .pg.cur{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700;cursor:default}
  .pg:disabled{opacity:.4;cursor:default;box-shadow:none}
  .pg-gap{color:var(--muted-2);align-self:center;padding:0 2px}
  .pager-info{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}

  footer{margin-top:18px;padding-top:13px;border-top:1px solid var(--border);font-size:11px;color:var(--muted-2);line-height:1.7}
  footer div+div{margin-top:3px}
  .guides{margin:26px 0 0}
  .guides h2,.faq h2{font-size:15px;margin:0 0 10px;letter-spacing:-.01em}
  .guides ul{list-style:none;padding:0;margin:0;display:grid;gap:7px;
             grid-template-columns:repeat(auto-fit,minmax(258px,1fr))}
  .guides a{display:block;background:var(--surface);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:10px 12px;color:var(--text);
            text-decoration:none;font-size:13px;box-shadow:var(--shadow-sm)}
  .guides a:hover{border-color:var(--accent);color:var(--accent)}
  .guides span{display:block;color:var(--muted);font-size:11.5px;margin-top:2px}
  .faq{margin:26px 0 0}
  .faq details{background:var(--surface);border:1px solid var(--border);
               border-radius:var(--radius-sm);padding:9px 12px;margin-bottom:6px;font-size:13px}
  .faq summary{cursor:pointer;font-weight:600}
  .faq p{margin:8px 0 2px;color:var(--muted);line-height:1.7}

  /* 긴 원재료 문자열이 칸 밖으로 새지 않도록 전역 가드 */
  td,th,.detail-box,.tier-why,.maker-name{overflow-wrap:anywhere;word-break:break-word}

  @media (max-width:860px){
    .tier-row{grid-template-columns:30px 1fr;gap:3px 10px}
    .tier-ing,.tier-why{grid-column:2}
    .maker-name{width:140px}
  }

  /* ── 좁은 화면: 9열 표를 카드로 전환한다 ──
     가로 스크롤 컨테이너로 감싸면 th 의 sticky 기준이 뷰포트가 아니라 그 컨테이너가
     되어 헤더 고정이 깨진다. 그래서 감싸지 않고 표 자체를 블록으로 편다. */
  @media (max-width:640px){
    body{padding:14px 12px 36px;font-size:13.5px}
    h1{font-size:19px}
    .meta{font-size:12px}
    .searchbar{padding:11px 11px 9px;border-radius:12px}
    .badges{gap:6px}
    .badge{padding:5px 10px 5px 9px;font-size:12px}
    .sortsel{display:flex;margin-left:0;width:100%}
    .sortsel select{flex:1;min-width:0}
    .maker-name{width:106px;font-size:12px}
    .panel-body{padding:2px 11px 11px}

    .tablecard{border-radius:12px;padding:2px 0}
    table,tbody,tr,td{display:block;width:auto}
    thead{display:none}                      /* 정렬은 .sortsel 로 대체 */
    tbody tr.row{position:relative;padding:11px 13px 12px;border-bottom:1px solid var(--border)}
    tbody tr.row:last-child{border-bottom:0}
    tbody tr.row:hover td{background:transparent}
    tbody tr.row td{border:0;padding:1px 0;display:flex;flex-wrap:wrap;gap:2px 8px;
                    align-items:baseline;min-width:0}
    tbody tr.row td>*{min-width:0;max-width:100%}
    tbody tr.row td::before{content:attr(data-label);flex:0 0 62px;color:var(--muted-2);
                            font-size:10.5px;font-weight:700;letter-spacing:.02em}
    /* 제품명은 카드 제목, 티어칩은 우상단 배지 */
    td.c-name{display:block;padding-right:46px;font-size:14.5px;margin-bottom:5px}
    td.c-name::before{display:none}
    td.c-tier{position:absolute;top:11px;right:13px;padding:0;display:block}
    td.c-tier::before{display:none}
    td.num{text-align:left}
    td.c-sweet{max-width:none;font-size:11.5px}
    tr.fake-zero{background:var(--danger-soft)}
    tr.fake-zero td:first-child{box-shadow:none}
    tr.fake-zero::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
                         background:var(--danger)}
    tr.row.expanded{background:#f4f8fd}
    tr.row.expanded td:first-child{box-shadow:none}
    tr.row.expanded::after{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
                            background:var(--accent)}
    tr.detail td{padding:0}
    tr.detail td::before{display:none}
    tr.empty td{display:block;text-align:center;padding:28px 10px}
    tr.empty td::before{display:none}
    .pg{min-width:32px;height:32px;padding:0 8px;font-size:12px}
    .detail-box{padding:10px 12px;font-size:11.5px}
  }
</style>
</head>
<body>
<div class="page">
<header>
  <h1>제로 탄산음료 티어 리포트</h1>
  <div class="meta">생성 __GENERATED_AT__ · 대상 식품유형 __TYPES__ · 당류 없는 음료와 제로 표기 제품 __TOTAL__개<br><span class="meta-note">설탕이 들어간 일반 음료는 제외했습니다. 단, 제로를 표방하면서 당류가 있는 제품은 F 티어로 남겼습니다.</span></div>
  <section class="searchbar">
    <div class="searchfield">
      <svg class="s-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
      <input type="search" id="q" autocomplete="off" spellcheck="false"
             placeholder="제품명·제조사 검색   예: 밀키스 제로">
      <button type="button" class="s-clear" id="qClear" aria-label="검색어 지우기" hidden>&times;</button>
    </div>
    <div class="searchmeta">
      <span class="count-pill"><b id="shownCount">0</b>개 검색됨</span>
      <span class="hint">행을 누르면 원재료 전문이 열립니다</span>
    </div>
  </section>
  <div class="badges" id="badges">__BADGES__<button class="clear-tiers" id="clearTiers" disabled>전체 해제</button></div>
  <div class="warn" id="fakeZeroBanner">제로 표기 제품 __ZERO_TOTAL__개 중 __FAKE_ZERO__개는 신고 원재료에 당류가 있습니다</div>
  <details class="panel tierlegend" open>
    <summary>티어 기준</summary>
    <div class="panel-body">
      <div class="tier-row"><span class="tier-chip" data-tier="무감미료">무</span><b>무감미료</b><span class="tier-ing">감미료 표기 없음</span><span class="tier-why">신고 원재료에 감미료가 없음. 코카콜라 제로처럼 <b>식품첨가물혼합제제</b>로 뭉뚱그려져 감미료를 확인할 수 없는 제품도 여기 들어가며, 이때는 <b>감미료 미표기</b> 표시가 붙습니다 (열량·당류 0 확인 기준)</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="S">S</span><b>S</b><span class="tier-ing">알룰로스, 타가토스</span><span class="tier-why">0.2~0.4 kcal/g. 식후 혈당을 오히려 낮춤 (2026 AJCN 메타분석)</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="A">A</span><b>A</b><span class="tier-ing">스테비올배당체, 나한과(모그로사이드)</span><span class="tier-why">0 kcal, 혈당 영향 없음, 장기 안전성 양호</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="B">B</span><b>B</b><span class="tier-ing">수크랄로스, 아세설팜칼륨, 아스파탐, 사카린</span><span class="tier-why">0 kcal이나 공복 인슐린·HbA1c 상승 신호 (2026 Tufts 메타분석)</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="C">C</span><b>C</b><span class="tier-ing">에리스리톨, 자일리톨</span><span class="tier-why">혈당은 무해하나 혈소판 반응성·심혈관 사건 신호 (Cleveland Clinic). 인과관계는 확정되지 않음</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="D">D</span><b>D</b><span class="tier-ing">말티톨, 소르비톨, 락티톨 등 당알코올</span><span class="tier-why">실제 2~2.6 kcal/g, 말티톨은 GI 35~52로 혈당 상승</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="F">F</span><b>F</b><span class="tier-ing">설탕, 액상과당, 농축과즙 등</span><span class="tier-why">제로를 표방하지만 신고 원재료에 당류가 있음</span></div>
      <div class="tier-note">한 제품에 여러 감미료가 있으면 가장 나쁜 등급이 최종 티어가 됩니다. 전체 구성은 '조합' 열에서 볼 수 있습니다.<br>이 리포트는 <b>당류가 없는 음료</b>와 <b>제로를 표방한 제품</b>만 다룹니다. 제로 표기가 없는 일반 당류 음료는 수집 대상에서 제외됩니다.<br>원재료에 농축과즙·올리고당이 <b>착향 목적으로 미량</b> 들어간 경우, 실측 당류가 0g이면 F로 보지 않습니다. 반대로 감미료가 표기되지 않아도 당류가 검출되면 F입니다.</div>
    </div>
  </details>
  <details class="panel makers">
    <summary>제조사별 제로 제품 티어 분포 (상위 15)</summary>
    <div class="panel-body"><div id="makerList"></div></div>
  </details>
</header>
<div class="toolbar">
  <div class="chks">
    <label class="chk"><input type="checkbox" id="fFake"> 제로사칭만</label>
    <label class="chk" title="제품명에 제로 표기가 없지만 신고 영양성분상 100ml당 4kcal 미만인 제품. 실제로는 제로인데 이름으로 알리지 않습니다."><input type="checkbox" id="fHidden"> 숨은 제로</label>
    <label class="chk"><input type="checkbox" id="fAllulose"> 알룰로스 함유</label>
    <label class="chk"><input type="checkbox" id="fErythritol"> 에리스리톨 함유</label>
    <label class="chk"><input type="checkbox" id="fNoCaffeine"> 카페인 없음</label>
    <label class="chk"><input type="checkbox" id="fNoAspartame"> 아스파탐 없음</label>
    <label class="chk"><input type="checkbox" id="fHasKcal"> 열량 데이터 있음</label>
  </div>
  <label class="sortsel">정렬
    <select id="sortSel">
      <option value="티어">티어</option><option value="조합">조합</option>
      <option value="제품명">제품명</option><option value="업소명">업소명</option>
      <option value="보고일자">보고일자</option><option value="열량">열량</option>
      <option value="당류">당류</option><option value="용량">용량</option>
      <option value="감미료">감미료</option>
    </select>
    <button type="button" id="sortDir" aria-label="정렬 방향 전환">&#9650;</button>
  </label>
</div>
<div class="tablecard">
<table id="tbl">
  <thead><tr>
    <th data-key="티어">티어</th><th data-key="조합">조합</th><th data-key="제품명">제품명</th>
    <th data-key="업소명">업소명</th><th data-key="보고일자">보고일자</th>
    <th data-key="열량">열량<span class="th-unit">100mL당</span></th><th data-key="당류">당류<span class="th-unit">100mL당</span></th><th data-key="용량">용량</th>
    <th data-key="감미료">감미료</th>
  </tr></thead>
  <tbody id="tbody"></tbody>
</table>
</div>
<nav class="pager" id="pager" aria-label="페이지 이동"></nav>
__GUIDES__
__FAQ_HTML__
<footer>
  <div>출처: 식품의약품안전처 C002 품목제조보고(원재료). 표시된 배합은 각 제품의 최신 보고일자 기준이며 배합은 자주 바뀝니다.</div>
  <div>열량·당류: 전국통합식품영양성분정보(가공식품) 표준데이터(공공데이터포털 15100066). <b>표의 값은 100mL(또는 100g)당</b>이며 한 병·한 캔 전체 값이 아닙니다 — 제품 라벨은 전체 기준으로 적혀 있어 숫자가 달라 보입니다. 행을 누르면 전체 기준 환산값을 함께 보여줍니다. 품목제조보고번호로 조인되지 않은 제품은 공란이며 0을 의미하지 않습니다.</div>
  <div>C 티어 근거인 에리스리톨의 심혈관 사건 신호는 관찰 연구에서 제기된 것으로 인과관계가 확정되지 않았습니다.</div>
  <div>방문 통계를 위해 Google Analytics(GA4)를 사용합니다. 쿠키로 익명 식별자가 저장될 수 있습니다.</div>
  <div>'제로 사칭'은 제품명에 제로 표기가 있으면서 신고 원재료에 당류가 포함된 경우를 가리킵니다. 제조사의 표시 기준 위반을 뜻하지 않습니다 — 제로칼로리 표기 기준은 100ml당 4kcal 미만이며, 소량의 당류로도 이를 충족할 수 있습니다.</div>
</footer>
</div>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
// 클릭마다 DATA를 선형 탐색하지 않도록 제품명 -> 레코드 조회용 Map을 한 번만 만든다.
// canonicalize()가 제품명을 그룹 키로 쓰므로 고유하다.
const BY_NAME = new Map(DATA.map(function(r) { return [r['제품명'], r]; }));
const RANK = __RANK_JSON__;
const MAKERS = __MAKERS_JSON__;
const TIER_COLORS = {"무감미료":"#4caf50","S":"#8bc34a","A":"#cddc39","B":"#ffc107","C":"#ff9800","D":"#f4511e","F":"#c00","?":"#999"};

// PAGE_SIZE: 1,699행을 한 번에 그리면 표 높이가 11만 px가 되어 강제 레이아웃에만
// 216ms가 든다(실측). 한 페이지 분량만 그린다.
const PAGE_SIZE = 50;
let state = { q: "", qz: "", fFake:false, fHidden:false, fAllulose:false, fErythritol:false, fNoCaffeine:false, fNoAspartame:false, fHasKcal:false,
              tierFilters: new Set(), sortKey: "티어", sortDir: 1, expanded: new Set(), page: 1 };

// 공백·하이픈·가운뎃점류를 지운다. 산출 쪽 norm_name() 과 같은 기준이라
// `코카·콜라 제로`로 검색해도 `코카콜라 제로`가 잡힌다.
function norm(s) { return (s||"").replace(/[\s\-_·ㆍ•●‧∙⋅]/g, "").toLowerCase(); }

// 품목제조보고에 등록된 이름은 유통명이 아니다. 실제로는 `나랑드 사이다 제로`로
// 팔리는 제품이 `나랑드사이다`로 신고돼 있다. 그래서 검색어에서 제로 표기를
// 떼고 한 번 더 맞춰보되, 실제로 제로인 제품에만 허용한다 - 그러지 않으면
// `킨사이다 제로`로 검색했을 때 설탕이 든 `킨사이다`가 잡힌다.
function dropZero(s) { return s.replace(/제로|zero|0kcal/g, ""); }

function renderMakers() {
  const el = document.getElementById('makerList');
  el.innerHTML = MAKERS.map(function(entry) {
    const name = entry[0], tiers = entry[1];
    const total = Object.values(tiers).reduce(function(a,b){return a+b;}, 0);
    const bars = Object.entries(tiers).sort(function(a,b){return (RANK[a[0]] ?? 99)-(RANK[b[0]] ?? 99);})
      .map(function(kv){
        const t = kv[0], c = kv[1];
        return '<span style="width:' + (c/total*100) + '%;background:' + (TIER_COLORS[t]||'#ccc') + '" title="' + t + ':' + c + '"></span>';
      }).join('');
    return '<div class="maker-row"><div class="maker-name">' + name + ' (' + total + ')</div><div class="maker-bar">' + bars + '</div></div>';
  }).join('');
}

function filtered() {
  return DATA.filter(function(r) {
    if (state.tierFilters.size && !state.tierFilters.has(r['티어'])) return false;
    if (state.q) {
      const hay = norm(r['제품명']) + '\u0000' + norm(r['업소명']);
      if (!hay.includes(state.q)) {
        const isZero = r['실측제로'] === 'Y' || r['제로표기'] === 'Y';
        if (!isZero || state.qz.length < 2 || !dropZero(hay).includes(state.qz)) return false;
      }
    }
    if (state.fFake && r['제로사칭'] !== 'Y') return false;
    if (state.fHidden && !(r['제로표기'] !== 'Y' && r['실측제로'] === 'Y')) return false;
    if (state.fAllulose && !(r['조합']||'').split('+').includes('S')) return false;
    if (state.fErythritol && !(r['감미료']||'').includes('에리스')) return false;
    if (state.fNoCaffeine && r['카페인'] === 'Y') return false;
    if (state.fNoAspartame && r['아스파탐'] === 'Y') return false;
    if (state.fHasKcal && !r['열량']) return false;
    return true;
  });
}

function sortedRows(rows) {
  const key = state.sortKey, dir = state.sortDir;
  const numeric = key === '열량' || key === '당류';
  return rows.slice().sort(function(a,b) {
    let av = a[key], bv = b[key];
    if (key === '티어') { av = RANK[av] ?? 99; bv = RANK[bv] ?? 99; }
    else if (numeric) { av = parseFloat(av); if (isNaN(av)) av = -Infinity; bv = parseFloat(bv); if (isNaN(bv)) bv = -Infinity; }
    if (av < bv) return -1*dir;
    if (av > bv) return 1*dir;
    return 0;
  });
}

function escapeHtml(s) {
  // 따옴표까지 이스케이프해야 한다. 제품명에 " 가 들어간 제품이 실재하고
  // (예: "A+Live" 홍삼에너지 드링크), 빠뜨리면 data-name 속성이 깨져
  // 행 클릭 확장이 동작하지 않는다.
  return (s===undefined||s===null?'':String(s))
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function tierChip(t) {
  const v = escapeHtml(t);
  return '<span class="tier-chip" data-tier="' + v + '">' + (v === '무감미료' ? '무' : v) + '</span>';
}
function comboChips(c) {
  if (!c || c === '-') return '<span class="na">\u2014</span>';
  return c.split('+').map(function(p){ return tierChip(p.trim()); }).join('<span class="combo-plus">+</span>');
}

function rowHtml(r) {
  const cls = ['row']; if (r['제로사칭']==='Y') cls.push('fake-zero'); if (state.expanded.has(r['제품명'])) cls.push('expanded');
  const chips = (r['실측제로']==='Y' && r['제로표기']==='N' ? '<span class="chip ok-chip" title="제품명에 제로 표기가 없지만 신고 영양성분상 100ml당 4kcal 미만입니다. 식약처 기준으로 제로칼로리에 해당합니다.">0kcal 확인</span>':'')
    + (r['감미료미표기']==='Y' ? '<span class="chip warn-chip" title="신고 원재료가 식품첨가물혼합제제 등으로 뭉뚱그려져 어떤 감미료를 썼는지 확인할 수 없습니다. 티어는 열량·당류 실측으로 배치했습니다.">감미료 미표기</span>':'')
    + (r['카페인']==='Y' ? '<span class="chip">카페인</span>':'') + (r['아스파탐']==='Y' ? '<span class="chip">아스파탐</span>':'');
  const na = function(v){ return v ? escapeHtml(v) : '<span class="na">\u2014</span>'; };
  return '<tr class="' + cls.join(' ') + '" data-name="' + escapeHtml(r['제품명']) + '">' +
    '<td class="c-tier">' + tierChip(r['티어']) + '</td>' +
    '<td class="c-combo" data-label="조합">' + comboChips(r['조합']) + '</td>' +
    '<td class="c-name"><span class="pname">' + escapeHtml(r['제품명']) + '</span>' + chips + '</td>' +
    '<td class="c-maker" data-label="업소명">' + escapeHtml(r['업소명']) + '</td>' +
    '<td class="c-date" data-label="보고일자">' + na(r['보고일자']) + '</td>' +
    '<td class="num" data-label="열량">' + na(r['열량']) + '</td>' +
    '<td class="num" data-label="당류">' + na(r['당류']) + '</td>' +
    '<td class="c-vol" data-label="용량">' + na(r['용량']) + '</td>' +
    '<td class="c-sweet" data-label="감미료">' + na(r['감미료']) + '</td></tr>';
}

function detailHtml(r) {
  let extra = '';
  // 표의 열량·당류는 100mL 당 값이다. 라벨은 한 병 전체를 적으므로 헷갈린다.
  // 용량을 알면 전체 기준으로 환산해 같이 보여준다 (계산값임을 밝힌다).
  if (r['열량'] !== '' && r['열량'] != null) {
    const base = r['기준량'] || '100ml';
    let line = '열량 ' + escapeHtml(String(r['열량'])) + ' kcal / ' + escapeHtml(base);
    if (r['당류'] !== '' && r['당류'] != null) line += ' \u00b7 당류 ' + escapeHtml(String(r['당류'])) + ' g / ' + escapeHtml(base);
    const vol = parseFloat(String(r['용량'] || '').replace(/[^\d.]/g, ''));
    const kcal = parseFloat(r['열량']);
    if (isFinite(vol) && vol > 0 && isFinite(kcal)) {
      line += ' \u2192 ' + escapeHtml(String(r['용량'])) + ' 한 개 약 ' + Math.round(kcal * vol / 100) + ' kcal (계산값)';
    }
    extra += '<div>' + line + '</div>';
  }
  if (r['표시원재료']) {
    // C002 원재료가 혼합제제로 가려진 제품이다. 무엇으로 판정했는지 그대로 보여준다.
    extra += '<div><b>표시 원재료</b> (' +
             (r['유통명출처'] ? '<a href="' + escapeHtml(r['유통명출처']) + '" target="_blank" rel="noopener">상품정보제공 고시</a>' : '고시') +
             '): ' + escapeHtml(r['표시원재료']) + '</div>' +
             '<div>위 신고 원재료는 식품첨가물혼합제제로 뭉뚱그려져 감미료가 보이지 않습니다. 티어는 고시 표시 원재료로 판정했습니다.</div>';
  }
  if (r['카페인수동'] === 'Y') {
    // 신고 원재료에 카페인이 안 보이는 제품이다. 손으로 판단했음을 숨기지 않는다.
    extra += '<div>카페인 유무는 신고 원재료가 혼합제제로 뭉뚱그려져 확인할 수 없어, 널리 알려진 제품 정보를 근거로 <b>손으로 표시</b>했습니다. 함량은 다루지 않습니다.</div>';
  }
  if (r['등록명']) {
    // 표시한 이름이 품목제조보고 등록명과 다르면 반드시 출처를 함께 밝힌다.
    extra += '<div>품목제조보고 등록명: ' + escapeHtml(r['등록명']) +
             (r['유통명출처'] ? ' \u00b7 유통명 출처: <a href="' + escapeHtml(r['유통명출처']) +
                              '" target="_blank" rel="noopener">제조사 공식몰 상품정보제공 고시</a>' : '') +
             '</div>';
  }
  if (r['일반판']) extra += '<div>일반판 대비: ' + escapeHtml(r['일반판']) + ' [' + escapeHtml(r['일반판티어']) + '] \u2192 [' + escapeHtml(r['티어']) + ']</div>';
  if (r['배합변경'] === 'Y') {
    extra += '<div>배합 이력:</div>' + (r['이력']||[]).map(function(h){
      return '<div>&nbsp;&nbsp;' + escapeHtml(h['보고일자']) + ' \u00b7 ' + escapeHtml(h['보고번호']) + ' \u00b7 ' + escapeHtml(h['원재료전문']) + '</div>';
    }).join('');
  }
  return '<tr class="detail"><td colspan="9"><div class="detail-cell"><div class="detail-box">' +
         '<div class="detail-raw">' + escapeHtml(r['원재료전문']) + '</div>' + extra + '</div></div></td></tr>';
}

function pagerHtml(total, page, pages) {
  if (pages <= 1) return '';
  const btn = function(p, label, cls) {
    if (p === page) return '<button class="pg cur" disabled>' + label + '</button>';
    if (p < 1 || p > pages) return '<button class="pg" disabled>' + label + '</button>';
    return '<button class="pg' + (cls ? ' ' + cls : '') + '" data-page="' + p + '">' + label + '</button>';
  };
  // 현재 페이지 주변 최대 5개만 노출한다. 34페이지를 전부 그리면 모바일에서 넘친다.
  let start = Math.max(1, page - 2);
  let end = Math.min(pages, start + 4);
  start = Math.max(1, Math.min(start, end - 4));

  let out = '<div class="pager-btns">' + btn(page - 1, '\u2039 이전');
  if (start > 1) {
    out += btn(1, '1');
    if (start > 2) out += '<span class="pg-gap">\u2026</span>';
  }
  for (let p = start; p <= end; p++) out += btn(p, String(p));
  if (end < pages) {
    if (end < pages - 1) out += '<span class="pg-gap">\u2026</span>';
    out += btn(pages, String(pages));
  }
  out += btn(page + 1, '다음 \u203a') + '</div>';

  const from = (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);
  out += '<div class="pager-info">' + from.toLocaleString() + '\u2013' + to.toLocaleString() +
         ' / ' + total.toLocaleString() + '개 · ' + page + '/' + pages + ' 페이지</div>';
  return out;
}

function render() {
  const rows = sortedRows(filtered());
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (state.page > pages) state.page = pages;
  if (state.page < 1) state.page = 1;

  const begin = (state.page - 1) * PAGE_SIZE;
  const slice = rows.slice(begin, begin + PAGE_SIZE);
  let html = '';
  slice.forEach(function(r) {
    html += rowHtml(r);
    if (state.expanded.has(r['제품명'])) html += detailHtml(r);
  });
  if (!slice.length) {
    html = '<tr class="empty"><td colspan="9">조건에 맞는 제품이 없습니다.</td></tr>';
  }
  document.getElementById('tbody').innerHTML = html;
  document.getElementById('pager').innerHTML = pagerHtml(rows.length, state.page, pages);

  document.querySelectorAll('#badges .badge').forEach(function(b) {
    b.classList.toggle('active', state.tierFilters.has(b.dataset.tier));
  });
  document.getElementById('clearTiers').disabled = state.tierFilters.size === 0;
  document.getElementById('shownCount').textContent = rows.length.toLocaleString();
  document.getElementById('qClear').hidden = !document.getElementById('q').value;
  document.getElementById('sortSel').value = state.sortKey;
  document.getElementById('sortDir').textContent = state.sortDir === 1 ? '\u25b2' : '\u25bc';
  document.querySelectorAll('th[data-key]').forEach(function(th) {
    th.classList.toggle('sorted', th.dataset.key === state.sortKey);
    th.setAttribute('data-dir', state.sortDir === 1 ? '\u25b2' : '\u25bc');
  });
}

function goPage(p) {
  state.page = p;
  render();
  const card = document.querySelector('.tablecard');
  const top = card.getBoundingClientRect().top + window.scrollY - 12;
  window.scrollTo({top: top, behavior: 'smooth'});
}

// 필터·검색·정렬이 바뀌면 1페이지로 돌아간다. 행 펼치기는 페이지를 유지한다.
function update() {
  state.page = 1;
  render();
}

document.getElementById('pager').addEventListener('click', function(e) {
  const b = e.target.closest('button[data-page]');
  if (b) goPage(parseInt(b.dataset.page, 10));
});

document.getElementById('tbody').addEventListener('click', function(e) {
  const tr = e.target.closest('tr.row');
  if (!tr) return;
  const nm = tr.getAttribute('data-name');
  const next = tr.nextElementSibling;
  const anchor = tr.getBoundingClientRect().top;

  if (next && next.classList.contains('detail')) {
    // 접기: 상세 행만 제거한다. tbody 전체를 다시 그리지 않는다.
    next.remove();
    tr.classList.remove('expanded');
    state.expanded.delete(nm);
    const delta = tr.getBoundingClientRect().top - anchor;
    if (delta) window.scrollBy(0, delta);
    return;
  }

  // 펼치기: 상세 행을 클릭한 행 바로 뒤에만 삽입한다.
  const r = BY_NAME.get(nm);
  if (!r) return;
  tr.insertAdjacentHTML('afterend', detailHtml(r));
  tr.classList.add('expanded');
  state.expanded.add(nm);

  // 클릭한 행이 삽입 전후로 화면에서 움직이지 않도록 보정한다
  // (sticky 헤더·마진 상쇄·모바일 카드 레이아웃 때문에 이론과 다르게 어긋날 수 있다).
  const delta = tr.getBoundingClientRect().top - anchor;
  if (delta) window.scrollBy(0, delta);

  // 펼친 상세가 화면 아래로 넘치면 넘친 만큼만 스크롤한다. 중앙 정렬은 그 자체가
  // 큰 점프라 쓰지 않는다. tr이 화면 위로 밀려나거나 sticky 헤더 밑으로 들어가지
  // 않는 한도 안에서만 움직인다.
  const detail = tr.nextElementSibling;
  const overflow = detail.getBoundingClientRect().bottom - window.innerHeight;
  if (overflow > 0) {
    const theadEl = document.querySelector('table thead');
    const safeTop = (theadEl && theadEl.offsetParent) ? theadEl.getBoundingClientRect().bottom : 0;
    const headroom = Math.max(0, tr.getBoundingClientRect().top - safeTop);
    const scrollAmt = Math.min(overflow, headroom);
    if (scrollAmt > 0) window.scrollBy({top: scrollAmt, behavior: 'smooth'});
  }
});

document.getElementById('q').addEventListener('input', function(e) {
  state.q = norm(e.target.value); state.qz = dropZero(state.q); update();
});
document.getElementById('qClear').addEventListener('click', function() {
  const q = document.getElementById('q');
  q.value = ''; state.q = ''; state.qz = ''; q.focus(); update();
});
document.getElementById('sortSel').addEventListener('change', function(e) {
  state.sortKey = e.target.value; state.sortDir = 1; update();
});
document.getElementById('sortDir').addEventListener('click', function() {
  state.sortDir *= -1; update();
});
document.getElementById('fFake').addEventListener('change', function(e) { state.fFake = e.target.checked; update(); });
document.getElementById('fHidden').addEventListener('change', function(e) { state.fHidden = e.target.checked; update(); });
document.getElementById('fAllulose').addEventListener('change', function(e) { state.fAllulose = e.target.checked; update(); });
document.getElementById('fErythritol').addEventListener('change', function(e) { state.fErythritol = e.target.checked; update(); });
document.getElementById('fNoCaffeine').addEventListener('change', function(e) { state.fNoCaffeine = e.target.checked; update(); });
document.getElementById('fNoAspartame').addEventListener('change', function(e) { state.fNoAspartame = e.target.checked; update(); });
document.getElementById('fHasKcal').addEventListener('change', function(e) { state.fHasKcal = e.target.checked; update(); });
document.getElementById('fakeZeroBanner').addEventListener('click', function() {
  state.fFake = !state.fFake;
  document.getElementById('fFake').checked = state.fFake;   // 체크박스 표시도 함께 맞춘다
  update();
});
document.getElementById('badges').addEventListener('click', function(e) {
  const t = e.target.closest('.badge'); if (!t) return;
  state.tierFilters.has(t.dataset.tier) ? state.tierFilters.delete(t.dataset.tier) : state.tierFilters.add(t.dataset.tier);
  update();
});
document.getElementById('clearTiers').addEventListener('click', function() {
  state.tierFilters.clear(); update();
});
document.querySelectorAll('th[data-key]').forEach(function(th) {
  th.addEventListener('click', function() {
    if (state.sortKey === th.dataset.key) state.sortDir *= -1;
    else { state.sortKey = th.dataset.key; state.sortDir = 1; }
    update();
  });
});

renderMakers();
render();
</script>
</body>
</html>
"""


def write_html(records, meta, meta_info, path):
    payload = [{
        "티어": r["티어"], "조합": r["조합"], "제품명": r["제품명"],
        "식품유형": r["식품유형"], "업소명": r["업소명"], "보고일자": r["보고일자"],
        "감미료": r["감미료"], "열량": r["열량"], "기준량": r["기준량"],
        "당류": r["당류"], "용량": r["용량"], "이력행수": r["이력행수"],
        "배합변경": r["배합변경"], "티어불일치": r["티어불일치"],
        "감미료미표기": r["감미료미표기"],
        "원재료전문": r["원재료전문"], "제로표기": r["제로표기"], "실측제로": r["실측제로"],
        "등록명": r["등록명"], "유통명출처": r["유통명출처"],
        "표시원재료": r["표시원재료"],
        "제로사칭": r["제로사칭"], "카페인": r["카페인"], "카페인수동": r.get("카페인수동", ""), "아스파탐": r["아스파탐"],
        "일반판": r["일반판"], "일반판티어": r["일반판티어"], "이력": r["이력"],
    } for r in records]

    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    rank_json = json.dumps(TIER_RANK, ensure_ascii=False)
    makers_json = json.dumps(meta.get("제조사", []), ensure_ascii=False).replace("</", "<\\/")

    tier_counts = {}
    for r in records:
        tier_counts[r["티어"]] = tier_counts.get(r["티어"], 0) + 1
    badge_order = ["무감미료", "S", "A", "B", "C", "D", "F", "?"]
    badges_html = "".join(
        f'<button class="badge" data-tier="{t}">'
        f'<span class="dot"></span>{t}<span class="cnt">{tier_counts.get(t, 0)}</span>'
        f'</button>'
        for t in badge_order if tier_counts.get(t)
    )

    zero_total = sum(1 for r in records if r["제로표기"] == "Y")
    fake_zero = sum(1 for r in records if r["제로사칭"] == "Y")

    html = _HTML_TEMPLATE
    html = html.replace("__GENERATED_AT__", meta_info["generated_at"])
    html = html.replace("__TYPES__", ", ".join(meta_info["types"]) or "-")
    html = html.replace("__TOTAL__", str(len(records)))
    html = html.replace("__PAGE_URL__", PAGE_URL)
    html = html.replace("__FAVICON__", _FAVICON_HTML)

    # 질문별 정적 목록으로 가는 링크. 크롤러의 탐색 경로이자 사용자 진입점이다.
    guides = [
        ("products.html", f"{len(records)}개 전체 목록", "무JS 정적 표. 티어·감미료·열량 한눈에"),
        ("allulose.html", "알룰로스 쓰는 제로 음료", "가장 높은 S 등급 감미료를 쓴 제품"),
        ("no-aspartame.html", "아스파탐 없는 제로 음료", "신고 원재료에 아스파탐이 없는 제품"),
        ("no-erythritol.html", "에리스리톨 없는 제로 음료", "심혈관 신호 연구를 피하고 싶을 때"),
        ("no-caffeine.html", "카페인 없는 제로 음료", "콜라·에너지드링크 계열 제외"),
        ("fake-zero.html", "제로라면서 당류가 있는 음료", "표기와 신고 원재료의 불일치"),
        ("hidden-zero.html", "이름에 제로가 없는데 0kcal", "이름만 보면 놓치는 제품"),
    ]
    guides_html = (
        '<section class="guides">\n<h2>질문별로 골라 보기</h2>\n<ul>\n'
        + "".join(f'<li><a href="{PAGE_URL}{slug}"><b>{title}</b><span>{note}</span></a></li>\n'
                  for slug, title, note in guides)
        + "</ul>\n</section>")
    html = html.replace("__GUIDES__", guides_html)

    # 가시 FAQ 와 FAQPage LD 를 같은 _FAQ 에서 만든다 — 글자가 어긋나면 스팸 판정 위험.
    faq_html = ('<section class="faq">\n<h2>자주 묻는 질문</h2>\n'
                + "".join(f"<details><summary>{q}</summary><p>{a}</p></details>\n"
                          for q, a in _FAQ)
                + "</section>")
    html = html.replace("__FAQ_HTML__", faq_html)

    faq_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in _FAQ
        ],
    }
    html = html.replace("__FAQ_LD__", '<script type="application/ld+json">'
                        + json.dumps(faq_ld, ensure_ascii=False, indent=1) + "</script>")
    html = html.replace("__GA__", _GA_SNIPPET.replace("__GA_ID__", GA_ID) if GA_ID else "")
    html = html.replace("__GENERATED_DATE__", meta_info["generated_at"][:10])
    html = html.replace("__BADGES__", badges_html)
    html = html.replace("__ZERO_TOTAL__", str(zero_total))
    html = html.replace("__FAKE_ZERO__", str(fake_zero))
    html = html.replace("__DATA_JSON__", data_json)
    html = html.replace("__RANK_JSON__", rank_json)
    html = html.replace("__MAKERS_JSON__", makers_json)

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# ── build ─────────────────────────────────────────────────────
def build(raw_path, cache_path, out_csv, out_html, find_text, keep_alcohol=False,
          keep_sugar=False, enrich_cache=DEFAULT_ENRICH_CACHE, keep_discontinued=False):
    rows, types = load_raw_full(raw_path)

    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            nutrition = json.load(f).get("rows", {})
    else:
        nutrition = {}
        print("[build] 영양 캐시가 없습니다. 열량/당류는 공란으로 채웁니다. "
              "(--mode nutrition 을 먼저 실행하면 채울 수 있습니다)")


    discontinued, _checked = load_enrich_cache(enrich_cache)
    labels = load_labels()
    if labels:
        print(f"[build] 공식몰 고시에서 확인된 유통명 {len(labels):,}건 반영")
    records = canonicalize(rows, nutrition, discontinued, labels)
    if not keep_discontinued:
        before = len(records)
        records = [r for r in records if not r["생산중단일"]]
        if before != len(records):
            print(f"[build] 생산중단 제품 {before - len(records)}건 제외 "
                  f"(--keep-discontinued 로 유지 가능)")
    excluded = 0
    if not keep_alcohol:
        before = len(records)
        records = [r for r in records
                   if r["식품유형"] not in NON_BEVERAGE_TYPES
                   and not is_alcoholic(r["제품명"], r["원재료전문"])]
        excluded = before - len(records)
        print(f"[build] 주류·비음료 {excluded}건 제외 "
              f"(--keep-alcohol 로 유지 가능)")
    meta = annotate(records)

    # 이 리포트는 '제로 음료' 티어다. 설탕이 든 데다 제로 표기도 없는 제품은
    # 애초에 대상이 아니다. 제로 표기가 있는 F 티어(= 제로 사칭)만 남긴다.
    #
    # annotate() 를 다시 부르지 않는 이유: 제로↔일반판 짝의 '일반판'이 바로 여기서
    # 지워지는 당류 음료라, 재실행하면 짝이 전부 사라진다. 제조사 집계도 이미
    # 제로 표기 제품만 세므로 이 제외의 영향을 받지 않는다.
    sugar_dropped = 0
    if not keep_sugar:
        before = len(records)
        # 남기는 기준:
        #  - 대체당이 탐지된 제품(S/A/B/C/D) → 감미료가 궁금한 대상이므로 이름과 무관하게 유지
        #  - 그 외(F·무감미료·?) → 제로를 표방한 경우에만 유지
        #    탄산수·일반 음료는 애초에 '어떤 대체당이 들었나' 묻는 대상이 아니다.
        records = [r for r in records
                   if r["티어"] not in ("F", "무감미료") or r["제로표기"] == "Y"]
        sugar_dropped = before - len(records)
        print(f"[build] 제로 표기 없는 일반 음료 {sugar_dropped}건 제외 "
              f"(--keep-sugar 로 유지 가능)")

    records.sort(key=lambda r: (TIER_RANK.get(r["티어"], 99), r["제품명"]))

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    meta_info = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "types": types or sorted({r["식품유형"] for r in records if r["식품유형"]}),
    }
    write_html(records, meta, meta_info, out_html)

    print(f"\n완료: {len(records):,}개 제품 -> {out_csv}, {out_html}")
    if records:
        counts = {}
        for r in records:
            counts[r["티어"]] = counts.get(r["티어"], 0) + 1
        print("티어 분포:", ", ".join(
            f"{k}:{v}" for k, v in sorted(counts.items(), key=lambda kv: TIER_RANK.get(kv[0], 99))))
        changed = sum(1 for r in records if r["배합변경"] == "Y")
        mismatch = sum(1 for r in records if r["티어불일치"] == "Y")
        with_kcal = sum(1 for r in records if r["열량"])
        print(f"배합변경 Y: {changed}건 · 티어불일치 Y: {mismatch}건 · "
              f"영양 조인: {with_kcal}/{len(records)} ({with_kcal / len(records):.0%})")
        print('열량은 품목제조보고번호로 조인된 제품만 표시됩니다. '
              '공란은 "0"이 아니라 "데이터 없음"입니다.')

    tops = [r for r in records if TIER_RANK.get(r["티어"], 99) <= 2]
    if tops:
        print(f"\n── 무감미료/S/A 후보 {len(tops)}건 (상위 30) ──")
        for r in tops[:30]:
            print(f"  [{r['티어']}] {r['제품명']} / {r['업소명']} / {r['감미료']}")

    if meta.get("제조사"):
        print(f"\n── 제조사별 제로 제품 티어 분포 상위 {min(15, len(meta['제조사']))} ──")
        for name, tiers in meta["제조사"]:
            tier_str = ", ".join(
                f"{t}{c}" for t, c in sorted(tiers.items(), key=lambda kv: TIER_RANK.get(kv[0], 99)))
            print(f"  {name}: {tier_str}")

    if find_text:
        find_products(records, find_text)

    tier_counts = {}
    for r in records:
        tier_counts[r["티어"]] = tier_counts.get(r["티어"], 0) + 1
    return {
        "records": records,
        "raw_rows": len(rows),
        "excluded": excluded,
        "sugar_dropped": sugar_dropped,
        "total": len(records),
        "tier_counts": tier_counts,
        "with_kcal": sum(1 for r in records if r["열량"]),
        "zero_total": sum(1 for r in records if r["제로표기"] == "Y"),
        "fake_zero": sum(1 for r in records if r["제로사칭"] == "Y"),
        "recipe_changed": sum(1 for r in records if r["배합변경"] == "Y"),
        "paired": sum(1 for r in records if r["일반판"]),
        "generated_at": meta_info["generated_at"],
    }


# ── Step 7-a: --find ─────────────────────────────────────────
def find_products(records, text):
    q = text.replace(" ", "").lower()
    hits = [r for r in records
            if q in r["제품명"].replace(" ", "").lower()
            or q in r["업소명"].replace(" ", "").lower()]
    if not hits:
        print(f"\n'{text}'에 해당하는 제품이 없습니다. (총 {len(records):,}개 제품 중 검색)")
        return
    shown = hits[:20]
    print(f"\n=== '{text}' 검색 결과 {len(hits)}건 ===")
    for r in shown:
        print(f"\n[{r['티어']}] {r['제품명']}  (조합 {r['조합']})")
        print(f"  업소   {r['업소명']}")
        print(f"  보고   {r['보고일자']} (이력 {r['이력행수']}건, 배합변경 {r['배합변경'] or 'N'})")
        if r["열량"]:
            print(f"  열량   {r['열량']} kcal / {r['기준량']} · 당류 {r['당류']} g · 용량 {r['용량']}")
        else:
            print("  열량   데이터 없음 (영양DB 미조인)")
        print(f"  감미료 {r['감미료'] or '-'}")
        flags = [
            "카페인 있음" if r["카페인"] == "Y" else "카페인 없음",
            "아스파탐 있음" if r["아스파탐"] == "Y" else "아스파탐 없음",
        ]
        print(f"  플래그 {' · '.join(flags)}")
        if r["일반판"]:
            print(f"  대비   {r['일반판']} [{r['일반판티어']}] -> [{r['티어']}]")
        print(f"  원재료 {r['원재료전문']}")
    if len(hits) > 20:
        print(f"\n... 외 {len(hits) - 20}건")


# ── Step 7-b: diff ───────────────────────────────────────────
def diff_mode(raw_path, diff_against):
    if not os.path.exists(diff_against):
        raise SystemExit(f"이전 스냅샷 파일이 없습니다: {diff_against}")

    cur_records = canonicalize(load_raw(raw_path), {})
    cur_records = [r for r in cur_records
                    if r["식품유형"] not in NON_BEVERAGE_TYPES
                    and not is_alcoholic(r["제품명"], r["원재료전문"])]
    annotate(cur_records)
    prev_records = canonicalize(load_raw(diff_against), {})
    prev_records = [r for r in prev_records
                     if r["식품유형"] not in NON_BEVERAGE_TYPES
                     and not is_alcoholic(r["제품명"], r["원재료전문"])]
    annotate(prev_records)

    cur_by_name = {r["제품명"]: r for r in cur_records}
    prev_by_name = {r["제품명"]: r for r in prev_records}

    new_names = sorted(set(cur_by_name) - set(prev_by_name))
    gone_names = sorted(set(prev_by_name) - set(cur_by_name))
    common = sorted(set(cur_by_name) & set(prev_by_name))
    changed = [(n, prev_by_name[n], cur_by_name[n]) for n in common
               if prev_by_name[n]["원재료전문"] != cur_by_name[n]["원재료전문"]]

    print(f"신규 제품 {len(new_names)}건")
    for n in new_names:
        r = cur_by_name[n]
        print(f"  [{r['티어']}] {n} / {r['업소명']}")

    print(f"\n배합 변경 {len(changed)}건")
    for n, prev, cur in changed:
        star = " ★" if prev["티어"] != cur["티어"] else ""
        print(f"  {n} / {cur['업소명']}{star}")
        print(f"    이전 {prev['보고일자']}: {prev['원재료전문']}")
        print(f"    현행 {cur['보고일자']}: {cur['원재료전문']}")
        print(f"    티어 {prev['티어']} -> {cur['티어']}")

    print(f"\n사라진 제품 {len(gone_names)}건")
    for n in gone_names:
        r = prev_by_name[n]
        print(f"  [{r['티어']}] {n} / {r['업소명']}")


# ── Step 8: 월간 증분 동기화 ─────────────────────────────────
README_PATH = "README.md"
STATS_START = "<!-- STATS:START -->"
STATS_END = "<!-- STATS:END -->"


def diff_raw(old_rows, new_rows):
    """보고번호 기준 added/changed/removed 판정. 보고번호는 행당 고유하다."""
    def index(rows):
        return {pick(r, FIELD_REPORT_NO): r for r in rows if pick(r, FIELD_REPORT_NO)}

    old, new = index(old_rows), index(new_rows)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(no for no in set(old) & set(new) if old[no] != new[no])
    return added, changed, removed


def render_stats_block(stats, fetched_at):
    total = stats["total"]
    tc = stats["tier_counts"]
    order = ["무감미료", "S", "A", "B", "C", "D", "F"]
    kcal_pct = stats["with_kcal"] / total * 100 if total else 0

    s_rows = sorted((r for r in stats["records"] if r["티어"] == "S"),
                    key=lambda r: r["보고일자"], reverse=True)

    def d(s):
        s = (s or "").strip()
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else (s or "—")

    lines = [
        STATS_START,
        f"`{d(fetched_at)}` 수집 · `{stats['generated_at'][:10]}` 산출 기준 "
        f"— 매월 `--mode sync`로 갱신",
        "",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| C002 원본 응답 행 | {stats['raw_rows']:,}건 |",
        f"| 주류·무알콜맥주 등 비대상 제외 | −{stats['excluded']:,}건 |",
        f"| 제로 표기 없는 일반 음료 제외 | −{stats['sugar_dropped']:,}건 |",
        f"| 제품 단위로 통합한 최종 레코드 | **{total:,}개** |",
        f"| 열량·당류 조인 성공 | {stats['with_kcal']:,}개 ({kcal_pct:.1f}%) |",
        f"| 제품명에 제로 표기 | {stats['zero_total']:,}개 |",
        f"| └ 그중 **원재료에 당류가 있는 제품** | **{stats['fake_zero']:,}개** |",
        f"| 배합 변경 이력이 확인된 제품 | {stats['recipe_changed']:,}개 |",
        f"| 제로↔일반판 짝이 매칭된 제품 | {stats['paired']:,}개 |",
        "",
        "### 티어 분포",
        "",
        "| " + " | ".join(order) + " |",
        "|" + "---:|" * len(order),
        "| " + " | ".join(f"{tc.get(t, 0):,}" for t in order) + " |",
        "",
    ]

    empty = [t for t in order if not tc.get(t)]
    if empty:
        lines += [
            f"<sub>{', '.join(empty)} 티어는 이번 수집분에서 **실제로 0건**입니다. "
            "판정 규칙은 유지하되 결과를 있는 그대로 표시합니다.</sub>",
            "",
        ]

    if s_rows:
        lines += [
            f"**S 티어 전체 {len(s_rows)}개** — 알룰로스만 사용:",
            "",
            "| 제품명 | 업소명 | 보고일자 |",
            "|---|---|---|",
        ]
        lines += [f"| {r['제품명']} | {r['업소명']} | {d(r['보고일자'])} |" for r in s_rows]
        lines.append("")

    lines.append(STATS_END)
    return "\n".join(lines)


def update_readme(stats, fetched_at, path=README_PATH):
    """README의 STATS 마커 블록만 교체한다. 마커가 없으면 건드리지 않는다."""
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        text = f.read()
    i, j = text.find(STATS_START), text.find(STATS_END)
    if i == -1 or j == -1 or j < i:
        print(f"[readme] {STATS_START} 마커가 없어 갱신을 건너뜁니다")
        return False
    updated = text[:i] + render_stats_block(stats, fetched_at) + text[j + len(STATS_END):]
    if updated == text:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    return True


def sync(key, types, raw_path, cache_path, out_csv, out_html, docs_html, force=False):
    """월 1회 실행용. 변경이 없으면 다운로드·재빌드·커밋을 전부 건너뛴다."""
    new_rows, counts = fetch_all(key, types)
    if not new_rows:
        raise ApiError("수집 결과가 0건입니다 — 기존 데이터를 덮어쓰지 않고 중단합니다")

    old_rows = load_raw_full(raw_path)[0] if os.path.exists(raw_path) else []
    added, changed, removed = diff_raw(old_rows, new_rows)
    print(f"\n[sync] 신규 {len(added)}건 · 변경 {len(changed)}건 · 삭제 {len(removed)}건")

    if not (added or changed or removed) and not force:
        print("[sync] 변경 없음 — 영양 다운로드·재빌드·커밋을 모두 생략합니다")
        return False

    for no in added[:10]:
        r = next(x for x in new_rows if pick(x, FIELD_REPORT_NO) == no)
        print(f"  + {pick(r, FIELD_NAME)} / {pick(r, FIELD_MAKER)}")
    for no in changed[:10]:
        r = next(x for x in new_rows if pick(x, FIELD_REPORT_NO) == no)
        print(f"  ~ {pick(r, FIELD_NAME)} / {pick(r, FIELD_MAKER)}")

    write_raw(new_rows, types, raw_path)
    fetched_at = time.strftime("%Y%m%d")

    wanted = {pick(r, FIELD_REPORT_NO).strip() for r in new_rows}
    wanted.discard("")
    sync_nutrition(wanted, cache_path)

    stats = build(raw_path, cache_path, out_csv, out_html, None)

    if docs_html:
        _, slugs = publish_docs(docs_html, out_html, stats)
        ping_indexnow([PAGE_URL] + [f"{PAGE_URL}{s}" for s in slugs])

    if update_readme(stats, fetched_at):
        print("[readme] 수집 현황 블록 갱신")

    print(f"\n[sync] 갱신 완료 — 신규 {len(added)} / 변경 {len(changed)} / 삭제 {len(removed)}")
    return True


# 커밋 대상. 재생성 산출물(CSV·로컬 HTML)은 .gitignore 대상이라 제외한다.
DEFAULT_DOCS_DIR = os.path.dirname(DEFAULT_DOCS_HTML) or "."
PUSH_PATHS = [
    DEFAULT_RAW, DEFAULT_NUTRITION_CACHE, DEFAULT_DOCS_HTML, README_PATH,
    os.path.join(DEFAULT_DOCS_DIR, "sitemap.xml"),
    os.path.join(DEFAULT_DOCS_DIR, "robots.txt"),
    os.path.join(DEFAULT_DOCS_DIR, "llms.txt"),
    os.path.join(DEFAULT_DOCS_DIR, "llms-full.txt"),
    os.path.join(DEFAULT_DOCS_DIR, "products.html"),
    os.path.join(DEFAULT_DOCS_DIR, "allulose.html"),
    os.path.join(DEFAULT_DOCS_DIR, "no-aspartame.html"),
    os.path.join(DEFAULT_DOCS_DIR, "no-erythritol.html"),
    os.path.join(DEFAULT_DOCS_DIR, "no-caffeine.html"),
    os.path.join(DEFAULT_DOCS_DIR, "fake-zero.html"),
    os.path.join(DEFAULT_DOCS_DIR, "hidden-zero.html"),
]


# -- SEO: 정적 페이지 생성 -------------------------------------
# 리포트는 단일 페이지 앱이라 제품 616개가 JSON 블록 안에 갇혀 크롤러에게 안 보인다.
# 그래서 빌드 때 무JS 정적 페이지를 같이 뽑는다. 답변엔진·생성엔진은 표를
# 구조화된 사실로 파싱하므로, 질문 하나당 페이지 하나 원칙으로 만든다.

_STATIC_CSS = """*{box-sizing:border-box}
body{font-family:-apple-system,"Malgun Gothic",sans-serif;margin:0;padding:20px 16px 56px;
     background:#f4f5f7;color:#16191d;line-height:1.7}
main{max-width:1000px;margin:0 auto}
h1{font-size:23px;margin:0 0 10px;line-height:1.35}
h2{font-size:17px;margin:30px 0 8px}
.lead{font-size:16px;font-weight:600;background:#eef4ff;border-left:4px solid #2563eb;
      padding:12px 14px;margin:0 0 14px;border-radius:0 8px 8px 0}
.meta{color:#6b7280;font-size:13px;margin:0 0 20px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;
      box-shadow:0 1px 3px rgba(16,24,40,.06);border-radius:8px;overflow:hidden}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #e4e7eb;vertical-align:top}
th{background:#f7f8fa;font-weight:700;font-size:12px;white-space:nowrap}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.t{display:inline-block;min-width:22px;text-align:center;padding:1px 6px;border-radius:999px;
   font-weight:700;font-size:11.5px;color:#16191d}
nav{font-size:13px;margin:0 0 16px}
nav a{color:#2563eb;margin-right:12px}
footer{margin-top:34px;font-size:12px;color:#6b7280;border-top:1px solid #e4e7eb;padding-top:14px}
footer div{margin-bottom:5px}
.q{font-weight:700;margin-top:14px}\n.caveat{background:#fdf4f4;border-left:4px solid #c0262c;padding:10px 12px;\n        margin:0 0 12px;font-size:13px;border-radius:0 6px 6px 0}
@media(max-width:720px){table{font-size:12px}th,td{padding:6px 7px}h1{font-size:20px}}"""

_TIER_BG = {"무감미료": "#4caf50", "S": "#8bc34a", "A": "#cddc39", "B": "#ffc107",
            "C": "#ff9800", "D": "#f4511e", "F": "#c00", "?": "#999"}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _tier_badge(tier):
    label = "무" if tier == "무감미료" else tier
    return f'<span class="t" style="background:{_TIER_BG.get(tier, "#999")}">{_esc(label)}</span>'


def _rows_table(records, cols=("티어", "제품명", "업소명", "감미료", "열량", "당류", "용량")):
    head = "".join(f"<th>{_esc(c)}{'<br><small>100mL당</small>' if c in ('열량', '당류') else ''}</th>"
                   for c in cols)
    out = [f"<table><thead><tr>{head}</tr></thead><tbody>"]
    for r in records:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if c == "티어":
                cells.append(f"<td>{_tier_badge(v)}</td>")
            elif c in ("열량", "당류"):
                cells.append(f'<td class="n">{_esc(v) if v != "" else "&mdash;"}</td>')
            else:
                cells.append(f"<td>{_esc(v) if v != '' else '&mdash;'}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def _static_page(slug, title, desc, h1, lead, body, lastmod, ld=None):
    """무JS 정적 페이지 한 장. 가시 텍스트와 JSON-LD 를 어긋나게 만들지 않는다."""
    ld_html = ""
    if ld:
        ld_html = ('<script type="application/ld+json">'
                   + json.dumps(ld, ensure_ascii=False, indent=1) + "</script>\n")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{PAGE_URL}{slug}">
<link rel="icon" type="image/png" sizes="32x32" href="data:image/png;base64,{_FAVICON_B64}">
<meta property="og:type" content="article">
<meta property="og:locale" content="ko_KR">
<meta property="og:site_name" content="대체당 제로 음료 티어">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{PAGE_URL}{slug}">
<meta property="og:image" content="{PAGE_URL}og-card.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(title)}">
<meta name="twitter:description" content="{_esc(desc)}">
<meta name="twitter:image" content="{PAGE_URL}og-card.png">
{ld_html}{_GA_SNIPPET.replace("__GA_ID__", GA_ID) if GA_ID else ""}
<style>{_STATIC_CSS}</style>
</head>
<body>
<main>
<nav><a href="{PAGE_URL}">&larr; 전체 리포트(검색·필터)</a><a href="{PAGE_URL}products.html">616개 전체 목록</a></nav>
<h1>{h1}</h1>
<p class="lead">{lead}</p>
<div class="meta">기준일 {lastmod} &middot; 출처 식품의약품안전처 품목제조보고(C002) &middot; 열량·당류는 공공데이터포털 전국통합식품영양성분정보(15100066)</div>
{body}
<footer>
<div>이 표의 감미료는 제조사가 식약처에 신고한 <b>품목제조보고 원재료 전문</b>에서 탐지한 것입니다. 추정으로 채우지 않으며 데이터에 없으면 표시하지 않습니다.</div>
<div>열량·당류는 <b>100mL(또는 100g)당</b> 값입니다. 제품 라벨은 한 병 전체 기준이라 숫자가 달라 보일 수 있습니다.</div>
<div>티어는 인용된 연구를 근거로 한 이 프로젝트의 해석이며 정부 기관의 공식 평가가 아닙니다. 의학적 조언이 아닙니다.</div>
<div>데이터 &copy; 식품의약품안전처 &middot; 공공데이터포털 &middot; <a href="https://github.com/gulf1324/zero-drinks-tier">소스·산출 방법</a></div>
</footer>
</main>
</body>
</html>
"""


def _item_list_ld(name, desc, slug, records, limit=100):
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": name,
        "description": desc,
        "url": f"{PAGE_URL}{slug}",
        "numberOfItems": min(len(records), limit),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "item": {"@type": "Product", "name": r["제품명"],
                      "brand": {"@type": "Organization", "name": r["업소명"]}}}
            for i, r in enumerate(records[:limit])
        ],
    }


def _is_opaque(rec):
    """원재료가 혼합제제 등으로 뭉뚱그려져 성분 유무를 단정할 수 없는 제품인가.

    '탐지되지 않음'과 '들어 있지 않음'은 다르다. 이 구분을 흐리면 아스파탐을
    피해야 하는 사람에게 잘못된 목록을 주게 된다.
    """
    text = (rec.get("표시원재료") or rec.get("원재료전문", "")).replace(" ", "")
    return any(tok in text for tok in OPAQUE_TOKENS)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def seo_landing_specs(records):
    """의도 랜딩 정의. (slug, title, desc, h1, 직답, [(소제목, 설명, 레코드)], 읽는 법).

    사람이 검색창에 실제로 치는 질문 하나당 페이지 하나로 만든다. 각 질문의 답은
    데이터로 확정되는 것만 쓴다 - 추천·권유는 넣지 않는다.

    '○○ 없는 음료' 류는 반드시 **확인된 목록과 확인 불가 목록을 나눈다.**
    원재료가 식품첨가물혼합제제로 뭉뚱그려진 제품은 성분 유무를 단정할 수 없는데,
    이를 '없음'으로 묶으면 화면이 사실 아닌 것을 말하게 된다.
    """
    n = len(records)
    rank = lambda r: (TIER_RANK.get(r["티어"], 99), r["제품명"])

    def split(pred):
        """조건을 만족하는 제품을 (원재료 투명 = 확인됨, 가려짐 = 확인 불가) 로 쪼갠다."""
        hit = [r for r in records if pred(r) and r["티어"] != "F"]
        clear = sorted([r for r in hit if not _is_opaque(r)], key=rank)
        murky = sorted([r for r in hit if _is_opaque(r)], key=rank)
        return clear, murky

    allulose = sorted([r for r in records if "S" in (r["조합"] or "").split("+")],
                      key=lambda r: r["제품명"])
    asp_clear, asp_murky = split(lambda r: r["아스파탐"] != "Y")
    ery_clear, ery_murky = split(lambda r: "에리스" not in (r["감미료"] or ""))
    caf_clear, caf_murky = split(lambda r: r["카페인"] != "Y")
    fake = sorted([r for r in records if r["티어"] == "F"],
                  key=lambda r: -(_num(r["당류"]) or 0))
    hidden = sorted([r for r in records if r["제로표기"] != "Y" and r["실측제로"] == "Y"],
                    key=lambda r: (_num(r["열량"]) if _num(r["열량"]) is not None else 99,
                                   r["제품명"]))

    MURKY_NOTE = ("아래 제품들은 신고 원재료가 <b>식품첨가물혼합제제</b> 등으로 뭉뚱그려져 "
                  "해당 성분이 들어 있는지 <b>확인할 수 없습니다</b>. 없다는 뜻이 아닙니다.")

    def negative(slug, subject, clear, murky, why, extra=""):
        return (
            slug,
            f"{subject} 없는 제로 음료 {len(clear)}개 — 원재료 전문으로 확인",
            f"신고 원재료 전문에서 {subject}이 없는 것으로 확인된 제로·무당류 탄산음료 "
            f"{len(clear)}개입니다. 원재료가 혼합제제로 가려져 확인할 수 없는 {len(murky)}개는 "
            f"따로 구분해 표시했습니다.",
            f"{subject} 없는 제로 음료는 무엇인가?",
            f"결론부터: 신고 원재료가 투명하게 공개된 제품 중 {subject}이 없는 것은 "
            f"<b>{len(clear)}개</b>입니다. 별도로 <b>{len(murky)}개</b>는 원재료가 "
            f"'식품첨가물혼합제제'로 뭉뚱그려져 {subject} 포함 여부를 <b>확인할 수 없습니다</b>. "
            f"(전체 {n}개 기준)",
            [(f"{subject} 없음이 확인된 {len(clear)}개", "", clear),
             (f"확인할 수 없는 {len(murky)}개", MURKY_NOTE, murky)],
            why + extra,
        )

    return [
        ("allulose.html",
         f"알룰로스 쓰는 제로 음료 {len(allulose)}개 — 식약처 원재료 기준",
         f"국내 유통 제로 탄산음료 가운데 알룰로스·타가토스를 쓰는 제품 {len(allulose)}개를 "
         f"식약처 품목제조보고 원재료 전문에서 추려 정리했습니다.",
         "알룰로스 쓰는 제로 음료는 무엇인가?",
         f"결론부터: 수집한 {n}개 제품 중 알룰로스 계열(알룰로스·타가토스)을 신고 원재료에 "
         f"올린 제품은 <b>{len(allulose)}개</b>입니다.",
         [("", "", allulose)],
         "알룰로스는 0.2~0.4 kcal/g 이고 식후 혈당을 오히려 낮춘다는 메타분석 결과가 있어 "
         "이 리포트에서 가장 높은 S 등급입니다. 다만 <b>다른 감미료가 함께 들어가면 최종 등급은 "
         "더 나쁜 쪽을 따릅니다</b> - 그래서 이 목록의 대부분은 S 가 아닙니다."),
        negative("no-aspartame.html", "아스파탐", asp_clear, asp_murky,
                 "아스파탐이 든 제품은 라벨에 '페닐알라닌 함유' 문구가 함께 붙습니다. "
                 "페닐케톤뇨증(PKU) 때문에 피해야 하는 경우라면 <b>확인 불가 목록의 제품은 "
                 "제품 라벨을 직접 확인하세요.</b>"),
        negative("no-erythritol.html", "에리스리톨", ery_clear, ery_murky,
                 "에리스리톨의 혈소판 반응성·심혈관 사건 신호는 관찰연구에서 제기되고 소규모 "
                 "개입연구로 보강된 단계이며 <b>인과관계가 확정되지 않았습니다</b>. "
                 "스테비아 제품은 대부분 에리스리톨과 혼합되므로 원재료를 직접 확인해야 합니다."),
        negative("no-caffeine.html", "카페인", caf_clear, caf_murky,
                 "<b>콜라 계열은 표기가 없어도 카페인이 들어가는 것이 일반적입니다.</b> "
                 "펩시 계열처럼 널리 알려진 제품은 손으로 카페인 표시를 넣었지만, 확인 불가 "
                 "목록에는 여전히 카페인이 들어 있을 수 있는 제품이 남아 있습니다."),
        ("fake-zero.html",
         f"제로라면서 당류가 있는 음료 {len(fake)}개 — 표기와 원재료 불일치",
         f"제품명에 제로를 표기하면서 신고 원재료에 당류가 들어간 제품 {len(fake)}개입니다. "
         f"제로칼로리 표시 기준은 100mL당 4kcal 미만이라 소량의 당류로도 적법하게 표기할 수 있습니다.",
         "제로라고 적혀 있는데 당류가 들어간 음료가 있나?",
         f"결론부터: 제로를 표기한 제품 가운데 신고 원재료에 당류가 있는 것은 "
         f"<b>{len(fake)}개</b>입니다. 법 위반이 아니라 표시 기준 안의 일입니다.",
         [("", "", fake)],
         "<b>표시 기준 위반이 아닙니다.</b> 제로칼로리 표기 기준은 100mL당 4kcal 미만이므로 "
         "소량의 당류가 들어가도 적법하게 '제로'를 붙일 수 있습니다. 이 표는 표기와 신고 원재료의 "
         "불일치를 보여줄 뿐입니다. 실측 당류가 0g으로 확인된 제품은 착향용 미량으로 보고 "
         "이 목록에서 제외했습니다."),
        ("hidden-zero.html",
         f"이름에 제로가 없는데 실제로 0kcal인 음료 {len(hidden)}개",
         f"제품명에 제로 표기가 없지만 신고 영양성분상 100mL당 4kcal 미만인 제품 {len(hidden)}개입니다. "
         f"제로 음료를 찾을 때 이름만 보면 놓치는 제품들입니다.",
         "이름에 제로가 없는데 실제로는 제로인 음료가 있나?",
         f"결론부터: 제품명에 제로 표기가 없으면서 100mL당 4kcal 미만인 제품이 "
         f"<b>{len(hidden)}개</b> 있습니다.",
         [("", "", hidden)],
         "식약처 표시 기준으로 100mL당 4kcal 미만이면 '제로칼로리'로 표기할 수 있습니다. "
         "이 제품들은 조건을 충족하는데 제품명으로 알리지 않는 경우입니다. 열량은 신고 영양성분 값입니다."),
    ]


def write_seo_pages(docs_dir, records, lastmod):
    """정적 목록·의도 랜딩 페이지를 쓰고 생성한 slug 목록을 돌려준다."""
    written = []

    ordered = sorted(records, key=lambda r: (TIER_RANK.get(r["티어"], 99), r["제품명"]))
    body = (f"<p>식약처 품목제조보고에 신고된 원재료 전문에서 감미료를 탐지해 "
            f"{len(records)}개 제품을 S~F 티어로 분류한 전체 목록입니다. "
            f"검색·필터·정렬이 필요하면 <a href=\"{PAGE_URL}\">전체 리포트</a>를 쓰세요.</p>"
            + _rows_table(ordered))
    page = _static_page(
        "products.html",
        f"제로 탄산음료 {len(records)}개 전체 목록 — 감미료·티어·열량 한눈에",
        f"국내 유통 제로·무당류 탄산음료 {len(records)}개의 감미료 구성과 티어, 100mL당 열량·당류를 "
        f"한 페이지에 정리한 전체 목록입니다. 식약처 품목제조보고 원재료 전문 기준입니다.",
        f"제로 탄산음료 {len(records)}개 전체 목록",
        f"결론부터: 수집·분류한 제품은 <b>{len(records)}개</b>이며 티어 분포는 "
        + ", ".join(f"{t} {sum(1 for r in records if r['티어'] == t)}개"
                    for t in ("무감미료", "S", "A", "B", "C", "D", "F")
                    if sum(1 for r in records if r["티어"] == t)) + " 입니다.",
        body, lastmod,
        _item_list_ld(f"제로 탄산음료 {len(records)}개 전체 목록",
                      "식약처 품목제조보고 원재료 기준 감미료 티어 분류", "products.html", ordered))
    with open(os.path.join(docs_dir, "products.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    written.append("products.html")

    for slug, title, desc, h1, lead, sections, note in seo_landing_specs(records):
        parts, all_rows = [], []
        for heading, caveat, subset in sections:
            all_rows += subset
            if heading:
                parts.append(f"<h2>{heading}</h2>")
            if caveat:
                parts.append(f'<p class="caveat">{caveat}</p>')
            parts.append(_rows_table(subset) if subset else "<p>해당하는 제품이 없습니다.</p>")
        body = "".join(parts) + f"<h2>읽는 법</h2><p>{note}</p>"
        page = _static_page(slug, title, desc, h1, lead, body, lastmod,
                            _item_list_ld(h1, desc, slug, all_rows))
        with open(os.path.join(docs_dir, slug), "w", encoding="utf-8", newline="\n") as f:
            f.write(page)
        written.append(slug)

    print(f"[seo] 정적 페이지 {len(written)}장 생성: {', '.join(written)}")
    return written


def write_llms_files(docs_dir, records, lastmod):
    """llms.txt(안내서) / llms-full.txt(데이터 전문). 생성엔진이 1차 소스로 읽게 한다."""
    dist = {t: sum(1 for r in records if r["티어"] == t)
            for t in ("무감미료", "S", "A", "B", "C", "D", "F")}
    dist_line = " / ".join(f"{k} {v}개" for k, v in dist.items() if v)

    guide = f"""# 대체당 제로 음료 티어

> 국내 유통 제로·무당류 탄산음료 {len(records)}개의 감미료(대체당) 구성을 식품의약품안전처
> 품목제조보고 원재료 전문으로 수집해 S~F 티어로 분류한 데이터셋입니다.
> **이 사이트가 이 분류의 1차 소스입니다** — 다른 곳에서 요약된 값이 아니라 정부 신고
> 데이터에서 직접 산출합니다.

## 핵심 페이지

- [전체 리포트]({PAGE_URL}): 검색·필터·정렬 가능한 {len(records)}개 전량 (JS 필요)
- [전체 목록]({PAGE_URL}products.html): 같은 데이터의 무JS 정적 표
- [알룰로스 쓰는 제로 음료]({PAGE_URL}allulose.html)
- [아스파탐 없는 제로 음료]({PAGE_URL}no-aspartame.html)
- [에리스리톨 없는 제로 음료]({PAGE_URL}no-erythritol.html)
- [카페인 없는 제로 음료]({PAGE_URL}no-caffeine.html)
- [제로라면서 당류가 있는 음료]({PAGE_URL}fake-zero.html)
- [이름에 제로가 없는데 0kcal인 음료]({PAGE_URL}hidden-zero.html)
- [데이터 전문]({PAGE_URL}llms-full.txt): 전 제품의 티어·감미료·열량·당류 텍스트 전량

## 데이터 정책

- 원출처: 식품의약품안전처 식품(첨가물)품목제조보고 원재료 `C002` (제품명·업소명·원재료 전문)
- 열량·당류: 공공데이터포털 전국통합식품영양성분정보(가공식품) 표준데이터 `15100066`
- 조인 키: 품목제조보고번호(`PRDLST_REPORT_NO`). 제품명 문자열 매칭이 아닙니다
- 기준일: {lastmod} / 갱신 주기: 월 1회
- 산출 코드 공개: https://github.com/gulf1324/zero-drinks-tier (MIT)
- **추정하지 않습니다.** 신고 원재료에 없으면 없다고 표시합니다. 원재료가
  '식품첨가물혼합제제'로 뭉뚱그려진 제품은 판매처 표시사항으로 보강하고 출처를 함께 밝힙니다

## 티어 기준

- S 알룰로스·타가토스 — 0.2~0.4 kcal/g, 식후 혈당을 낮춤 (AJCN 2026 메타분석)
- A 스테비올배당체·나한과 — 0 kcal, 혈당 영향 없음
- B 수크랄로스·아세설팜칼륨·아스파탐·사카린 — RCT 21건 메타분석에서 공복 인슐린·HbA1c 상승
- C 에리스리톨·자일리톨 — 혈소판 반응성·심혈관 사건 신호 (인과관계 미확정)
- D 말티톨·소르비톨 등 당알코올 — 실제 2~2.6 kcal/g
- F 제로를 표방하나 신고 원재료에 당류가 있음
- 무감미료 — 신고 원재료에 감미료가 없음
- 한 제품에 여러 감미료가 있으면 **가장 나쁜 등급**을 최종 티어로 부여합니다

## 현재 분포 ({lastmod} 기준)

{dist_line} / 총 {len(records)}개

## 인용 시 표기

`zero-drinks-tier.vercel.app` (데이터 원출처: 식품의약품안전처 · 공공데이터포털)
"""

    lines = [
        f"# 대체당 제로 음료 티어 — 데이터 전문 ({lastmod} 기준)",
        "",
        f"제품 {len(records)}개. 출처: 식품의약품안전처 품목제조보고 원재료(C002) + "
        f"공공데이터포털 전국통합식품영양성분정보(15100066).",
        "열량·당류는 100mL(또는 100g)당 값이며 한 병 전체 기준이 아닙니다.",
        f"정본: {PAGE_URL}  /  산출 코드: https://github.com/gulf1324/zero-drinks-tier",
        "",
        "| 티어 | 제품명 | 제조사 | 감미료 | 열량 | 당류 | 용량 |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for r in sorted(records, key=lambda r: (TIER_RANK.get(r["티어"], 99), r["제품명"])):
        cell = lambda v: str(v).replace("|", "/") if v != "" else "-"
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            cell(r["티어"]), cell(r["제품명"]), cell(r["업소명"]),
            cell(r["감미료"]), cell(r["열량"]), cell(r["당류"]), cell(r["용량"])))
    lines.append("")

    for name, body in (("llms.txt", guide), ("llms-full.txt", "\n".join(lines))):
        with open(os.path.join(docs_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    print(f"[seo] llms.txt / llms-full.txt 생성 ({len(records)}개 제품)")


def publish_docs(docs_html, out_html, stats):
    """배포 디렉터리에 리포트를 복사하고 SEO 산출물을 전부 다시 만든다.

    build 와 sync 가 같은 경로를 쓰게 해서, 어느 쪽으로 돌려도 정적 페이지·
    llms.txt·사이트맵이 리포트와 같은 시점을 가리키게 한다.
    """
    docs_dir = os.path.dirname(docs_html) or "."
    os.makedirs(docs_dir, exist_ok=True)
    shutil.copyfile(out_html, docs_html)
    print(f"[docs] {out_html} -> {docs_html}")
    slugs = write_seo_files(docs_dir, stats["generated_at"][:10], stats["records"])
    return docs_dir, slugs


def write_seo_files(docs_dir, lastmod, records):
    """sitemap.xml / robots.txt / 정적 페이지 / llms.txt 를 한 번에 생성한다.

    Vercel 은 도메인 루트로 서빙하므로 robots.txt 가 실제로 읽힌다
    (GitHub Pages 하위 경로 시절에는 무시됐다).

    robots.txt 는 매칭되는 첫 User-agent 블록만 적용되므로, 크롤러를 명시적으로
    허용하려면 그 블록 안에도 Allow: / 를 따로 둬야 한다 (없으면 자신의 블록만
    보고 전부 차단된 것으로 해석한다). Sitemap 지시문은 전역이라 한 번만 적는다.

    AI 크롤러는 용도가 세 가지고 (학습·검색색인·실시간 fetch) 이 프로젝트는 인용
    유입이 목표라 전부 허용한다. 데이터 자체가 공개 정부 데이터이고 산출 코드도
    MIT 로 공개돼 있어 학습을 막을 이유가 없다.
    """
    if not records:
        # 사이트맵을 1 URL 로 덮어쓰고 정적 페이지를 낡은 채 남기는 사고를 막는다.
        raise ValueError("write_seo_files 에는 records 가 필요합니다 "
                         "(build()/sync() 가 돌려주는 stats['records'])")
    slugs = write_seo_pages(docs_dir, records, lastmod)
    write_llms_files(docs_dir, records, lastmod)

    urls = [(PAGE_URL, "1.0", "monthly")]
    urls += [(f"{PAGE_URL}{s}", "0.8", "monthly") for s in slugs]
    body = "".join(
        f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{freq}</changefreq>\n    <priority>{pri}</priority>\n  </url>\n"
        for loc, pri, freq in urls)
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + body + "</urlset>\n")

    ai_agents = [
        # 학습 (모델 훈련) — 미래 모델의 인지를 얻는다
        "GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "Applebot-Extended",
        # 검색 색인 (AI 검색의 자체 인덱스)
        "OAI-SearchBot", "Claude-SearchBot", "PerplexityBot",
        # 실시간 fetch (사용자 질문 시 페이지 열람)
        "ChatGPT-User", "Claude-User", "Perplexity-User",
    ]
    robots = "".join(f"User-agent: {a}\nAllow: /\n\n" for a in ["Yeti"] + ai_agents)
    robots += "User-agent: *\nAllow: /\n\n"
    robots += f"Sitemap: {PAGE_URL}sitemap.xml\n"

    for name, text in (("sitemap.xml", sitemap), ("robots.txt", robots)):
        with open(os.path.join(docs_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    keyfile = write_indexnow_key(docs_dir)
    if keyfile:
        print(f"[indexnow] 키 파일 {os.path.basename(keyfile)} 생성")
    print(f"[seo] sitemap.xml({len(urls)} URL) / robots.txt 갱신 (lastmod {lastmod})")
    return slugs


def indexnow_key(docs_dir=None):
    """IndexNow 키를 찾는다. 환경변수 우선, 없으면 배포 디렉터리의 키 파일에서 읽는다.

    키 파일은 사이트 루트에 공개되도록 설계된 값이라 저장소에 그대로 들어간다.
    그래서 한 번 배치해 두면 환경변수 없이도 계속 쓸 수 있다 - 손으로 넣는
    환경변수에 의존하면 월간 갱신 때 반드시 빠뜨린다.

    파일명(확장자 제외)과 내용이 같은 .txt 만 키로 인정한다. llms.txt 처럼
    무관한 텍스트 파일을 키로 오인하지 않기 위한 조건이다.
    """
    env = os.environ.get("INDEXNOW_KEY", "").strip()
    if env:
        return env
    docs_dir = docs_dir or DEFAULT_DOCS_DIR
    if not os.path.isdir(docs_dir):
        return ""
    for name in sorted(os.listdir(docs_dir)):
        if not name.endswith(".txt"):
            continue
        stem = name[:-4]
        if not re.fullmatch(r"[A-Za-z0-9\-]{8,128}", stem):
            continue
        try:
            with open(os.path.join(docs_dir, name), encoding="utf-8") as f:
                if f.read().strip() == stem:
                    return stem
        except OSError:
            continue
    return ""


def write_indexnow_key(docs_dir, key=None):
    """IndexNow 키 파일을 사이트 루트에 쓴다. 내용은 키 문자열 그대로여야 한다.

    키 파일이 없으면 API 가 422 를 준다. 키를 환경변수로만 넣고 파일을 빼먹는 것이
    IndexNow 실패의 1순위 원인이라, 키가 있으면 파일도 같이 만든다.
    """
    key = key or indexnow_key(docs_dir)
    if not key:
        return None
    if not re.fullmatch(r"[A-Za-z0-9\-]{8,128}", key):
        print(f"[indexnow] 키 형식이 올바르지 않아 건너뜀 (8~128자 영숫자·하이픈): {key[:12]}…")
        return None
    path = os.path.join(docs_dir, f"{key}.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(key)
    return path


def ping_indexnow(urls, key=None):
    """IndexNow 로 갱신을 알린다. Bing·Naver·Yandex 계열이 소비한다 (Google 미지원).

    키 파일이 사이트 루트에 있어야 유효하다. 키가 없으면 조용히 건너뛴다 -
    색인 가속은 부가 기능이라 실패가 빌드를 막아서는 안 된다.
    """
    key = key or indexnow_key()
    if not key or not urls:
        return False
    host = PAGE_URL.split("//", 1)[1].strip("/")
    payload = json.dumps({
        "host": host, "key": key,
        "keyLocation": f"{PAGE_URL}{key}.txt",
        "urlList": list(urls),
    }).encode()
    req = urllib.request.Request("https://api.indexnow.org/IndexNow", data=payload,
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"[indexnow] {r.status} — {len(urls)}개 URL 통보")
            return 200 <= r.status < 300
    except Exception as e:  # 네트워크·인증 실패가 빌드를 막지 않게 한다
        print(f"[indexnow] 건너뜀: {e}")
        return False


def ping_mode(docs_dir=None):
    """사이트맵에 실린 URL 을 IndexNow 로 통보한다. 데이터를 건드리지 않는다.

    Bing·네이버·Yandex 계열이 IndexNow 를 소비한다 (Google 은 미지원이라
    사이트맵 lastmod 정확성으로 승부한다). 키는 Bing 웹마스터도구에서 발급한다.
    """
    docs_dir = docs_dir or DEFAULT_DOCS_DIR
    path = os.path.join(docs_dir, "sitemap.xml")
    if not os.path.exists(path):
        sys.exit(f"사이트맵이 없습니다: {path} — 먼저 --mode build 를 실행하세요")
    urls = re.findall(r"<loc>([^<]+)</loc>", open(path, encoding="utf-8").read())
    if not urls:
        sys.exit("사이트맵에 URL 이 없습니다")
    key = indexnow_key(docs_dir)
    if not key:
        print("IndexNow 키를 찾을 수 없습니다. Bing 웹마스터도구 > IndexNow 에서 키를")
        print("발급받아 아래처럼 넣으세요 (키 파일은 자동 생성됩니다):")
        print("  set INDEXNOW_KEY=<발급키>   (Windows)")
        print(f"통보 대상 {len(urls)}개 URL:")
        for u in urls:
            print("  " + u)
        return False
    kf = write_indexnow_key(docs_dir, key)
    if kf:
        print(f"[indexnow] 키 파일 {os.path.basename(kf)} 준비 — 배포 후 유효해집니다")
    return ping_indexnow(urls, key)


def git_push(message=None):
    """sync가 실제로 바꾼 파일만 커밋·푸시한다. 변경이 없으면 아무것도 하지 않는다."""
    import subprocess

    def git(*args, check=True):
        return subprocess.run(("git",) + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=check)

    paths = [p for p in PUSH_PATHS if os.path.exists(p)]
    git("add", "--", *paths)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("[push] 커밋할 변경 없음")
        return False

    msg = message or f"데이터 동기화: {time.strftime('%Y-%m-%d')}"
    git("commit", "-m", msg)
    r = git("push", check=False)
    if r.returncode != 0:
        print(f"[push] 실패:\n{r.stderr.strip()}")
        return False
    print(f"[push] 완료 — {msg}")
    return True


def update_mode(args, types):
    """update.cmd 가 부르는 로컬 정기 갱신 루틴.

    사전점검 → git pull → sync → push 를 한 번에 처리하고, 사람이 읽을
    요약을 남긴다. 한글 출력을 여기서 담당하는 이유는 .cmd 파일이
    OEM 코드페이지로 파싱돼 UTF-8 한글이 깨지기 때문이다.
    """
    import subprocess

    print("=" * 58)
    print("  대체당 제로 음료 티어 — 데이터 갱신")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 58)

    if not os.path.exists(ENV_FILE) and not os.environ.get(KEY_NAMES[0]):
        print(f"\n[오류] {ENV_FILE} 파일이 없습니다.")
        print(f"       이 폴더에 아래 내용으로 만들어 주세요.\n")
        print(f"       {KEY_NAMES[0]}=발급받은키")
        return 1

    print("\n[1/3] 원격 저장소와 동기화...")
    r = subprocess.run(["git", "pull", "--rebase", "--autostash"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or r.stderr).strip()[:400])
    if r.returncode != 0:
        print("\n[오류] git pull 실패. 충돌이 있는지 확인하세요.")
        return 1

    print("\n[2/3] 데이터 수집 및 비교 (변경이 없으면 재빌드를 건너뜁니다)...")
    try:
        changed = sync(load_key(args.key), types, args.raw, args.nutrition_cache,
                       args.out, args.out_html, args.docs_html, args.force)
    except ApiError as e:
        print(f"\n[오류] 수집 실패: {e}")
        print("       일일 호출 한도를 넘었다면 다음 날 다시 실행하면 됩니다.")
        print("       기존 데이터는 그대로 보존됩니다.")
        return 1

    pushed = git_push() if changed else False

    print("\n[3/3] 완료.")
    if pushed:
        print("  변경분을 푸시했습니다. Pages 재배포까지 1~2분 걸립니다.")
    elif changed:
        print("  재빌드는 했지만 푸시하지 못했습니다. 위 메시지를 확인하세요.")
    else:
        print("  갱신할 내용이 없습니다. 아무것도 바꾸지 않았습니다.")
    print(f"\n  리포트  {PAGE_URL}")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key", help="식품안전나라 인증키 (probe/collect에만 필요)")
    p.add_argument("--mode",
                   choices=["probe", "collect", "nutrition", "enrich", "build", "run",
                            "diff", "sync", "update", "ping"],
                   default="build")
    p.add_argument("--type", action="append", default=[],
                   help="수집할 식품유형(PRDLST_DCNM). 여러 번 지정 가능. 기본: 탄산음료, 탄산수")
    p.add_argument("--raw", default=DEFAULT_RAW)
    p.add_argument("--nutrition-cache", default=DEFAULT_NUTRITION_CACHE)
    p.add_argument("--enrich-cache", default=DEFAULT_ENRICH_CACHE)
    p.add_argument("--out", default=DEFAULT_OUT_CSV)
    p.add_argument("--out-html", default=DEFAULT_OUT_HTML)
    p.add_argument("--docs-html", default=DEFAULT_DOCS_HTML,
                   help="sync 모드 전용: GitHub Pages가 서빙할 사본 경로")
    p.add_argument("--force", action="store_true",
                   help="sync 모드 전용: 변경이 없어도 재빌드")
    p.add_argument("--push", action="store_true",
                   help="sync 모드 전용: 변경이 있으면 커밋·푸시까지 수행")
    p.add_argument("--refresh-nutrition", action="store_true",
                   help="캐시가 있어도 영양 데이터를 재다운로드")
    p.add_argument("--find", help="build 모드 전용: 산출 후 매칭 제품 상세를 콘솔에 출력")
    p.add_argument("--diff-against", help="diff 모드 전용·필수: 비교할 이전 raw JSON 경로")
    p.add_argument("--keep-alcohol", action="store_true",
                    help="주류·비음료를 제외하지 않고 그대로 산출 (기본: 제외)")
    p.add_argument("--keep-sugar", action="store_true",
                    help="제로 표기 없는 당류 음료도 그대로 산출 (기본: 제외)")
    p.add_argument("--keep-discontinued", action="store_true",
                    help="생산이 중단된 제품도 그대로 산출 (기본: 제외)")
    args = p.parse_args()

    if args.find and args.mode != "build":
        p.error("--find 는 --mode build 에서만 사용할 수 있습니다.")
    if args.keep_alcohol and args.mode not in ("build", "run"):
        p.error("--keep-alcohol 은 --mode build 또는 run 에서만 사용할 수 있습니다.")
    if args.keep_sugar and args.mode not in ("build", "run"):
        p.error("--keep-sugar 는 --mode build 또는 run 에서만 사용할 수 있습니다.")
    if args.keep_discontinued and args.mode not in ("build", "run"):
        p.error("--keep-discontinued 는 --mode build 또는 run 에서만 사용할 수 있습니다.")
    if args.mode == "diff" and not args.diff_against:
        p.error("--mode diff 는 --diff-against 가 필요합니다.")
    if args.diff_against and args.mode != "diff":
        p.error("--diff-against 는 --mode diff 에서만 사용할 수 있습니다.")

    types = args.type or list(DEFAULT_TYPES)

    if args.mode == "probe":
        probe(load_key(args.key))
    elif args.mode == "collect":
        collect(load_key(args.key), types, args.raw)
    elif args.mode == "nutrition":
        nutrition_mode(args.raw, args.nutrition_cache, args.refresh_nutrition)
    elif args.mode == "enrich":
        enrich_mode(load_key(args.key), args.raw, args.enrich_cache,
                    args.nutrition_cache)
    elif args.mode == "build":
        stats = build(args.raw, args.nutrition_cache, args.out, args.out_html, args.find,
                      args.keep_alcohol, args.keep_sugar, args.enrich_cache,
                      args.keep_discontinued)
        # --docs-html 을 주면 배포본 복사와 SEO 산출물 생성까지 한 번에 끝낸다.
        # 손으로 build 만 돌리고 docs 를 복사하면 정적 페이지·llms.txt 가 낡는다.
        if stats and args.docs_html:
            publish_docs(args.docs_html, args.out_html, stats)
    elif args.mode == "diff":
        diff_mode(args.raw, args.diff_against)
    elif args.mode == "sync":
        changed = sync(load_key(args.key), types, args.raw, args.nutrition_cache,
                       args.out, args.out_html, args.docs_html, args.force)
        if changed and args.push:
            git_push()
    elif args.mode == "ping":
        ping_mode(os.path.dirname(args.docs_html) or None)
    elif args.mode == "update":
        return update_mode(args, types)
    elif args.mode == "run":
        key = load_key(args.key)
        collect(key, types, args.raw)
        nutrition_mode(args.raw, args.nutrition_cache, args.refresh_nutrition)
        enrich_mode(key, args.raw, args.enrich_cache, args.nutrition_cache)
        build(args.raw, args.nutrition_cache, args.out, args.out_html, args.find, args.keep_alcohol,
              args.keep_sugar, args.enrich_cache, args.keep_discontinued)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        sys.exit(130)
    except ApiError as e:
        sys.exit(f"API 오류: {e}")
