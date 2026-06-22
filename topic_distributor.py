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

# Phase 2 FIX2：lazy proxy（import 不碰 generated.json；dir 已於上方 sibling import 加入 sys.path）
from _lazy_map import LazyMap

# ── owner_projection.generated.json loader（Phase 2 step2）──
def _load_owner_projection() -> dict:
    """
    讀 sibling owner_projection.generated.json，fail-loud（不存在/壞 JSON/缺欄位 → SystemExit）。
    回傳 owners dict（{name: rec}）。
    """
    _proj_path = Path(__file__).resolve().parent / "owner_projection.generated.json"
    if not _proj_path.exists():
        raise SystemExit(
            f"[topic_distributor] owner_projection.generated.json 不存在：{_proj_path}\n"
            f"請先跑 gen_owner_projection_cache.py 產生此檔。"
        )
    try:
        with open(_proj_path, encoding="utf-8") as _f:
            _proj = json.load(_f)
    except Exception as _e:
        raise SystemExit(
            f"[topic_distributor] owner_projection.generated.json 解析失敗：{_e}"
        )
    _owners = _proj.get("owners")
    if not isinstance(_owners, dict) or not _owners:
        raise SystemExit(
            f"[topic_distributor] owner_projection.generated.json 缺 'owners' 欄位或為空。"
        )
    # 必要欄位驗證（逐 owner）
    _required = {"owner_dir", "l2_path", "owner_code"}
    for _name, _rec in _owners.items():
        _missing = _required - set(_rec.keys())
        if _missing:
            raise SystemExit(
                f"[topic_distributor] owner_projection.generated.json owner={_name!r} 缺欄位：{_missing}"
            )
    return _owners

# Phase 2 FIX2：lazy——import 不載 JSON；首次存取才 materialize（proxy.items() 觸發載入）
_OWNER_PROJECTION = LazyMap(_load_owner_projection)

# 業主資料夾 + 偏好.md 對照表（lazy；builder 於首次存取才迭代 _OWNER_PROJECTION）
OWNER_META = LazyMap(lambda: {
    _name: {
        "dir": L2_BASE / _rec["owner_dir"],
        "pref": Path(_rec["l2_path"]),
    }
    for _name, _rec in _OWNER_PROJECTION.items()
})


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
    # mapping 由 owner_projection.generated.json 產（Phase 2 step2）
    mapping = {_name: _rec["owner_code"] for _name, _rec in _OWNER_PROJECTION.items()}
    code = mapping.get(owner)
    if code:
        return code
    # fallback：非 mapping 業主 → 若含非 ASCII（中文）會產出壞 script_id，fail-loud
    fb = owner.lower()[:6]
    if not fb.isascii():
        raise SystemExit(
            f"[topic_distributor] _owner_code 缺業主代號 mapping：{owner!r}（中文 fallback 會產壞 script_id）。"
            f"請補進 owner_projection.generated.json 並重跑 gen_owner_projection_cache.py。"
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
    parser.add_argument(
        "--batch-dir",
        help="批次目錄路徑（WP-B：讀 _batch_flags.yml topic_intel_closure policy；缺省=off）",
        default=None,
    )
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

    # WP-B Step 5：assign_topic_sources（flag-gated，--batch-dir 缺省=off）
    # 零足跡鐵律：off 時不 import、不讀池、不新增 key、stdout 無 [WP-B] 行
    assign_report: Optional[dict] = None
    if args.batch_dir is not None:
        # lazy import（off 時完全不 import）
        from topic_intel_policy import load_topic_intel_policy  # type: ignore[import]
        policy = load_topic_intel_policy(args.batch_dir)

        if policy.get("enabled"):
            # 找 owner projection path（走 config）
            try:
                import json as _json_m
                _ti_cfg_path = Path(r"C:\Users\00sta\claude-state\topic_intel_paths.json")
                _ti_cfg = _json_m.loads(_ti_cfg_path.read_text(encoding="utf-8")) if _ti_cfg_path.exists() else {}
                _proj_dir = _ti_cfg.get("topic_intel_projection_dir", "")
                owner_code_val = _owner_code(owner)
                _proj_path = str(Path(_proj_dir) / "by_owner" / owner_code_val / "active.json") if _proj_dir else None
            except Exception as _pe:
                print(f"[WARN] WP-B: 讀 projection path 失敗: {_pe}", file=sys.stderr)
                _proj_path = None

            plan, assign_report = assign_topic_sources(
                plan=plan,
                dedup_info=dedup_info,
                policy=policy,
                projection_path=_proj_path,
            )
            print(f"\n[WP-B] assign: {assign_report.get('detail', '')}")

            # ── WP-C.2：offered 事件帳本（flag-gated，預設 OFF → 零足跡）──────────
            # OFF（env TOPIC_INTEL_OFFERED_LEDGER != "1"）時：不 import offered 模組、不寫、
            # assign_report 不新增 offered_ledger key、stdout 無 [WP-C.2] 行 → 輸出 byte-identical。
            # 只在 enabled + 無 error + mode in {shadow,enforce} 才記（失敗的派工不記 offered）。
            if os.environ.get("TOPIC_INTEL_OFFERED_LEDGER", "").strip() == "1" \
                    and assign_report and assign_report.get("enabled") \
                    and assign_report.get("error") is None \
                    and assign_report.get("mode") in ("shadow", "enforce"):
                try:
                    from topic_intel_offered import emit_offered_events  # type: ignore[import]
                    _offered_report = emit_offered_events(
                        plan=plan,
                        assign_report=assign_report,
                        owner_code=owner_code_val,
                        owner_name=owner,
                    )
                    assign_report["offered_ledger"] = _offered_report
                    print(f"[WP-C.2] offered: {_offered_report.get('detail', '')}")
                except Exception as _oe:
                    print(f"[WARN] WP-C.2 offered emit 失敗（fail-soft，不擋）：{_oe}", file=sys.stderr)
        elif policy.get("mode") == "invalid":
            # Fix P0-2：invalid policy（有寫 topic_intel_closure 但設定不合法）→ assign error，不綁
            # 只有「無 _batch_flags.yml」或明確 mode=off 才 disabled 零足跡；invalid ≠ off
            _invalid_detail = policy.get("detail", "topic_intel_closure 設定不合法")
            assign_report = {
                "mode": "invalid",
                "enabled": False,
                "selected_count": 0,
                "assigned_slots": [],
                "error": f"topic_intel_closure 設定不合法（invalid），fail-closed 不綁：{_invalid_detail}",
                "warnings": [],
                "detail": f"assign 拒絕：policy invalid",
            }
            print(f"\n[WP-B] assign 拒絕（invalid policy）：{_invalid_detail}", file=sys.stderr)
        # policy disabled / off → assign_report 維持 None，stdout 零足跡

    # 組輸出 JSON（off 時無 assign_report key，保持 byte-identical）
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
    if assign_report is not None:
        output_data["assign_report"] = assign_report

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


# ════════════════════════════════════════
# WP-B Step 5：assign_topic_sources（flag-gated）
# ════════════════════════════════════════

def assign_topic_sources(
    plan: list[dict],
    dedup_info: dict,
    policy: Optional[dict],
    projection_path: Optional[str],
) -> tuple[list[dict], dict]:
    """
    WP-B：按 policy 把選題情報池候選綁進 plan 前 N 個 slot。

    flag-off / policy 未提供 / mode=off → 完全不 import adapter/projection、
    不讀池、回原 plan 零改動、assign_report 標 disabled。
    （lazy import 設計：import 寫在函式內、不在模組頂層）

    參數：
      plan            : distribute_topics() 回傳的 plan list
      dedup_info      : distribute_topics() 回傳的 dedup_info dict
      policy          : load_topic_intel_policy() 回傳的 policy dict；
                        None 視為 disabled
      projection_path : 業主 active.json 的絕對路徑字串；
                        None 且 policy enabled 時 → assign_report error

    回傳：
      (plan, assign_report)
      plan：加了 source_topic_intel 欄位（off 時不動）
      assign_report：dict{mode/enabled/selected_count/assigned_slots/error/warnings}

    規格 §9（r3）：
      - off/disabled → 完全不 import、回原 plan
      - on：讀 projection；按 §9.1 排序（projection 已排序，直接用）
      - in-batch reservation（§9.7 set 去重）
      - 不足 min + enforce → 不綁 + error
      - batch_id 單一來源 = plan[0]["batch"]；不一致 → error
    """
    # --- invalid policy 路徑（Fix P0-2）：有寫 topic_intel_closure 但設定不合法 ---
    # invalid ≠ off；invalid 要回 error（不綁）讓外層看到失敗狀態
    if policy is not None and policy.get("mode") == "invalid":
        _inv_detail = policy.get("detail", "topic_intel_closure 設定不合法")
        return plan, {
            "mode": "invalid",
            "enabled": False,
            "selected_count": 0,
            "assigned_slots": [],
            "error": f"topic_intel_closure 設定不合法（invalid），fail-closed 不綁：{_inv_detail}",
            "warnings": [],
            "detail": f"assign 拒絕：policy invalid",
        }

    # --- off 路徑（零足跡）---
    if policy is None or not policy.get("enabled", False):
        return plan, {
            "mode": "off",
            "enabled": False,
            "selected_count": 0,
            "assigned_slots": [],
            "error": None,
            "warnings": [],
            "detail": "WP-B assign disabled（policy off/None）",
        }

    # --- on 路徑（lazy import）---
    import json as _json  # noqa: PLC0415（lazy import）
    from pathlib import Path as _Path  # noqa: PLC0415

    mode = policy.get("mode", "off")
    min_slots: int = policy.get("min_slots") or 2
    max_slots: int = policy.get("max_slots") or 4

    warnings: list[str] = []
    assign_report_base = {
        "mode": mode,
        "enabled": True,
        "min_slots": min_slots,
        "max_slots": max_slots,
    }

    # batch_id 一致性（§9 r3 盲點1）
    batch_id: Optional[str] = None
    if plan:
        batch_id = plan[0].get("batch")
        inconsistent = [
            i for i, item in enumerate(plan)
            if item.get("batch") != batch_id
        ]
        if inconsistent:
            msg = (
                f"plan 內 batch 欄位不一致（plan[0]['batch']={batch_id!r}，"
                f"不一致 slot index: {inconsistent}）"
            )
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": msg,
                "warnings": warnings,
                "detail": f"assign error: {msg}",
            }

    # 讀 projection
    if not projection_path:
        msg = "projection_path 未提供，無法讀選題情報池 projection"
        return plan, {
            **assign_report_base,
            "selected_count": 0,
            "assigned_slots": [],
            "error": msg,
            "warnings": warnings,
            "detail": f"assign error: {msg}",
        }

    proj_file = _Path(projection_path)
    if not proj_file.exists():
        msg = f"projection 檔不存在：{projection_path}"
        return plan, {
            **assign_report_base,
            "selected_count": 0,
            "assigned_slots": [],
            "error": msg,
            "warnings": warnings,
            "detail": f"assign error: {msg}",
        }

    try:
        proj_data = _json.loads(proj_file.read_text(encoding="utf-8"))
    except Exception as e:
        msg = f"projection 讀取失敗：{e}"
        return plan, {
            **assign_report_base,
            "selected_count": 0,
            "assigned_slots": [],
            "error": msg,
            "warnings": warnings,
            "detail": f"assign error: {msg}",
        }

    # ── Fix 1a：新鮮度驗（expires_at TTL）──────────────────────────────────────
    # assign 只驗 expires_at；池變動新鮮度由「出批前重生 projection」保證。
    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415
    _now_utc = _dt.now(tz=_tz.utc)

    proj_expires_at = proj_data.get("expires_at", "")
    # Fix D【P1】enforce 模式下，expires_at 缺失/空/parse 失敗 → error + 不綁；shadow → WARN
    _expires_at_ok = False
    _expires_at_err: str = ""
    if not proj_expires_at:
        _expires_at_err = "projection expires_at 缺失或空白，無法驗新鮮度"
    else:
        try:
            _exp = _dt.fromisoformat(proj_expires_at.replace("Z", "+00:00"))
            if _now_utc > _exp:
                _expires_at_err = (
                    f"projection expires_at={proj_expires_at} 已過期（stale），"
                    f"請先重生 projection（python gen_topic_intel_projection.py）"
                )
            else:
                _expires_at_ok = True
        except Exception as _exp_err:
            _expires_at_err = (
                f"expires_at 解析失敗（{proj_expires_at!r}）: {_exp_err}"
            )

    if not _expires_at_ok:
        if mode == "enforce":
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": _expires_at_err,
                "warnings": warnings,
                "detail": f"assign error（enforce expires_at）: {_expires_at_err}",
            }
        else:
            warnings.append(f"[WARN] {_expires_at_err}，shadow 繼續跑")

    # ── Fix 1b：跨批去重（is_recently_used）─────────────────────────────────────
    # lazy import reconcile_topic_intel_usage.is_recently_used
    # usage index 不存在/空 → fail-soft 不跳過（首批正常）
    _owner_code_for_dedup: str = ""
    try:
        # 從 projection metadata 取 owner_code（避免主動讀 config）
        _owner_code_for_dedup = str(proj_data.get("owner_code", "") or "")
    except Exception:
        pass

    # Fix E【P1】is_recently_used 三態：ok / used / error（index 存在但讀失敗 → enforce 擋）
    # 回傳 (is_used: bool, error_msg: str | None)
    def _is_recently_used_tristate(tid: str) -> tuple:
        """
        三態查詢（直接呼叫 is_recently_used + load_topic_usage_index，支援 monkeypatch）：
          (True, None)  → 近期已用
          (False, None) → 確認未用 / index 不存在（首批）
          (False, str)  → index 存在但讀取/解析失敗（error_msg 非空）
        """
        if not _owner_code_for_dedup:
            return (False, None)
        try:
            from reconcile_topic_intel_usage import (  # type: ignore[import]
                load_topic_usage_index as _load_idx,
                is_recently_used as _iru,
            )
            # 先嘗試讀 index（可被 monkeypatch 攔）
            try:
                _by_owner, _ = _load_idx()
            except Exception as _load_err:
                # index 讀失敗 → error 三態
                return (False, f"index 讀取失敗：{_load_err}")

            # index 不含此 owner → 首批（WARN 放行，不是 error）
            if _owner_code_for_dedup not in _by_owner:
                return (False, None)

            # owner 有記錄 → 呼叫完整查詢
            _result = _iru(tid, _owner_code_for_dedup)
            return (_result, None)
        except Exception as _e:
            # reconcile 模組 import 失敗 → fail-soft 放行（未部署場景）
            return (False, None)

    # 候選（projection 已按 §9.1 排序）
    candidates: list[dict] = proj_data.get("candidates", [])

    # Fix E：過濾使用三態查詢；index 存在但讀失敗 → enforce 擋
    filtered_candidates: list[dict] = []
    skipped_recently_used: list[str] = []
    _dedup_index_error: str = ""
    for _cand in candidates:
        _tid = _cand.get("topic_id", "")
        _used, _err = _is_recently_used_tristate(_tid)
        if _err and not _dedup_index_error:
            _dedup_index_error = _err  # 記第一個錯誤
        if _used:
            skipped_recently_used.append(_tid)
            continue
        filtered_candidates.append(_cand)

    # index 讀失敗處理（Fix E）
    if _dedup_index_error:
        _err_msg = f"跨批去重 index 讀取失敗（{_dedup_index_error}）"
        if mode == "enforce":
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": _err_msg,
                "warnings": warnings,
                "detail": f"assign error（enforce dedup index error）: {_err_msg}",
            }
        else:
            warnings.append(f"[WARN] {_err_msg}，shadow 繼續跑")

    if skipped_recently_used:
        warnings.append(
            f"跨批去重：跳過 {len(skipped_recently_used)} 支近期已用候選（owner={_owner_code_for_dedup}）"
        )

    # Fix P2：usage_index_state 三值（shadow/enforce 都記，供部署審查分辨「首批空」vs「路徑配錯」）
    if _dedup_index_error:
        _usage_index_state = "error"
    elif not _owner_code_for_dedup:
        _usage_index_state = "missing"
    else:
        _usage_index_state = "ok"
    assign_report_base["usage_index_state"] = _usage_index_state

    # P1-b round 5（御史 M2）跨業主 7 天冷卻 — flag gate TOPIC_INTEL_CROSS_OWNER_COOLDOWN
    # 預設關（免每 build 打 reconcile API）；開時 shadow WARN，S3 enforce 才擋
    _cross_owner_cooldown_enabled = os.environ.get('TOPIC_INTEL_CROSS_OWNER_COOLDOWN', '').strip() == '1'
    _cross_owner_warned: list[str] = []
    if _cross_owner_cooldown_enabled:
        try:
            from reconcile_topic_intel_usage import is_recently_used_by_other_owner as _iru_cross
            _current_industry = proj_data.get("industry_id") if isinstance(proj_data, dict) else None
            for _cand in filtered_candidates:
                _tid = _cand.get("topic_id", "")
                if not _tid:
                    continue
                try:
                    _cross_used = _iru_cross(
                        topic_id=_tid,
                        current_owner=_owner_code_for_dedup or "",
                        current_industry=_current_industry,
                        max_days=7,
                        same_industry_only=True,
                    )
                    if _cross_used:
                        _cross_owner_warned.append(_tid)
                except Exception:
                    pass  # fail-soft 不擋
        except ImportError:
            pass  # reconcile 未部署 → skip（非 blocker）

        if _cross_owner_warned:
            warnings.append(
                f"[WARN/industry-native] 跨業主 7 天冷卻：{len(_cross_owner_warned)} 支候選近 7 天被同行業其他業主採用過"
                f"（shadow 觀測、S3 enforce 才擋）: {_cross_owner_warned[:5]}"
            )

    qualified_count = len(filtered_candidates)

    # 計算 selected_count
    if qualified_count < min_slots:
        selected_count = 0
    else:
        selected_count = min(max_slots, qualified_count)

    # enforce 不足 min → 不綁 + error
    if selected_count == 0:
        msg = (
            f"合格候選 {qualified_count} 支 < min_slots={min_slots}，"
            f"enforce 不綁（需補充選題情報池 pending 料）"
        )
        if mode == "shadow":
            # shadow 不足 min → 綁 qualified_count 個觀察（規格 §9 r3）
            selected_count = qualified_count
            warnings.append(f"shadow: 合格候選 {qualified_count} < min_slots={min_slots}，綁 {qualified_count} 個觀察")
        else:
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "error": msg,
                "warnings": warnings,
                "detail": f"assign error（enforce）: {msg}",
            }

    # in-batch reservation（§9.7）+ 跨批去重已在 filtered_candidates 完成
    reserved_topic_ids: set[str] = set()
    selected: list[dict] = []
    for candidate in filtered_candidates:
        if len(selected) >= selected_count:
            break
        tid = candidate.get("topic_id", "")
        if tid in reserved_topic_ids:
            continue
        selected.append(candidate)
        reserved_topic_ids.add(tid)

    # 綁進 plan 前 N 個 slot（§9 r3）
    assigned_slots: list[int] = []
    plan_copy = [dict(item) for item in plan]  # 不 mutate 原 plan

    for i, candidate in enumerate(selected):
        if i >= len(plan_copy):
            warnings.append(f"plan 長度 {len(plan_copy)} < selected_count {len(selected)}，截斷")
            break
        # Fix G：evidence_path 從 projection candidate 的 evidence_path 欄取 canonical path
        # gen_topic_intel_projection 在 qualified.append(proj) 前已填入 path.resolve()
        _ev_path_raw = candidate.get("evidence_path")  # None = 欄不存在（舊格式/fixture）
        _ev_path = str(_ev_path_raw or "").strip()
        # Fix P1（縱深）：欄存在但空字串 → enforce 跳過不綁；shadow WARN 仍綁
        # 欄不存在（None）= 舊格式候選，不觸發此檢查（沿用空路徑繼續綁）
        # 生產 projection 必填 evidence_path（gen_topic_intel_projection 保證填入 resolve() 值）
        if _ev_path_raw is not None and not _ev_path:
            _tid_for_warn = candidate.get("topic_id", "?")
            if mode == "enforce":
                warnings.append(
                    f"[WARN] 候選 topic_id={_tid_for_warn!r} evidence_path 空，enforce 跳過不綁"
                )
                continue  # 不綁這個候選，繼續下一個
            else:
                warnings.append(
                    f"[WARN] 候選 topic_id={_tid_for_warn!r} evidence_path 空，shadow 綁但標空路徑"
                )
        plan_copy[i]["source_topic_intel"] = {
            "topic_id": candidate.get("topic_id", ""),
            "source_kind": "cyborg_yaml",
            "evidence_path": _ev_path,       # Fix G+Fix5：assign 端必填 canonical path
            "evidence_sha256": candidate.get("source_sha256", ""),
            "adopted_topic_statement": "",   # 編劇填
            "assigned_by": "topic_distributor",
            "assignment_mode": mode,
        }
        assigned_slots.append(i)

    # Fix P1 縱深：assign loop 後若 enforce 且實際綁入數 < min_slots（evidence_path 空等情形跳過）→ error
    if mode == "enforce" and len(assigned_slots) < min_slots:
        _post_assign_err = (
            f"實際綁入 {len(assigned_slots)} 個 < min_slots={min_slots}，"
            f"enforce 不足（候選可能被 evidence_path 空等過濾跳過）"
        )
        return plan_copy, {
            **assign_report_base,
            "selected_count": len(selected),
            "assigned_slots": assigned_slots,
            "qualified_count": qualified_count,
            "batch_id": batch_id,
            "error": _post_assign_err,
            "warnings": warnings,
            "detail": f"assign error（post-loop enforce）: {_post_assign_err}",
        }

    return plan_copy, {
        **assign_report_base,
        "selected_count": len(selected),
        "assigned_slots": assigned_slots,
        "qualified_count": qualified_count,
        "batch_id": batch_id,
        "error": None,
        "warnings": warnings,
        "detail": (
            f"assign OK: mode={mode}, selected={len(selected)}/{qualified_count}, "
            f"slots={assigned_slots}"
        ),
    }


if __name__ == "__main__":
    main()
