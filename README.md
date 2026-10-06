<div align="center">

# 대체당 제로 음료 티어

[![사이트 바로가기](https://img.shields.io/badge/%F0%9F%A5%A4%20%EC%82%AC%EC%9D%B4%ED%8A%B8%20%EB%B0%94%EB%A1%9C%EA%B0%80%EA%B8%B0-zero--drinks--tier.vercel.app-2563eb?style=for-the-badge)](https://zero-drinks-tier.vercel.app/)

**식약처 신고 원재료 · 피어리뷰 연구 근거 · 공개 데이터**

국내 유통 제로·무당류 탄산음료의 감미료(대체당) 구성을 식품의약품안전처 품목제조보고
원재료 전문으로 수집하고, 피어리뷰 연구를 근거로 **S~F 티어**로 분류한 데이터셋입니다.

![데이터](https://img.shields.io/badge/data-%EC%8B%9D%ED%92%88%EC%95%88%EC%A0%84%EB%82%98%EB%9D%BC%20C002-005BAC)
![영양](https://img.shields.io/badge/nutrition-%EA%B3%B5%EA%B3%B5%EB%8D%B0%EC%9D%B4%ED%84%B0%ED%8F%AC%ED%84%B8%2015100066-0B5FA5)
![last commit](https://img.shields.io/github/last-commit/gulf1324/zero-drinks-tier)

</div>

---

## 무엇을 볼 수 있나

"제로"라고 적힌 음료도 쓰는 감미료가 제각각입니다. 알룰로스를 쓰는 제품, 아스파탐을 쓰는
제품, 제로를 표방하면서 원재료에 당류가 있는 제품이 섞여 있습니다.

제조사가 식약처에 법적으로 신고한 **품목제조보고 원재료 전문**에서 감미료 표기를 읽어
판정합니다. 추정으로 채우지 않으며, 데이터에 없으면 없다고 표시합니다.

| 페이지 | 내용 |
|---|---|
| [메인 검색](https://zero-drinks-tier.vercel.app/) | 제품명으로 감미료와 티어를 바로 확인 |
| [전체 목록](https://zero-drinks-tier.vercel.app/products.html) | 전 제품 표. 제품명을 누르면 상세 페이지(원재료 전문 · 탐지된 감미료 · 열량·당류 · 배합 신고 이력) |
| [고급 검색](https://zero-drinks-tier.vercel.app/report.html) | 티어·성분 필터, 정렬, 제조사별 분포 |
| [연구 동향](https://zero-drinks-tier.vercel.app/research.html) | 티어의 근거 논문과 최근 연구, 각 연구의 티어 영향 |

조건별 목록: [알룰로스 사용](https://zero-drinks-tier.vercel.app/allulose.html) ·
[아스파탐 없음](https://zero-drinks-tier.vercel.app/no-aspartame.html) ·
[에리스리톨 없음](https://zero-drinks-tier.vercel.app/no-erythritol.html) ·
[카페인 없음](https://zero-drinks-tier.vercel.app/no-caffeine.html) ·
[제로인데 당류 있음](https://zero-drinks-tier.vercel.app/fake-zero.html) ·
[이름에 제로 없는 0kcal](https://zero-drinks-tier.vercel.app/hidden-zero.html)

---

## 데이터 출처

<table>
<thead>
<tr><th width="52"></th><th>출처</th><th>사용 내용</th></tr>
</thead>
<tbody>
<tr>
<td align="center"><img src="https://www.google.com/s2/favicons?domain=foodsafetykorea.go.kr&sz=64" width="32" height="32" alt="식품안전나라"></td>
<td><b><a href="https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=C002">식품안전나라 OpenAPI <code>C002</code></a></b><br>
<sub>식품의약품안전처 · 식품(첨가물)품목제조보고(원재료)</sub></td>
<td>제품명 · 업소명 · 식품유형 · <b>원재료 전문</b> · 보고일자 · 품목제조보고번호</td>
</tr>
<tr>
<td align="center"><img src="https://www.google.com/s2/favicons?domain=data.go.kr&sz=64" width="32" height="32" alt="공공데이터포털"></td>
<td><b><a href="https://www.data.go.kr/data/15100066/standard.do">공공데이터포털 표준데이터 <code>15100066</code></a></b><br>
<sub>전국통합식품영양성분정보(가공식품)</sub></td>
<td>열량(kcal) · 당류(g) · 기준량 · 내용량</td>
</tr>
<tr>
<td align="center"><img src="https://www.google.com/s2/favicons?domain=mfds.go.kr&sz=64" width="32" height="32" alt="식품의약품안전처"></td>
<td><b><a href="https://www.mfds.go.kr/">식품의약품안전처</a></b><br>
<sub>제로칼로리 표시 기준</sub></td>
<td>100mL당 4kcal 미만</td>
</tr>
</tbody>
</table>

> **결합 키** — C002 의 `PRDLST_REPORT_NO` ↔ 영양성분 데이터의 `ITEM_MNFTR_RPT_NO`
> (품목제조보고번호). 제품명 문자열이 아니라 **법정 보고번호로 결합**하므로 이름이 비슷한
> 다른 제품이 섞이지 않습니다.

---

## 수집 현황

<!-- STATS:START -->
`2026-10-06` 수집 · `2026-10-06` 산출 기준 — 매월 갱신

| 항목 | 값 |
|---|---:|
| C002 원본 응답 행 | 2,428건 |
| 주류·수출용 등 비대상 제외 | −124건 |
| 제로 표기 없는 일반 음료 제외 | −1,001건 |
| 제품 단위로 통합한 최종 레코드 | **639개** |
| 열량·당류 조인 성공 | 416개 (65.1%) |
| 제품명에 제로 표기 | 328개 |
| └ 그중 **원재료에 당류가 있는 제품** | **16개** |
| 배합 변경 이력이 확인된 제품 | 151개 |
| 제로↔일반판 짝이 매칭된 제품 | 64개 |

### 티어 분포

| 무감미료 | S | A | B | C | D | F |
|---:|---:|---:|---:|---:|---:|---:|
| 7 | 3 | 25 | 330 | 254 | 4 | 16 |

**S 티어 전체 3개** — 알룰로스만 사용:

| 제품명 | 업소명 | 보고일자 |
|---|---|---|
| 테라 제로 | 오케이에프음료 주식회사 외 3곳 | 2026-08-11 |
| 암바사 ZERO by 환타 | 코카콜라음료주식회사 외 1곳 | 2025-04-29 |
| 제로칼로리 포도(알룰로스 100%) CAN | (주)금강비앤에프 | 2023-06-08 |

<!-- STATS:END -->

---

## 티어 기준

원재료에서 감미료를 탐지하고, 여러 감미료가 섞이면 **가장 나쁜 등급이 최종 티어**입니다
(알룰로스 + 수크랄로스 → `B`).

<!-- TIERS:START -->
| 티어 | 성분 | 근거 |
|:---:|---|---|
| **무감미료** | 감미료 표기 없음 | 신고 원재료에 감미료가 없음. 코카콜라 제로처럼 식품첨가물혼합제제로 뭉뚱그려져 감미료를 확인할 수 없는 제품도 여기 들어가며, 이때는 감미료 미표기 표시가 붙습니다 (열량·당류 0 확인 기준) |
| **S** | 알룰로스, 타가토스 | 식후 혈당·인슐린을 오히려 낮춤 (2026 AJCN 메타분석). 알룰로스는 0.4 kcal/g (미국 FDA). 타가토스 열량은 추정치가 1.0~3.0 kcal/g 로 갈림 |
| **A** | 스테비올배당체(스테비아) | 0 kcal. RCT 메타분석에서 공복혈당·당화혈색소·인슐린 상승 없음 (Nutrients 2019·Diabetes Metab Syndr 2024) |
| **B** | 수크랄로스, 아세설팜칼륨, 아스파탐, 사카린, 나한과, 감초추출물 등 | 0 kcal이나 공복 인슐린·HbA1c 소폭 상승 신호 (2026 Tufts 메타분석). 나한과·감초추출물처럼 성분별 메타분석이 없는 비열량 감미료도 이 근거를 따름. 아스파탐·아세설팜칼륨의 안전성은 EFSA 2026 재평가에서 현재 섭취량 기준 우려 없음으로 재확인 |
| **C** | 에리스리톨 | 열량 0·혈당 무해하나 혈전·심혈관 사건 신호 (Nat Med 2023). 단일 연구 수준이고 인과관계는 확정되지 않았지만, 결과가 치명적일 수 있어 예방적으로 반영 |
| **D** | 말티톨, 소르비톨, 자일리톨, 락티톨 등 당알코올 | 1.6~3.0 kcal/g (미국 21 CFR 101.9). 말티톨은 혈당지수 35, 말티톨시럽 48~53으로 혈당 상승 (Nutr Res Rev 2003). 자일리톨은 심혈관 사건 신호도 있음 (Eur Heart J 2024) |
| **F** | 설탕, 액상과당, 농축과즙 등 | 제로를 표방하지만 신고 원재료에 당류가 있음 |
<!-- TIERS:END -->

근거는 피어리뷰된 사람 대상 **메타분석·체계적 고찰**을 가장 무겁게 보고, 단일 연구는 참고로
씁니다. 논문 목록과 최근 연구의 티어 영향은 [연구 동향](https://zero-drinks-tier.vercel.app/research.html)에
정리되어 있습니다.

### 원재료 표기와 실측이 어긋날 때

- **원재료에 당류 표기가 있지만 실측 당류가 0g** — 착향용 미량으로 보고 F 로 판정하지 않습니다.
- **감미료 표기가 없는데 당류가 검출됨** — F 로 판정합니다.
- **원재료가 '식품첨가물혼합제제'로만 신고됨** — 감미료를 확인할 수 없어 `감미료 미표기`로
  표시합니다. 판매처에 실린 제품 라벨·표시사항에서 품목제조보고번호가 C002 와 일치하는
  경우에만 그 원재료로 판정하고, 제품 페이지에 출처를 함께 표시합니다.

### 근거의 한계

- **C 티어의 인과관계는 확정되지 않았습니다.** 에리스리톨의 심혈관 신호는 관찰 코호트와
  혈소판 실험 수준이며 메타분석은 아직 없습니다. 치명적일 수 있는 신호라 등급에 반영했습니다.
- **A 와 B 는 장기 섭취 지표로 갈립니다.** 감미료를 한 번 먹었을 때의 혈당 반응은 종류와
  관계없이 차이가 없습니다([AJCN 2020](https://doi.org/10.1093/ajcn/nqaa167)).
- **티어는 건강 조언이 아닙니다.** 감미료 구성의 상대 비교이며, 섭취량·개인 질환·전체 식단을
  반영하지 않습니다.
- **'제로인데 당류 있음'은 법 위반을 뜻하지 않습니다.** 제로칼로리 표시 기준은 100mL당
  4kcal 미만이므로 소량의 당류가 있어도 '제로'를 표기할 수 있습니다.

---

## 파일

| 파일 | 내용 |
|---|---|
| `zero_soda_raw.json` | C002 원본 응답 스냅샷. `rows` 의 각 행은 C002 응답 필드 10개(`PRDLST_NM`, `RAWMTRL_NM`, `PRDLST_DCNM`, `BSSH_NM`, `PRMS_DT`, `CHNG_DT`, `PRDLST_REPORT_NO`, `RAWMTRL_ORDNO`, `LCNS_NO`, `ETQTY_XPORT_PRDLST_YN`) |
| `zero_soda_nutrition.json` | 품목제조보고번호로 결합한 열량·당류. `rows` 는 보고번호별 영양성분, `checked` 는 조회한 보고번호 전체 |
| `docs/` | 웹사이트 정적 파일 |

## 이용 조건

원본 데이터의 권리는 각 제공 기관에 있습니다. 재사용 조건은 [`NOTICE.md`](NOTICE.md)를
참고하세요. 인용할 때는 원 제공 기관(식품의약품안전처, 공공데이터포털)을 출처로 밝혀 주세요.
