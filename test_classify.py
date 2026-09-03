#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""z.py 분류기·통합·파생플래그 테스트. 네트워크 0, 픽스처 0."""

import tempfile
import shutil
import os
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
    사이트 이름(og:site_name / WebSite.name / title 접미)뿐이다. Organization·
    Person·Dataset 은 서로 다른 엔티티이고, 같은 문자열로 두면 Knowledge Graph
    에서 뭉개진다.
    """

    def setUp(self):
        self.tpl = re.search(r'_HTML_TEMPLATE = r"""(.*?)\n"""',
                             open('zero_soda_scan.py', encoding='utf-8').read(), re.S).group(1)
        head = self.tpl.split("</head>")[0]
        self.ld = json.loads(
            re.search(r'<script type="application/ld\+json">(.*?)</script>', head, re.S)
            .group(1).replace("__TOTAL__", "616").replace("__PAGE_URL__", z.PAGE_URL)
            .replace("__GENERATED_DATE__", "2026-01-01"))
        self.nodes = {n["@type"]: n for n in self.ld["@graph"]}

    def test_site_name_matches_across_every_slot(self):
        name = self.nodes["WebSite"]["name"]
        self.assertEqual(re.search(r'og:site_name" content="(.*?)"', self.tpl).group(1), name)
        title = re.search(r"<title>(.*?)</title>", self.tpl).group(1)
        self.assertTrue(title.startswith(name) or title.endswith(name),
                        f"title 이 사이트명을 담지 않는다: {title}")
        # 정적 페이지도 같은 사이트다
        self.assertEqual(z._STATIC_PAGE_SITE_NAME, name)

    def test_entity_names_stay_distinct(self):
        site = self.nodes["WebSite"]["name"]
        self.assertNotEqual(self.nodes["Person"]["name"], site,
                            "발행 주체 이름이 사이트 이름과 같으면 엔티티가 겹친다")
        self.assertNotEqual(self.nodes["Dataset"]["name"], site,
                            "Dataset 은 서술적 제목을 쓴다 - alternateName 으로 연결한다")
        self.assertEqual(self.nodes["Dataset"]["alternateName"], site)

    def test_publisher_is_a_real_referenced_entity(self):
        # 실체 없는 Organization 을 발행 주체로 세워 두면 안 된다
        for node in ("WebSite", "Dataset"):
            ref = self.nodes[node]["publisher"]["@id"]
            self.assertEqual(ref, self.nodes["Person"]["@id"],
                             f"{node}.publisher 가 정의된 엔티티를 가리키지 않는다")
        self.assertIn("github.com/gulf1324", self.nodes["Person"]["sameAs"][0])

    def test_search_action_points_at_a_working_query_url(self):
        tpl = self.nodes["WebSite"]["potentialAction"]["target"]["urlTemplate"]
        self.assertIn("{search_term_string}", tpl)
        # 선언한 파라미터 이름이 실제 프리필 코드와 같아야 한다. 다르면 Google 이
        # 검색창을 붙여도 결과가 걸러지지 않는다.
        self.assertIn("?q={search_term_string}", tpl)
        self.assertIn("get('q')", z._FINDER_JS)

