#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_distributor.py — 題目分配機 v1.0
自動分 13 題目方向（按業主流派比例 + 去重已用主題）

用法：
  python topic_distributor.py --owner 阿奇 --batch 第02批_2026-05-25
  python topic_distributor.py --owner 阿奇 --batch 第02批_2026-05-25 --output /path/to/plan.json

輸出：JSON 含 plan list + ratio_validation

建檔：2026-05-22 / 對齊 _腳本生產SOP_v3.0.yaml §1 batch_spec
"""

import sys
import os
import re
import json
import argparse
import yaml
from pathlib import Path
from typing import Optional

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 共用派系解析器（第一刀 2026-06-05）──
try:
    _FP_DIR = Path(__file__).resolve().parent
    import sys as _sys
    if str(_FP_DIR) not in _sys.path:
        _sys.path.insert(0, str(_FP_DIR))
    from _faction_parser import (
        load_l0_faction_names as _load_l0_faction_names,
        parse_faction_mix_from_headings as _parse_faction_mix,
        FactionParseResult as _FactionParseResult,
    )
    _FACTION_PARSER_OK = True
except Exception as _fp_err:
    _FACTION_PARSER_OK = False
    _load_l0_faction_names = None  # type: ignore
    _parse_faction_mix = None      # type: ignore

# ── 共用雙身份解析器（第二刀 2026-06-05）──
try:
    _FP_DIR2 = Path(__file__).resolve().parent
    if str(_FP_DIR2) not in _sys.path:
        _sys.path.insert(0, str(_FP_DIR2))
    from _identity_parser import (
        parse_identity_mix_from_headings as _parse_identity_mix,
        IdentityParseResult as _IdentityParseResult,
    )
    _IDENTITY_PARSER_OK = True
except Exception as _ip_err:
    _IDENTITY_PARSER_OK = False
    _parse_identity_mix = None  # type: ignore

# ── 路徑常數 ──
L2_BASE = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L2_業主層")
SOP_YAML = Path(r"C:\Users\00sta\Documents\Claude\Projects\短影音系統\L0_跨行業公版\_腳本生產SOP_v3.0.yaml")

# 業主資料夾 + 偏好.md 對照表
OWNER_META = {
    "瑞祥": {
        "dir": L2_BASE / "房仲_瑞祥",
        "pref": L2_BASE / "房仲_瑞祥" / "00_業主核心檔" / "source_overlay" / "_瑞祥偏好.md",
    },
    "仲豪": {
        "dir": L2_BASE / "房仲_仲豪",
        "pref": L2_BASE / "房仲_仲豪" / "00_業主核心檔" / "source_overlay" / "_仲豪偏好.md",
    },
    "昀臻": {
        "dir": L2_BASE / "美容_昀臻",
        "pref": L2_BASE / "美容_昀臻" / "00_業主核心檔" / "source_overlay" / "_昀臻偏好.md",
    },
    "叭噗_小C": {
        "dir": L2_BASE / "情侶_叭噗_小C",
        "pref": L2_BASE / "情侶_叭噗_小C" / "00_業主核心檔" / "source_overlay" / "_叭噗_小C偏好.md",
    },
    "阿奇": {
        "dir": L2_BASE / "餐飲_阿奇",
        "pref": L2_BASE / "餐飲_阿奇" / "00_業主核心檔" / "source_overlay" / "_阿奇偏好.md",
    },
    "溫蒂": {
        "dir": L2_BASE / "美容_溫蒂",
        "pref": L2_BASE / "美容_溫蒂" / "00_業主核心檔" / "source_overlay" / "_溫蒂偏好.md",
    },
    "詩婷": {
        "dir": L2_BASE / "房仲_詩婷",
        "pref": L2_BASE / "房仲_詩婷" / "00_業主核心檔" / "source_overlay" / "_詩婷偏好.md",
    },
}


# ════════════════════════════════════════
# 1. 讀業主偏好.md
# ════════════════════════════════════════

def load_pref_text(owner: str) -> Optional[str]:
    meta = OWNER_META.get(owner)
    if not meta:
        return None
    pref_path = meta["pref"]
    if pref_path.exists():
        return pref_path.read_text(encoding="utf-8")
    return None


# ════════════════════════════════════════
# 2. 從偏好.md 解析派系比例
#    支援「§8.X」「第 8 章」兩種 heading
# ════════════════════════════════════════

# 14 派系庫白名單（第一刀 2026-06-05：改從 L0 yaml 動態讀，廢除第三份硬編）
# 若 _faction_parser 可用則從 L0 yaml 載；否則 fallback 硬編（對齊 validate_deploy 做法）
if _FACTION_PARSER_OK:
    VALID_SCHOOLS: frozenset[str] = _load_l0_faction_names()
else:
    VALID_SCHOOLS = frozenset({
        "直球派", "人間觀察派", "嗆辣派", "雙城合作派", "結構分析派",
        "老前輩權威派", "時事追擊派", "爆文公式派", "綜合派", "市場觀察派",
        "故事戲劇派", "自嘲反差派", "拆解派", "家人朋友模擬派",
    })


def parse_school_ratios(pref_text: str) -> dict[str, int]:
    """
    薄 wrapper（第一刀 2026-06-05）：呼叫 _faction_parser.parse_faction_mix_from_headings。
    只回傳 canonical_ratios（L0 14 標準名）。
    unknown / provisional 狀態只印 warning，不靜默 normalize（消除 C-011 放水洞）。
    若 _faction_parser 不可用，退回 empty dict（由 main() 均等 fallback 處理）。
    """
    if not _FACTION_PARSER_OK:
        print("[WARN] _faction_parser 不可用，parse_school_ratios 回空（均等 fallback）")
        return {}

    result: _FactionParseResult = _parse_faction_mix(pref_text, valid_schools=VALID_SCHOOLS)

    # 印 warning（透明，不靜默）
    for w in result.warnings:
        print(f"[WARN] parse_school_ratios: {w}")

    if result.provisional:
        print("[WARN] 偏好.md 標記「建議傾向/尚無批次」，派系比例尚未算盤覆核，回空")
        return {}

    if result.unknown_ratios:
        # Codex P0 修（2026-06-05）：unknown 非空時不可只回 canonical-only。
        # distribute_topics 以 sum(school_ratios) 當分母正規化 → canonical 子集合被塌成
        # 單一派系 100%（仲豪 {直球派:36} → round(13×36/36)=13 支全直球派 = 產錯批次）。
        # fail-loud 拒絕產出、逼走 Phase 2 補 alias 對照表，不靜默產錯。
        raise ValueError(
            f"偏好含未知派系名（非 L0 14 標準名）：{result.unknown_ratios}。"
            f"現有工具無法可靠分題（canonical 子集合會被 distribute 塌成單一派系 100%），"
            f"需 Phase 2 補 alias 對照表後才能分題。本次拒絕產出（fail-loud）。"
        )

    return dict(result.canonical_ratios)


# ════════════════════════════════════════
# 3. 從偏好.md 解析雙身份比例（第 3 章）
# ════════════════════════════════════════

def parse_identity_ratios(pref_text: str) -> dict[str, int]:
    """
    抓偏好.md 雙身份比例（heading-based，第二刀 2026-06-05）
    薄 wrapper 呼叫 _identity_parser.parse_identity_mix_from_headings。
    回傳 {身份類型: 比例} e.g. {"生活 / 觀點 / 個人故事": 50, "餐飲": 30, ...}
    名稱已 normalize（全形/半形括號 strip）。
    """
    if _IDENTITY_PARSER_OK and _parse_identity_mix is not None:
        result = _parse_identity_mix(pref_text)
        return dict(result.ratios)
    # fallback：_identity_parser 不可用時回空，讓呼叫方走 fallback 路徑
    return {}


# ════════════════════════════════════════
# 4. 從偏好.md 抓禁用派系
# ════════════════════════════════════════

def parse_banned_schools(pref_text: str) -> list[str]:
    """
    只抓確定禁用的派系，來自「§8.2 禁用派系」或「§8.3 禁用/慎用派系」小節。
    策略：進入「禁用派系」heading 後，抓表格行中同行有 ❌ 或「禁用」字樣的派系名。
    不在禁用小節裡的 ❌ 符號（例：禁區章節）不納入。
    """
    banned = []
    in_banned_section = False

    for line in pref_text.splitlines():
        # 進入「禁用派系」小節
        if re.search(r"禁用.*派系|禁用\s*/\s*慎用", line):
            in_banned_section = True
            continue
        # 遇到下一個 ## 主節則離開
        if in_banned_section and re.match(r"^#{1,3}\s", line) and "禁用" not in line:
            in_banned_section = False

        if in_banned_section:
            # 格式 A：| 嗆辣派 | ❌ 禁用 | ...（表格行同行有 ❌ 或「禁用」字樣）
            m = re.search(r"\|\s*\*{0,2}([一-龥a-zA-Z（）_\/]+派)\*{0,2}\s*\|", line)
            if m and re.search(r"[❌⛔]|禁用", line):
                banned.append(m.group(1).strip())
            # 格式 B：**禁用**：嗆辣派 / 爆文公式派
            m2 = re.search(r"\*{0,2}禁用\*{0,2}\s*[：:]\s*(.+)", line)
            if m2:
                names = re.findall(r"([一-龥a-zA-Z（）_]+派)", m2.group(1))
                banned.extend(names)

    return list(set(banned))


# ════════════════════════════════════════
# 5. 去重已用主題 — 掃歷史 yaml
# ════════════════════════════════════════

def collect_used_topics(owner: str) -> list[dict]:
    """
    掃業主 01_腳本生產/ 底下所有歷史 yaml
    回傳 [{script_id, title, pattern, 派系}, ...]
    """
    meta = OWNER_META.get(owner)
    if not meta:
        return []
    prod_dir = meta["dir"] / "01_腳本生產"
    if not prod_dir.exists():
        return []

    used = []
    for yaml_file in sorted(prod_dir.rglob("*.yaml")):
        if ".bak" in yaml_file.name or ".tmp" in yaml_file.name:
            continue
        try:
            text = yaml_file.read_text(encoding="utf-8")
            text = re.sub(r"^---\s*\n", "", text, count=1)
            text = re.sub(r"\n---\s*$", "", text)
            data = yaml.safe_load(text)
            if data and isinstance(data, dict):
                used.append({
                    "script_id": data.get("script_id", ""),
                    "title": data.get("title", ""),
                    "pattern": data.get("pattern", ""),
                    "派系": data.get("派系", ""),
                })
        except Exception:
            pass
    return used


# ════════════════════════════════════════
# 6. SOP batch_spec 讀取（B 段 2026-06-05：薄 wrapper 改讀 _sop_config）
# ════════════════════════════════════════

def load_sop_batch_spec() -> dict:
    """薄 wrapper：呼叫 _sop_config.load_l0_batch_spec，回傳完整 batch_spec dict。
    B 段 2026-06-05（Codex must-fix）：補 try/except 恢復 graceful fallback——與
    validate/skeleton 容錯姿態一致；_sop_config 模組 import/load 失敗 → 退舊硬編值不 crash。"""
    try:
        from _sop_config import load_l0_batch_spec
        return load_l0_batch_spec()
    except Exception as e:
        print(f"[WARN] topic_distributor: _sop_config import/load failed ({e}); using hardcoded fallback",
              file=sys.stderr)
        return {"main_scripts": 13, "cta_distribution": {}}


# ════════════════════════════════════════
# 7. 分配 13 題目方向
# ════════════════════════════════════════

def distribute_topics(
    school_ratios: dict[str, int],
    identity_ratios: dict[str, int],
    used_topics: list[dict],
    batch_spec: dict,
    owner: str,
    batch: str,
) -> list[dict]:
    """
    按流派比例分配 13 個題目方向（skeleton）
    每題只含：方向 + 流派 + 雙身份 — 不寫內文
    """
    main_count = batch_spec.get("main_scripts", 13)

    # ── 正規化流派比例（只計非禁用派系）──
    total_pct = sum(school_ratios.values())
    if total_pct == 0:
        print("[WARN] 流派比例加總 = 0，改用均等分配")
        schools = list(school_ratios.keys()) or ["故事戲劇派", "人間觀察派", "直球派"]
        school_ratios = {s: 100 // len(schools) for s in schools}
        total_pct = 100

    # 計算每流派配幾支（按比例四捨五入，最後湊滿 main_count）
    slots: dict[str, int] = {}
    for name, pct in sorted(school_ratios.items(), key=lambda x: -x[1]):
        n = round(main_count * pct / total_pct)
        slots[name] = max(1, n)

    # 調整總數 = main_count
    current_total = sum(slots.values())
    diff = main_count - current_total
    if diff != 0:
        # 從比例最高的流派加減
        top_school = max(slots, key=lambda k: school_ratios.get(k, 0))
        slots[top_school] = max(1, slots[top_school] + diff)

    # ── 正規化雙身份比例 ──
    id_total = sum(identity_ratios.values())
    if id_total == 0 or not identity_ratios:
        # fallback：均等
        identity_ratios = {"觀點分享": 40, "生活日常": 30, "業務": 15, "開箱": 5}
        id_total = 90

    # ── 產 plan list ──
    # 依流派 slot 展開
    plan: list[dict] = []
    seq = 1
    for school, count in slots.items():
        for i in range(count):
            # 計算雙身份（按比例循環）
            id_choice = _pick_identity(identity_ratios, id_total, seq, main_count)
            plan.append({
                "seq": seq,
                "script_id": f"{_owner_code(owner)}_{_batch_code(batch)}_{seq:02d}",
                "direction": f"[編劇填] — {school}方向 {seq}",
                "派系": school,
                "雙身份": id_choice,
                "owner": owner,
                "batch": _batch_code(batch),
                "batch_tag": batch,
            })
            seq += 1

    # ── 附加去重資訊 ──
    used_titles = [u["title"] for u in used_topics if u["title"]]
    used_patterns = [u["pattern"] for u in used_topics if u["pattern"]]

    return plan, {
        "used_title_count": len(used_titles),
        "used_titles_sample": used_titles[:10],
        "used_patterns": list(set(used_patterns))[:10],
    }


def _pick_identity(ratios: dict[str, int], total: int, seq: int, main_count: int) -> str:
    """按比例輪流選雙身份類型"""
    # 建立累積槽
    slots_list = []
    for label, pct in sorted(ratios.items(), key=lambda x: -x[1]):
        n = max(1, round(main_count * pct / total))
        slots_list.extend([label] * n)
    if not slots_list:
        return "觀點分享"
    return slots_list[(seq - 1) % len(slots_list)]


def _owner_code(owner: str) -> str:
    mapping = {
        "瑞祥": "ruixiang",
        "仲豪": "zhonghao",
        "昀臻": "yunzhen",
        "叭噗_小C": "bappu",
        "阿奇": "achi",
        "詩婷": "shihting",   # 2026-06-05 補（對齊 validate_deploy prefix）
        "溫蒂": "wendi",      # 2026-06-05 補
    }
    code = mapping.get(owner)
    if code:
        return code
    # fallback：非 mapping 業主 → 若含非 ASCII（中文）會產出壞 script_id，fail-loud
    fb = owner.lower()[:6]
    if not fb.isascii():
        raise SystemExit(
            f"[topic_distributor] _owner_code 缺業主代號 mapping：{owner!r}（中文 fallback 會產壞 script_id）。"
            f"請補進 _owner_code mapping（對齊 validate_deploy OWNER_MAP prefix）。"
        )
    return fb


def _batch_code(batch: str) -> str:
    """第02批_2026-05-25 → 02"""
    m = re.search(r"第(\d+)批", batch)
    return m.group(1) if m else "01"


# ════════════════════════════════════════
# 8. ratio_validation 對比
# ════════════════════════════════════════

def build_ratio_validation(plan: list[dict], school_ratios: dict, identity_ratios: dict) -> dict:
    total = len(plan)
    actual_school: dict[str, int] = {}
    actual_id: dict[str, int] = {}
    for item in plan:
        s = item["派系"]
        actual_school[s] = actual_school.get(s, 0) + 1
        i = item["雙身份"]
        actual_id[i] = actual_id.get(i, 0) + 1

    school_validation = {}
    for name, target_pct in school_ratios.items():
        actual_pct = round(actual_school.get(name, 0) / total * 100)
        diff = actual_pct - target_pct
        school_validation[name] = {
            "target_pct": target_pct,
            "actual_pct": actual_pct,
            "actual_count": actual_school.get(name, 0),
            "diff": diff,
            "ok": abs(diff) <= 5,  # ±5% 容許（對齊 validate_script_batch.py C-011 TOLERANCE = 5）
        }

    id_validation = {}
    for name, target_pct in identity_ratios.items():
        actual_pct = round(actual_id.get(name, 0) / total * 100) if total else 0
        id_validation[name] = {
            "target_pct": target_pct,
            "actual_pct": actual_pct,
            "actual_count": actual_id.get(name, 0),
        }

    return {
        "total_scripts": total,
        "school_validation": school_validation,
        "identity_validation": id_validation,
    }


# ════════════════════════════════════════
# 主程式
# ════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="題目分配機 — 自動分 13 題目方向")
    parser.add_argument("--owner",  required=True, help="業主名（瑞祥/仲豪/昀臻/叭噗_小C/阿奇）")
    parser.add_argument("--batch",  required=True, help="批次名，e.g. 第02批_2026-05-25")
    parser.add_argument("--output", help="輸出 JSON 路徑（預設同目錄 topic_plan_<owner>_<batch>.json）")
    args = parser.parse_args()

    owner = args.owner
    batch = args.batch

    print(f"\n{'='*60}")
    print(f"  題目分配機 v1.0")
    print(f"  業主：{owner}  /  批次：{batch}")
    print(f"{'='*60}\n")

    # 驗業主名
    if owner not in OWNER_META:
        print(f"[ERROR] 不認識的業主名：{owner}，可選：{list(OWNER_META.keys())}")
        sys.exit(1)

    # 讀偏好.md
    pref_text = load_pref_text(owner)
    if not pref_text:
        print(f"[ERROR] 找不到業主偏好.md：{OWNER_META[owner]['pref']}")
        sys.exit(1)
    print(f"[OK] 讀入偏好.md ({len(pref_text)} chars)")

    # 解析派系比例
    try:
        school_ratios = parse_school_ratios(pref_text)
    except ValueError as e:
        print(f"[ERROR] 派系比例解析失敗：{e}", file=sys.stderr)
        sys.exit(1)
    if not school_ratios:
        print("[WARN] 偏好.md 無法解析派系比例，使用均等分配")
        school_ratios = {"故事戲劇派": 40, "人間觀察派": 30, "直球派": 20, "其他": 10}
    else:
        # 移除禁用派系
        banned = parse_banned_schools(pref_text)
        for b in banned:
            if b in school_ratios:
                del school_ratios[b]
                print(f"[INFO] 移除禁用派系：{b}")

    print(f"[OK] 流派比例（{len(school_ratios)} 派）：{school_ratios}")

    # 解析雙身份比例
    identity_ratios = parse_identity_ratios(pref_text)
    if not identity_ratios:
        print("[WARN] 偏好.md 第 3 章無法解析雙身份比例，使用均等分配")
        identity_ratios = {}
    else:
        print(f"[OK] 雙身份比例（{len(identity_ratios)} 類）：{identity_ratios}")

    # 去重已用主題
    used_topics = collect_used_topics(owner)
    print(f"[OK] 歷史已用主題：{len(used_topics)} 支（title 樣本：{[u['title'] for u in used_topics[:5]]}）")

    # 讀 SOP batch_spec
    batch_spec = load_sop_batch_spec()
    main_count = batch_spec.get("main_scripts", 13)
    print(f"[OK] SOP batch_spec.main_scripts = {main_count}")

    # 分配 13 題目方向
    plan, dedup_info = distribute_topics(
        school_ratios, identity_ratios, used_topics, batch_spec, owner, batch
    )
    ratio_validation = build_ratio_validation(plan, school_ratios, identity_ratios)

    # 組輸出 JSON
    output_data = {
        "meta": {
            "tool": "topic_distributor.py v1.0",
            "owner": owner,
            "batch": batch,
            "main_scripts": main_count,
        },
        "plan": plan,
        "dedup_info": dedup_info,
        "ratio_validation": ratio_validation,
    }

    # 決定輸出路徑
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(f"topic_plan_{owner}_{_batch_code(batch)}.json")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 驗 file size
    fsize = out_path.stat().st_size
    print(f"\n[DONE] 輸出：{out_path}  ({fsize} bytes)")
    print(f"  plan 數量：{len(plan)} 題")
    print(f"\n  ratio_validation（流派）：")
    for name, v in ratio_validation["school_validation"].items():
        ok_mark = "OK" if v["ok"] else "WARN"
        print(f"    [{ok_mark}] {name}: 目標 {v['target_pct']}% → 實際 {v['actual_pct']}% ({v['actual_count']} 支)")
    print(f"\n  已用主題去重：{dedup_info['used_title_count']} 筆歷史 title 已載入")
    print(f"  (去重邏輯：編劇填題目時請參考 dedup_info.used_titles_sample 避免重複)\n")

    print(f"{'='*60}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
