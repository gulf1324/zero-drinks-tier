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
PAGE_URL = "https://gulf1324.github.io/zero-drinks-tier/"   # GitHub Pages 배포 주소 (canonical/OG용)


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


def call(key, start, end, cond=None):
    """cond: dict 형태의 검색조건. 예: {'PRDLST_DCNM': '탄산음료'}"""
    url = f"{BASE}/{key}/{SERVICE}/json/{start}/{end}"
    if cond:
        for k, v in cond.items():
            url += "/" + urllib.parse.quote(f"{k}={v}", safe="=")
    return _get_json(url)


def unwrap(payload):
    """{'C002': {'RESULT': {...}, 'total_count': '..', 'row': [...]}} 구조를 벗김"""
    body = payload.get(SERVICE)
    if body is None:
        raise ApiError(f"예상과 다른 응답: {json.dumps(payload, ensure_ascii=False)[:400]}")
    result = body.get("RESULT", {})
    code = result.get("CODE", "")
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


# ── Step 4: 제품 통합과 배합 이력 ────────────────────────────
def recency(row):
    return (max(pick(row, FIELD_DATE) or "", pick(row, FIELD_CHNG) or ""),
            pick(row, FIELD_REPORT_NO) or "")


CSV_FIELDS = ["티어", "조합", "제품명", "식품유형", "업소명", "보고일자", "감미료",
              "열량", "기준량", "당류", "용량", "이력행수", "배합변경", "티어불일치",
              "원재료전문", "제로표기", "제로사칭", "카페인", "아스파탐",
              "일반판", "일반판티어"]


def canonicalize(rows, nutrition):
    groups = {}
    for row in rows:
        name = pick(row, FIELD_NAME).strip()
        if not name:
            continue
        groups.setdefault(name, []).append(row)

    records = []
    for name, group in groups.items():
        group.sort(key=recency, reverse=True)
        cur = group[0]
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

        records.append({
            "티어": cls["tier"],
            "조합": cls["combo"],
            "제품명": name,
            "식품유형": pick(cur, FIELD_TYPE),
            "업소명": display_maker,
            "보고일자": recency(cur)[0],
            "감미료": " / ".join(f"{h['표기']}({h['티어']},{h['순번']})" for h in cls["hits"]),
            "열량": nut.get("ENERC", "") if nut else "",
            "기준량": nut.get("NUT_CON_SRTR_QUA", "") if nut else "",
            "당류": nut.get("SUGAR", "") if nut else "",
            "용량": nut.get("FOOD_SIZE", "") if nut else "",
            "이력행수": len(group),
            "배합변경": "Y" if changed else "",
            "티어불일치": mismatch,
            "원재료전문": raw,
            "_원본업소명": maker,      # 제조사 집계용 (annotate). CSV/HTML에는 안 씀
            "이력": history,          # HTML 배합 이력용. CSV에는 안 씀
        })
    return records


# ── Step 4b: 파생 플래그와 제로↔일반판 짝 매칭 ─────────────────
def annotate(records):
    for rec in records:
        name = rec["제품명"]
        rec["제로표기"] = "Y" if ZERO_TOKEN.search(name) else "N"
        rec["제로사칭"] = "Y" if rec["제로표기"] == "Y" and rec["티어"] == "F" else ""
        text = rec["원재료전문"].replace(" ", "")
        rec["카페인"] = "Y" if any(tok in text for tok in CAFFEINE_TOKENS) else ""
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


# ── Step 5: 단일 파일 HTML 리포트 ────────────────────────────
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제로 탄산음료 감미료 티어 리포트 | 식약처 원재료 데이터 기반 __TOTAL__개 제품 분석</title>
<meta name="description" content="국내 유통 제로·무당류 탄산음료 __TOTAL__개의 감미료 구성을 식약처 품목제조보고 원재료 데이터로 분석해 S~F 티어로 분류합니다. 알룰로스·스테비아·수크랄로스·아스파탐·에리스리톨 등 성분별 연구 근거와 제로 표기 사칭 여부까지 확인하세요.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="__PAGE_URL__">
<meta property="og:type" content="website">
<meta property="og:locale" content="ko_KR">
<meta property="og:title" content="제로 탄산음료 감미료 티어 리포트">
<meta property="og:description" content="식약처 원재료 데이터로 분류한 국내 제로·무당류 탄산음료 __TOTAL__개의 감미료 티어(S~F). 알룰로스부터 아스파탐까지 성분별 근거를 확인하세요.">
<meta property="og:url" content="__PAGE_URL__">
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
  "isAccessibleForFree": true,
  "keywords": ["제로음료", "대체당", "감미료", "알룰로스", "스테비아", "수크랄로스", "아스파탐", "에리스리톨", "탄산음료", "식품영양", "오픈데이터"],
  "variableMeasured": ["티어", "감미료 조합", "원재료 전문", "열량", "당류", "카페인 함유", "아스파탐 함유", "제로 표기 여부"],
  "creator": {"@type": "Person", "name": "gulf1324", "url": "https://github.com/gulf1324"},
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
    {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": "https://raw.githubusercontent.com/gulf1324/zero-drinks-tier/main/zero_soda_raw.json"}
  ]
}
</script>
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
  th:first-child{border-top-left-radius:var(--radius)}
  th:last-child{border-top-right-radius:var(--radius)}
  th.sorted{color:var(--accent)}
  th.sorted::after{content:" " attr(data-dir);font-size:9px}
  tbody tr:last-child td{border-bottom:0}
  tr.row{cursor:pointer}
  tr.row:hover td{background:#f7f9fc}
  tr.fake-zero td:first-child{box-shadow:inset 3px 0 0 var(--danger)}
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
  tr.detail td{background:#fafbfc;font-size:12px;padding:0}
  .detail-box{padding:11px 13px;border-left:3px solid var(--accent);margin:2px 0;white-space:pre-wrap;line-height:1.65}
  .detail-raw{color:var(--text);margin-bottom:6px}
  .detail-box div{color:var(--muted)}
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
      <div class="tier-row"><span class="tier-chip" data-tier="무감미료">무</span><b>무감미료</b><span class="tier-ing">감미료 표기 없음</span><span class="tier-why">원재료 전문이 투명하고 감미료가 실제로 없음</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="S">S</span><b>S</b><span class="tier-ing">알룰로스, 타가토스</span><span class="tier-why">0.2~0.4 kcal/g. 식후 혈당을 오히려 낮춤 (2026 AJCN 메타분석)</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="A">A</span><b>A</b><span class="tier-ing">스테비올배당체, 나한과(모그로사이드)</span><span class="tier-why">0 kcal, 혈당 영향 없음, 장기 안전성 양호</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="B">B</span><b>B</b><span class="tier-ing">수크랄로스, 아세설팜칼륨, 아스파탐, 사카린</span><span class="tier-why">0 kcal이나 공복 인슐린·HbA1c 상승 신호 (2026 Tufts 메타분석)</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="C">C</span><b>C</b><span class="tier-ing">에리스리톨, 자일리톨</span><span class="tier-why">혈당은 무해하나 혈소판 반응성·심혈관 사건 신호 (Cleveland Clinic). 인과관계는 확정되지 않음</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="D">D</span><b>D</b><span class="tier-ing">말티톨, 소르비톨, 락티톨 등 당알코올</span><span class="tier-why">실제 2~2.6 kcal/g, 말티톨은 GI 35~52로 혈당 상승</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="F">F</span><b>F</b><span class="tier-ing">설탕, 액상과당, 농축과즙 등</span><span class="tier-why">제로를 표방하지만 신고 원재료에 당류가 있음</span></div>
      <div class="tier-row"><span class="tier-chip" data-tier="?">?</span><b>확인 불가</b><span class="tier-ing">식품첨가물혼합제제 등</span><span class="tier-why">감미료가 없는 것이 아니라, 신고 원재료가 뭉뚱그려져 무엇을 썼는지 확인할 수 없음 (예: 코카콜라 제로)</span></div>
      <div class="tier-note">한 제품에 여러 감미료가 있으면 가장 나쁜 등급이 최종 티어가 됩니다. 전체 구성은 '조합' 열에서 볼 수 있습니다.<br>이 리포트는 <b>당류가 없는 음료</b>와 <b>제로를 표방한 제품</b>만 다룹니다. 제로 표기가 없는 일반 당류 음료는 수집 대상에서 제외됩니다.</div>
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
    <th data-key="열량">열량</th><th data-key="당류">당류</th><th data-key="용량">용량</th>
    <th data-key="감미료">감미료</th>
  </tr></thead>
  <tbody id="tbody"></tbody>
</table>
</div>
<nav class="pager" id="pager" aria-label="페이지 이동"></nav>
<footer>
  <div>출처: 식품의약품안전처 C002 품목제조보고(원재료). 표시된 배합은 각 제품의 최신 보고일자 기준이며 배합은 자주 바뀝니다.</div>
  <div>열량·당류: 전국통합식품영양성분정보(가공식품) 표준데이터(공공데이터포털 15100066). 품목제조보고번호로 조인되지 않은 제품은 공란이며 0을 의미하지 않습니다.</div>
  <div>C 티어 근거인 에리스리톨의 심혈관 사건 신호는 관찰 연구에서 제기된 것으로 인과관계가 확정되지 않았습니다.</div>
  <div>'제로 사칭'은 제품명에 제로 표기가 있으면서 신고 원재료에 당류가 포함된 경우를 가리킵니다. 제조사의 표시 기준 위반을 뜻하지 않습니다 — 제로칼로리 표기 기준은 100ml당 4kcal 미만이며, 소량의 당류로도 이를 충족할 수 있습니다.</div>
</footer>
</div>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const RANK = __RANK_JSON__;
const MAKERS = __MAKERS_JSON__;
const TIER_COLORS = {"무감미료":"#4caf50","S":"#8bc34a","A":"#cddc39","B":"#ffc107","C":"#ff9800","D":"#f4511e","F":"#c00","?":"#999"};

// PAGE_SIZE: 1,699행을 한 번에 그리면 표 높이가 11만 px가 되어 강제 레이아웃에만
// 216ms가 든다(실측). 한 페이지 분량만 그린다.
const PAGE_SIZE = 50;
let state = { q: "", fFake:false, fAllulose:false, fErythritol:false, fNoCaffeine:false, fNoAspartame:false, fHasKcal:false,
              tierFilters: new Set(), sortKey: "티어", sortDir: 1, expanded: new Set(), page: 1 };

function norm(s) { return (s||"").replace(/\s+/g, "").toLowerCase(); }

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
    if (state.q && !norm(r['제품명']).includes(state.q) && !norm(r['업소명']).includes(state.q)) return false;
    if (state.fFake && r['제로사칭'] !== 'Y') return false;
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
  const cls = ['row']; if (r['제로사칭']==='Y') cls.push('fake-zero');
  const chips = (r['카페인']==='Y' ? '<span class="chip">카페인</span>':'') + (r['아스파탐']==='Y' ? '<span class="chip">아스파탐</span>':'');
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
  if (r['일반판']) extra += '<div>일반판 대비: ' + escapeHtml(r['일반판']) + ' [' + escapeHtml(r['일반판티어']) + '] \u2192 [' + escapeHtml(r['티어']) + ']</div>';
  if (r['배합변경'] === 'Y') {
    extra += '<div>배합 이력:</div>' + (r['이력']||[]).map(function(h){
      return '<div>&nbsp;&nbsp;' + escapeHtml(h['보고일자']) + ' \u00b7 ' + escapeHtml(h['보고번호']) + ' \u00b7 ' + escapeHtml(h['원재료전문']) + '</div>';
    }).join('');
  }
  return '<tr class="detail"><td colspan="9"><div class="detail-box">' +
         '<div class="detail-raw">' + escapeHtml(r['원재료전문']) + '</div>' + extra + '</div></td></tr>';
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
  if (state.expanded.has(nm)) state.expanded.delete(nm);
  else state.expanded.add(nm);
  render();
});

document.getElementById('q').addEventListener('input', function(e) { state.q = norm(e.target.value); update(); });
document.getElementById('qClear').addEventListener('click', function() {
  const q = document.getElementById('q');
  q.value = ''; state.q = ''; q.focus(); update();
});
document.getElementById('sortSel').addEventListener('change', function(e) {
  state.sortKey = e.target.value; state.sortDir = 1; update();
});
document.getElementById('sortDir').addEventListener('click', function() {
  state.sortDir *= -1; update();
});
document.getElementById('fFake').addEventListener('change', function(e) { state.fFake = e.target.checked; update(); });
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
        "원재료전문": r["원재료전문"], "제로표기": r["제로표기"],
        "제로사칭": r["제로사칭"], "카페인": r["카페인"], "아스파탐": r["아스파탐"],
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
          keep_sugar=False):
    rows, types = load_raw_full(raw_path)

    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            nutrition = json.load(f).get("rows", {})
    else:
        nutrition = {}
        print("[build] 영양 캐시가 없습니다. 열량/당류는 공란으로 채웁니다. "
              "(--mode nutrition 을 먼저 실행하면 채울 수 있습니다)")

    records = canonicalize(rows, nutrition)
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
                   if r["티어"] not in ("F", "무감미료", "?") or r["제로표기"] == "Y"]
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
    order = ["무감미료", "S", "A", "B", "C", "D", "F", "?"]
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
        os.makedirs(os.path.dirname(docs_html) or ".", exist_ok=True)
        shutil.copyfile(out_html, docs_html)
        print(f"[sync] {out_html} -> {docs_html}")
        write_seo_files(os.path.dirname(docs_html) or ".", stats["generated_at"][:10])

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
]


def write_seo_files(docs_dir, lastmod):
    """sitemap.xml / robots.txt 생성. lastmod 는 리포트 산출일(YYYY-MM-DD).

    robots.txt 는 원 단위(도메인 루트)로만 읽히므로 하위 경로인 현재 배포
    주소에서는 크롤러가 참조하지 않는다. 커스텀 도메인으로 옮길 때를 대비해
    같이 두되, 색인 유도는 sitemap 을 Search Console 에 직접 제출해서 한다.
    """
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url>\n'
        f'    <loc>{PAGE_URL}</loc>\n'
        f'    <lastmod>{lastmod}</lastmod>\n'
        '    <changefreq>monthly</changefreq>\n'
        '    <priority>1.0</priority>\n'
        '  </url>\n'
        '</urlset>\n'
    )
    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {PAGE_URL}sitemap.xml\n"
    )
    for name, body in (("sitemap.xml", sitemap), ("robots.txt", robots)):
        path = os.path.join(docs_dir, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    print(f"[seo] sitemap.xml / robots.txt 갱신 (lastmod {lastmod})")


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
                   choices=["probe", "collect", "nutrition", "build", "run", "diff",
                            "sync", "update"],
                   default="build")
    p.add_argument("--type", action="append", default=[],
                   help="수집할 식품유형(PRDLST_DCNM). 여러 번 지정 가능. 기본: 탄산음료, 탄산수")
    p.add_argument("--raw", default=DEFAULT_RAW)
    p.add_argument("--nutrition-cache", default=DEFAULT_NUTRITION_CACHE)
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
    args = p.parse_args()

    if args.find and args.mode != "build":
        p.error("--find 는 --mode build 에서만 사용할 수 있습니다.")
    if args.keep_alcohol and args.mode not in ("build", "run"):
        p.error("--keep-alcohol 은 --mode build 또는 run 에서만 사용할 수 있습니다.")
    if args.keep_sugar and args.mode not in ("build", "run"):
        p.error("--keep-sugar 는 --mode build 또는 run 에서만 사용할 수 있습니다.")
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
    elif args.mode == "build":
        build(args.raw, args.nutrition_cache, args.out, args.out_html, args.find, args.keep_alcohol,
              args.keep_sugar)
    elif args.mode == "diff":
        diff_mode(args.raw, args.diff_against)
    elif args.mode == "sync":
        changed = sync(load_key(args.key), types, args.raw, args.nutrition_cache,
                       args.out, args.out_html, args.docs_html, args.force)
        if changed and args.push:
            git_push()
    elif args.mode == "update":
        return update_mode(args, types)
    elif args.mode == "run":
        key = load_key(args.key)
        collect(key, types, args.raw)
        nutrition_mode(args.raw, args.nutrition_cache, args.refresh_nutrition)
        build(args.raw, args.nutrition_cache, args.out, args.out_html, args.find, args.keep_alcohol,
              args.keep_sugar)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        sys.exit(130)
    except ApiError as e:
        sys.exit(f"API 오류: {e}")
