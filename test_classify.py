#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zero_soda_scan.py 분류기·통합·파생플래그 테스트. 네트워크 0, 픽스처 0."""

import unittest

import zero_soda_scan as z


def mk_row(name, raw, prms_dt="20260101", chng_dt="", report_no="1",
           maker="테스트업체", ftype="탄산음료"):
    return {
        "PRDLST_NM": name,
        "RAWMTRL_NM": raw,
        "PRDLST_DCNM": ftype,
        "BSSH_NM": maker,
        "PRMS_DT": prms_dt,
        "CHNG_DT": chng_dt,
        "PRDLST_REPORT_NO": report_no,
    }


class ClassifyTests(unittest.TestCase):
    def test_substring_guard_hwanwon_mulyeot(self):
        r = z.classify("정제수, 환원물엿, 향료")
        self.assertEqual(r["tier"], "D")

    def test_duplicate_hit_dedup_liquid_fructose(self):
        r = z.classify("액상과당, 정제수")
        self.assertEqual(len(r["hits"]), 1)
        self.assertEqual(r["hits"][0]["표기"], "액상과당")
        self.assertEqual(r["tier"], "F")

    def test_real_lime_cider(self):
        raw = ("알룰로오스, 구연산, 수크랄로스, 아세설팜칼륨, 천연향료, 향료, "
               "향료, 향료, 이산화탄소, 정제수")
        r = z.classify(raw)
        self.assertEqual(r["tier"], "B")
        self.assertEqual(r["combo"], "S+B")
        allulose = next(h for h in r["hits"] if h["표기"] == "알룰로오스")
        self.assertEqual(allulose["순번"], 1)

    def test_no_sweetener(self):
        r = z.classify("정제수, 이산화탄소, 천연향료")
        self.assertEqual(r["tier"], "무감미료")
        self.assertEqual(r["combo"], "-")

    def test_opaque_ingredients_are_unknown_not_sweetener_free(self):
        # 코카콜라 제로의 실제 신고 원재료. 감미료가 '없는' 게 아니라 '안 보이는'
        # 것이라 무감미료로 표시하면 사실과 다르다.
        r = z.classify("이산화탄소, 향료, 식품첨가물혼합제제, 정제수")
        self.assertEqual(r["tier"], "?")
        self.assertEqual(r["combo"], "-")

    def test_opaque_with_detected_sweetener_keeps_real_tier(self):
        # 감미료가 하나라도 명시돼 있으면 판정을 보류하지 않는다.
        r = z.classify("정제수, 식품첨가물혼합제제, 수크랄로스")
        self.assertEqual(r["tier"], "B")

    def test_mixed_beverage_base_is_unknown(self):
        r = z.classify("혼합음료, 이산화탄소, 합성향료, 정제수")
        self.assertEqual(r["tier"], "?")

    def test_negation_no_sugar_gum_base(self):
        r = z.classify("정제수, 무설탕껌베이스, 향료")
        self.assertEqual(r["tier"], "무감미료")

    def test_stevia_erythritol_trap(self):
        r = z.classify("정제수, 에리스리톨, 효소처리스테비아")
        self.assertEqual(r["tier"], "C")
        self.assertEqual(r["combo"], "A+C")

    def test_parenthesis_comma_protected(self):
        parts = z.split_ingredients("정제수, 혼합제제(구연산, 향료), 수크랄로스")
        self.assertEqual(len(parts), 3)
        r = z.classify("정제수, 혼합제제(구연산, 향료), 수크랄로스")
        sucralose = next(h for h in r["hits"] if h["표기"] == "수크랄로스")
        self.assertEqual(sucralose["순번"], 3)

    def test_empty_input(self):
        r = z.classify("")
        self.assertEqual(r["tier"], "?")

    def test_tier_rank_order(self):
        order = ["무감미료", "S", "A", "B", "C", "D", "F"]
        ranks = [z.TIER_RANK[t] for t in order]
        self.assertEqual(ranks, sorted(ranks))


class AlcoholClassifyTests(unittest.TestCase):
    def test_malt_hop_extract_beer(self):
        self.assertTrue(z.is_alcoholic("카스 제로", "정제수, 맥아, 이산화탄소, 호프추출물"))

    def test_juju(self):
        self.assertTrue(z.is_alcoholic("하이트 논알콜릭 0.7%", "향료, 정제수, 주정, 이산화탄소"))

    def test_name_signal_makgeolli(self):
        self.assertTrue(z.is_alcoholic("안동역 논알콜 막걸리 맛 음료", "정제수, 이산화탄소, 자일리톨"))

    def test_malt_extract_powder_flavoring_not_beer(self):
        self.assertFalse(z.is_alcoholic("에너린 ENERIN", "정제수, 구연산, 맥아추출물분말"))

    def test_malt_syrup_flavoring_not_beer(self):
        self.assertFalse(z.is_alcoholic("진로 토닉워터 진저에일", "정제수, 이산화탄소, 맥아시럽"))

    def test_ale_substring_trap(self):
        self.assertFalse(z.is_alcoholic("슈웹스 진저에일", "정제수, 이산화탄소, 향료"))

    def test_rum_substring_trap(self):
        self.assertFalse(z.is_alcoholic("칠성사이다제로그린플럼", "정제수, 이산화탄소, 수크랄로스"))

    def test_maker_name_not_used(self):
        self.assertFalse(z.is_alcoholic("OB워터", "정제수, 이산화탄소"))


class CanonicalizeTests(unittest.TestCase):
    def test_recency_picks_latest_change_date(self):
        rows = [
            mk_row("테스트콜라", "정제수, 설탕", prms_dt="20260101", chng_dt="20260105", report_no="A"),
            mk_row("테스트콜라", "정제수, 수크랄로스", prms_dt="20260101", chng_dt="20260110", report_no="B"),
            mk_row("테스트콜라", "정제수, 아스파탐", prms_dt="20260101", chng_dt="20260103", report_no="C"),
        ]
        records = z.canonicalize(rows, {})
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["이력행수"], 3)
        self.assertEqual(rec["원재료전문"], "정제수, 수크랄로스")


class AnnotateTests(unittest.TestCase):
    def test_fake_zero_flagged(self):
        rows = [mk_row("진로토닉워터 제로", "정제수, 설탕, 이산화탄소")]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        rec = records[0]
        self.assertEqual(rec["제로표기"], "Y")
        self.assertEqual(rec["티어"], "F")
        self.assertEqual(rec["제로사칭"], "Y")

    def test_fake_zero_not_flagged_for_c_tier(self):
        rows = [mk_row("제로 콜라", "정제수, 에리스리톨")]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        rec = records[0]
        self.assertEqual(rec["티어"], "C")
        self.assertEqual(rec["제로사칭"], "")

    def test_zero_normal_pairing(self):
        rows = [
            mk_row("얼박사 제로", "정제수, 수크랄로스", report_no="1"),
            mk_row("얼박사", "정제수, 설탕", report_no="2"),
        ]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        by_name = {r["제품명"]: r for r in records}
        self.assertEqual(by_name["얼박사 제로"]["일반판"], "얼박사")
        self.assertEqual(by_name["얼박사 제로"]["일반판티어"], "F")
        self.assertEqual(by_name["얼박사"]["일반판"], "")

    def test_pairing_excludes_zero_token_variants(self):
        rows = [
            mk_row("탐스제로파인애플", "정제수, 이소말토올리고당", report_no="1"),
            mk_row("탐스ZERO파인애플", "정제수, 이소말토올리고당", report_no="2"),
        ]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        for r in records:
            self.assertEqual(r["일반판"], "")

    def test_pairing_picks_worst_normal(self):
        rows = [
            mk_row("테스트콜라제로", "정제수, 수크랄로스", report_no="1"),
            mk_row("테스트콜라", "정제수, 아세설팜", report_no="2"),
            mk_row("테스트 콜라", "정제수, 설탕", report_no="3"),
        ]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        rec = next(r for r in records if r["제품명"] == "테스트콜라제로")
        self.assertEqual(rec["일반판티어"], "F")

    def test_ingredient_flags_positive(self):
        rows = [mk_row("테스트드링크", "정제수, 무수카페인, 아스파탐")]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        rec = records[0]
        self.assertEqual(rec["카페인"], "Y")
        self.assertEqual(rec["아스파탐"], "Y")

    def test_ingredient_flags_negative(self):
        rows = [mk_row("테스트사이다", "정제수, 이산화탄소")]
        records = z.canonicalize(rows, {})
        z.annotate(records)
        rec = records[0]
        self.assertEqual(rec["카페인"], "")
        self.assertEqual(rec["아스파탐"], "")


if __name__ == "__main__":
    unittest.main()


class NameNormalizationTests(unittest.TestCase):
    def test_separator_variants_collapse(self):
        for variant in ["코카·콜라 제로", "코카●콜라 제로", "코카 - 콜라 제로", "코카•콜라 제로"]:
            self.assertEqual(z.norm_name(variant), z.norm_name("코카콜라 제로"))

    def test_parentheses_kept_so_flavors_stay_distinct(self):
        self.assertNotEqual(z.norm_name("콜앤비(트로피칼)"),
                            z.norm_name("콜앤비(핑크 그레이프프룻)"))

    def test_period_kept(self):
        self.assertNotEqual(z.norm_name("1.5 스파클링"), z.norm_name("15 스파클링"))

    def test_display_name_prefers_fewest_symbols(self):
        self.assertEqual(z.display_name(["코카●콜라 제로", "코카·콜라 제로", "코카콜라 제로"]),
                         "코카콜라 제로")

    def test_display_name_breaks_tie_by_frequency(self):
        self.assertEqual(z.display_name(["나랑드사이다", "나랑드사이다", "나랑드 사이다"]),
                         "나랑드사이다")

    def test_canonicalize_merges_spacing_variants(self):
        rows = [mk_row("나랑드 사이다", "정제수, 수크랄로스", prms_dt="20200101", report_no="1"),
                mk_row("나랑드사이다", "정제수, 수크랄로스", prms_dt="20240101", report_no="2")]
        recs = z.canonicalize(rows, {})
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["제품명"], "나랑드사이다")
        self.assertEqual(recs[0]["이력행수"], 2)


class MeasuredZeroTests(unittest.TestCase):
    def test_below_threshold_is_zero(self):
        self.assertEqual(z.kcal_per_100({"열량": "1", "기준량": "100ml"}), 1.0)

    def test_scales_to_100ml(self):
        self.assertAlmostEqual(z.kcal_per_100({"열량": "16", "기준량": "500ml"}), 3.2)

    def test_missing_energy_is_none(self):
        self.assertIsNone(z.kcal_per_100({"열량": "", "기준량": "100ml"}))

    def test_annotate_flags_unlabelled_zero_drink(self):
        recs = [{"제품명": "나랑드사이다", "티어": "B", "원재료전문": "정제수, 수크랄로스",
                 "열량": "0", "기준량": "100ml"}]
        z.annotate(recs)
        self.assertEqual(recs[0]["제로표기"], "N")
        self.assertEqual(recs[0]["실측제로"], "Y")

    def test_annotate_marks_non_zero_when_measured_high(self):
        recs = [{"제품명": "일반사이다", "티어": "F", "원재료전문": "정제수, 설탕",
                 "열량": "40", "기준량": "100ml"}]
        z.annotate(recs)
        self.assertEqual(recs[0]["실측제로"], "N")

    def test_annotate_leaves_blank_without_nutrition(self):
        recs = [{"제품명": "무명사이다", "티어": "B", "원재료전문": "정제수, 수크랄로스",
                 "열량": "", "기준량": ""}]
        z.annotate(recs)
        self.assertEqual(recs[0]["실측제로"], "")


class EnrichJoinTests(unittest.TestCase):
    """I2570/C005/I2852 조인. 필드명은 서비스 상세 페이지 스펙 그대로다."""

    def setUp(self):
        self.rows = [
            mk_row("나랑드사이다", "정제수, 수크랄로스", prms_dt="20240304", report_no="A1"),
            mk_row("킨사이다", "정제수, 설탕", prms_dt="20200101", report_no="B1"),
        ]

    def test_retail_name_replaces_registered_name(self):
        barcode = {"A1": {"유통명": "나랑드 사이다 제로", "바코드": "8801069415014"}}
        recs = z.canonicalize(self.rows, {}, barcode, {})
        r = next(r for r in recs if r["바코드"])
        self.assertEqual(r["제품명"], "나랑드 사이다 제로")
        self.assertEqual(r["등록명"], "나랑드사이다")

    def test_registered_name_kept_when_no_retail_name(self):
        recs = z.canonicalize(self.rows, {}, {}, {})
        r = next(r for r in recs if r["제품명"] == "나랑드사이다")
        self.assertEqual(r["등록명"], "")
        self.assertEqual(r["바코드"], "")

    def test_identical_retail_name_leaves_registered_blank(self):
        recs = z.canonicalize(self.rows, {}, {"A1": {"유통명": "나랑드사이다"}}, {})
        r = next(r for r in recs if r["제품명"] == "나랑드사이다")
        self.assertEqual(r["등록명"], "")

    def test_discontinued_only_when_every_report_no_ended(self):
        rows = [mk_row("옛사이다", "정제수, 설탕", prms_dt="20100101", report_no="C1"),
                mk_row("옛사이다", "정제수, 설탕", prms_dt="20200101", report_no="C2")]
        # 구버전만 단종 -> 현행 제품이므로 살아 있어야 한다
        recs = z.canonicalize(rows, {}, {}, {"C1": {"생산중단일": "20150101"}})
        self.assertEqual(recs[0]["생산중단일"], "")
        # 전부 단종 -> 단종
        recs = z.canonicalize(rows, {}, {},
                              {"C1": {"생산중단일": "20150101"}, "C2": {"생산중단일": "20230101"}})
        self.assertEqual(recs[0]["생산중단일"], "20230101")

    def test_retail_name_found_on_any_history_row(self):
        rows = [mk_row("코카콜라 제로", "정제수", prms_dt="20240101", report_no="D2"),
                mk_row("코카·콜라 제로", "정제수", prms_dt="20100101", report_no="D1")]
        recs = z.canonicalize(rows, {}, {"D1": {"유통명": "코카콜라 제로 250ml"}}, {})
        self.assertEqual(recs[0]["제품명"], "코카콜라 제로 250ml")

    def test_unwrap_treats_no_data_as_empty(self):
        payload = {"I2570": {"total_count": "0",
                             "RESULT": {"CODE": "INFO-200", "MSG": "해당하는 데이터가 없습니다."}}}
        self.assertEqual(z.unwrap(payload, service="I2570"), (0, []))

    def test_unwrap_raises_on_real_error(self):
        payload = {"C005": {"RESULT": {"CODE": "ERROR-503", "MSG": "09시~19시에는..."}}}
        with self.assertRaises(z.ApiError):
            z.unwrap(payload, service="C005")

    def test_unwrap_reads_rows_for_other_service(self):
        payload = {"I2852": {"total_count": "1", "RESULT": {"CODE": "INFO-000"},
                             "row": [{"PRDLST_REPORT_NO": "X1", "END_DT": "20240101"}]}}
        total, rows = z.unwrap(payload, service="I2852")
        self.assertEqual((total, rows[0]["END_DT"]), (1, "20240101"))

    def test_enrich_cache_roundtrip_is_sorted(self):
        import tempfile, os, json as _json
        fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
        try:
            z.write_enrich_cache({"B9": {"유통명": "나"}, "A1": {"유통명": "가"}},
                                 {"C3": {"생산중단일": "20200101"}}, path)
            with open(path, encoding="utf-8") as f:
                raw = _json.load(f)
            self.assertEqual(list(raw["barcode"]), ["A1", "B9"])
            bc, dc = z.load_enrich_cache(path)
            self.assertEqual(bc["A1"]["유통명"], "가")
            self.assertEqual(dc["C3"]["생산중단일"], "20200101")
        finally:
            os.unlink(path)

    def test_missing_cache_is_not_an_error(self):
        self.assertEqual(z.load_enrich_cache("없는파일.json"), ({}, {}))


class EnrichPagingTests(unittest.TestCase):
    """fetch_service_rows: 전수 페이징 + 우리 보고번호만 남기기."""

    def _stub(self, total, page_size=2):
        rows = [{"PRDLST_REPORT_NO": f"R{i}", "PRDT_NM": f"제품{i}", "BRCD_NO": f"88{i:05d}"}
                for i in range(1, total + 1)]
        calls = []

        def fake_call(key, start, end, cond=None, service=None):
            calls.append((start, end))
            page = rows[start - 1:end]
            return {service: {"total_count": str(total),
                              "RESULT": {"CODE": "INFO-000"}, "row": page}}
        return fake_call, calls

    def test_pages_until_total_and_filters_to_wanted(self):
        fake, calls = self._stub(5)
        orig, z.call = z.call, fake
        try:
            found = z.fetch_service_rows("k", "I2570", {}, 2, {"R2", "R5"},
                                         ["PRDT_NM", "BRCD_NO"])
        finally:
            z.call = orig
        self.assertEqual(set(found), {"R2", "R5"})
        self.assertEqual(found["R2"]["PRDT_NM"], "제품2")
        self.assertEqual(calls, [(1, 2), (3, 4), (5, 6)])

    def test_stops_at_call_cap(self):
        fake, calls = self._stub(100)
        orig, z.call = z.call, fake
        try:
            z.fetch_service_rows("k", "I2570", {}, 2, {"R99"}, ["PRDT_NM"], max_calls=3)
        finally:
            z.call = orig
        self.assertEqual(len(calls), 3)

    def test_first_non_empty_value_wins(self):
        rows = [{"PRDLST_REPORT_NO": "R1", "PRDT_NM": "", "BRCD_NO": "880001"},
                {"PRDLST_REPORT_NO": "R1", "PRDT_NM": "진짜이름", "BRCD_NO": "880002"}]

        def fake_call(key, start, end, cond=None, service=None):
            return {service: {"total_count": "2", "RESULT": {"CODE": "INFO-000"}, "row": rows}}
        orig, z.call = z.call, fake_call
        try:
            found = z.fetch_service_rows("k", "I2570", {}, 10, {"R1"}, ["PRDT_NM", "BRCD_NO"])
        finally:
            z.call = orig
        self.assertEqual(found["R1"]["PRDT_NM"], "진짜이름")
        self.assertEqual(found["R1"]["BRCD_NO"], "880001")
