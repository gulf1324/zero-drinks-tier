# 유통명 수집 절차

`zero_soda_label.json` 을 채우는 방법. **손으로 검증해 넣는다.** 자동 수집 금지.

## 왜 필요한가

C002 의 제품명은 **품목제조보고 등록명**이지 유통명이 아니다.
실제로 `나랑드 사이다 제로`로 팔리는 제품이 `나랑드사이다`로 신고돼 있다.
같은 제품이 등록명·유통명 양쪽으로 중복 신고된 경우도 있다.

## 어디서 가져올 수 있나 (2026-08-10 `robots.txt` 실측)

| 소스 | 정책 | 비고 |
|---|---|---|
| `donga-bluemall.com` | `/product/` 허용 | **실증 완료** — 고시표 + 라벨 이미지 |
| `lottemartzetta.com` | `/products/` 허용 | **실증 완료** — 고시가 **HTML 텍스트**라 OCR 불필요. 단 연속 요청하면 `HTTP 202` 봇 챌린지가 걸린다 |
| `mall.lottechilsung.co.kr` | `Allow: /` | 미실증 |
| `www.7-eleven.co.kr` | 제품 경로 허용 | 미실증 |
| `ccbk.co.kr` (코카콜라음료) | `Allow: /` | JS 셸, 제품 정보 없음 |
| `search.shopping.naver.com` | `Disallow: /` | **금지** |
| `brand.naver.com` | **`ClaudeBot Disallow: /`** | **금지** |
| `coupang.com` | robots 조회 403 | **금지** |
| `emart.ssg.com` | `User-agent: * Disallow: /` | **금지** |

**위키·블로그·영양앱은 쓰지 않는다.** 「작성 원칙」이 금지하는 출처다.

## 절차

1. 허용된 공식몰에서 제품 상세페이지를 연다.
2. 상세 설명은 대개 `#prdDetail` 안의 **긴 이미지 한 장**이다. 지연 로드라
   스크롤해야 나온다. 이미지 URL을 받아 내려받는다.
3. 이미지에서 두 곳을 읽는다.
   - **상품정보제공 고시** 표의 `제품명` → 유통명
   - **제품 라벨 사진**의 `원재료명` 과 **`품목보고번호`**
4. **품목보고번호로 검증한다.** 이게 핵심이다 — 이름을 추측하지 않고
   C002 레코드에 정확히 붙일 수 있고, OCR 이 맞았는지도 같이 검증된다.

   ```bash
   python - <<'PY'
   import sys; sys.path.insert(0,'.')
   import zero_soda_scan as z
   rows,_ = z.load_raw_full('zero_soda_raw.json')
   by = {}
   for r in rows:
       by.setdefault(z.pick(r, z.FIELD_REPORT_NO).strip(), []).append(z.pick(r, z.FIELD_NAME))
   for no in ["1973028800636", "1996061705334"]:
       print(no, "->", by.get(no, "없음"))
   PY
   ```

   조회 결과가 예상한 제품이 아니면 **넣지 않는다.** 숫자를 잘못 읽은 것이다.
5. `zero_soda_label.json` 의 `labels` 에 보고번호별로 넣는다.
   `유통명`·`출처`(URL)·`확인일` 세 개가 **전부** 있어야 한다.
6. `python zero_soda_scan.py --mode build` 로 반영하고 결과를 확인한다.

## 주의

- 원재료는 **C002 가 혼합제제로 가려 감미료를 알 수 없을 때만** 넣는다(`원재료` 필드).
  이때만 티어를 고시 표시 원재료로 다시 판정하고, 리포트 상세에 출처와 함께 밝힌다.
  C002 로 이미 판정된 제품은 건드리지 않는다 - 정부 신고 데이터가 우선이다.
- **대량 수집하지 말 것.** 롯데마트 제타는 몇 번만 연속 요청해도 `HTTP 202`
  봇 챌린지로 막힌다. 검색 API 가 아니라 상점이다. 필요한 제품만 하나씩 본다.
- 팩 단위 SKU(`245ml 30입`)가 아니라 **제품 단위 이름**을 넣는다.
- 유통명이 붙은 제품은 리포트 상세에 **등록명과 출처 링크가 함께** 표시된다.
  출처 없이 이름만 바꾸면 이 프로젝트의 근거 원칙이 깨진다.
