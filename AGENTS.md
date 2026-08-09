# AGENTS.md

## 프로젝트 개요

국내 유통 탄산음료의 **대체당(감미료) 구성**을 식약처 공식 데이터로 수집하고,
연구 근거에 기반한 티어로 분류하는 프로젝트.

목적은 "제로 음료 중 어떤 게 실제로 가장 나은가"를 마케팅 문구가 아니라
**품목제조보고에 신고된 원재료 전문**으로 판정하는 것.

## 데이터 출처

- **식품안전나라 OpenAPI, 서비스 코드 `C002`** (식품(첨가물)품목제조보고 - 원재료)
- 엔드포인트: `http://openapi.foodsafetykorea.go.kr/api/{KEY}/C002/json/{start}/{end}[/{조건}]`
- 조건은 경로에 `PRDLST_NM=제로` 형태로 붙임
- 서비스 상세/키 발급: `https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=C002`
- **공공데이터포털 표준데이터 `15100066`** (전국통합식품영양성분정보-가공식품) — 열량·당류 조인용.
  **인증키·활용신청 불필요.** 엔드포인트: `https://www.data.go.kr/download/standard.json`
  (파라미터: `publicDataPk=15100066`, `svcTableNm=tn_pubr_public_nutri_process_info_svc`,
  `perPage`, `page`, 컬럼 목록은 `colNmList`를 반복). **요청 헤더에 `X-Requested-With: XMLHttpRequest`,
  `Referer: https://www.data.go.kr/data/15100066/standard.do`, `Accept: application/json, ...`가
  없으면 404/500을 반환한다.** 조인 키는 C002의 `PRDLST_REPORT_NO` ↔ 이쪽의 `ITEM_MNFTR_RPT_NO`.
  I2790(식품영양성분DB)은 쓰지 않는다 — `~2023` 데이터의 레거시 서비스이고 활용신청이 별도로 필요하다.

### 중요: 웹 포털은 자동 접속이 차단됨

`foodsafetykorea.go.kr` 본 포털(`searchInfoProduct.do` 등)은 robots 정책상
스크래핑이 불가능하다. **웹 크롤링으로 우회하려 하지 말 것.** 반드시 OpenAPI를 쓴다.

## 파일

| 파일 | 역할 |
|---|---|
| `zero_soda_scan.py` | 수집·영양조인·산출 CLI. 표준 라이브러리만 사용 |
| `zero_soda_result.csv` | 결과물 (UTF-8 BOM, 엑셀 호환) |
| `zero_soda_report.html` | 검색·필터·정렬 가능한 단일 파일 리포트 (외부 리소스 0) |
| `zero_soda_raw.json` | C002 원본 응답 보관. 재분류 시 API 재호출 없이 사용 |
| `zero_soda_nutrition.json` | 영양(열량·당류) 조인 캐시. 재호출 없이 재사용 |

## 실행

```bash
# 필드명 확인 — 새 환경에서는 항상 이것부터
python zero_soda_scan.py --mode probe

# 전수 수집 (기본: 탄산음료 + 탄산수). --type 으로 다른 식품유형 추가 가능
python zero_soda_scan.py --mode collect

# 열량·당류 조인 (인증키 불필요)
python zero_soda_scan.py --mode nutrition

# 산출 (오프라인, API 호출 없음) — CSV + HTML 리포트
python zero_soda_scan.py --mode build

# 위 세 단계를 한번에
python zero_soda_scan.py --mode run

# 특정 제품만 콘솔에서 조회
python zero_soda_scan.py --mode build --find 밀키스제로

# 이전 스냅샷과 비교 (신제품/배합변경/단종 탐지)
python zero_soda_scan.py --mode diff --diff-against zero_soda_raw.20260101.json
```

- Python 3.8+, **외부 의존성 없음**. 새 패키지를 추가하지 말 것
- API 키(C002용)는 `--key` 인자, `FOOD_API_KEY` 환경변수, 또는 `.env` 파일(`FOOD_API_KEY=...` 또는
  `API=...`) 중 하나로 넘긴다. `probe`/`collect`/`run` 모드에만 필요하고 **소스나 커밋에 하드코딩 금지**
- `nutrition`/`build`/`diff` 모드는 인증키가 필요 없다 (영양 데이터는 키리스, `build`/`diff`는 오프라인)
- `.gitignore`에 `*.csv`, `*.json`, `*.html`, `.env` 유지

## 필드명 (2026-08-07 probe로 검증됨)

`zero_soda_scan.py`의 `FIELD_NAME` / `FIELD_RAW` / `FIELD_TYPE` / `FIELD_MAKER` / `FIELD_DATE`
상수는 **실제 응답으로 검증되었다** (각 리스트의 첫 후보가 정답). 응답 껍데기 구조도
`{"C002": {"RESULT": {...}, "total_count": "...", "row": [...]}}`로 확인됨.

API가 응답 스펙을 바꾸면 먼저 `--mode probe`를 돌려 실제 키 목록을 다시 확인하고,
맞지 않으면 해당 상수만 수정한다. `pick()`이 후보 리스트를 순회하므로 후보를 추가하는
방식으로 고치면 된다. `PRDLST_DCNM=탄산음료` 같은 식품유형 조건 검색도 동작 확인됨 —
`collect()`는 키워드가 아니라 이 조건으로 전수 수집한다.

## 티어 판정 규칙 (도메인 로직 — 함부로 바꾸지 말 것)

원재료 문자열에서 감미료를 탐지하고, **가장 나쁜 등급을 최종 티어로** 부여한다.

| 티어 | 성분 | 근거 |
|---|---|---|
| S | 알룰로스, 타가토스 | 0.2~0.4 kcal/g. 식후 혈당을 오히려 낮춤 (2026 AJCN 메타분석) |
| A | 스테비올배당체, 나한과(모그로사이드) | 0 kcal, 혈당 영향 없음, 장기 안전성 양호 |
| B | 수크랄로스, 아세설팜칼륨, 아스파탐, 사카린 | 0 kcal이나 공복 인슐린·HbA1c 상승 신호 (2026 Tufts 메타분석) |
| C | 에리스리톨, 자일리톨 | 혈당은 무해하나 혈소판 반응성·심혈관 사건 신호 (Cleveland Clinic) |
| D | 말티톨, 소르비톨, 락티톨 등 당알코올 | 실제 2~2.6 kcal/g, 말티톨은 GI 35~52로 혈당 상승 |
| F | 설탕, 액상과당, 농축과즙 등 | 제로가 아님 |

**표기 흔들림에 주의.** 알룰로스/알룰로오스, 에리스리톨/에리스리트리톨/에리트리톨,
소르비톨/솔비톨 등이 혼재한다. 새 표기를 발견하면 `SWEETENERS` 딕셔너리에 추가한다.
비교 전 공백을 제거하는 현재 방식을 유지할 것.

## 알려진 함정

1. **한 제품에 여러 품목보고 행이 존재한다.** 용량별·공장별·리뉴얼 이력별로 중복되고,
   과거 배합이 그대로 남아 있다. 같은 제품명이면 **보고일자 최신 행을 우선**하고,
   구버전을 현행으로 제시하지 말 것.
2. **"제로칼로리" 표기 기준은 100ml당 4kcal 미만**이다. 제로 표기 제품도 실제 열량이
   있을 수 있다 (예: 밀키스 제로 500ml = 16kcal). 열량을 0으로 단정하지 말 것.
3. 1회 호출 최대 100건. 일일 호출 제한이 있으니 재실행 시 `zero_soda_raw.json`을 먼저 볼 것.
4. 스테비아 제품은 대부분 에리스리톨과 혼합된다. "스테비아 제품 = A"로 단순화하지 말고
   원재료 전문에서 에리스리톨 동반 여부를 확인해야 한다.

## 작성 원칙

- **원재료를 추정으로 채우지 않는다.** 데이터에 없으면 없다고 쓴다.
  블로그·커뮤니티 티어표를 근거로 삼지 말 것 (기준이 제각각이고 출처가 불명확하다).
- 제품 정보를 요약할 때는 **어느 보고일자 기준인지 명시**한다. 배합은 자주 바뀐다.
- 건강 관련 서술은 연구 근거와 그 한계를 함께 적는다. 특히 에리스리톨 심혈관 신호는
  인과관계가 확정되지 않았다는 점을 생략하지 말 것.
- 커밋 메시지·주석·문서는 한국어.
