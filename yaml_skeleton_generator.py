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

# ════════════════════════════════════════
# 6 段時間軸 — IMMUTABLE（SOP §2 固定，禁改）
# ════════════════════════════════════════
TIME_SLOTS = [
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

# 業主台詞欄位名對照（不同業主 yaml 用不同 key）
OWNER_DIALOGUE_KEY = {
    "瑞祥":     "台詞_瑞祥",
    "仲豪":     "台詞_仲豪",
    "昀臻":     "台詞_昀臻",
    "叭噗_小C": "台詞_叭噗",
    "阿奇":     "台詞_阿奇",
    "溫蒂":     "台詞_溫蒂",
}

# 業主主推平台
OWNER_PLATFORM = {
    "瑞祥":     "FB Reels",
    "仲豪":     "FB Reels",
    "昀臻":     "IG Reels",
    "叭噗_小C": "IG Reels",
    "阿奇":     "FB Reels",
    "溫蒂":     "IG Reels",
}


# ════════════════════════════════════════
# 產單一 yaml 骨架文字
# ════════════════════════════════════════

def build_yaml_skeleton(item: dict) -> str:
    """
    item: topic plan 裡一條記錄
    回傳完整 yaml 文字（字串，含 --- frontmatter markers）
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

    # ── Frontmatter ──
    lines = ["---"]
    lines.append(f"script_id: {script_id}")
    lines.append(f"owner: {owner}")
    lines.append(f"batch: \"{batch}\"")
    lines.append(f"batch_tag: {batch_tag}")
    lines.append(f"title: [編劇填]  # 15 字內金句")
    lines.append(f"template: {school}方向")
    lines.append(f"pattern: [編劇填]  # e.g. 創業故事型 / 觀點分享型")
    lines.append(f"雙身份分類: {identity}")
    lines.append(f"dominant_viewer_takeaway: [編劇填]  # e.g. 共鳴認同 / 實用學習")
    lines.append(f"duration: 60s")
    lines.append(f"main_platform: {platform}")
    lines.append(f"suggested_po_time: [編劇填]  # e.g. 週三晚 8PM")
    lines.append(f"派系: {school}")
    lines.append(f"")
    lines.append(f"# 題目方向（topic_distributor.py 分配，編劇填內文後請刪此行）")
    lines.append(f"# direction: {direction}")
    lines.append(f"")

    # ── 藏鏡人 block ──
    lines.append("藏鏡人:")
    lines.append("  位置1: Hook後 0-3s（懸念型）")
    lines.append("  句子1: \"[編劇填]\"")
    lines.append("  位置2: 轉折段後 25-40s（共鳴型）")
    lines.append("  句子2: \"[編劇填]\"")
    lines.append("")

    # ── 6 段 scenes ──
    lines.append("scenes:")
    for slot in TIME_SLOTS:
        ts = slot["timestamp"]
        seg_type = slot["type"]
        task = slot["task"]
        note = slot["note"]

        lines.append(f"  - timestamp: \"{ts}\"")
        lines.append(f"    type: {seg_type}")
        lines.append(f"    # 任務：{task}")
        lines.append(f"    # 注意：{note}")
        lines.append(f"    {dialogue_key}: \"[編劇填]\"")

        # Hook 和轉折段附藏鏡人欄位
        if ts == "0-3s":
            lines.append("    藏鏡人: \"[編劇填]\"")
        elif ts == "25-40s":
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

    # ── schema_check ──
    lines.append("schema_check:")
    lines.append("  禁虛構: true")
    lines.append("  藏鏡人數量: 2  # 請維持 >= 2")
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
    parser = argparse.ArgumentParser(description="yaml 骨架機 — 產 13 個空 yaml 骨架")
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
