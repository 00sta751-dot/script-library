import unittest
from pathlib import Path

from validate_script_batch import (
    TOPIC_TYPE_TARGET_COUNTS,
    TOPIC_TYPE_VALUES,
    chk_r_src_001_origin_source,
    chk_r_type_001_topic_type_quota,
)


def _topic_types() -> list[str]:
    return [
        topic_type
        for topic_type in TOPIC_TYPE_VALUES
        for _ in range(TOPIC_TYPE_TARGET_COUNTS[topic_type])
    ]


def _yamls(topic_types, *, origin_sources=None):
    origin_sources = origin_sources or [None] * len(topic_types)
    rows = []
    for index, (topic_type, origin_source) in enumerate(
        zip(topic_types, origin_sources), start=1
    ):
        data = {"topic_type": topic_type}
        if origin_source is not None:
            data["origin_source"] = origin_source
        rows.append((Path(f"script_{index:02d}.yaml"), data))
    return rows


class Q8QuotaTests(unittest.TestCase):
    """0826 Q1–Q8 現役配額只驗 validator 的單一真相源。"""

    def test_exact_quota_passes(self):
        status, _ = chk_r_type_001_topic_type_quota(_yamls(_topic_types()))
        self.assertEqual("PASS", status)

    def test_thirteen_scripts_fail(self):
        status, _ = chk_r_type_001_topic_type_quota(_yamls(_topic_types()[:-1]))
        self.assertEqual("FAIL", status)

    def test_fifteen_scripts_fail(self):
        status, _ = chk_r_type_001_topic_type_quota(
            _yamls(_topic_types() + ["Q1"])
        )
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
        status, _ = chk_r_src_001_origin_source(
            _yamls(_topic_types(), origin_sources=sources)
        )
        self.assertEqual("FAIL", status)

    def test_non_string_origin_source_fails(self):
        sources = [None] * 14
        sources[-1] = 4
        status, _ = chk_r_src_001_origin_source(
            _yamls(_topic_types(), origin_sources=sources)
        )
        self.assertEqual("FAIL", status)

    def test_legacy_batch_skips_type_and_source_checks(self):
        legacy = [(Path(f"legacy_{index}.yaml"), {}) for index in range(14)]
        self.assertEqual("SKIP", chk_r_type_001_topic_type_quota(legacy)[0])
        self.assertEqual("SKIP", chk_r_src_001_origin_source(legacy)[0])


if __name__ == "__main__":
    unittest.main()
