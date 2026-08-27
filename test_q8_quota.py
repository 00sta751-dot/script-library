import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import topic_distributor
from topic_distributor import (
    TOPIC_TYPE_TARGET_COUNTS,
    TOPIC_TYPE_VALUES,
    apply_q8_quota,
    distribute_topics,
    evaluate_q8_allocation,
)
from validate_script_batch import (
    _declared_hybrid_not_built,
    _expected_main_scripts_for_batch,
    chk_l1_008_batch_count,
    chk_r_src_001_origin_source,
    chk_r_type_001_topic_type_quota,
)
from yaml_skeleton_generator import build_yaml_skeleton


def _topic_types():
    return [q for q in TOPIC_TYPE_VALUES for _ in range(TOPIC_TYPE_TARGET_COUNTS[q])]


def _yamls(topic_types, *, origin_sources=None):
    origin_sources = origin_sources or [None] * len(topic_types)
    rows = []
    for index, (topic_type, origin_source) in enumerate(zip(topic_types, origin_sources), start=1):
        data = {"topic_type": topic_type}
        if origin_source is not None:
            data["origin_source"] = origin_source
        rows.append((Path(f"script_{index:02d}.yaml"), data))
    return rows


class Q8QuotaTests(unittest.TestCase):
    def test_exact_quota_passes(self):
        topic_types = _topic_types()
        verdict = evaluate_q8_allocation([{"topic_type": q} for q in topic_types])
        self.assertEqual([], verdict["infeasible_constraints"])
        status, _ = chk_r_type_001_topic_type_quota(_yamls(topic_types))
        self.assertEqual("PASS", status)

    def test_skeleton_prefills_topic_type_and_optional_source(self):
        text = build_yaml_skeleton({"seq": 13, "owner": "未知"})
        self.assertIn('topic_type: "Q7"', text)
        self.assertIn('origin_source: ""', text)

    def test_thirteen_scripts_fail(self):
        status, _ = chk_r_type_001_topic_type_quota(_yamls(_topic_types()[:-1]))
        self.assertEqual("FAIL", status)

    def test_fifteen_scripts_fail(self):
        status, _ = chk_r_type_001_topic_type_quota(_yamls(_topic_types() + ["Q1"]))
        self.assertEqual("FAIL", status)

    def test_missing_q_slot_fails(self):
        topic_types = [q for q in _topic_types() if q != "Q3"] + ["Q1", "Q1"]
        status, _ = chk_r_type_001_topic_type_quota(_yamls(topic_types))
        self.assertEqual("FAIL", status)

    def test_invalid_topic_type_fails(self):
        topic_types = _topic_types()
        topic_types[-1] = "Q9"
        status, _ = chk_r_type_001_topic_type_quota(_yamls(topic_types))
        self.assertEqual("FAIL", status)

    def test_source_4_created_three_fails(self):
        sources = ["source_4_created"] * 3 + [None] * 11
        status, _ = chk_r_src_001_origin_source(_yamls(_topic_types(), origin_sources=sources))
        self.assertEqual("FAIL", status)

    def test_non_string_origin_source_fails(self):
        sources = [None] * 14
        sources[-1] = 4
        status, _ = chk_r_src_001_origin_source(_yamls(_topic_types(), origin_sources=sources))
        self.assertEqual("FAIL", status)

    def test_eight_equal_factions_allocate_exactly_fourteen_q_slots(self):
        ratios = {f"派{index}": 1 for index in range(8)}
        plan, _ = distribute_topics(ratios, {}, [], {"main_scripts": 14}, "瑞祥", "第01批")
        plan, verdict = apply_q8_quota(plan)
        self.assertEqual(14, len(plan))
        self.assertEqual([], verdict["infeasible_constraints"])

    def test_legacy_thirteen_uses_grandfather_count_for_batch_and_plan_lock(self):
        legacy = [(Path(f"legacy_{index}.yaml"), {"content_axis": "offpro"}) for index in range(13)]
        self.assertEqual(13, _expected_main_scripts_for_batch(legacy))
        self.assertEqual("PASS", chk_l1_008_batch_count(legacy, Path("."))[0])
        self.assertFalse(_declared_hybrid_not_built(True, 13, Path("topic_plan.json"), [{}] * 13, 13))

    def test_invalid_q8_plan_exits_before_output_write(self):
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "must_not_exist.json"
            with patch.object(topic_distributor, "OWNER_META", {"tester": {}}), \
                 patch.object(topic_distributor, "load_pref_text", return_value="pref"), \
                 patch.object(topic_distributor, "parse_school_ratios", return_value={"派": 100}), \
                 patch.object(topic_distributor, "parse_banned_schools", return_value=[]), \
                 patch.object(topic_distributor, "parse_identity_ratios", return_value={}), \
                 patch.object(topic_distributor, "collect_used_topics", return_value=[]), \
                 patch.object(topic_distributor, "load_sop_batch_spec", return_value={"main_scripts": 13}), \
                 patch("sys.argv", ["topic_distributor.py", "--owner", "tester", "--batch", "第01批", "--output", str(output)]):
                with self.assertRaises(SystemExit) as raised:
                    topic_distributor.main()
            self.assertEqual(1, raised.exception.code)
            self.assertFalse(output.exists())

    def test_legacy_batch_skips_type_and_source_checks(self):
        legacy = [(Path(f"legacy_{index}.yaml"), {}) for index in range(14)]
        self.assertEqual("SKIP", chk_r_type_001_topic_type_quota(legacy)[0])
        self.assertEqual("SKIP", chk_r_src_001_origin_source(legacy)[0])


if __name__ == "__main__":
    unittest.main()
