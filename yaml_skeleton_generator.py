#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yaml_skeleton_generator.py — yaml 骨架機 v1.0
吃 topic_distributor.py 產的 JSON，產 13 個空 yaml 骨架給編劇填

用法：
  python yaml_skeleton_generator.py --topic-plan /path/to/plan.json --output-dir /path/to/batch/

注意：
- 時間軸 6 段 immutable（SOP _腳本生產SOP_v3.0.yaml §2 script_schema 固定）
- 各欄位放 [編劇填] placeholder
- 輸出 .yaml（正式用途）

建檔：2026-05-22 / 對齊 _腳本生產SOP_v3.0.yaml §2 script_schema
"""

import sys
import re
import json
import argparse
from pathlib import Path

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── _sop_config import（B 段 2026-06-05）──
try:
    _SC_DIR = Path(__file__).resolve().parent
    import sys as _sys
    if str(_SC_DIR) not in _sys.path:
        _sys.path.insert(0, str(_SC_DIR))
    from _sop_config import (
        load_l0_batch_spec as _load_l0_batch_spec,
        load_l0_time_slots as _load_l0_time_slots,
    )
    _SOP_CONFIG_OK = True
except Exception as _sop_err:
    print(
        f"[WARN] yaml_skeleton_generator: _sop_config import failed ({_sop_err}); "
        f"using hardcoded fallback",
        file=sys.stderr,
    )
    _SOP_CONFIG_OK = False

    def _load_l0_batch_spec():  # type: ignore
        return {"main_scripts": 14, "duration_seconds": 60, "title_max_chars": 15, "actor_interaction_min": 1}

    def _load_l0_time_slots():  # type: ignore
        return ()

# ════════════════════════════════════════
# 6 段時間軸 — IMMUTABLE（SOP §2 固定，禁改）
# ════════════════════════════════════════
# B 段：HARDCODED_TIME_SLOTS 作為 fallback；實際骨架由 build_time_slots() 從 L0 組裝
HARDCODED_TIME_SLOTS = [
    {
        "timestamp": "0-3s",
        "type": "Hook",
        "task": "Hook 開場金句（決定觀眾留不留下）",
        "note": "必須是金句，不能是問候語",
    },
    {
        "timestamp": "3-12s",
        "type": "破題",
        "task": "破題 + 拋出痛點 / 疑問",
        "note": "讓觀眾有理由繼續看",
    },
    {
        "timestamp": "12-25s",
        "type": "核心論述",
        "task": "核心論述 + 數據佐證",
        "note": "必給完整答案，禁止全留到下集/PDF",
    },
    {
        "timestamp": "25-40s",
        "type": "案例轉折",
        "task": "案例 / 故事 / 轉折",
        "note": "主體段必給觀眾可立即實踐的內容",
    },
    {
        "timestamp": "40-52s",
        "type": "收束金句",
        "task": "收束觀點、強化記憶點",
        "note": "金句要能獨立截圖分享",
    },
    {
        "timestamp": "52-60s",
        "type": "CTA",
        "task": "CTA 導流",
        "note": "固定話術：不用怕，問問不用錢",
    },
]

# 本地 type mapping（與 L0 段數綁定，B 段 §4 防呆）
LOCAL_SLOT_TYPES = ["Hook", "破題", "核心論述", "案例轉折", "收束金句", "CTA"]


def build_time_slots() -> list:
    """
    從 L0 time_slots + 本地 type mapping 組骨架用 slot list。
    若 L0 slots 數 != LOCAL_SLOT_TYPES 數 → fallback HARDCODED_TIME_SLOTS + WARN。
    """
    l0 = _load_l0_time_slots()
    if len(l0) != len(LOCAL_SLOT_TYPES):
        print(
            f"[WARN] yaml_skeleton_generator: L0 time_slots count "
            f"{len(l0)} != local type mapping {len(LOCAL_SLOT_TYPES)}; using hardcoded skeleton fallback",
            file=sys.stderr,
        )
        return list(HARDCODED_TIME_SLOTS)
    # timestamp 來自 L0（config 值）；type/task/note 用本地骨架文字（presentation 非 config，
    # 保持 skeleton 輸出 byte-identical 零行為改變 — B 段 §0 承諾「數字不變、只改來源」）。
    return [
        {
            "timestamp": s["timestamp"],
            "type":      LOCAL_SLOT_TYPES[i],
            "task":      HARDCODED_TIME_SLOTS[i]["task"],
            "note":      HARDCODED_TIME_SLOTS[i]["note"],
        }
        for i, s in enumerate(l0)
    ]


# 舊名 TIME_SLOTS 指向 build_time_slots()，維持向後相容（其他非關鍵引用不壞）
TIME_SLOTS = build_time_slots()


# ════════════════════════════════════════
# 時長 & 藏鏡人配額（cxp-fullimport-s r2 2026-08-12；r9 Q5 2026-08-13 fail-closed 修正）
#   ①60 秒＝L0 層的預設值非鎖；但**骨架機端非 60 秒＝fail-closed、未支援**：
#     plan item 或批級 meta.time_axis 只要宣告 duration ≠ 60，一律報錯不產骨架
#     （見 _assert_batch_duration_default_only；r6 P6 的「宣告一致就放行」半通路徑已真刪）。
#     可變時間軸段落組裝＝**backlog**（非本輪範圍），故此處不另造平行 schema。
#     驗證層的 time_axis 契約（validate_script_batch W4-K12）不受本閘影響——
#     既有非 60 秒稿件照樣驗得過，只是不能用骨架機生。
#   ②藏鏡人長度感知配額（L0 §9.4；2026-08-13 TG19773 各檔 +1）：<=25s→2／26-70s→3／>70s→≤4。
#     與 validate_script_batch._mirror_quota_for_duration 同一張表。
#     ⚠️ 本表共四處落地，改一處要四處同步：①L0 §9.4 表（正本）
#        ②SOP yaml batch_spec.actor_interaction_quota
#        ③validate_script_batch._MIRROR_QUOTA_TABLE ④本檔 _MIRROR_QUOTA_TABLE
# ════════════════════════════════════════
_MIRROR_QUOTA_TABLE = ((25, 2), (70, 3))   # TG19773 各檔 +1（舊 (25,1),(70,2)）
_MIRROR_QUOTA_LONG = 4                     # TG19773 +1（舊 3）

# L0 預設時長（60 秒）：骨架機只支援 60 秒；宣告非 60 秒＝報錯不產骨架（r9 Q5 fail-closed）
DEFAULT_DURATION_SECONDS = 60

# ── 題目鎖判準（單一真相＝topic_distributor；r6 P5）──
# import 失敗時 fail-closed：無法驗鎖就不准產骨架（禁自造寬鬆版判準）。
try:
    from topic_distributor import (
        assert_topics_locked as _assert_topics_locked,
        assert_topic_ids_resolvable as _assert_topic_ids_resolvable,
        MANUAL_TOPIC_ID_PREFIX as _MANUAL_TOPIC_ID_PREFIX,
        TOPIC_REJECT as _TOPIC_REJECT,
    )
    _TOPIC_LOCK_AVAILABLE = True
except Exception as _tl_err:   # pragma: no cover - 環境缺件才會走到
    _TOPIC_LOCK_AVAILABLE = False
    _TOPIC_REJECT = "TOPIC_REJECT"
    _MANUAL_TOPIC_ID_PREFIX = "MANUAL-"
    _TOPIC_LOCK_IMPORT_ERR = _tl_err

    def _assert_topics_locked(plan):  # type: ignore
        return False, [(None, [f"題目鎖判準 import 失敗（{_TOPIC_LOCK_IMPORT_ERR}）＝fail-closed，不產骨架"])]

    def _assert_topic_ids_resolvable(plan, owner):  # type: ignore
        # W3 fail-closed：解析器 import 失敗＝無法證明題源真實性，不准產骨架
        return False, [(None, f"題源解析器 import 失敗（{_TOPIC_LOCK_IMPORT_ERR}）＝fail-closed，不產骨架")]


def _mirror_quota_for_duration(duration_seconds) -> int:
    """時長 → 藏鏡人建議點數上限（L0 §9.4）。時長不明＝回 60s 檔（3）。"""
    if not isinstance(duration_seconds, int) or duration_seconds <= 0:
        duration_seconds = 60
    for upper, quota in _MIRROR_QUOTA_TABLE:
        if duration_seconds <= upper:
            return quota
    return _MIRROR_QUOTA_LONG


def _resolve_item_duration(item: dict, batch_spec: dict) -> int:
    """本支時長：plan item 宣告優先（duration_seconds / duration，支援 "45s"），
    否則回 L0 batch_spec.duration_seconds（預設 60）。解析不出＝回預設，不猜。"""
    for key in ("duration_seconds", "duration"):
        v = item.get(key)
        if type(v) is int and v > 0:
            return v
        if isinstance(v, str):
            m = re.match(r"^\s*(\d{1,4})\s*s?\s*$", v)
            if m and int(m.group(1)) > 0:
                return int(m.group(1))
    try:
        return int(batch_spec.get("duration_seconds", 60))
    except Exception:
        return 60


def _item_declares_duration(item: dict) -> bool:
    """本支 plan item 是否**自己宣告**了時長（不含 L0 預設回退）。"""
    if not isinstance(item, dict):
        return False
    for key in ("duration_seconds", "duration"):
        v = item.get(key)
        if type(v) is int and v > 0:
            return True
        if isinstance(v, str) and re.match(r"^\s*(\d{1,4})\s*s?\s*$", v):
            return True
    return False


def _batch_declared_time_axis_duration(meta: dict) -> tuple:
    """從 plan meta 取批級 time_axis 宣告的一致時長 →（有宣告?, duration or None）。

    只認既有批級 time_axis 契約（validate_script_batch W4-K12 / _batch_flags.yml time_axis），
    不另造平行 schema：meta.time_axis.duration_seconds，或 meta.time_axis_duration_seconds。
    r9 Q5 起僅供**錯誤訊息說明**用（宣告了也不放行），不再作為放行條件。
    """
    if not isinstance(meta, dict):
        return False, None
    axis = meta.get("time_axis")
    if isinstance(axis, dict):
        v = axis.get("duration_seconds")
        if type(v) is int and v > 0:
            return True, v
    v = meta.get("time_axis_duration_seconds")
    if type(v) is int and v > 0:
        return True, v
    return False, None


def _assert_batch_duration_default_only(plan, meta: dict) -> None:
    """非 60 秒 fail-closed（r9 Q5 2026-08-13，取代 r6 P6 的 `_assert_batch_duration_consistent`）。

    r6 P6 舊法（本輪真刪）：非 60 秒時只要批級 time_axis 宣告了一致值就**放行**。
    那是半通路徑——骨架機的 scenes 段落仍由 L0 60 秒六段組裝，放行等於產出
    「duration 標 15s、scenes 仍排到 52-60s」的 60 秒六段假骨架，比擋掉更糟。

    r9 新法：**任一支宣告 duration ≠ 60 一律報錯不產骨架**，含批級 meta.time_axis 已宣告者。
    骨架機不支援非 60 秒＝backlog（要支援得先做可變時間軸段落組裝，非本輪範圍）。
    驗證層的 time_axis 契約（validate_script_batch W4-K12）不受本閘影響——
    既有非 60 秒稿件照樣驗得過，只是**不能用骨架機生**。
    60 秒預設路徑（無 item 宣告，或宣告就是 60）逐字不變。
    """
    if not isinstance(plan, list):
        return
    declared = {}
    for idx, item in enumerate(plan, start=1):
        if not isinstance(item, dict) or not _item_declares_duration(item):
            continue
        d = _resolve_item_duration(item, {})
        declared.setdefault(d, []).append(item.get("seq", idx))

    non60 = {d: seqs for d, seqs in declared.items() if d != DEFAULT_DURATION_SECONDS}
    if not non60:
        return

    detail = "；".join(f"{d}s → seq {seqs}" for d, seqs in sorted(non60.items()))
    axis_declared, axis_duration = _batch_declared_time_axis_duration(meta)

    print(f"\n[ERROR] 非 {DEFAULT_DURATION_SECONDS} 秒骨架生成未支援＝backlog：{detail}")
    print(f"        骨架機的 scenes 段落固定由 L0 {DEFAULT_DURATION_SECONDS} 秒六段組裝；"
          f"產出會是「duration 標 Xs、scenes 仍到 {DEFAULT_DURATION_SECONDS}s」的假骨架。")
    if axis_declared:
        print(f"        （批級 time_axis 已宣告 {axis_duration}s 也一樣不放行——r9 Q5 刪除半通路徑："
              f"宣告只證明批次核准了時間軸，不代表骨架機會照該軸產段落。）")
    print(f"        驗證層的 time_axis 契約（validate_script_batch W4-K12）不受此閘影響："
          f"非 {DEFAULT_DURATION_SECONDS} 秒稿件仍可送驗，只是不能用本骨架機生。")
    print(f"        本批要出稿：請把 duration 改回 {DEFAULT_DURATION_SECONDS}，"
          f"或走人工／既有非 60 秒稿路徑。\n")
    sys.exit(3)


# Phase 2 FIX2：lazy proxy + cached projection loader（import 不碰 generated.json）
from functools import lru_cache
_YSG_DIR = Path(__file__).resolve().parent
if str(_YSG_DIR) not in sys.path:
    sys.path.insert(0, str(_YSG_DIR))
from _lazy_map import LazyMap

# ── owner_projection.generated.json loader（Phase 2 step1 2026-06-06）──
# 讀 sibling owner_projection.generated.json，建 OWNER_DIALOGUE_KEY / OWNER_PLATFORM。
# JSON 不存在 / 壞 / 缺欄位 → fail-loud raise SystemExit（禁保留硬編 fallback）。
def _load_owner_projection() -> tuple[dict, dict]:
    _proj_path = Path(__file__).resolve().parent / "owner_projection.generated.json"
    if not _proj_path.exists():
        raise SystemExit(
            f"[ERROR] yaml_skeleton_generator: owner_projection.generated.json not found at {_proj_path}\n"
            f"  Run gen_owner_projection_cache.py to regenerate."
        )
    try:
        _proj_data = json.loads(_proj_path.read_text(encoding="utf-8"))
    except Exception as _e:
        raise SystemExit(
            f"[ERROR] yaml_skeleton_generator: failed to parse owner_projection.generated.json: {_e}"
        )
    _owners = _proj_data.get("owners")
    if not isinstance(_owners, dict):
        raise SystemExit(
            "[ERROR] yaml_skeleton_generator: owner_projection.generated.json missing 'owners' dict"
        )
    _dialogue_key: dict = {}
    _platform: dict = {}
    for _name, _rec in _owners.items():
        if "dialogue_key" not in _rec:
            raise SystemExit(
                f"[ERROR] yaml_skeleton_generator: owner '{_name}' missing 'dialogue_key' in projection"
            )
        if "platform" not in _rec:
            raise SystemExit(
                f"[ERROR] yaml_skeleton_generator: owner '{_name}' missing 'platform' in projection"
            )
        _dialogue_key[_name] = _rec["dialogue_key"]
        _platform[_name] = _rec["platform"]
    return _dialogue_key, _platform


# 業主台詞欄位名對照 + 業主主推平台（Phase 2 FIX2 lazy——首次存取才載入；_proj_pair 快取一次）
@lru_cache(maxsize=1)
def _proj_pair():
    return _load_owner_projection()

OWNER_DIALOGUE_KEY = LazyMap(lambda: _proj_pair()[0])
OWNER_PLATFORM = LazyMap(lambda: _proj_pair()[1])


def _yaml_quote(value) -> str:
    return json.dumps(value, ensure_ascii=False)


TOPIC_TYPE_VALUES = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8")
TOPIC_TYPE_TARGET_COUNTS = {
    "Q1": 2, "Q2": 2, "Q3": 2, "Q4": 2,
    "Q5": 2, "Q6": 2, "Q7": 1, "Q8": 1,
}


def _topic_type_for_item(item: dict) -> str:
    """Use the allocator value, or deterministically prefill its Q1-Q8 slot."""
    value = item.get("topic_type")
    if value in TOPIC_TYPE_VALUES:
        return value
    try:
        seq = int(item.get("seq", 0))
    except (TypeError, ValueError):
        seq = 0
    sequence = [q for q in TOPIC_TYPE_VALUES for _ in range(TOPIC_TYPE_TARGET_COUNTS[q])]
    return sequence[seq - 1] if 1 <= seq <= len(sequence) else "[編劇填]"


def _append_quote_selector(
    lines: list[str],
    indent: str,
    field_name: str,
    dialogue_key: str,
    *,
    list_item: bool = False,
) -> None:
    """Append a G11 v1 {timestamp, dialogue_key} selector."""
    marker = "- " if list_item else ""
    lines.append(f"{indent}{marker}{field_name}:")
    child_indent = indent + ("    " if list_item else "  ")
    lines.append(f"{child_indent}timestamp: {_yaml_quote('[編劇填]')}")
    lines.append(f"{child_indent}dialogue_key: {_yaml_quote(dialogue_key)}")


def _append_hybrid_prefill(lines: list[str], item: dict, dialogue_key: str) -> None:
    if "content_axis" not in item:
        return

    content_axis = item.get("content_axis", "")
    lane = item.get("lane", "")
    derived_flags = item.get("derived_flags") or []
    topic_category = item.get("topic_category", "")

    lines.append("# hybrid allocator metadata")
    lines.append(f"content_axis: {_yaml_quote(content_axis)}  # allocator-locked, 編劇禁手改")
    lines.append(f"lane: {_yaml_quote(lane)}  # allocator-locked, 編劇禁手改")
    if isinstance(derived_flags, list) and derived_flags:
        lines.append("derived_flags:  # allocator-locked, 編劇禁手改")
        for flag in derived_flags:
            lines.append(f"  - {_yaml_quote(flag)}")
    else:
        lines.append("derived_flags: []  # allocator-locked, 編劇禁手改")
    lines.append(f"lane_reason: {_yaml_quote('[編劇填]')}")
    lines.append(f"voice_asset_quote: {_yaml_quote('[編劇填]')}")
    lines.append(f"topic_category: {_yaml_quote(topic_category)}")
    lines.append(f"cta_offer_scope: {_yaml_quote('[編劇填]')}")
    lines.append("")

    # G11：新 hybrid skeleton 一律走 selector runtime；hash 在填完 scenes 後
    # 由 derive_quotes.py --write 寫入，骨架不可偽造 placeholder hash。
    lines.append("quote_derivation_version: 1")
    lines.append("script_method:")
    lines.append("  chxp_v1:")
    lines.append("    four_materials:")
    lines.append(f"      problem_scene: {_yaml_quote('[編劇填]')}")
    lines.append("      old_answer:")
    _append_quote_selector(lines, "        ", "quote", dialogue_key)
    lines.append(f"        believer_profile: {_yaml_quote('[編劇填]')}")
    lines.append(f"        why_reasonable: {_yaml_quote('[編劇填]')}")
    lines.append(f"        weakness: {_yaml_quote('[編劇填]')}")
    lines.append("      new_answer:")
    _append_quote_selector(lines, "        ", "quote", dialogue_key)
    lines.append(f"      answer_expansion: {_yaml_quote('[編劇填]')}")
    lines.append("    assembly:")
    lines.append(f"      story_vehicle: {_yaml_quote('[編劇填]')}")
    lines.append("    optimization:")
    lines.append("      concrete_signals:")
    _append_quote_selector(lines, "        ", "quote", dialogue_key, list_item=True)
    lines.append(f"          type: {_yaml_quote('[編劇填]')}")
    lines.append("      hook_debts:")
    lines.append(f"        - opened_at: {_yaml_quote('[編劇填]')}")
    _append_quote_selector(lines, "          ", "opened_quote", dialogue_key)
    lines.append(f"          closed_at: {_yaml_quote('[編劇填]')}")
    _append_quote_selector(lines, "          ", "closed_quote", dialogue_key)
    lines.append("      barriers_removed:")
    lines.append(f"        - {_yaml_quote('[編劇填]')}")
    lines.append("    packaging:")
    _append_quote_selector(lines, "      ", "hook_promise", dialogue_key)
    _append_quote_selector(lines, "      ", "final_payoff", dialogue_key)
    lines.append(f"      cta_type: {_yaml_quote('[編劇填]')}")
    lines.append("")

    lines.append("friend_close:")
    lines.append("  evidence:")
    _append_quote_selector(lines, "    ", "value_delivered_quote", dialogue_key)
    _append_quote_selector(lines, "    ", "core_answer_quote", dialogue_key)
    _append_quote_selector(lines, "    ", "cta_quote", dialogue_key)
    lines.append(f"    cta_action_count: {_yaml_quote('[編劇填]')}")
    lines.append(f"    cta_offer_scope: {_yaml_quote('[編劇填]')}")
    lines.append("")

    if content_axis == "professional":
        lines.append(f"professional_topic_type: {_yaml_quote('[編劇填]')}")
        lines.append("actionable_steps:")
        lines.append(f"  - {_yaml_quote('[編劇填]')}")
        lines.append(f"core_answer: {_yaml_quote('[編劇填]')}")
        lines.append("")


def _proof_mode_for_hybrid_lane(item: dict) -> str | None:
    if "content_axis" not in item:
        return None
    lane = str(item.get("lane", "") or "").strip()
    return {
        "voice_first": "voice_first",
        "demand_first": "demand_first",
        "anchor_first": "anchor_first",
        "professional": "proof_first",
    }.get(lane)


# ════════════════════════════════════════
# 產單一 yaml 骨架文字
# ════════════════════════════════════════

def build_yaml_skeleton(item: dict) -> str:
    """
    item: topic plan 裡一條記錄
    回傳完整 yaml 文字（字串，含 --- frontmatter markers）
    B 段 2026-06-05：duration / title_max_chars / actor_interaction_min 改讀 L0；
    藏鏡人位置改用 seg_type in {"Hook","案例轉折"} 不寫死 timestamp；
    TIME_SLOTS 改由 build_time_slots() 組裝。
    """
    owner = item.get("owner", "未知")
    batch = item.get("batch", "01")
    batch_tag = item.get("batch_tag", f"第{batch}批")
    script_id = item.get("script_id", f"{owner}_{batch}_{item.get('seq', 1):02d}")
    school = item.get("派系", "[編劇填]")
    identity = item.get("雙身份", "[編劇填]")
    direction = item.get("direction", "[編劇填]")
    dialogue_key = OWNER_DIALOGUE_KEY.get(owner, "台詞")
    platform = OWNER_PLATFORM.get(owner, "FB Reels")

    # 讀 L0 值
    bs = _load_l0_batch_spec()
    title_max_chars    = int(bs.get("title_max_chars", 15))
    # （r6 P4）actor_min 死變數已刪：藏鏡人配額改由 _mirror_quota_for_duration(duration) 決定，
    # 不再讀 batch_spec.actor_interaction_min。

    # 時長（cxp r2 2026-08-12；r9 Q5 2026-08-13 fail-closed 修正）：
    #   本函式只組 60 秒六段骨架。非 60 秒＝**已在 _assert_batch_duration_default_only 擋掉**，
    #   走不到這裡（骨架機不支援可變時間軸＝backlog；批級 time_axis 宣告也不放行）。
    #   解析優先序＝①plan item 宣告（duration_seconds/duration）②L0 batch_spec.duration_seconds 預設。
    duration_seconds = _resolve_item_duration(item, bs)
    mirror_quota = _mirror_quota_for_duration(duration_seconds)

    # 骨架用的 slot list（由 build_time_slots() 從 L0 組裝）
    active_slots = build_time_slots()

    # ── Frontmatter ──
    lines = ["---"]
    lines.append(f"script_id: {script_id}")
    lines.append(f"owner: {owner}")
    lines.append(f"batch: \"{batch}\"")
    lines.append(f"batch_tag: {batch_tag}")
    lines.append(f"title: \"[編劇填]\"  # {title_max_chars} 字內金句")
    lines.append(f"template: {school}方向")
    lines.append(f"pattern: \"[編劇填]\"  # e.g. 創業故事型 / 觀點分享型（亦作 §21.1 破套路骨架型，C-21.1 統計此欄；帶引號從源頭消除 YAML 解析成 list 的歧義）")
    lines.append(f"雙身份分類: {identity}")
    lines.append(f"dominant_viewer_takeaway: [編劇填]  # e.g. 共鳴認同 / 實用學習")
    lines.append(f"duration: {duration_seconds}s")
    lines.append(f"main_platform: {platform}")
    lines.append(f"publish_mode: manual_today  # enum: manual_today / platform_scheduled / draft_only")
    lines.append(f"distribution_mode: organic_only  # enum: organic_only / boost_candidate / paid_ad")
    lines.append(f"topic_type: {_yaml_quote(_topic_type_for_item(item))}  # required enum: Q1 / Q2 / Q3 / Q4 / Q5 / Q6 / Q7 / Q8")
    lines.append("origin_source: \"\"  # optional enum: source_1_comment / source_2_reference / source_3_owner / source_4_created / aux")
    _append_hybrid_prefill(lines, item, dialogue_key)
    lines.append(f"voice_lock: true  # 聲明業主聲音語料強制入 Hook（見 L2 偏好.md §voice_lock）")
    lines.append(f"suggested_po_time: \"[編劇填]\"  # e.g. 週三晚 8PM")
    lines.append(f"派系: {school}")
    lines.append(f"")
    # ── §21.7 誠實天花板三欄（2026-06-17 機器化 §21；C-21.7 per-file 驗）──
    lines.append(f"score_type: angle  # angle / script / finished_video（角度90≠成片90，誠實分層）")
    lines.append(f"true_material_source: none  # none / transcript / video（transcript/video 須帶路徑 true_material_path）")
    lines.append(f"claim_allowed: \"[編劇填]\"  # 本支允許的宣稱，e.g. 角度到位、成片估分X待真語料（true_material_source=none 時禁寫「成片 90」）")
    # 系列批用（§21.1 系列例外：同時填 series_id+episode 才豁免主公式統計；預設註解不啟用）
    lines.append(f"# series_id: \"\"      # 系列批才填，e.g. 總督系列")
    lines.append(f"# episode: 0          # 系列批集數，e.g. 1")
    lines.append(f"")
    # ── §22 選題公式（proof_mode 四型 + 6 件套；2026-06-17 機器化 §22、2026-07-13 W2-D20 四型對齊；C-22 + C-22b batch-level shadow WARN）──
    # 好角度 = 專屬證據→非顯主張→受眾真代價→行為改變 + 決策時刻 + 業主可信度（見 scripter.md §22.1）
    hybrid_proof_mode = _proof_mode_for_hybrid_lane(item)
    if hybrid_proof_mode:
        lines.append(f"proof_mode: {_yaml_quote(hybrid_proof_mode)}             # hybrid allocator-locked from lane；編劇禁手改")
    else:
        lines.append(f"proof_mode: \"[編劇填]\"             # proof_first / demand_first / anchor_first / voice_first（四型擇一；voice_first=立場 lane 專用、hybrid 批由 allocator 鎖定非手填，見 scripter.md §22.2）")
    lines.append(f"proof_asset: \"[編劇填]\"            # 業主 §0/§10.5 真料（真故事/案例/數據/服務觀察/客戶FAQ）+ source_ref；proof_first 必先有、禁腦補（anchor_first 改走下方 anchor_ref）")
    lines.append(f"non_obvious_claim: \"[編劇填]\"      # 一句同行不會講的話（驗收：proof-removed test — 拿掉業主料若同行仍能講 → 太一般退回）")
    lines.append(f"audience_decision_cost: \"[編劇填]\"  # 連受眾哪個真代價：多花錢/延誤/踩雷/錯買/錯信/錯過（必填、無 → 案例獵奇降權）")
    lines.append(f"behavior_delta: \"[編劇填]\"          # 看完下次具體改什麼動作（非情緒、是動作，e.g.「下次看到 X 先查 Y 再回」；必填）")
    lines.append(f"audience_decision_moment: \"[編劇填]\"  # 具體處境（非「想買房的人」「想保養的人」）")
    lines.append(f"owner_credibility: \"[編劇填]\"       # 硬訊號 ≥1：親身服務案例/可追溯 source_ref/去識別客戶FAQ/獨有流程或檢查表")
    lines.append(f"# anchor_first 專用三必填（proof_mode=anchor_first 時取消註解並填，見 scripter.md §22.8；C-22b 機械閘 shadow）")
    lines.append(f"# anchor_ref: \"[編劇填]\"      # 指向 L2 偏好.md §9.5 voice_lock 真料（禁指向 .generated.md 退役拼接本）")
    lines.append(f"# anchor_cost: \"[編劇填]\"     # 具體代價（禁「很努力/很辛苦/低谷/成長」空泛詞）")
    lines.append(f"# because_bridge: \"[編劇填]\"  # 因為 X 代價 → 所以本題先看 A 不看 B（要有因果結構）")
    lines.append(f"")
    # C-22-OFFPRO-ANGLE stub（2026-06-24 shadow）：只對 voice_first 稿輸出
    if hybrid_proof_mode == "voice_first":
        lines.append("# C-22-OFFPRO-ANGLE 角度守門 stub（C-22-OFFPRO-ANGLE 機械閘 Phase 0 shadow，2026-06-24 建）")
        lines.append("# 把本支角度投影成 11 欄（對應 §22.3/§22.4/§22.9/§22.9.1 反一般化欄位）")
        lines.append("# 先把 topic 寫成過 stub 的尖角度、再寫台詞（見 scripter.md §22.9）")
        lines.append("c22_offpro_angle_stub:")
        lines.append("  topic: \"[填：本支題目一句話]\"")
        lines.append("  generic_take: \"[填：同行都能講的通用觀點，作對照用]\"")
        lines.append("  sharp_claim: \"[填：一句同行講不出的尖主張（禁溫共識詞如『做自己/活在當下』，需有對比或取捨結構）]\"")
        lines.append("  rejected_common_belief: \"[填：你要挑戰的主流觀念/錯誤前提]\"")
        lines.append("  tradeoff_or_cost: \"[填：這個主張帶來的真實代價或取捨（不是情緒，是行動後果）]\"")
        lines.append("  behavior_delta: \"[填：看完下次具體改什麼動作（非情緒，是動作）]\"")
        lines.append("  audience_decision_moment: \"[填：具體情境（禁寫『大家/人人/所有人』等寬泛詞）]\"")
        lines.append("  opposing_rebuttal: \"[填：持相反觀點者會怎麼反駁（不得等於 sharp_claim）]\"")
        lines.append("  concrete_scene: \"[填：例子場景——禁真人見證口吻，用示意例如『舉個示意例：有人...』]\"")
        lines.append("  timeliness_or_context: \"[填：為什麼現在講這個有時效性或情境關聯]\"")
        lines.append("  title_gap: \"[填：能讓觀眾停下來的標題角度（禁重述 topic，要有資訊落差）]\"")
        lines.append("  voice_removed:              # 投影 §22.9 offpro_voice_removed 三分制（各項 0-5，目標 ≥4）")
        lines.append("    concreteness: 0           # [完稿後填] 具體化程度（0=空泛 / 5=有場景/人/代價）")
        lines.append("    stance_sharpness: 0       # [完稿後填] 立場銳度（0=溫共識 / 5=有人想反駁）")
        lines.append("    replacement_loss: 0       # [完稿後填] 去掉業主聲音後損失（0=誰都能講 / 5=失去唯一性）")
        lines.append("")
    lines.append(f"# 題目方向（topic_distributor.py 分配，編劇填內文後請刪此行）")
    lines.append(f"# direction: {str(direction).replace(chr(10), ' ')}")
    lines.append(f"")

    # ── 題目鎖 block（cxp r2 2026-08-12；r6 P5 補 YAML escape）──
    # 舊法真刪：骨架機原本照抄 `direction: [編劇填] — X方向 N` 空題殼就開工。
    # 新法：真題五欄隨骨架落地，供 validator/審查逐支查得到題從哪來。
    # r6 P5：題目字串一律走 _yaml_quote（json.dumps）——含雙引號/反斜線/換行的真題
    #        不再產出無效 YAML（Codex 阻擋項 1 末條）。
    _lock = item.get("topic_lock") if isinstance(item.get("topic_lock"), dict) else {}
    lines.append("# 題目鎖（topic_distributor 題目層鎖題；寫稿端不得自行換題，題不合用回 TOPIC_REJECT）")
    lines.append("topic_lock:")
    for _f, _hint in (
        ("topic_statement", "真題一句話（禁『X派方向N』這類殼）"),
        ("topic_source", "題從哪來（情報池 topic_id／業主訪談／客戶問題／時事）"),
        ("topic_id", "情報池／題庫題目識別碼（r9 Q4 必填）"),
        ("audience_scene", "講給誰＋什麼情境下有用"),
        ("can_shoot", "業主拍得到的素材／場景"),
        ("want_shoot", "業主本人願意講"),
    ):
        _raw = _lock.get(_f, "")
        # r11 T1：序列化層與 topic_lock_status 型別契約對齊——
        #   非法型別（bool／數字／dict／list／None）**不做 str() 救援**，一律落成空值＋[題目層填]。
        #   舊法 str(_raw) 會把 True→"True"、0→"0"、{}→"{}" 寫進 yaml，
        #   下游看起來像已填的真題，等於序列化層把未鎖題洗成已鎖（--allow-unlocked-topics 路徑尤甚）。
        if _f in ("can_shoot", "want_shoot"):
            _v = _raw if isinstance(_raw, str) else ("true" if _raw is True else "")
        else:
            _v = _raw if isinstance(_raw, str) else ""
        lines.append(f"  {_f}: {_yaml_quote(_v)}  # {'[題目層填]' if not _v else ''}{_hint}")
    # r9 Q4：流量候選＝清單型必填欄（非空才算鎖）
    # r11 T1：型別對齊——限 list/tuple，且只收非空 str 元素（單一字串／數字／dict 皆不救援）
    _tc = _lock.get("traffic_candidates")
    _tc_items = ([x for x in _tc if isinstance(x, str) and x.strip()]
                 if isinstance(_tc, (list, tuple)) else [])
    lines.append(f"  traffic_candidates:  # {'[題目層填]' if not _tc_items else ''}"
                 f"流量候選（r9 Q4 必填，至少一項）")
    for _x in _tc_items:
        lines.append(f"    - {_yaml_quote(str(_x))}")
    lines.append(f"  locked_by: {_yaml_quote(str(_lock.get('locked_by', '') or ''))}")
    lines.append(f"  locked_at: {_yaml_quote(str(_lock.get('locked_at', '') or ''))}")
    lines.append("")

    # ── 藏鏡人（長度感知配額，cxp r2 2026-08-12；r6 P7 併回 scenes）──
    # 舊法真刪①：原固定產「位置1／位置2」兩點 + schema_check 藏鏡人數量 >= 2。
    # 舊法真刪②（r6 P7，Codex 阻擋項 3）：原本同時產「頂層平行 block（位置N/句子N/接球N/酸度N）」
    #   與「scenes 內固定 Hook＋案例轉折各一點」＝同一支兩套來源。
    #   validator 優先讀 scenes（canonical），看不到頂層 block → ≤25s 假超額、60s 新骨架報接球酸度全缺。
    # 新法：藏鏡人點**只產在 scenes 內**（canonical `_canonical_scenes_structured` 的
    #   `藏鏡人` → offscreen_interaction 落點，chk_l1_003 讀得到），
    #   點數＝本支時長配額（不再寫死 2 點），每點就地帶「藏鏡人接球 / 藏鏡人酸度」欄
    #   （鍵名對齊 validator._MIRROR_REPLY_KEYS / _MIRROR_SOURNESS_KEYS）。
    hook_ts     = next((s["timestamp"] for s in active_slots if s["type"] == "Hook"),     "0-3s")
    turning_ts  = next((s["timestamp"] for s in active_slots if s["type"] == "案例轉折"), "25-40s")
    cta_ts      = active_slots[-1]["timestamp"] if active_slots else "52-60s"
    # 配額 → 用哪些段落型別放藏鏡人（依序取前 mirror_quota 個）
    _MIRROR_SEG_PRIORITY = ("Hook", "案例轉折", "CTA")
    _mirror_seg_types = set(_MIRROR_SEG_PRIORITY[:mirror_quota])
    _mirror_role_hint = {
        "Hook": "破題後的第一反應",
        "案例轉折": "案例後的恍然大悟",
        "CTA": "要更多／下決心",
    }
    # 段落型別不齊時（批級 time_axis 自訂軸）：退回「前 mirror_quota 個段落」
    _available_types = [s["type"] for s in active_slots]
    if not _mirror_seg_types.intersection(_available_types):
        _mirror_seg_types = set(_available_types[:mirror_quota])
    lines.append(f"# 藏鏡人：{duration_seconds}s → 建議 {mirror_quota} 點（L0 §9.4 長度感知配額，"
                 f"非硬性 >=2；超量只 WARN 不擋批）")
    lines.append("# 每點必附業主接球（藏鏡人拋、業主接）＋酸度分級 S0/S1/S2（天花板見 L2 業主檔）")
    lines.append("# r6 P7：藏鏡人只寫在下方 scenes 內（單一來源），不另設頂層平行 block")
    lines.append("")

    # ── scenes ──
    lines.append("scenes:")
    _mirror_written = 0
    for slot in active_slots:
        ts = slot["timestamp"]
        seg_type = slot["type"]
        task = slot["task"]
        note = slot["note"]

        lines.append(f"  - timestamp: \"{ts}\"")
        lines.append(f"    type: {seg_type}")
        lines.append(f"    # 任務：{task}")
        lines.append(f"    # 注意：{note}")
        lines.append(f"    {dialogue_key}: \"[編劇填]\"")

        # 藏鏡人：依配額落在指定段落型別（r6 P7；不再寫死 Hook+案例轉折 兩點）
        if seg_type in _mirror_seg_types and _mirror_written < mirror_quota:
            _mirror_written += 1
            _hint = _mirror_role_hint.get(seg_type, "觀眾內心話")
            lines.append(f"    藏鏡人: \"[編劇填]\"  # 第 {_mirror_written}/{mirror_quota} 點（{_hint}）")
            lines.append(f"    藏鏡人接球: \"[編劇填]\"  # 業主怎麼接這句（必填，L0 §9.4）")
            lines.append(f"    藏鏡人酸度: \"S1\"  # S0 中性替問 / S1 直球點破 / S2 嘴賤最大檔（不得超 L2 天花板）")

        lines.append(f"    畫面: \"[編劇填]\"  # 視覺場景建議（地點/穿著/氛圍/道具）")
        lines.append(f"    翠文: \"[編劇填]\"  # 字幕（≠ 畫面描述，是觀眾看的字幕文字）")
        lines.append("")

    # ── caption + hashtag ──
    lines.append("caption: \"[編劇填]\"  # 60-80 字純文（不含 hashtag）")
    lines.append("hashtag:")
    for i in range(1, 11):
        lines.append(f'  - "[編劇填{i}]"  # 8-12 個')
    lines.append("")

    # ── 範本引用（§12.3 強制餵範本系統，2026-06-01 後新批必填）──
    lines.append("# 高規格批次（對外+業績+S級）須在批次資料夾附 _quality_gate_report.md（整稿閘 R10-R20，見 scripter.md §21.6 / C-21.6 驗）；")
    lines.append("# 非 S 級批要豁免整稿閘 → 在批次資料夾的 _batch_flags.yml 寫（不是單支 yaml）：")
    lines.append("#   quality_gate:")
    lines.append("#     exempt: true")
    lines.append("#     reason: \"B 級內部測試批，不過外部整稿閘\"")
    lines.append("# （C-21.6 P1-4：只認 batch-level _batch_flags.yml 的 quality_gate 段，單支 yaml 的 quality_gate_exempt 已不認）")
    lines.append("# 範本引用：請跑 template_retriever.py 查詢後填入（新批 2026-06-01 後強制，缺失 → FAIL）")
    lines.append("template_source_ids: []  # [編劇填] 3-5 張範本 id，e.g. [\"style-1-bw-fact_001\", ...]")
    lines.append("template_adaptation:")
    lines.append("  learned_structure: \"[編劇填]  # 從範本學到的結構，e.g. 反差 hook + 案例收束\"")
    lines.append("  changed_context: \"[編劇填]  # 把範本情境換成本批，e.g. 把帶看換成瑞祥帶看日出段\"")
    lines.append("  forbidden_copy_check: pending  # 編劇確認無直接複製範本 → 改為 PASS")
    lines.append("")

    # ── WP-B source_topic_intel block（只有 assign on + plan item 有此欄才輸出）──
    # 零足跡鐵律：off 時 item 無 source_topic_intel → 不輸出任何 block/空行/註解
    sti = item.get("source_topic_intel")
    if sti and isinstance(sti, dict):
        lines.append("# 選題情報來源（topic_distributor.py WP-B assign 寫入，編劇填 adopted_topic_statement）")
        lines.append("source_topic_intel:")
        lines.append(f"  topic_id: \"{sti.get('topic_id', '')}\"")
        lines.append(f"  source_kind: {sti.get('source_kind', 'cyborg_yaml')}")
        ev_path = sti.get("evidence_path", "") or ""
        # Fix：Windows 反斜線在 YAML 雙引號字串中會被解為 Unicode escape（\U → 解析失敗）
        # 改用正斜線（Python pathlib / YAML 解析器均接受）
        ev_path_yaml = ev_path.replace("\\", "/")
        lines.append(f"  evidence_path: \"{ev_path_yaml}\"")
        lines.append(f"  evidence_sha256: \"{sti.get('evidence_sha256', '')}\"")
        # adopted_topic_statement：編劇填（validator skeleton 階段 SKIP，成稿驗關鍵詞交集）
        adopted = sti.get("adopted_topic_statement", "") or ""
        lines.append(f"  adopted_topic_statement: \"{adopted}\"  # [編劇填] 本支採用的題材一句話（≥12 中文字）")
        lines.append(f"  assigned_by: {sti.get('assigned_by', 'topic_distributor')}")
        lines.append(f"  assignment_mode: {sti.get('assignment_mode', 'off')}")
        lines.append("")

    # ── schema_check ──
    lines.append("schema_check:")
    lines.append("  禁虛構: true")
    lines.append(f"  藏鏡人數量: {mirror_quota}  # {duration_seconds}s 建議 {mirror_quota} 點（L0 §9.4 長度感知配額；下限 1）")
    lines.append("  流量密碼: [\"[編劇填]\", \"[編劇填]\", \"[編劇填]\"]  # L0 §1.5 十五元素具名宣告（>= traffic_codes_min；2026-08-12 起關鍵詞計數已廢）")
    # ── 零件庫機器契約三欄（r9 Q7 2026-08-13）──
    # 五項導入的三個零件庫（標題六型／開頭四型／結尾三型）原本只有文檔敘述，
    # yaml 沒有欄位＝機器讀不到、驗不了。此三欄讓編劇具名宣告用了哪個型。
    # validator 端＝WARN-only（缺欄或非法 enum 只提示，不 FAIL）——130+ 現役稿無此欄，
    # 直上硬閘會把既有批次全打紅（同 _MIRROR_REPLY_ENFORCE 的過渡取捨）。
    lines.append("  標題型: \"[編劇填 T1-T6]\"  # L0 §11.0.4 標題六型（T1新知識/T2提問/T3解答/T4反常識/T5佔便宜/T6揭秘），一支一型")
    lines.append("  開頭軸: \"[編劇填 O1-O4]\"  # L0 §11.0.5 開頭四型（O1懸念/O2故事/O3極端對比/O4提供價值），一選一互斥")
    lines.append("  結尾型: \"[編劇填 E1-E3]\"  # L0 §13.6 結尾三型正本（E1互動/E2金句Slogan/E3情緒昇華夥伴式）；反轉＝payoff 技法，不是第四型")
    lines.append("  答案完整不拆集: true")
    lines.append("  CTA類型: \"[編劇填]\"  # e.g. 互動留言型 / 釣魚型 / 個人化諮詢型（亦作 §21.2 cta_effect，C-21.2 統計種類多樣性）")
    lines.append("  禁用詞自查: \"[編劇填後改為 PASS]\"")
    lines.append(f"  雙身份比例: {identity}")
    lines.append(f"  派系比例: {school}")

    # ── chxp_receipt：「這支用了哪幾招」收據（cxp-enforce-t2 梯 2，2026-08-13）──
    # 得標定稿骨架＝Codex R1 chxp_receipt 結構層；嫁接【愛馬仕】C-quote-source
    # 「宣告必須兌現」範式、【龍蝦】conditional 由機器重算不准編劇自填 N/A。
    # 🔴 applicable_ids **由 validator 依 registry 重算**，這裡只印機器算出來的值供編劇參考；
    #    編劇改它不會改變判定（改了只會在報表上被標「與機器重算不符，以機器為準」）。
    # 🔴 validator 只驗結構三件事：method_id 合法／證據指標解得回稿內位置／該型必填欄在不在。
    #    **不判用得好不好**（澤君 TG19810 紅線：不鎖死寫法、零語意品質判斷）。
    lines.append("")
    lines.append("# ── 方法收據（陳修平 128 條 registry；validator: C-CXP-RECEIPT / C-CXP-0xx）──")
    lines.append("# 填法：這支真的用到哪幾招，就在 used 底下列一條。")
    lines.append("#   method_id：registry 的三位數 id（如 \"041\"）；不在冊的 id ＝ FAIL。")
    lines.append("#   evidence_ref：指回稿內位置，只認兩種寫法——")
    lines.append("#     path:<欄位路徑>   例 path:chxp_method_selection.041.段落安排")
    lines.append("#     quote:<稿內原句>  例 quote:喜歡是感覺，付款是條件（須真的出現在本稿）")
    lines.append("#   指不回去 ＝ FAIL（宣告必須兌現）。系統不判你這招用得好不好。")
    lines.append("# 選型欄（用到才填，沒用到整段不必寫；沒選＝不適用，不會被扣）：")
    lines.append("#   chxp_method_selection:")
    lines.append("#     \"041\": {type: POV|熱門梗|生活觀察, 段落安排: \"...\"}      # 演劇情三式")
    lines.append("#     \"053\": {used: true, 回憶點: \"...\"}                        # 懷舊")
    lines.append("#     \"055\": {type: 吸睛外型|氣氛, 同意紀錄: \"...\"}             # 需取得同意")
    lines.append("#     \"064\": {used: true, 不為人知的規則: \"...\", 原因: \"...\"}   # 行業揭秘")
    lines.append("#     \"068\": {type: 正推|反推, 理由: \"...\", 結論: \"...\"}        # 推薦題")
    lines.append("#     \"069\": {used: true, 分類: \"...\", 順序: \"...\"}             # 資訊整理")
    lines.append("#     \"101\": {mode: 整理既有資料, sources: [\"...\"]}             # 記錄不創造")
    lines.append("#   #103（60 秒稿口白 240-300 字）＝機器自己數，不用填。")
    lines.append("# receipt 層 5 條（用到就在 used 具名＋給證據；沒用到不用填）：")
    lines.append("#   018 前十支試 2-3 種拍法／027 Google 下拉選題／028 關鍵字工具選題")
    lines.append("#   043 上一層思維破圈／080 看別人框架→實測→留下有效")
    lines.append("#   #058 切片一魚多吃＝**BLOCKED**，走獨立入口，不在本表宣稱完成。")
    lines.append("#   #021/#022/#109＝人工清單（chxp_manual_checklist_template.md），系統零自動對外。")
    lines.append("# 🔴 always 11 條（一律適用）：每條都要在 used 具名，或在 waiver 寫一句為何本支沒用。")
    lines.append(f"#   現值：{', '.join(_chxp_always_ids_for_skeleton())}")
    lines.append("#   waiver 寫法： waiver: {\"010\": \"本支為單點知識，無系列鋪陳\"}")
    lines.append("# 🔴 receipt_hash＝新鮮度錨：**稿件填完後要重算一次**，否則收據過期＝FAIL。")
    lines.append("#   重算指令：python3 chxp_registry.py --stamp <本檔路徑>")
    lines.append("chxp_receipt:")
    lines.append(f"  registry_version: \"{_chxp_registry_version_for_skeleton()}\"  # 產骨架當下的 registry 版本（供追溯，不用改）")
    lines.append("  applicable_ids: []  # 機器重算，不用填（填了也以機器為準；填未知 id ＝ FAIL）")
    lines.append("  used: []  # [編劇填] 例：- {method_id: \"041\", evidence_ref: \"path:chxp_method_selection.041.段落安排\"}")
    lines.append("  waiver: {}  # [編劇填] always 11 條中本支沒用到的，逐條寫一句理由（只驗有無申報，不判品質）")
    lines.append("  source_artifact_hashes: {}  # 來源檔 sha256（無來源檔就留空 mapping）")
    lines.append(f"  receipt_hash: \"{'0' * 64}\"  # 佔位；填完稿執行 --stamp 重算（不重算＝收據過期 FAIL）")
    lines.append("---")

    return "\n".join(lines)


def _chxp_always_ids_for_skeleton() -> list[str]:
    """取 registry 的 always 11 條 id 供骨架註解列出（讀不到回明碼標記）。"""
    try:
        import chxp_registry as _cr  # type: ignore[import]
        reg, err = _cr.load_registry()
        if err or reg is None:
            return [f"UNAVAILABLE:{err}"]
        return _cr.always_applicable_ids(reg)
    except Exception as e:
        return [f"UNAVAILABLE:{type(e).__name__}"]


def _chxp_registry_version_for_skeleton() -> str:
    """取 registry 版本字串供骨架留痕；registry 不可用時回明碼標記（不假裝有版本）。"""
    try:
        import chxp_registry as _cr  # type: ignore[import]
        reg, err = _cr.load_registry()
        if err or reg is None:
            return f"UNAVAILABLE:{err}"
        return str(reg.get("registry_version", "UNKNOWN"))
    except Exception as e:
        return f"UNAVAILABLE:{type(e).__name__}"


# ════════════════════════════════════════
# 主程式
# ════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="yaml 骨架機 — 產 SOP batch_spec.main_scripts 個空 yaml 骨架")
    parser.add_argument("--topic-plan", required=True, help="topic_distributor.py 產的 JSON 路徑")
    parser.add_argument("--output-dir", required=True, help="產出目標資料夾（會自動建立）")
    parser.add_argument("--tmp",        action="store_true", help="輸出 .tmp yaml（自驗用，不 commit）")
    parser.add_argument(
        "--allow-unlocked-topics", action="store_true",
        help=("允許為未鎖題的 plan 產骨架（過渡用）。預設不允許：得標定稿 §4「骨架只接受已鎖真題」。"
              "用了會逐槽列出缺欄，且產出的骨架 topic_lock 欄留空、寫稿端仍不得自行補題。"),
    )
    args = parser.parse_args()

    plan_path = Path(args.topic_plan)
    if not plan_path.exists():
        print(f"[ERROR] topic-plan 不存在：{plan_path}")
        sys.exit(1)

    try:
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] 讀 topic-plan JSON 失敗：{e}")
        sys.exit(1)

    plan = plan_data.get("plan", [])
    meta = plan_data.get("meta", {})
    owner = meta.get("owner", "未知")
    batch = meta.get("batch", "未知")

    print(f"\n{'='*60}")
    print(f"  yaml 骨架機 v1.0")
    print(f"  業主：{owner}  /  批次：{batch}  /  plan 數量：{len(plan)}")
    print(f"{'='*60}\n")

    # ── 題目鎖閘（r6 P5 2026-08-12）──
    # 舊法真刪：--allow-unlocked-topics 只宣告不使用，未鎖 plan 照樣 exit 0。
    # 新法：主流程開工前呼叫 assert_topics_locked()，未鎖且無旗標 → 逐槽列缺欄、非零 exit。
    all_locked, unlocked = _assert_topics_locked(plan)
    if not all_locked:
        print(f"[題目鎖] {len(unlocked)} 槽未鎖（得標定稿 §4：骨架只接受已鎖真題）：")
        for seq, missing in unlocked:
            print(f"    - seq {seq}：{'、'.join(missing)}")
        if not args.allow_unlocked_topics:
            print(f"\n[ERROR] 題目未鎖，拒產骨架。請題目層補齊上列欄位後重跑；")
            print(f"        寫稿端不得自行補題或換題，題不合用回 {_TOPIC_REJECT} 退回題目層。")
            print(f"        （過渡期確需產空殼骨架：加 --allow-unlocked-topics）\n")
            sys.exit(2)
        print(f"[WARN] --allow-unlocked-topics 已指定：續產骨架，topic_lock 欄留空。\n")
    else:
        print(f"[題目鎖] {len(plan)} 槽全部已鎖 ✓\n")

    # ── 題源真實性閘（W3／cxp-gapfix-w1 2026-08-13）──
    # 龍蝦堵法表 P0-1 實測：七欄填自造值＋假 topic_id（FAKE-999）→ 舊法 exit 0。
    # 新法：鎖到的 topic_id 必須命中 owner 的 projection record，或走 typed 人工
    # namespace（MANUAL- 前綴＋具名 locked_by）。無命中＝假題，exit 2、不產骨架。
    # 與 --allow-unlocked-topics 的關係：該旗標只放行「欄位未填」的空殼骨架
    # （此時 topic_lock 欄留空、下游仍擋），**不放行「填了假 topic_id」**——
    # 那正是本閘要堵的偷跳路徑，故本閘無旗標可繞。
    if all_locked:
        ids_ok, bad_ids = _assert_topic_ids_resolvable(plan, owner)
        if not ids_ok:
            print(f"[題源] {len(bad_ids)} 槽 topic_id 無法解析到真實題源：")
            for seq, detail in bad_ids:
                print(f"    - seq {seq}：{detail}")
            print(f"\n[ERROR] 題源不可驗，拒產骨架。")
            print(f"        情報池題：topic_id 需來自 projection record（跑 gen_topic_intel_projection.py 更新）。")
            print(f"        人工題　：topic_id 用 {_MANUAL_TOPIC_ID_PREFIX} 前綴＋topic_lock.locked_by 具名。")
            print(f"        題不合用回 {_TOPIC_REJECT} 退回題目層，禁自行造 id。\n")
            sys.exit(2)
        print(f"[題源] {len(plan)} 槽 topic_id 全部可解析 ✓\n")

    # ── 時長 fail-closed 閘（r9 Q5 2026-08-13，取代 r6 P6 半通路徑）──
    _assert_batch_duration_default_only(plan, meta)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = ".tmp.yaml" if args.tmp else ".yaml"

    generated: list[Path] = []
    for item in plan:
        seq = item.get("seq", 0)
        script_id = item.get("script_id", f"unknown_{seq:02d}")

        # 檔名：script_<owner_code>_<batch>_<seq>.yaml
        fname = f"script_{script_id}{ext}"
        out_path = out_dir / fname

        yaml_text = build_yaml_skeleton(item)
        out_path.write_text(yaml_text, encoding="utf-8")

        fsize = out_path.stat().st_size
        print(f"  [{seq:02d}] {fname}  ({fsize} bytes, {len(yaml_text.splitlines())} lines)")
        generated.append(out_path)

    print(f"\n[DONE] 產出 {len(generated)} 個 yaml 骨架  →  {out_dir}")
    print(f"\n{'='*60}\n")

    # 彙總報告
    total_size = sum(p.stat().st_size for p in generated)
    print(f"  彙總：{len(generated)} 檔 / 總 {total_size} bytes")
    print(f"  路徑：{out_dir}\n")

    if len(generated) != len(plan):
        print(f"[ERROR] 輸出 {len(generated)} 檔，但 plan 有 {len(plan)} 條 — 請檢查")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
