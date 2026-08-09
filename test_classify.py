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
