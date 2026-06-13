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
        return {"main_scripts": 13, "duration_seconds": 60, "title_max_chars": 15, "actor_interaction_min": 2}

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
    duration_seconds   = int(bs.get("duration_seconds", 60))
    title_max_chars    = int(bs.get("title_max_chars", 15))
    actor_min          = int(bs.get("actor_interaction_min", 2))

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
    lines.append(f"pattern: [編劇填]  # e.g. 創業故事型 / 觀點分享型")
    lines.append(f"雙身份分類: {identity}")
    lines.append(f"dominant_viewer_takeaway: [編劇填]  # e.g. 共鳴認同 / 實用學習")
    lines.append(f"duration: {duration_seconds}s")
    lines.append(f"main_platform: {platform}")
    lines.append(f"publish_mode: manual_today  # enum: manual_today / platform_scheduled / draft_only")
    lines.append(f"distribution_mode: organic_only  # enum: organic_only / boost_candidate / paid_ad")
    lines.append(f"voice_lock: true  # 聲明業主聲音語料強制入 Hook（見 L2 偏好.md §voice_lock）")
    lines.append(f"suggested_po_time: \"[編劇填]\"  # e.g. 週三晚 8PM")
    lines.append(f"派系: {school}")
    lines.append(f"")
    lines.append(f"# 題目方向（topic_distributor.py 分配，編劇填內文後請刪此行）")
    lines.append(f"# direction: {direction}")
    lines.append(f"")

    # ── 藏鏡人 block（位置描述固定用 slot type 名稱，不寫死 timestamp）──
    hook_ts     = next((s["timestamp"] for s in active_slots if s["type"] == "Hook"),     "0-3s")
    turning_ts  = next((s["timestamp"] for s in active_slots if s["type"] == "案例轉折"), "25-40s")
    lines.append("藏鏡人:")
    lines.append(f"  位置1: Hook後 {hook_ts}（懸念型）")
    lines.append("  句子1: \"[編劇填]\"")
    lines.append(f"  位置2: 轉折段後 {turning_ts}（共鳴型）")
    lines.append("  句子2: \"[編劇填]\"")
    lines.append("")

    # ── scenes ──
    lines.append("scenes:")
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

        # 藏鏡人欄位：Hook 和 案例轉折 段，用 seg_type 判斷不寫死 timestamp
        if seg_type in {"Hook", "案例轉折"}:
            lines.append("    藏鏡人: \"[編劇填]\"")

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
        lines.append(f"  evidence_path: \"{ev_path}\"")
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
    lines.append(f"  藏鏡人數量: {actor_min}  # 請維持 >= {actor_min}")
    lines.append("  答案完整不拆集: true")
    lines.append("  CTA類型: \"[編劇填]\"  # e.g. 互動留言型 / 釣魚型 / 個人化諮詢型")
    lines.append("  禁用詞自查: \"[編劇填後改為 PASS]\"")
    lines.append(f"  雙身份比例: {identity}")
    lines.append(f"  派系比例: {school}")
    lines.append("---")

    return "\n".join(lines)


# ════════════════════════════════════════
# 主程式
# ════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="yaml 骨架機 — 產 SOP batch_spec.main_scripts 個空 yaml 骨架")
    parser.add_argument("--topic-plan", required=True, help="topic_distributor.py 產的 JSON 路徑")
    parser.add_argument("--output-dir", required=True, help="產出目標資料夾（會自動建立）")
    parser.add_argument("--tmp",        action="store_true", help="輸出 .tmp yaml（自驗用，不 commit）")
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
