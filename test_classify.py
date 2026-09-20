#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""z.py 분류기·통합·파생플래그 테스트. 네트워크 0, 픽스처 0."""

import tempfile
import shutil
import os
import html
import json
import re
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


class ManualCaffeineTests(unittest.TestCase):
    """신고 원재료가 혼합제제로 카페인을 가릴 때만 손으로 표시한다 (펩시 계열)."""

    OPAQUE = "정제수, 혼합제제, 혼합제제, 아스파탐, 이산화탄소"

    def _rec(self, labels, raw=None):
        rows = [mk_row("펩시제로슈거", raw or self.OPAQUE, report_no="P1")]
        recs = z.canonicalize(rows, {}, {}, labels)
        z.annotate(recs)
        return recs[0]

    def test_manual_flag_marks_caffeine(self):
        r = self._rec({"P1": {"카페인": "Y", "확인일": "2026-08-20"}})
        self.assertEqual(r["카페인"], "Y")
        self.assertEqual(r["카페인수동"], "Y")

    def test_no_flag_leaves_caffeine_blank(self):
        r = self._rec({})
        self.assertEqual(r["카페인"], "")
        self.assertEqual(r.get("카페인수동", ""), "")

    def test_ingredient_text_wins_over_manual(self):
        # 원재료에 카페인이 적혀 있으면 그게 근거다. 수동 표시로 덮지 않는다.
        r = self._rec({"P1": {"카페인": "Y"}}, raw="정제수, 카페인, 이산화탄소")
        self.assertEqual(r["카페인"], "Y")
        self.assertEqual(r.get("카페인수동", ""), "")

    def test_flag_only_label_does_not_rename_product(self):
        # 유통명 없는 플래그 전용 항목이 제품명·그룹을 건드리면 안 된다.
        r = self._rec({"P1": {"카페인": "Y"}})
        self.assertEqual(r["제품명"], "펩시제로슈거")
        self.assertEqual(r["등록명"], "")
        self.assertEqual(r["유통명출처"], "")


class IndexNowKeyTests(unittest.TestCase):
    """키는 배포 디렉터리에서 스스로 찾는다. 손으로 넣는 환경변수에 의존하면 끊긴다."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = os.environ.pop("INDEXNOW_KEY", None)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        if self.saved is not None:
            os.environ["INDEXNOW_KEY"] = self.saved
        else:
            os.environ.pop("INDEXNOW_KEY", None)

    def _put(self, name, body):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(body)

    def test_finds_key_file(self):
        key = "99deea80987e4be2a215ce8ce2030776"
        self._put(f"{key}.txt", key)
        self.assertEqual(z.indexnow_key(self.dir), key)

    def test_ignores_unrelated_txt(self):
        # llms.txt 처럼 무관한 텍스트 파일을 키로 오인하면 안 된다.
        self._put("llms.txt", "# 안내서\n본문")
        self._put("robots.txt", "User-agent: *\nAllow: /")
        self.assertEqual(z.indexnow_key(self.dir), "")

    def test_ignores_mismatched_content(self):
        # 파일명과 내용이 다르면 키가 아니다.
        self._put("99deea80987e4be2a215ce8ce2030776.txt", "다른내용")
        self.assertEqual(z.indexnow_key(self.dir), "")

    def test_env_wins(self):
        self._put("99deea80987e4be2a215ce8ce2030776.txt", "99deea80987e4be2a215ce8ce2030776")
        os.environ["INDEXNOW_KEY"] = "envkey1234567890"
        self.assertEqual(z.indexnow_key(self.dir), "envkey1234567890")

    def test_write_rejects_bad_format(self):
        self.assertIsNone(z.write_indexnow_key(self.dir, "짧음"))
        self.assertIsNone(z.write_indexnow_key(self.dir, "has space in it"))

    def test_write_creates_matching_file(self):
        key = "abcdef1234567890abcdef1234567890"
        path = z.write_indexnow_key(self.dir, key)
        self.assertTrue(path.endswith(f"{key}.txt"))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), key)


class JosaTests(unittest.TestCase):
    """조사 자동 선택. negative() 가 여러 성분에 재사용되므로 손으로 박으면 언젠가 틀린다."""

    def test_final_consonant_takes_i_eul(self):
        for w in ("아스파탐", "에리스리톨", "카페인", "사카린", "말티톨"):
            self.assertEqual(z._josa(w, "이", "가"), "이", w)
            self.assertEqual(z._josa(w, "을", "를"), "을", w)

    def test_no_final_consonant_takes_ga_reul(self):
        for w in ("알룰로스", "수크랄로스", "타가토스", "스테비아"):
            self.assertEqual(z._josa(w, "이", "가"), "가", w)
            self.assertEqual(z._josa(w, "을", "를"), "를", w)

    def test_empty_is_safe(self):
        self.assertEqual(z._josa("", "이", "가"), "이")


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


class DiscontinuedJoinTests(unittest.TestCase):
    """I2852 생산중단 조인. 필드명은 서비스 상세 페이지 스펙 그대로다."""

    def test_only_current_report_decides_discontinuation(self):
        rows = [mk_row("옛사이다", "정제수, 설탕", prms_dt="20100101", report_no="C1"),
                mk_row("옛사이다", "정제수, 설탕", prms_dt="20200101", report_no="C2")]
        # 구버전(C1)만 단종 -> 현행 보고(C2)가 살아 있으므로 판매 중이다
        recs = z.canonicalize(rows, {}, {"C1": {"생산중단일": "20150101"}})
        self.assertEqual(recs[0]["생산중단일"], "")
        # 현행 보고(C2)가 단종 -> 단종
        recs = z.canonicalize(rows, {},
                              {"C1": {"생산중단일": "20150101"}, "C2": {"생산중단일": "20230101"}})
        self.assertEqual(recs[0]["생산중단일"], "20230101")

    def test_enrich_targets_are_current_rows_of_beverages_only(self):
        rows = [mk_row("옛사이다", "정제수, 설탕", prms_dt="20100101", report_no="C1"),
                mk_row("옛사이다", "정제수, 설탕", prms_dt="20200101", report_no="C2"),
                mk_row("테라 맥주", "정제수, 맥아, 호프", report_no="BEER1"),
                mk_row("베이킹소다", "탄산수소나트륨", report_no="ADD1",
                       ftype="탄산수소나트륨")]
        # 옛사이다는 설탕+제로 표기 없음이라 게시 대상이 아니다 -> 전부 제외
        self.assertEqual(z.enrich_targets(rows, {}), set())

    def test_enrich_targets_keep_current_row_of_published_product(self):
        rows = [mk_row("제로사이다", "정제수, 수크랄로스", prms_dt="20100101", report_no="Z1"),
                mk_row("제로사이다", "정제수, 수크랄로스", prms_dt="20200101", report_no="Z2"),
                mk_row("테라 맥주", "정제수, 맥아, 호프", report_no="BEER1")]
        # 제품당 현행 보고번호 하나만, 주류는 제외
        self.assertEqual(z.enrich_targets(rows, {}), {"Z2"})

    def test_no_cache_means_nothing_discontinued(self):
        rows = [mk_row("킨사이다", "정제수, 설탕", report_no="B1")]
        self.assertEqual(z.canonicalize(rows, {})[0]["생산중단일"], "")

    def test_unwrap_treats_no_data_as_empty(self):
        payload = {"I2852": {"total_count": "0",
                             "RESULT": {"CODE": "INFO-200", "MSG": "해당하는 데이터가 없습니다."}}}
        self.assertEqual(z.unwrap(payload, service="I2852"), (0, []))

    def test_unwrap_raises_on_real_error(self):
        payload = {"I2852": {"RESULT": {"CODE": "ERROR-503", "MSG": "09시~19시에는..."}}}
        with self.assertRaises(z.ApiError):
            z.unwrap(payload, service="I2852")

    def test_unwrap_reads_rows_for_other_service(self):
        payload = {"I2852": {"total_count": "1", "RESULT": {"CODE": "INFO-000"},
                             "row": [{"PRDLST_REPORT_NO": "X1", "END_DT": "20240101"}]}}
        total, rows = z.unwrap(payload, service="I2852")
        self.assertEqual((total, rows[0]["END_DT"]), (1, "20240101"))

    def test_cache_roundtrip_is_sorted_and_keeps_checked(self):
        import tempfile, os, json as _json
        fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
        try:
            z.write_enrich_cache({"B9": {"생산중단일": "20240101"}, "A1": {"생산중단일": "20200101"}},
                                 {"A1", "B9", "C3"}, path)
            with open(path, encoding="utf-8") as f:
                raw = _json.load(f)
            self.assertEqual(list(raw["discontinued"]), ["A1", "B9"])
            dc, checked = z.load_enrich_cache(path)
            self.assertEqual(dc["A1"]["생산중단일"], "20200101")
            # 단종이 아닌 C3 도 기록해 둬야 매달 다시 묻지 않는다
            self.assertIn("C3", checked)
        finally:
            os.unlink(path)

    def test_missing_cache_is_not_an_error(self):
        self.assertEqual(z.load_enrich_cache("없는파일.json"), ({}, set()))


class DiscontinuedFetchTests(unittest.TestCase):
    """fetch_discontinued: 보고번호별 개별 조회. I2852는 전수 페이징이 1,000행에서 잘린다."""

    def _stub(self, ended):
        calls = []

        def fake_call(key, start, end, cond=None, service=None):
            no = (cond or {}).get("PRDLST_REPORT_NO")
            calls.append(no)
            row = [{"PRDLST_REPORT_NO": no, "END_DT": ended[no], "ARTCL_END_WHY": "사유"}] \
                if no in ended else []
            return {service: {"total_count": str(len(row)),
                              "RESULT": {"CODE": "INFO-000"}, "row": row}}
        return fake_call, calls

    def test_queries_each_report_no_and_keeps_only_ended(self):
        fake, calls = self._stub({"R2": "20240101"})
        orig, z.call = z.call, fake
        try:
            found, confirmed = z.fetch_discontinued("k", {"R1", "R2", "R3"})
        finally:
            z.call = orig
        self.assertEqual(sorted(calls), ["R1", "R2", "R3"])
        self.assertEqual(set(found), {"R2"})
        self.assertEqual(found["R2"], {"생산중단일": "20240101", "사유": "사유"})
        # 단종이 아닌 것도 '확인함'에 들어가야 다음 달에 다시 묻지 않는다
        self.assertEqual(confirmed, {"R1", "R2", "R3"})

    def test_quota_error_stops_and_does_not_mark_checked(self):
        seen = []

        def fake_call(key, start, end, cond=None, service=None):
            no = (cond or {}).get("PRDLST_REPORT_NO")
            seen.append(no)
            if len(seen) > 2:
                raise z.ApiError("API 오류 INFO-300: 유효 호출건수를 이미 초과하셨습니다.")
            return {service: {"total_count": "0", "RESULT": {"CODE": "INFO-000"}, "row": []}}
        orig, z.call = z.call, fake_call
        try:
            found, confirmed = z.fetch_discontinued("k", {f"R{i}" for i in range(9)})
        finally:
            z.call = orig
        self.assertEqual(found, {})
        self.assertEqual(len(confirmed), 2)      # 성공한 2개만
        self.assertEqual(len(seen), 3)           # 한도 감지 즉시 중단

    def test_respects_call_cap(self):
        fake, calls = self._stub({})
        orig, z.call = z.call, fake
        try:
            z.fetch_discontinued("k", {f"R{i}" for i in range(10)}, max_calls=4)
        finally:
            z.call = orig
        self.assertEqual(len(calls), 4)

    def test_one_failure_does_not_abort_the_rest(self):
        def fake_call(key, start, end, cond=None, service=None):
            no = (cond or {}).get("PRDLST_REPORT_NO")
            if no == "R1":
                raise z.ApiError("일시 오류")
            return {service: {"total_count": "1", "RESULT": {"CODE": "INFO-000"},
                              "row": [{"END_DT": "20240101"}]}}
        orig, z.call = z.call, fake_call
        try:
            found, confirmed = z.fetch_discontinued("k", {"R1", "R2"})
        finally:
            z.call = orig
        self.assertEqual(set(found), {"R2"})
        self.assertEqual(confirmed, {"R2"})      # 실패한 R1 은 확인함에 안 들어간다


class RetailLabelTests(unittest.TestCase):
    """공식몰 고시에서 확인한 유통명 반영. 품목제조보고번호로 조인한다."""

    LBL = {"R2": {"유통명": "나랑드사이다 제로", "출처": "https://example.com/p", "확인일": "2026-08-10"}}

    def test_retail_name_replaces_registered_and_keeps_source(self):
        rows = [mk_row("나랑드사이다", "정제수, 수크랄로스", prms_dt="20240101", report_no="R2")]
        r = z.canonicalize(rows, {}, {}, self.LBL)[0]
        self.assertEqual(r["제품명"], "나랑드사이다 제로")
        self.assertEqual(r["등록명"], "나랑드사이다")
        self.assertEqual(r["유통명출처"], "https://example.com/p")

    def test_without_label_registered_name_is_used(self):
        rows = [mk_row("나랑드사이다", "정제수, 수크랄로스", report_no="R9")]
        r = z.canonicalize(rows, {}, {}, self.LBL)[0]
        self.assertEqual(r["제품명"], "나랑드사이다")
        self.assertEqual((r["등록명"], r["유통명출처"]), ("", ""))

    def test_duplicate_registrations_merge_into_one_product(self):
        # 같은 제품이 등록명과 유통명 양쪽으로 신고된 경우
        rows = [mk_row("나랑드사이다 그린애플", "정제수, 알룰로오스", prms_dt="20200101", report_no="G1"),
                mk_row("나랑드사이다 제로 그린애플", "정제수, 알룰로오스", prms_dt="20240101", report_no="G2")]
        labels = {"G1": {"유통명": "나랑드사이다 제로 그린애플", "출처": "u", "확인일": "d"}}
        recs = z.canonicalize(rows, {}, {}, labels)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["제품명"], "나랑드사이다 제로 그린애플")
        self.assertEqual(recs[0]["이력행수"], 2)

    def test_partial_labelling_does_not_split_a_product(self):
        # 여러 공장 중 하나만 라벨에 실려도 제품이 쪼개지면 안 된다
        rows = [mk_row("나랑드사이다", "정제수, 수크랄로스", prms_dt="20200101", report_no="R2"),
                mk_row("나랑드사이다", "정제수, 수크랄로스", prms_dt="20100101", report_no="R7")]
        recs = z.canonicalize(rows, {}, {}, self.LBL)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["이력행수"], 2)

    def test_missing_label_file_is_not_an_error(self):
        self.assertEqual(z.load_labels("없는파일.json"), {})


class LabelIngredientTests(unittest.TestCase):
    """고시 표시 원재료로 '확인 불가'를 해소한다. 코카콜라 제로가 이 경로로 교정된다."""

    OPAQUE = "정제수, 식품첨가물혼합제제, 향료, 이산화탄소"
    LBL = {"K1": {"유통명": "코카콜라 제로",
                  "원재료": "정제수, 탄산가스, 카라멜색소, 인산, 천연착향료, "
                            "합성감미료(아스파탐, 아세설팜칼륨), 천연카페인(향미증진제)",
                  "출처": "https://example.com/p", "확인일": "2026-08-11"}}

    def _rec(self, labels):
        rows = [mk_row("코카콜라 제로", self.OPAQUE, report_no="K1")]
        recs = z.canonicalize(rows, {}, {}, labels)
        z.annotate(recs)
        return recs[0]

    def test_label_ingredients_resolve_unknown_tier(self):
        r = self._rec(self.LBL)
        self.assertEqual(r["티어"], "B")
        self.assertEqual(r["감미료미표기"], "")
        self.assertEqual(r["유통명출처"], "https://example.com/p")

    def test_without_label_it_stays_unknown_and_flagged(self):
        r = self._rec({})
        self.assertEqual(r["감미료미표기"], "Y")
        self.assertNotEqual(r["티어"], "B")

    def test_flags_read_label_ingredients(self):
        r = self._rec(self.LBL)
        self.assertEqual(r["아스파탐"], "Y")
        self.assertEqual(r["카페인"], "Y")

    def test_label_ingredients_do_not_override_a_known_tier(self):
        # C002 로 이미 판정된 제품은 건드리지 않는다. 정부 신고 데이터가 우선이다.
        rows = [mk_row("어떤사이다", "정제수, 에리스리톨", report_no="K1")]
        recs = z.canonicalize(rows, {}, {}, self.LBL)
        self.assertEqual(recs[0]["티어"], "C")

    def test_label_overrides_no_sweetener_filing(self):
        # C002 신고서에 감미료가 아예 없어 '무감미료'로 잡혔더라도, 라벨에 감미료가
        # 명시돼 있으면 라벨을 따른다. '없음'보다 '있음'이 구체적인 증거다.
        # 실제 사례: 제로슈거 하이진저 (신고서 감미료 0건, 라벨은 알룰로스+수크랄로스+아세설팜)
        rows = [mk_row("제로슈거 하이진저", "정제수, 생강착즙액, 탄산가스", report_no="K2")]
        labels = {"K2": {"유통명": "제로슈거 하이진저",
                         "원재료": "정제수, 액상 알룰로스, 감미료(수크랄로스, 아세설팜칼륨), 탄산가스",
                         "출처": "https://example.com/hi", "확인일": "2026-08-20"}}
        r = z.canonicalize(rows, {}, {}, labels)[0]
        self.assertEqual(r["티어"], "B")
        self.assertEqual(r["조합"], "S+B")

    def test_label_can_confirm_no_sweetener(self):
        # 라벨에도 감미료가 없으면 무감미료가 확정된다. 경고 표시가 사라져야 한다.
        # 실제 사례: 하이트제로 0.00 (폴리덱스트로스는 식이섬유다)
        rows = [mk_row("하이트제로 0.00", self.OPAQUE, report_no="K3")]
        labels = {"K3": {"유통명": "하이트제로 0.00",
                         "원재료": "정제수, 폴리덱스트로스, 이산화탄소, 맥아추출베이스, 홉추출물",
                         "출처": "https://example.com/hz", "확인일": "2026-08-20"}}
        recs = z.canonicalize(rows, {}, {}, labels)
        z.annotate(recs)
        self.assertEqual(recs[0]["티어"], "무감미료")
        self.assertEqual(recs[0]["감미료미표기"], "")

class PaletteSyncTests(unittest.TestCase):
    """색은 _PALETTE_CSS 하나에서만 나온다.

    예전에는 팔레트를 리포트와 정적 페이지에 복사해 두었다가, 한쪽만 고쳐서
    다크모드가 리포트에만 먹는 사고가 났다. 지금은 같은 문자열을 공유한다.
    """

    def _report_css(self):
        tpl = re.search(r'_HTML_TEMPLATE = r"""(.*?)\n"""',
                        open('zero_soda_scan.py', encoding='utf-8').read(), re.S).group(1)
        return re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)

    def test_both_stylesheets_share_one_palette(self):
        self.assertIn("__PALETTE__", self._report_css(),
                      "리포트가 팔레트를 인라인으로 갖고 있다 - 복사본을 만들지 말 것")
        self.assertTrue(z._STATIC_CSS.startswith(z._PALETTE_CSS),
                        "정적 CSS 가 공유 팔레트로 시작하지 않는다")

    def test_no_hardcoded_colors_outside_the_palette(self):
        for name, css in (("정적", z._STATIC_CSS.replace(z._PALETTE_CSS, "")),
                          ("리포트", self._report_css())):
            # var(--tc,#fff) 형태의 폴백은 허용한다 - 토큰이 없을 때의 방어값이고
            # 팔레트를 우회하지 않는다.
            stripped = re.sub(r"var\(--[a-z0-9-]+,\s*#[0-9a-fA-F]{3,6}\)", "", css)
            leaked = [h for h in re.findall(r"#[0-9a-fA-F]{3,6}", stripped)
                      if h not in z._THEME_CSS]
            self.assertEqual(leaked, [], f"{name} CSS 에 하드코딩 색이 남았다: {leaked}")

    def test_three_theme_modes_are_expressible(self):
        pal = z._PALETTE_CSS
        # 자동: 미디어 쿼리. 단, 사용자가 라이트를 고르면 이겨야 한다.
        self.assertIn("@media (prefers-color-scheme: dark)", pal)
        self.assertIn(':root:not([data-theme="light"])', pal)
        # 명시 선택: 속성 선택자
        self.assertIn(':root[data-theme="dark"]{', pal)
        self.assertIn(':root[data-theme="light"]{color-scheme:light}', pal)
        # 다크 토큰이 자동·명시 두 경로에 다 들어갔는지
        self.assertEqual(pal.count("--bg:#101315"), 2)

    def test_theme_boot_is_synchronous_and_in_head(self):
        boot = z._THEME_BOOT_JS
        self.assertNotIn("defer", boot)
        self.assertNotIn("async", boot)
        self.assertIn("localStorage", boot)
        tpl = re.search(r'_HTML_TEMPLATE = r"""(.*?)\n"""',
                        open('zero_soda_scan.py', encoding='utf-8').read(), re.S).group(1)
        head = tpl.split("</head>")[0]
        self.assertIn("__THEME_BOOT__", head, "FOUC 방지 스크립트가 head 밖에 있다")

    def test_search_input_focus_does_not_hardcode_white(self):
        # 다크에서 흰 배경 + 거의 흰 글자가 되어 입력이 안 보이던 버그
        css = self._report_css()
        focus = re.search(r"input\[type=search\]:focus\{([^}]*)\}", css).group(1)
        self.assertNotIn("#fff", focus)
        self.assertIn("background:var(--surface)", focus)


class ProductPageTests(unittest.TestCase):
    def test_slugs_are_unique_and_url_safe(self):
        import re
        recs = [{"제품명": "코카콜라 제로"}, {"제품명": "코카콜라·제로"},
                {"제품명": "A/B (테스트)"}, {"제품명": "코카콜라 제로"}]
        z.assign_slugs(recs)
        slugs = [r["슬러그"] for r in recs]
        self.assertEqual(len(set(slugs)), len(slugs), f"슬러그 충돌: {slugs}")
        for s in slugs:
            self.assertNotRegex(s, r'[\\/:*?"<>|#%&]', f"파일명·URL 에 위험한 문자: {s}")
            self.assertTrue(s)

    def test_sugar_tokens_are_not_called_sweeteners(self):
        rec = {"감미료": "수크랄로스(B,5) / 아세설팜(B,19) / 농축과즙(SUGAR,11)"}
        sweet, sugar = z._sweetener_rows(rec)
        self.assertEqual([w for w, _ in sweet], ["수크랄로스", "아세설팜"])
        self.assertEqual([w for w, _ in sugar], ["농축과즙"])

class SiteIdentityTests(unittest.TestCase):
    """사이트 이름은 통일하고 엔티티 이름은 구분한다.

    'SEO 에 좋으니 전부 통일하자' 는 반쯤만 맞다. 검색엔진이 교차 검증하는 것은
    사이트 이름(og:site_name / WebSite.name / title)뿐이다. Person·Dataset 은
    서로 다른 엔티티이고, 같은 문자열로 두면 Knowledge Graph 에서 뭉개진다.
    """

    def setUp(self):
        self.ld = z.site_ld(616, "2026-01-01")
        self.nodes = {n["@type"]: n for n in self.ld["@graph"]}

    def test_site_name_matches_across_every_slot(self):
        name = self.nodes["WebSite"]["name"]
        self.assertEqual(name, z.SITE_NAME)
        # 메인 랜딩과 정적 페이지 셸이 같은 상수를 쓴다
        self.assertIn('content="{site_name}"', z._LANDING_TEMPLATE)
        self.assertIn("{site_name}", z._LANDING_TEMPLATE.split("</title>")[0])
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertIn('og:site_name" content="{_STATIC_PAGE_SITE_NAME}"', src)

    def test_entity_names_stay_distinct(self):
        site = self.nodes["WebSite"]["name"]
        self.assertNotEqual(self.nodes["Person"]["name"], site,
                            "발행 주체 이름이 사이트 이름과 같으면 엔티티가 겹친다")
        self.assertNotEqual(self.nodes["Dataset"]["name"], site,
                            "Dataset 은 서술적 제목을 쓴다 - alternateName 으로 연결한다")
        self.assertEqual(self.nodes["Dataset"]["alternateName"], site)

    def test_publisher_is_a_real_referenced_entity(self):
        for node in ("WebSite", "Dataset"):
            self.assertEqual(self.nodes[node]["publisher"]["@id"],
                             self.nodes["Person"]["@id"],
                             f"{node}.publisher 가 정의된 엔티티를 가리키지 않는다")
        self.assertIn("github.com/gulf1324", self.nodes["Person"]["sameAs"][0])

    def test_search_action_points_at_a_working_query_url(self):
        tpl = self.nodes["WebSite"]["potentialAction"]["target"]["urlTemplate"]
        self.assertIn("?q={search_term_string}", tpl)
        # 선언한 파라미터 이름이 실제 프리필 코드와 같아야 한다
        self.assertIn("get('q')", z._FINDER_JS)
        # 메인 검색 폼도 같은 이름·같은 목적지를 쓴다 (JS 없이도 동작해야 한다)
        self.assertIn('action="{page_url}products.html" method="get"', z._LANDING_TEMPLATE)
        self.assertIn('name="q"', z._LANDING_TEMPLATE)

    def test_only_the_home_page_declares_the_website_node(self):
        # WebPage 노드는 하위 페이지에만 붙는다
        self.assertNotIn("WebPage", self.nodes)
        sub = {n["@type"] for n in z.site_ld(616, "2026-01-01", "report.html")["@graph"]}
        self.assertIn("WebPage", sub)


class FaqTests(unittest.TestCase):
    """FAQ 는 가시 텍스트와 LD 가 글자까지 같아야 한다.

    화면에 없는 것을 구조화 데이터가 주장하면 스팸 판정 위험이고, 이 프로젝트의
    제1원칙(데이터에 없으면 없다고 쓴다)에도 어긋난다.
    """

    LBL = {"K1": {"유통명": "", "원재료": "", "출처": "", "확인일": ""}}

    def _rec(self, **kw):
        base = {"제품명": "테스트 제로", "티어": "B", "감미료": "수크랄로스(B,1)",
                "열량": "0", "당류": "0.00", "용량": "500ml", "기준량": "100ml",
                "아스파탐": "", "감미료미표기": "", "업소명": "테스트공장"}
        base.update(kw)
        return base

    def _strip(self, s):
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s)).strip())

    def test_visible_block_and_ld_carry_identical_text(self):
        pairs = [("질문인가요?", "답 <b>강조</b>입니다.")]
        vis = self._strip(z._faq_block(pairs))
        node = z._faq_ld(pairs)
        for q in node["mainEntity"]:
            self.assertIn(q["name"], vis)
            self.assertIn(q["acceptedAnswer"]["text"], vis)
            self.assertNotIn("<b>", q["acceptedAnswer"]["text"], "LD 에 태그가 남았다")

    def test_merge_keeps_existing_graph_nodes(self):
        ld = {"@context": "https://schema.org",
              "@graph": [{"@type": "Product", "name": "x"}]}
        out = z._merge_ld(ld, [("q?", "a")])
        self.assertEqual([n["@type"] for n in out["@graph"]], ["Product", "FAQPage"])
        # @graph 가 없는 단일 노드도 감싸 준다
        out2 = z._merge_ld({"@context": "https://schema.org", "@type": "ItemList"},
                           [("q?", "a")])
        self.assertEqual([n["@type"] for n in out2["@graph"]], ["ItemList", "FAQPage"])

    def test_opaque_product_never_claims_absence(self):
        rec = self._rec(감미료="", 감미료미표기="Y", 아스파탐="")
        pairs = z.product_faqs(rec, [], [], None)
        joined = " ".join(a for _, a in pairs)
        self.assertIn("확인할 수 없", joined)
        self.assertNotIn("탐지되지 않았습니다", joined,
                         "원재료가 가려진 제품에 '없다' 계열 답을 쓰면 안 된다")

    def test_missing_nutrition_is_not_reported_as_zero(self):
        rec = self._rec(열량="", 당류="")
        pairs = z.product_faqs(rec, [("수크랄로스", "B")], [], None)
        kcal = [a for q, a in pairs if "칼로리" in q][0]
        self.assertIn("확인할 수 없습니다", kcal)
        self.assertIn("0이라는 뜻이 아닙니다", kcal)

    def test_question_particles_follow_the_product_name(self):
        # '코카콜라 제로은' 같은 오류가 실제로 배포됐다
        # 숫자는 한국어 읽기(영·일·삼·육·칠·팔에 종성)를, 단위는 읽은 말을 따른다
        for name, want in (("코카콜라 제로", "제로는"), ("밀키스제로딸기바나나", "바나나는"),
                           ("하이트제로 0.00", "0.00은"), ("경이로운 프로틴 240ml", "240ml는"),
                           ("피타팝 250ML", "250ML는")):
            pairs = z.product_faqs(self._rec(제품명=name), [("수크랄로스", "B")], [], None)
            q = [q for q, _ in pairs if "칼로리" in q][0]
            self.assertIn(want, q, f"{name}: {q}")

    def test_landing_faq_reuses_the_pages_own_answer(self):
        lead = "확인된 것은 <b>10개</b>입니다."
        pairs = z.landing_faqs("아스파탐이 없는 제로 음료는 무엇인가요?", lead,
                               [("아스파탐을 넣었는지 확인할 수 없는 3개", "", [1, 2, 3])], 616)
        self.assertEqual(pairs[0], ("아스파탐이 없는 제로 음료는 무엇인가요?", lead))
        murky = [a for q, a in pairs if "들어 있지 않다는 뜻인가요" in q][0]
        self.assertIn("3개", murky)
        self.assertIn("아니요", murky)

    def test_landing_faq_omits_the_murky_question_when_absent(self):
        pairs = z.landing_faqs("전체 목록인가요?", "네.", [], 616)
        self.assertEqual(len(pairs), 2)

class PublishScopeTests(unittest.TestCase):
    """배포 대상과 산출물이 어긋나면 404 가 난다.

    사이트맵은 푸시되는데 제품 페이지가 푸시되지 않아 새 URL 이 404 가 되는
    사고가 실제로 대기 중이었다 (2026-09-08 발견).
    """

    def test_product_pages_are_in_push_paths(self):
        self.assertIn(os.path.join("docs", "p"), z.PUSH_PATHS,
                      "제품별 페이지가 git_push 대상에서 빠졌다 - 새 URL 이 404 가 된다")

    def test_sitemap_targets_are_all_pushed(self):
        # 사이트맵에 들어가는 산출물은 전부 푸시 대상이어야 한다
        for name in ("sitemap.xml", "robots.txt", "products.html", "allulose.html",
                     "no-aspartame.html", "no-erythritol.html", "no-caffeine.html",
                     "fake-zero.html", "hidden-zero.html"):
            self.assertIn(os.path.join("docs", name), z.PUSH_PATHS, name)
        self.assertIn(z.DEFAULT_DOCS_HTML, z.PUSH_PATHS)

    def test_renamed_product_leaves_no_orphan_page(self):
        d = tempfile.mkdtemp()
        try:
            recs = [{"제품명": "옛 이름 제로", "티어": "B", "감미료": "수크랄로스(B,1)",
                     "열량": "0", "당류": "0.00", "용량": "500ml", "기준량": "100ml",
                     "업소명": "공장", "식품유형": "탄산음료", "보고일자": "20260101",
                     "원재료전문": "정제수", "등록명": "", "이력": []}]
            z.assign_slugs(recs)
            z.write_product_pages(d, recs, "2026-01-01")
            old = os.path.join(d, "p", "옛-이름-제로.html")
            self.assertTrue(os.path.exists(old))

            recs[0]["제품명"] = "새 이름 제로"
            z.assign_slugs(recs)
            z.write_product_pages(d, recs, "2026-01-01")
            self.assertTrue(os.path.exists(os.path.join(d, "p", "새-이름-제로.html")))
            self.assertFalse(os.path.exists(old),
                             "이름이 바뀐 제품의 옛 페이지가 고아로 남았다")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ManualLabelTests(unittest.TestCase):
    """수동 등록 성분(zero_soda_label.json)은 코드가 절대 쓰지 않는다."""

    def test_label_file_is_read_only_in_source(self):
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        for m in re.finditer(r'open\(([^,]+),\s*["\']w', src):
            self.assertNotIn("LABEL", m.group(1).upper(),
                             "라벨 파일을 쓰는 코드가 생겼다 - 수동 입력이 날아간다")
        self.assertNotIn("DEFAULT_LABEL_FILE, \"w\"", src)

    def test_label_file_is_not_auto_committed(self):
        # 손으로 검증해 넣는 파일이라 자동 커밋 대상에 넣지 않는다.
        # 반쯤 입력한 상태가 '데이터 동기화' 커밋에 섞이면 되돌리기 어렵다.
        self.assertNotIn(z.DEFAULT_LABEL_FILE, z.PUSH_PATHS)

class LandingTests(unittest.TestCase):
    """메인은 검색 하나로 끝내는 짧은 페이지다.

    626행 표를 메인에 두면 스크롤이 13.7화면(12,633px)이 되고 그 아래 섹션은
    아무도 보지 못한다. 실측으로 확인하고 표를 /report.html 로 옮겼다.
    """

    def _recs(self, names):
        out = []
        for i, n in enumerate(names):
            out.append({"제품명": n, "티어": "B", "조합": "B",
                        "감미료": "수크랄로스(B,1)", "열량": "0", "당류": "0.00",
                        "용량": "500ml", "기준량": "100ml", "업소명": "공장",
                        "식품유형": "탄산음료", "보고일자": "20260101",
                        "원재료전문": "정제수", "등록명": "", "이력": [],
                        "감미료미표기": "", "아스파탐": "", "카페인": ""})
        z.assign_slugs(out)
        return out

    def test_landing_has_no_product_table(self):
        recs = self._recs(z.POPULAR_PICKS)
        page = z.landing_page(recs, "2026-01-01", {"records": recs})
        self.assertNotIn("<tr", page, "메인에 표가 들어갔다 - 스크롤이 길어진다")

    def test_landing_links_to_the_full_report_and_list(self):
        recs = self._recs(z.POPULAR_PICKS)
        page = z.landing_page(recs, "2026-01-01", {"records": recs})
        for target in ("report.html", "products.html", "llms-full.txt"):
            self.assertIn(z.PAGE_URL + target, page, f"{target} 링크가 없다")

    def test_popular_picks_all_resolve_to_real_products(self):
        # 인기 제품 목록에 데이터에 없는 이름을 적으면 카드가 조용히 사라진다
        recs = self._recs(z.POPULAR_PICKS)
        cards = z._pick_cards(recs)
        self.assertEqual(cards.count('class="pick"'), len(z.POPULAR_PICKS))

    def test_landing_makes_no_sales_or_ranking_claim(self):
        """판매량·순위는 우리가 측정한 값이 아니다.

        출처 표기를 지운 만큼 주장도 하지 않는다. '많이 찾는 제품'은 편집 선택이고
        섹션 제목도 그 이상을 말하지 않는다.
        """
        recs = self._recs(z.POPULAR_PICKS)
        page = z.landing_page(recs, "2026-01-01", {"records": recs})
        for claim in ("판매량", "판매 1위", "베스트셀러", "가장 많이 팔린", "점유율"):
            self.assertNotIn(claim, page, f"측정하지 않은 값을 주장한다: {claim}")
        self.assertIn("많이 찾는 제품", page)

    def test_report_is_published_at_its_own_url(self):
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertIn('"report.html"', src)
        self.assertIn(os.path.join("docs", "report.html"), z.PUSH_PATHS,
                      "리포트가 푸시 대상에서 빠졌다")
        self.assertIn('canonical" href="__PAGE_URL__report.html"', src,
                      "리포트 canonical 이 메인을 가리키면 중복 판정된다")

    def test_suggest_payload_stays_small(self):
        # 절대 URL 을 626개 실으면 45KB 가 더 붙는다. 슬러그만 싣고 JS 가 만든다.
        self.assertIn("encodeURIComponent(r.g)", z._SUGGEST_JS)
        self.assertNotIn("r.u", z._SUGGEST_JS)

    def test_suggest_prefers_the_shortest_name_on_a_tie(self):
        # '코카' 로 치면 '코카콜라 제로'가 '코카-콜라 제로 레몬'보다 먼저 와야 한다
        self.assertIn("a.n.length - b.n.length", z._SUGGEST_JS)

class ThemeUiScopeTests(unittest.TestCase):
    """테마 토글의 CSS·마크업·스크립트는 한 묶음으로 움직여야 한다.

    .topbar 규칙이 리포트 템플릿에만 있어서, 메인 랜딩에서는 톱니가 좌측 상단에
    가고 메뉴만 right:0 기준으로 우측에 떠 둘이 갈라졌다 (2026-09-14 버그).
    """

    def test_topbar_rule_lives_in_shared_theme_css(self):
        self.assertIn(".topbar{", z._THEME_CSS,
                      ".topbar 가 공유 CSS 밖에 있으면 페이지마다 정렬이 갈린다")
        self.assertIn("justify-content:flex-end", z._THEME_CSS)
        # 템플릿 쪽에 중복 정의가 남아 있으면 또 갈라진다
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertEqual(src.count(".topbar{"), 1)

    def test_every_theme_consumer_gets_css_ui_and_js(self):
        # 랜딩: 세 조각이 다 들어간다
        # 랜딩은 _STATIC_CSS 를 싣고, 그 안에 _THEME_CSS 가 이미 들어 있다.
        # {theme_css} 를 따로 넣으면 같은 규칙이 두 번 나간다.
        self.assertIn("{static_css}", z._LANDING_TEMPLATE)
        self.assertNotIn("{theme_css}", z._LANDING_TEMPLATE)
        self.assertIn("{theme_ui}", z._LANDING_TEMPLATE)
        self.assertIn("{theme_js}", z._LANDING_TEMPLATE)
        self.assertIn("{theme_boot}", z._LANDING_TEMPLATE)
        # 정적 페이지: _STATIC_CSS 가 _THEME_CSS 를 품고, 셸이 UI·JS 를 싣는다
        self.assertIn(z._THEME_CSS, z._STATIC_CSS)
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertIn("{_THEME_UI}", src)
        self.assertIn("{_THEME_JS}", src)

    def test_menu_anchors_to_the_button_not_the_page(self):
        # 메뉴는 .themer 기준으로 뜬다. .themer 가 늘어나면 버튼과 갈라진다.
        self.assertIn(".themer{position:relative", z._THEME_CSS)
        self.assertIn("flex:none", z._THEME_CSS)
        self.assertIn(".theme-menu{position:absolute", z._THEME_CSS)

class LandingBrevityTests(unittest.TestCase):
    """메인은 인상 파악용이다. 자세히 볼 페이지가 따로 있는 내용을 그대로 옮기면 안 된다.

    첫 방문자는 페이지 인상을 보고 원하는 것이 없으면 바로 떠난다. 그래서 메인의
    각 섹션은 '한 줄 판정 + 숫자'로 끝내고, 근거·한계·설명문은 /report.html 과
    의도 랜딩으로 보낸다.
    """

    def _recs(self):
        out = [{"제품명": n, "티어": t, "조합": t, "감미료": "수크랄로스(B,1)",
                "열량": "0", "당류": "0.00", "용량": "500ml", "기준량": "100ml",
                "업소명": "공장", "식품유형": "탄산음료", "보고일자": "20260101",
                "원재료전문": "정제수", "등록명": "", "이력": [], "감미료미표기": "",
                "아스파탐": "", "카페인": ""}
               for n, t in zip(z.POPULAR_PICKS, ["B"] * len(z.POPULAR_PICKS))]
        z.assign_slugs(out)
        return out

    def test_tier_section_is_a_strip_not_the_full_legend(self):
        recs = self._recs()
        page = z.landing_page(recs, "2026-01-01", {"records": recs})
        self.assertEqual(page.count('class="tcell"'), len(z._TIER_ROWS))
        # 티어 섹션 자체에는 근거 문장이 없다 (스트립은 한 줄 판정만)
        strip = re.search(r'<div class="tstrip">(.*?)</div>\s*\n', page, re.S).group(1)
        self.assertNotIn("tier-why", strip)
        for evidence in ("AJCN", "Tufts", "Cleveland Clinic", "GI 35~52"):
            self.assertNotIn(evidence, strip, f"근거 문장이 스트립에 들어왔다: {evidence}")
        # 상세 기준표는 FAQ 안에 '접힌 채로'만 존재한다 - 펼쳐 두면 스크롤이 길어진다
        legend = re.search(r'<details class="faq-legend">(.*?)</details>', page, re.S)
        self.assertIsNotNone(legend, "티어 기준표가 사라졌다")
        self.assertNotIn("open", page[page.index('<details class="faq-legend"')
                                       :page.index('<details class="faq-legend"') + 34])
        self.assertIn("tier-why", legend.group(1))

    def test_every_tier_has_a_one_line_gist(self):
        for tier, _, _ in z._TIER_ROWS:
            self.assertIn(tier, z._TIER_GIST, f"{tier} 의 한 줄 판정이 없다")
            ing, gist = z._TIER_GIST[tier]
            self.assertLessEqual(len(ing), 16, f"{tier} 성분 요약이 길다: {ing}")
            self.assertLessEqual(len(gist), 16, f"{tier} 판정이 길다: {gist}")

    def test_tier_strip_shows_counts_from_the_data(self):
        recs = self._recs()
        strip = z.tier_strip_html(recs)
        self.assertIn(f">{len(recs)}개<", strip, "B 등급 제품 수가 데이터와 다르다")
        self.assertIn(">0개<", strip, "0건인 등급도 숨기지 않고 보여준다")

    def test_condition_links_are_pills_without_descriptions(self):
        recs = self._recs()
        page = z.landing_page(recs, "2026-01-01", {"records": recs})
        self.assertIn('class="pills"', page)
        # 카드형 설명문(.guides span)은 메인에서 쓰지 않는다
        self.assertNotIn('class="guides"', page)
        for note in ("한눈에 볼 수 있습니다", "신경 쓰일 때 봅니다", "계열을 제외했습니다"):
            self.assertNotIn(note, page, f"설명문이 메인에 남았다: {note}")

    def test_pills_cover_every_intent_landing(self):
        html_out = z.guide_pills_html(626)
        for slug in ("allulose.html", "no-aspartame.html", "no-erythritol.html",
                     "no-caffeine.html", "fake-zero.html", "hidden-zero.html",
                     "products.html"):
            self.assertIn(z.PAGE_URL + slug, html_out, f"{slug} 알약이 없다")

class ReportUiTests(unittest.TestCase):
    """고급 검색(/report.html) 화면 규약."""

    def _css(self):
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        tpl = re.search(r'_HTML_TEMPLATE = r"""(.*?)\n"""', src, re.S).group(1)
        return tpl, re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)

    def test_tier_legend_starts_collapsed(self):
        tpl, _ = self._css()
        self.assertIn('<details class="panel tierlegend">', tpl)
        self.assertNotIn('class="panel tierlegend" open', tpl,
                         "787px 짜리 기준표를 처음부터 펼쳐 두면 표가 밀려난다")

    def test_sort_select_never_matches_the_search_width(self):
        # 셀렉트가 가로로 늘어나면 검색 입력과 구분이 안 된다 (실제 혼동 신고)
        _, css = self._css()
        mobile = css.split("@media (max-width:820px)")[-1]
        self.assertNotIn(".sortsel select{flex:1", mobile)
        self.assertIn("max-width:148px", mobile)
        self.assertIn(".sortsel{display:flex;margin-left:0;width:auto}", mobile)

    def test_search_inputs_have_no_placeholder_but_keep_a_label(self):
        tpl, _ = self._css()
        inp = re.search(r'<input type="search" id="q".*?>', tpl, re.S).group(0)
        self.assertNotIn("placeholder", inp)
        self.assertIn("aria-label", inp)
        # 메인도 같은 규칙
        main = re.search(r'<input type="search" id="q".*?>', z._LANDING_TEMPLATE, re.S).group(0)
        self.assertNotIn("placeholder", main)
        self.assertIn("aria-label", main)

    def test_logo_returns_to_the_home_page(self):
        """로고를 누르면 홈으로 간다 - 웹의 기본 규약이다.

        /report.html 에는 nav 의 '← 메인' 이 없어서 로고가 유일한 탈출구다.
        """
        tpl, css = self._css()
        m = re.search(r'<a class="brandlink" href="([^"]+)"', tpl)
        self.assertIsNotNone(m, "로고가 홈으로 가는 링크가 아니다")
        self.assertEqual(m.group(1), "__PAGE_URL__")
        # 로고와 제목이 함께 링크 안에 들어가야 클릭 영역이 쓸 만하다
        link = tpl[m.start():tpl.index("</a>", m.start())]
        self.assertIn('class="mark"', link)
        self.assertIn("<h1>", link)
        # 링크처럼 보이지 않게 두되 키보드 포커스는 드러낸다
        self.assertIn(".brandlink{", css)
        self.assertIn("text-decoration:none", css)
        self.assertIn(".brandlink:focus-visible{", css)

    def test_every_generated_page_can_reach_the_home_page(self):
        tpl, _ = self._css()
        self.assertIn('href="__PAGE_URL__"', tpl, "리포트에 홈 경로가 없다")
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertIn('<nav><a href="{PAGE_URL}">&larr; 메인</a>', src,
                      "정적 페이지 nav 에서 메인 링크가 사라졌다")

    def test_report_is_called_advanced_search_everywhere(self):
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        # 사용자에게 보이는 문구는 '고급 검색' 하나로 통일한다
        visible = re.findall(r'>전체 리포트[^<]*<', src)
        self.assertEqual(visible, [], f"'전체 리포트' 표기가 남았다: {visible}")
        self.assertIn("고급 검색", z._LANDING_TEMPLATE)

class ProductPageOrderTests(unittest.TestCase):
    """제품 상세는 사용자가 원하는 순서로 답한다.

    요약 -> 신고 원재료 전문 -> 등급인 이유 -> 읽는 법. 방법론(읽는 법)을 맨 위에
    두면 '무엇이 들었나'에 닿기까지 한 화면을 소비한다. 목록·랜딩은 반대로
    위에 둔다 (수백 행을 지나야 한계가 보이면 안 되기 때문).
    """

    def _page(self):
        rec = {"제품명": "테스트 제로", "티어": "B", "조합": "B",
               "감미료": "수크랄로스(B,1)", "열량": "0", "당류": "0.00",
               "용량": "500ml", "기준량": "100ml", "업소명": "공장",
               "식품유형": "탄산음료", "보고일자": "20260101",
               "원재료전문": "정제수, 수크랄로스", "등록명": "", "이력": [],
               "감미료미표기": "", "아스파탐": "", "카페인": ""}
        recs = [rec]
        z.assign_slugs(recs)
        return z.product_page(rec, recs, "2026-01-01")

    def test_sections_follow_the_users_question_order(self):
        page = self._page()
        order = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", page, re.S)]
        want = ["요약", "신고 원재료 전문", "제품 정보", "B 등급인 이유", "읽는 법"]
        self.assertEqual(order[:5], want, f"실제 순서: {order}")

    def test_howto_is_not_pushed_below_the_faq(self):
        page = self._page()
        self.assertLess(page.index("읽는 법"), page.index("자주 묻는 질문"),
                        "읽는 법이 FAQ 뒤로 밀리면 아무도 보지 않는다")
        self.assertNotIn("__HOWTO__", page, "자리표시자가 치환되지 않았다")

    def test_howto_is_split_into_labelled_rows(self):
        page = self._page()
        rows = re.findall(r'<div class="hrow"><dt>(.*?)</dt>', page)
        self.assertEqual(rows, ["판정 방법", "등급 기준", "기준량", "확인 불가", "기준일"])
        # 한 덩어리 문단으로 되돌아가면 모바일에서 세로로만 흐른다
        self.assertNotIn("이 페이지의 값은 제조사가", page)

    def test_howto_rows_keep_label_and_text_side_by_side(self):
        css = z._STATIC_CSS
        self.assertIn(".hrow{display:grid;grid-template-columns:74px 1fr", css)
        # 모바일에서도 세로로 쌓지 않는다 (항목 안은 가로 유지)
        narrow = css.split("@media(max-width:400px)")[-1]
        self.assertIn("grid-template-columns:62px 1fr", narrow)

    def test_product_info_says_nothing_twice(self):
        """같은 값을 두 번 말하지 않는다.

        '감미료 등급' 행은 직답 문단이 배지와 함께 이미 말하고, '용량' 은 열량
        환산 주석("500ml 한 개 약 …")에 들어간다. 환산이 불가능할 때만 따로 낸다.
        """
        page = self._page()
        kv = re.search(r'<dl class="kvs">(.*?)</dl>', page, re.S).group(1)
        labels = re.findall(r"<dt>(.*?)</dt>", kv)
        self.assertNotIn("감미료 등급", labels)
        self.assertNotIn("용량", labels, "열량 환산 주석에 이미 용량이 있다")
        self.assertIn("500ml 한 개 약 0 kcal", kv)

    def test_volume_reappears_when_calories_cannot_be_converted(self):
        rec = {"제품명": "테스트 제로", "티어": "B", "조합": "B",
               "감미료": "수크랄로스(B,1)", "열량": "", "당류": "",
               "용량": "500ml", "기준량": "100ml", "업소명": "공장",
               "식품유형": "탄산음료", "보고일자": "20260101",
               "원재료전문": "정제수", "등록명": "", "이력": [],
               "감미료미표기": "", "아스파탐": "", "카페인": ""}
        recs = [rec]
        z.assign_slugs(recs)
        kv = re.search(r'<dl class="kvs">(.*?)</dl>',
                       z.product_page(rec, recs, "2026-01-01"), re.S).group(1)
        self.assertIn("용량", re.findall(r"<dt>(.*?)</dt>", kv),
                      "환산이 안 되면 용량을 어디서도 볼 수 없게 된다")

    def test_summary_card_goes_horizontal_on_narrow_screens(self):
        """요약 8항목이 라벨을 값 위에 쌓으면 모바일에서 600px 넘게 먹는다.

        읽는 법(.hrow)과 같은 규율로 라벨을 왼쪽에 붙인다. 390px 실측
        620px -> 403px. 데스크톱은 4열이라 세로 쌓기를 유지한다.
        """
        css = z._STATIC_CSS
        narrow = css.split("@media(max-width:640px)")[-1]
        self.assertIn(".kv{display:grid;grid-template-columns:76px 1fr", narrow)
        self.assertIn(".kv dt{margin-bottom:0}", narrow)
        # 데스크톱 기본 규칙은 건드리지 않는다
        base = css.split("@media(max-width:640px)")[0]
        self.assertIn(".kv{background:var(--surface);padding:13px 15px}", base)
        self.assertNotIn("grid-template-columns:76px", base)

    def test_list_pages_still_show_the_method_up_front(self):
        # 제품 상세만 예외다. 목록·랜딩은 읽는 법이 표보다 위에 있어야 한다
        page = z._static_page("x.html", "t", "d", "h1", "요약문", "방법론",
                              "<h2>표</h2>", "2026-01-01")
        self.assertLess(page.index("방법론"), page.index("<h2>표</h2>"))

class TierBadgeContrastTests(unittest.TestCase):
    """등급 배지 글자색은 테마가 아니라 배경색이 정한다.

    _tier_badge 가 배경만 인라인으로 주고 글자는 var(--text) 를 쓰던 탓에,
    다크에서 파스텔 배경 위에 거의 흰 글자가 얹혀 안 읽혔다 (2026-09-14 신고).
    """

    def _lum(self, hx):
        hx = hx.lstrip("#")
        if len(hx) == 3:
            hx = "".join(c * 2 for c in hx)
        v = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(v[0]) + 0.7152 * f(v[1]) + 0.0722 * f(v[2])

    def _ratio(self, a, b):
        x, y = self._lum(a), self._lum(b)
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)

    def _parse(self):
        out = {}
        for m in re.finditer(r'\[data-tier="([^"]+)"\]\{--tc:(#[0-9a-fA-F]+);--tf:(#[0-9a-fA-F]+)\}',
                             z._TIER_CSS):
            out[m.group(1)] = (m.group(2), m.group(3))
        return out

    def test_badge_inherits_tokens_instead_of_inline_background(self):
        self.assertIn('data-tier=', z._tier_badge("A"))
        self.assertNotIn("style=", z._tier_badge("A"),
                         "배경을 인라인으로 주면 글자색이 테마를 따라가 버린다")
        self.assertIn("background:var(--tc", z._STATIC_CSS)
        self.assertIn("color:var(--tf", z._STATIC_CSS)
        # 배경 사본을 따로 두면 또 갈라진다
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertNotIn("_TIER_BG", src)

    def test_every_tier_badge_meets_wcag_aa(self):
        pairs = self._parse()
        self.assertEqual(len(pairs), 8, f"등급 토큰이 8개가 아니다: {list(pairs)}")
        for tier, (bg, fg) in pairs.items():
            r = self._ratio(bg, fg)
            self.assertGreaterEqual(round(r, 2), 4.5, f"{tier} 배지 대비 {r:.2f}:1")

    def test_pastel_tiers_use_dark_ink(self):
        # 밝은 배경에는 검은 글자여야 한다. F(#cc0000)만 흰 글자가 대비가 높다.
        pairs = self._parse()
        for tier in ("무감미료", "S", "A", "B", "C", "D", "?"):
            bg, fg = pairs[tier]
            self.assertLess(self._lum(fg), 0.5, f"{tier} 배지가 밝은 글자를 쓴다")
        bg, fg = pairs["F"]
        self.assertGreater(self._lum(fg), 0.5)
        self.assertGreater(self._ratio(bg, fg), self._ratio(bg, "#0d0f11"),
                           "F 는 검은 글자보다 흰 글자가 대비가 높다")

class SuggestOverlayTests(unittest.TestCase):
    """자동완성은 '떠 있는 레이어'로 보여야 한다.

    아래 '많이 찾는 제품' 카드와 생김새가 같아 어디까지가 검색 결과인지
    구분이 안 된다는 신고를 받았다 (2026-09-19, 모바일).
    """

    def test_suggestion_box_outranks_the_cards_visually(self):
        css = z._LANDING_CSS
        self.assertIn("border:2px solid var(--accent)", css, "제안 박스 테두리가 카드와 같다")
        self.assertIn(".sg-head{", css, "몇 건인지 알려주는 머리글이 없다")
        # 카드는 테두리 없이 1px 구분선만 쓴다 - 둘이 같아지면 안 된다
        self.assertNotIn(".pick{border:2px", css)

    def test_scrim_dims_the_page_on_narrow_screens_only(self):
        css = z._LANDING_CSS
        self.assertIn("body.sg-open .scrim{opacity:1", css)
        self.assertIn("@media(min-width:761px){body.sg-open .scrim{opacity:0", css,
                      "데스크톱에서도 화면을 덮으면 과하다")
        self.assertIn('<div class="scrim"', z._LANDING_TEMPLATE)

    def test_scrim_state_is_cleared_on_every_exit(self):
        js = z._SUGGEST_JS
        self.assertIn("document.body.classList.remove('sg-open')", js)
        self.assertIn("scrim.addEventListener('click', hide)", js,
                      "덮개를 눌러도 안 닫히면 갇힌다")
        # 여는 경로는 show() 하나로 모은다 (한 곳이라도 빠지면 스크림이 안 뜬다)
        self.assertEqual(js.count("box.hidden = false"), 1)
        self.assertIn("function show()", js)


class FaqContentTests(unittest.TestCase):
    """FAQ 답변은 데이터로 확인되는 것만 말한다."""

    def _answers(self):
        return dict(z.faq_pairs(z._FAQ))

    def test_tier_basis_question_comes_first(self):
        self.assertEqual(z._FAQ[0][0], "티어는 어떤 기준으로 나눈 건가요?")
        a = dict(z.faq_pairs(z._FAQ))[z._FAQ[0][0]]
        self.assertIn("맛, 가격, 인기는 평가에 반영하지 않았습니다", a)
        # 정부 평가가 아니라는 단서를 빼면 안 된다
        self.assertIn("공식 평가가 아니", a)
        self.assertIn("의학적 조언이나 진단을 위한 자료는 아닙니다", a)

    def test_bc_reassurance_answer_matches_the_data(self):
        a = self._answers()["제가 마시는 음료가 대부분 B~C 티어인데 걱정해야 하나요?"]
        for claim in ("제로 음료끼리 비교", "일반판은 대부분 F 티어",
                      "인과관계가 확정됐다는 연구결과는 아닙니다"):
            self.assertIn(claim, a, f"근거 문장이 빠졌다: {claim}")
        # '안전하다' 로 단정하지 않는다 - 우리가 말할 수 있는 범위가 아니다
        for overclaim in ("안전합니다", "걱정하지 않아도 됩니다", "문제없습니다"):
            self.assertNotIn(overclaim, a, f"단정 표현: {overclaim}")

    def test_faq_is_rendered_on_the_landing(self):
        recs = [{"제품명": n, "티어": "B", "조합": "B", "감미료": "수크랄로스(B,1)",
                 "열량": "0", "당류": "0.00", "용량": "500ml", "기준량": "100ml",
                 "업소명": "공장", "식품유형": "탄산음료", "보고일자": "20260101",
                 "원재료전문": "정제수", "등록명": "", "이력": [], "감미료미표기": "",
                 "아스파탐": "", "카페인": ""} for n in z.POPULAR_PICKS]
        z.assign_slugs(recs)
        page = z.landing_page(recs, "2026-01-01", {"records": recs})
        # 부가 블록(티어 기준표)의 summary 가 하나 더 붙는다
        extras = sum(1 for e in z._FAQ if len(e) > 2)
        self.assertEqual(page.count("<summary>"), len(z._FAQ) + extras)
        for q, *_ in z._FAQ:
            self.assertIn(q, page)

class ProductMarkupTests(unittest.TestCase):
    """Product 마크업을 쓰지 않는다.

    Google 은 Product 에 offers/review/aggregateRating 중 하나를 요구한다.
    이 사이트는 가격도 평점도 없고 없는 값을 만들어 넣을 수 없다. 애초에 물건을
    파는 페이지가 아니라 신고 데이터를 보여주는 페이지라 Product 가 맞지 않는다.
    GSC 가 목록 페이지에서 '잘못된 항목 100개'로 보고한 원인이었다 (2026-09-20).
    """

    def _rec(self, name="테스트 제로"):
        r = {"제품명": name, "티어": "B", "조합": "B", "감미료": "수크랄로스(B,1)",
             "열량": "0", "당류": "0.00", "용량": "500ml", "기준량": "100ml",
             "업소명": "공장", "식품유형": "탄산음료", "보고일자": "20260101",
             "원재료전문": "정제수", "등록명": "", "이력": [], "감미료미표기": "",
             "아스파탐": "", "카페인": ""}
        return r

    def test_detail_page_declares_no_product(self):
        recs = [self._rec()]
        z.assign_slugs(recs)
        page = z.product_page(recs[0], recs, "2026-01-01")
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                  page, re.S).group(1))
        types = [n["@type"] for n in ld["@graph"]]
        self.assertNotIn("Product", types, "Product 는 offers 없이는 무효 항목이 된다")
        self.assertEqual(types, ["WebPage", "BreadcrumbList", "FAQPage"])

    def test_list_items_carry_url_not_nested_products(self):
        recs = [self._rec(f"제품{i}") for i in range(3)]
        z.assign_slugs(recs)
        ld = z._item_list_ld("목록", "설명", "products.html", recs)
        self.assertNotIn("Product", json.dumps(ld))
        for el in ld["itemListElement"]:
            self.assertIn("url", el, "url 이 없으면 링크 신호로도 쓸모가 없다")
            self.assertIn("name", el)
            self.assertNotIn("item", el)

    def test_facts_survive_in_the_faq_graph(self):
        # Product.additionalProperty 를 뺐으므로, 감미료·열량이 구조화 데이터에서
        # 사라지지 않았는지 확인한다 (FAQPage 가 문답으로 담는다)
        recs = [self._rec()]
        z.assign_slugs(recs)
        page = z.product_page(recs[0], recs, "2026-01-01")
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                  page, re.S).group(1))
        faq = [n for n in ld["@graph"] if n["@type"] == "FAQPage"][0]
        blob = json.dumps(faq, ensure_ascii=False)
        self.assertIn("수크랄로스", blob)
        self.assertIn("kcal", blob)
        self.assertIn("B", blob)

    def test_no_generated_page_emits_product_markup(self):
        src = open("zero_soda_scan.py", encoding="utf-8").read()
        self.assertNotIn('"@type": "Product"', src)

class LastmodTests(unittest.TestCase):
    """사이트맵 lastmod 는 URL 마다 실제 변경일이어야 한다.

    예전에는 빌드할 때마다 635개 URL 전부에 오늘 날짜를 찍었다. 내용이 그대로인
    페이지도 매번 '바뀌었다'고 말한 셈이라 Google 이 lastmod 를 통째로 무시하고,
    626장이 '발견됨 - 현재 색인이 생성되지 않음'에 머물렀다 (2026-09-20 GSC).
    """

    def test_same_content_keeps_the_old_date(self):
        store = {}
        self.assertEqual(z.resolve_lastmod(store, "u", {"a": 1}, "2026-01-01"),
                         "2026-01-01")
        self.assertEqual(z.resolve_lastmod(store, "u", {"a": 1}, "2026-06-30"),
                         "2026-01-01", "내용이 같은데 날짜가 올라갔다")

    def test_changed_content_moves_the_date(self):
        store = {}
        z.resolve_lastmod(store, "u", {"a": 1}, "2026-01-01")
        self.assertEqual(z.resolve_lastmod(store, "u", {"a": 2}, "2026-06-30"),
                         "2026-06-30")

    def test_fingerprint_ignores_key_order(self):
        self.assertEqual(z._digest({"a": 1, "b": 2}), z._digest({"b": 2, "a": 1}))

    def test_product_fingerprint_covers_what_the_page_shows(self):
        fp = z._product_fingerprint({"제품명": "x", "티어": "B"})
        for field in ("제품명", "티어", "감미료", "열량", "당류", "원재료전문",
                      "표시원재료", "보고일자", "이력"):
            self.assertIn(field, fp, f"{field} 가 바뀌어도 lastmod 가 안 올라간다")
        # 렌더 시점에만 달라지는 값은 지문에 넣지 않는다
        self.assertNotIn("슬러그", fp)

    def test_store_is_tracked_and_pushed(self):
        # 이 파일이 없으면 다음 빌드가 전부 '오늘 바뀜'으로 되돌린다
        self.assertIn(z.DEFAULT_LASTMOD_STORE, z.PUSH_PATHS)
        gi = open(".gitignore", encoding="utf-8").read()
        self.assertIn("!" + z.DEFAULT_LASTMOD_STORE, gi)

    def test_live_sitemap_does_not_stamp_everything_with_one_date(self):
        # 산출물 기준: 전부 같은 날짜여도 '오늘'이 아니면 정상(첫 생성 직후 제외).
        # 여기서는 저장소가 URL 수만큼 채워졌는지만 본다.
        store = z.load_lastmod_store()
        if not store:
            self.skipTest("저장소 없음 - 빌드를 먼저 돌려야 한다")
        sm = open(os.path.join("docs", "sitemap.xml"), encoding="utf-8").read()
        self.assertEqual(len(store), sm.count("<loc>"),
                         "저장소와 사이트맵 URL 수가 다르다")

