#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_intel_adapter.py -- cyborg yaml -> closure projection adapter
WP-B Wave 1 Step 1 / 2026-06-13

職責：
  - cyborg dict（由 iter_cyborg_files() 讀到的原始 yaml）→ closure projection dict
  - 純函式，無 I/O 副作用（不讀檔、不寫檔）
  - eligibility 只收 status==pending + pipeline_status==success +
    confidence>=70 + transferability_score>=0.7 + 有 url/title/platform/publish_date +
    (有 transcript_preview 或 dissect.hook_structure)
  - 不合格回 None + eligible=False + reason

版本常數（規格 §9.6）：
  ADAPTER_VERSION / PROJECTION_SCHEMA_VERSION / SHADOW_REPORT_SCHEMA_VERSION / EVENT_SCHEMA_VERSION

STOPLIST（43 詞）：
  Wave 2 validator 關鍵詞比對用（規格 §9.2）。
  來源：GPT r3 thread 019ec0e2 原文逐字（reference_wpb_stoplist_2026-06-13.md）。
  Wave 1 不使用 stoplist（eligibility 不涉及關鍵詞比對），此處預留為模組頂部常數。
  Wave 2 施作時必須照抄 reference_wpb_stoplist_2026-06-13.md 完整 43 詞，不自行增減。
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── 版本常數（規格 §9.6，照抄不改）────────────────────────────────────────
ADAPTER_VERSION = "wpb-adapter-v1"
PROJECTION_SCHEMA_VERSION = 1
SHADOW_REPORT_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1

# ── STOPLIST（關鍵詞比對用，Wave 2 啟用）────────────────────────────────────
# 來源：GPT r3 thread 019ec0e2 reference_wpb_stoplist_2026-06-13.md（43 詞固定）
# 逐字照抄，不增不減。validator 的 _normalize_and_tokenize 使用此常數。
STOPLIST = {
    "今天", "就是", "其實", "然後", "因為", "所以", "一個", "我們", "你們",
    "大家", "這個", "那個", "可以", "不是", "沒有", "真的", "如果", "但是",
    "以及", "或者", "影片", "內容", "粉絲", "留言", "分享", "覺得", "知道",
    "看到", "很多", "現在", "可能", "應該", "這樣", "那樣", "什麼", "怎麼",
    "為什麼", "是不是", "一下", "比較", "直接", "問題", "重點",
}

# ── 合格 status 集合 ────────────────────────────────────────────────────────
_ELIGIBLE_STATUSES = frozenset(["pending"])

# ── 不合格 status（明示排除）───────────────────────────────────────────────
_INELIGIBLE_STATUSES = frozenset(["processed", "rejected", "stale", "partial_failed_skip"])

# ── expires_at TTL（24h，fingerprint 不符時由讀取端判 stale）───────────────
_PROJECTION_TTL_HOURS = 24


def _sha256_str(s: str) -> str:
    """計算字串的 sha256 hex digest"""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _compute_topic_id(cyborg: dict) -> str:
    """
    topic_id 生成（規格 §9 盲點2）：
    - cyborg 有 topic_id → 直接用
    - 無 → "cyborg_" + sha256(platform+"\n"+video_id+"\n"+url)[:16]
    """
    tid = cyborg.get("topic_id", "")
    if tid and isinstance(tid, str) and tid.strip():
        return tid.strip()
    platform = str(cyborg.get("platform", "") or "")
    video_id = str(cyborg.get("video_id", "") or "")
    url = str(cyborg.get("url", "") or "")
    raw = platform + "\n" + video_id + "\n" + url
    return "cyborg_" + _sha256_str(raw)[:16]


def _check_eligibility(cyborg: dict) -> tuple[bool, str]:
    """
    回 (eligible: bool, reason: str)。

    合格條件（規格 §8.A r2 盲點1）：
    1. status == "pending"（排除 processed/rejected/stale/partial_failed_skip）
    2. pipeline_status == "success"（或缺此欄時視為通過，實際 cyborg 多無此欄）
    3. confidence >= 70（數字）
    4. transferability_score >= 0.7（數字）
    5. 有 url / title / platform / publish_date（至少 url+title+platform 存在）
    6. 有 transcript_preview 或 dissect.hook_structure
    """
    status = cyborg.get("status", "")
    if status in _INELIGIBLE_STATUSES:
        return False, f"status={status!r} 不合格（只收 pending）"
    if status not in _ELIGIBLE_STATUSES:
        return False, f"status={status!r} 非合格 status（只收 pending）"

    # pipeline_status（非強制欄位，缺時允許通過）
    pipeline_status = cyborg.get("pipeline_status", None)
    if pipeline_status is not None and pipeline_status != "success":
        return False, f"pipeline_status={pipeline_status!r}（需 success）"

    # confidence >= 70
    confidence = cyborg.get("confidence", None)
    if confidence is None:
        return False, "缺 confidence 欄位"
    try:
        if float(confidence) < 70:
            return False, f"confidence={confidence} < 70"
    except (TypeError, ValueError):
        return False, f"confidence={confidence!r} 非數字"

    # transferability_score >= 0.7
    ts = cyborg.get("transferability_score", None)
    if ts is None:
        return False, "缺 transferability_score 欄位"
    try:
        if float(ts) < 0.7:
            return False, f"transferability_score={ts} < 0.7"
    except (TypeError, ValueError):
        return False, f"transferability_score={ts!r} 非數字"

    # 必要欄位：url / title / platform（publish_date 映射到 discovery_date，寬鬆驗）
    url = cyborg.get("url", "") or ""
    title = cyborg.get("title", "") or ""
    platform = cyborg.get("platform", "") or ""
    if not url.strip():
        return False, "缺 url"
    if not title.strip():
        return False, "缺 title"
    if not platform.strip():
        return False, "缺 platform"

    # publish_date：cyborg 用 discovery_date（非 publish_date），寬鬆允許 discovery_date
    publish_date = (
        cyborg.get("publish_date")
        or cyborg.get("discovery_date")
        or ""
    )
    if not str(publish_date).strip():
        return False, "缺 publish_date / discovery_date"

    # transcript_preview 或 dissect.hook_structure
    has_transcript = bool(cyborg.get("transcript_preview", ""))
    dissect = cyborg.get("dissect") or {}
    has_hook_structure = bool(dissect.get("hook_structure"))
    if not has_transcript and not has_hook_structure:
        return False, "缺 transcript_preview 且缺 dissect.hook_structure"

    return True, "ok"


def _compute_source_sha256(cyborg: dict) -> str:
    """
    source_sha256：對 cyborg dict 做 canonical JSON sha256（無法讀原始檔案時的替代）。
    呼叫端傳入 source_bytes 時優先用 source_bytes sha256。
    """
    import json
    canonical = json.dumps(cyborg, ensure_ascii=False, sort_keys=True)
    return _sha256_str(canonical)


def project_cyborg(
    cyborg: dict,
    source_sha256: Optional[str] = None,
) -> Optional[dict]:
    """
    將一支 cyborg dict 投影為 closure projection dict。

    參數：
      cyborg        : 原始 cyborg yaml 內容（dict）
      source_sha256 : 原始 yaml 檔的 sha256（由呼叫端傳入）；
                      None 時改算 dict canonical sha256（次佳）

    回傳：
      合格 → projection dict
      不合格 → None

    Projection dict 欄位（規格 §8）：
      schema_version          : int（PROJECTION_SCHEMA_VERSION）
      adapter_version         : str
      eligible                : True
      eligible_reason         : "ok"
      source_sha256           : str
      topic_id                : str
      evidence_snapshot       : dict{title,url,platform,publish_date,confidence,transferability_score}
      expires_at              : str（ISO8601 UTC，generated_at + 24h）
      generated_at            : str（ISO8601 UTC）
      applicable_owners       : list[str]（原始欄位，供 generator 過濾用）
      industry                : str
    """
    eligible, reason = _check_eligibility(cyborg)
    if not eligible:
        return None

    if source_sha256 is None:
        source_sha256 = _compute_source_sha256(cyborg)

    topic_id = _compute_topic_id(cyborg)

    publish_date = str(
        cyborg.get("publish_date")
        or cyborg.get("discovery_date")
        or ""
    )

    now_utc = datetime.now(tz=timezone.utc)
    generated_at = now_utc.isoformat()
    expires_at = (now_utc + timedelta(hours=_PROJECTION_TTL_HOURS)).isoformat()

    evidence_snapshot = {
        "title": str(cyborg.get("title", "") or ""),
        "url": str(cyborg.get("url", "") or ""),
        "platform": str(cyborg.get("platform", "") or ""),
        "publish_date": publish_date,
        "confidence": cyborg.get("confidence"),
        "transferability_score": cyborg.get("transferability_score"),
    }

    projection = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "eligible": True,
        "eligible_reason": reason,
        "source_sha256": source_sha256,
        "topic_id": topic_id,
        "evidence_snapshot": evidence_snapshot,
        "expires_at": expires_at,
        "generated_at": generated_at,
        "applicable_owners": list(cyborg.get("applicable_owners") or []),
        "industry": str(cyborg.get("industry", "") or ""),
    }

    return projection


def project_cyborg_with_rejection(
    cyborg: dict,
    source_sha256: Optional[str] = None,
) -> dict:
    """
    同 project_cyborg，但不合格時也回 dict（eligible=False + reason）。
    給測試 / debug 用。
    """
    eligible, reason = _check_eligibility(cyborg)
    if not eligible:
        return {
            "eligible": False,
            "eligible_reason": reason,
            "topic_id": _compute_topic_id(cyborg),
            "source_sha256": source_sha256 or _compute_source_sha256(cyborg),
        }
    proj = project_cyborg(cyborg, source_sha256=source_sha256)
    return proj  # type: ignore[return-value]


# ── 快速自測（python topic_intel_adapter.py）────────────────────────────────
if __name__ == "__main__":
    import json

    # Case 1：合格 pending（有 transcript_preview）
    good = {
        "status": "pending",
        "platform": "IG",
        "video_id": "ig_TESTGOOD",
        "url": "https://www.instagram.com/test/reel/TESTGOOD/",
        "title": "測試合格題材",
        "discovery_date": "2026-06-13",
        "confidence": 80,
        "transferability_score": 0.8,
        "applicable_owners": ["瑞祥", "仲豪"],
        "industry": "房仲",
        "transcript_preview": "這是逐字稿預覽",
        "dissect": {},
    }
    r1 = project_cyborg(good)
    assert r1 is not None, "Case 1 應 eligible"
    assert r1["eligible"] is True
    assert r1["schema_version"] == PROJECTION_SCHEMA_VERSION
    assert r1["adapter_version"] == ADAPTER_VERSION
    assert r1["topic_id"].startswith("cyborg_")
    print(f"Case 1 PASS: topic_id={r1['topic_id']}")

    # Case 2：processed → None
    processed = dict(good, status="processed")
    r2 = project_cyborg(processed)
    assert r2 is None, "Case 2 應 None（processed）"
    r2r = project_cyborg_with_rejection(processed)
    assert r2r["eligible"] is False
    assert "processed" in r2r["eligible_reason"]
    print(f"Case 2 PASS: reason={r2r['eligible_reason']}")

    # Case 3：低分 confidence < 70 → None
    low_conf = dict(good, status="pending", confidence=50)
    r3 = project_cyborg(low_conf)
    assert r3 is None, "Case 3 應 None（confidence 50）"
    r3r = project_cyborg_with_rejection(low_conf)
    assert "confidence" in r3r["eligible_reason"]
    print(f"Case 3 PASS: reason={r3r['eligible_reason']}")

    # Case 4：缺 url → None
    no_url = dict(good, status="pending", url="")
    r4 = project_cyborg(no_url)
    assert r4 is None, "Case 4 應 None（缺 url）"
    r4r = project_cyborg_with_rejection(no_url)
    assert "url" in r4r["eligible_reason"]
    print(f"Case 4 PASS: reason={r4r['eligible_reason']}")

    # Case 5：缺 transcript 且缺 hook_structure → None
    no_evidence = dict(good, status="pending")
    no_evidence["transcript_preview"] = ""
    no_evidence["dissect"] = {}
    r5 = project_cyborg(no_evidence)
    assert r5 is None, "Case 5 應 None（缺 evidence）"
    r5r = project_cyborg_with_rejection(no_evidence)
    assert "transcript" in r5r["eligible_reason"] or "hook_structure" in r5r["eligible_reason"]
    print(f"Case 5 PASS: reason={r5r['eligible_reason']}")

    # Case 6：有 dissect.hook_structure（無 transcript）→ eligible
    hook_only = dict(good, status="pending")
    hook_only["transcript_preview"] = ""
    hook_only["dissect"] = {"hook_structure": {"type": "反差"}}
    r6 = project_cyborg(hook_only)
    assert r6 is not None, "Case 6 應 eligible（有 hook_structure）"
    print(f"Case 6 PASS: eligible via hook_structure")

    # Case 7：rejected → None
    rejected = dict(good, status="rejected")
    r7 = project_cyborg(rejected)
    assert r7 is None, "Case 7 應 None（rejected）"
    print(f"Case 7 PASS: rejected 排除")

    print("\nAll cases PASS.")
    print(json.dumps(r1, ensure_ascii=False, indent=2))
