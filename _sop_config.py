#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_sop_config.py — L0 SOP accessor（B 段 2026-06-05）
讀 _腳本生產SOP_v3.0.yaml 的 batch_spec + script_schema.time_slots。
對齊 _faction_parser.load_l0_faction_names 模式：讀 yaml + 合理性驗 + hardcoded fallback + WARN 到 stderr。

API：
  load_l0_batch_spec(sop_yaml=None) -> dict
  load_l0_time_slots(sop_yaml=None) -> tuple[dict, ...]
  normalize_timestamp(value) -> str
  clear_sop_config_cache()
"""

import sys
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── L0 SOP 路徑（預設）──
# repo-relative：script-library 上 3 層 = 短影音系統 根（Codex should-fix：避免綁帳號/搬 workspace/CI 失效）
_DEFAULT_SOP_YAML = Path(__file__).resolve().parents[3] / "L0_跨行業公版" / "_腳本生產SOP_v3.0.yaml"

# ════════════════════════════════════════
# Fallback 常數（= 現行 L0 實值）
# ════════════════════════════════════════

_FALLBACK_BATCH_SPEC: dict = {
    "main_scripts":          13,
    "fishing_script":         0,   # 釣魚部下架（澤君 2026-06-05）：fallback 同步改 0，與 L0 一致（沉默坑防護）
    "threads_posts":          7,
    "visual_aid_scripts":     0,
    "duration_seconds":      60,
    "title_max_chars":       15,
    "traffic_codes_min":      3,
    "actor_interaction_min":  2,
    "school_diversity_min":   3,
    "theme_diversity_min":    4,
    "cta_distribution":      {},
}

_FALLBACK_TIME_SLOTS: tuple = (
    {"raw_slot": "0-3秒",   "timestamp": "0-3s",   "start":  0, "end":  3, "task": "Hook 開場金句（決定觀眾留不留下）",    "note": "必須是金句，不能是問候語"},
    {"raw_slot": "3-12秒",  "timestamp": "3-12s",  "start":  3, "end": 12, "task": "破題 + 拋出痛點 / 疑問",              "note": "讓觀眾有理由繼續看"},
    {"raw_slot": "12-25秒", "timestamp": "12-25s", "start": 12, "end": 25, "task": "核心論述 + 數據佐證",                  "note": "必給完整答案，禁止全留到下集/PDF"},
    {"raw_slot": "25-40秒", "timestamp": "25-40s", "start": 25, "end": 40, "task": "案例 / 故事 / 轉折",                   "note": "主體段必給觀眾可立即實踐的內容"},
    {"raw_slot": "40-52秒", "timestamp": "40-52s", "start": 40, "end": 52, "task": "收束觀點、強化記憶點",                 "note": "金句要能獨立截圖分享"},
    {"raw_slot": "52-60秒", "timestamp": "52-60s", "start": 52, "end": 60, "task": "CTA 導流",                            "note": "固定話術：不用怕，問問不用錢"},
)


# ════════════════════════════════════════
# normalize_timestamp
# ════════════════════════════════════════

def normalize_timestamp(value: str) -> str:
    """把 '0-3秒' / '0–3s' / '0-3 秒' 等正規化為 '0-3s' 標準格式。"""
    if not value:
        return value
    # 替換全形破折號 / en-dash → ASCII hyphen
    value = value.replace("–", "-").replace("—", "-")
    # 移除空格
    value = value.replace(" ", "")
    # 移除中文「秒」→ 加英文 s（如果末尾是數字）
    value = re.sub(r"秒$", "s", value)
    # 末尾無單位的純數字範圍 → 加 s
    if re.match(r"^\d+-\d+$", value):
        value = value + "s"
    return value


# ════════════════════════════════════════
# _parse_time_range：解析 "0-3秒" → (0, 3)
# ════════════════════════════════════════

def _parse_time_range(raw_slot: str) -> tuple[int, int]:
    """解析 slot 字串為 (start, end) int pair，失敗 raise ValueError。"""
    clean = normalize_timestamp(raw_slot)  # → "0-3s"
    m = re.match(r"^(\d+)-(\d+)s$", clean)
    if not m:
        raise ValueError(f"無法解析 slot：{raw_slot!r} (normalized: {clean!r})")
    return int(m.group(1)), int(m.group(2))


# ════════════════════════════════════════
# load_l0_batch_spec
# ════════════════════════════════════════

@lru_cache(maxsize=4)
def load_l0_batch_spec(sop_yaml: Optional[str] = None) -> dict:
    """
    讀 L0 SOP batch_spec，回補滿 fallback 的 dict。
    缺 key / 壞 int → 單 key fallback + WARN。
    檔讀不到 → 全 fallback + WARN。
    """
    import yaml as _yaml

    path = Path(sop_yaml) if sop_yaml else _DEFAULT_SOP_YAML

    # ── 讀檔 ──
    raw_spec: dict = {}
    try:
        data = _yaml.safe_load(path.read_text(encoding="utf-8"))
        raw_spec = data.get("batch_spec", {}) if isinstance(data, dict) else {}
    except Exception as exc:
        print(
            f"[WARN] _sop_config: failed to read L0 SOP at {path}: {exc}; "
            f"using hardcoded fallback for batch_spec.",
            file=sys.stderr,
        )
        return dict(_FALLBACK_BATCH_SPEC)

    # ── batch_spec 必須是 mapping（Codex must-fix：malformed shape list/str → 全 fallback + WARN，不可 crash）──
    if not isinstance(raw_spec, dict):
        print(
            f"[WARN] _sop_config: batch_spec is not a mapping ({type(raw_spec).__name__}); "
            f"using hardcoded fallback for batch_spec.",
            file=sys.stderr,
        )
        return dict(_FALLBACK_BATCH_SPEC)

    # ── 每個 key 補 fallback ──
    result: dict = {}
    int_keys = {
        "main_scripts", "fishing_script", "threads_posts", "visual_aid_scripts",
        "duration_seconds", "title_max_chars", "traffic_codes_min",
        "actor_interaction_min", "school_diversity_min", "theme_diversity_min",
    }
    for key, fallback_val in _FALLBACK_BATCH_SPEC.items():
        raw_val = raw_spec.get(key)
        if raw_val is None:
            # key 整個缺失
            print(
                f"[WARN] _sop_config: batch_spec.{key} missing/invalid ({raw_val!r}); "
                f"using fallback value {fallback_val!r}.",
                file=sys.stderr,
            )
            result[key] = fallback_val
        elif key in int_keys:
            try:
                result[key] = int(raw_val)
            except (TypeError, ValueError):
                print(
                    f"[WARN] _sop_config: batch_spec.{key} missing/invalid ({raw_val!r}); "
                    f"using fallback value {fallback_val!r}.",
                    file=sys.stderr,
                )
                result[key] = fallback_val
        else:
            result[key] = raw_val

    return result


# ════════════════════════════════════════
# load_l0_time_slots
# ════════════════════════════════════════

@lru_cache(maxsize=4)
def load_l0_time_slots(sop_yaml: Optional[str] = None) -> tuple:
    """
    讀 L0 SOP script_schema.time_slots。
    Sanity check（5 項）：
      ① 非空 list
      ② slot 可 parse start/end
      ③ start < end
      ④ 嚴格遞增不重疊
      ⑤ 末段 end == duration_seconds
    任一壞 → 全 fallback + WARN。
    """
    import yaml as _yaml

    path = Path(sop_yaml) if sop_yaml else _DEFAULT_SOP_YAML

    def _fallback(reason: str) -> tuple:
        print(
            f"[WARN] _sop_config: invalid script_schema.time_slots: {reason}; "
            f"using hardcoded fallback for time_slots.",
            file=sys.stderr,
        )
        return _FALLBACK_TIME_SLOTS

    # ── 讀檔 ──
    try:
        data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(
            f"[WARN] _sop_config: failed to read L0 SOP at {path}: {exc}; "
            f"using hardcoded fallback for time_slots.",
            file=sys.stderr,
        )
        return _FALLBACK_TIME_SLOTS

    # ── script_schema 必須是 mapping（Codex round2：malformed shape → 明確 fallback + 精準訊息，
    #    與 batch_spec guard 對稱，不靠 AttributeError 被 catch）──
    script_schema = data.get("script_schema", {}) if isinstance(data, dict) else {}
    if not isinstance(script_schema, dict):
        return _fallback(f"script_schema 非 mapping（{type(script_schema).__name__}）")
    raw_slots = script_schema.get("time_slots", [])

    # ── Sanity ① 非空 list ──
    if not raw_slots or not isinstance(raw_slots, list):
        return _fallback("time_slots 為空或非 list")

    # ── parse + sanity ② ③ ④ ──
    parsed: list[dict] = []
    prev_end = -1
    for i, slot in enumerate(raw_slots):
        # Codex must-fix：slot item 非 mapping（list/str）→ 全 fallback + WARN，不可 crash
        if not isinstance(slot, dict):
            return _fallback(f"slot[{i}] 非 mapping（{type(slot).__name__}）")
        raw_s = slot.get("slot", "")
        try:
            start, end = _parse_time_range(raw_s)
        except ValueError as ve:
            return _fallback(f"slot[{i}] 無法 parse：{ve}")
        # ③ start < end
        if start >= end:
            return _fallback(f"slot[{i}] start({start}) >= end({end})")
        # ④ 連續覆蓋（Codex should-fix）：首段 start==0、其後 start==prev_end（不重疊、不留 gap、不倒序）
        if i == 0:
            if start != 0:
                return _fallback(f"首段 start({start}) != 0")
        elif start != prev_end:
            return _fallback(f"slot[{i}] start({start}) != prev_end({prev_end})，slots 重疊/倒序/有 gap")
        prev_end = end
        ts = normalize_timestamp(raw_s)
        parsed.append({
            "raw_slot":  raw_s,
            "timestamp": ts,
            "start":     start,
            "end":       end,
            "task":      slot.get("task", ""),
            "note":      slot.get("note", ""),
        })

    # ── Sanity ⑤ 末段 end == duration_seconds ──
    duration = load_l0_batch_spec(sop_yaml).get("duration_seconds", 60)
    if parsed and parsed[-1]["end"] != duration:
        return _fallback(
            f"末段 end({parsed[-1]['end']}) != duration_seconds({duration})"
        )

    return tuple(parsed)


# ════════════════════════════════════════
# clear_sop_config_cache
# ════════════════════════════════════════

def clear_sop_config_cache():
    """清兩個 lru_cache（測試改 temp SOP 後呼叫）。"""
    load_l0_batch_spec.cache_clear()
    load_l0_time_slots.cache_clear()


# ════════════════════════════════════════
# __main__ — fixtures（B 段規格 §7）
# ════════════════════════════════════════

if __name__ == "__main__":
    import tempfile, os
    import yaml as _yaml

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    _pass = 0
    _fail = 0

    def _chk(label: str, ok: bool, detail: str = ""):
        global _pass, _fail
        if ok:
            _pass += 1
            print(f"  [PASS] {label}")
        else:
            _fail += 1
            print(f"  [FAIL] {label}  →  {detail}")

    print("\n" + "="*60)
    print("  _sop_config.py — B 段 fixtures")
    print("="*60)

    # ── F-SC1：正常讀取 batch_spec 全值 == 既有常數 ──
    print("\n[F-SC1] 正常讀取 batch_spec（讀真實 L0）")
    clear_sop_config_cache()
    bs = load_l0_batch_spec()
    _chk("F-SC1 main_scripts == 13",         bs.get("main_scripts") == 13, str(bs.get("main_scripts")))
    _chk("F-SC1 fishing_script == 0",         bs.get("fishing_script") == 0, str(bs.get("fishing_script")))
    _chk("F-SC1 threads_posts == 7",          bs.get("threads_posts") == 7, str(bs.get("threads_posts")))
    _chk("F-SC1 duration_seconds == 60",      bs.get("duration_seconds") == 60, str(bs.get("duration_seconds")))
    _chk("F-SC1 title_max_chars == 15",       bs.get("title_max_chars") == 15, str(bs.get("title_max_chars")))
    _chk("F-SC1 traffic_codes_min == 3",      bs.get("traffic_codes_min") == 3, str(bs.get("traffic_codes_min")))
    _chk("F-SC1 actor_interaction_min == 2",  bs.get("actor_interaction_min") == 2, str(bs.get("actor_interaction_min")))
    _chk("F-SC1 school_diversity_min == 3",   bs.get("school_diversity_min") == 3, str(bs.get("school_diversity_min")))
    _chk("F-SC1 theme_diversity_min == 4",    bs.get("theme_diversity_min") == 4, str(bs.get("theme_diversity_min")))

    # ── F-SC2：正常讀取 time_slots（6 個，timestamp 正規化）──
    print("\n[F-SC2] 正常讀取 time_slots（讀真實 L0）")
    clear_sop_config_cache()
    ts_list = load_l0_time_slots()
    _chk("F-SC2 6 個 slots",  len(ts_list) == 6, f"got {len(ts_list)}")
    expected_ts = ["0-3s", "3-12s", "12-25s", "25-40s", "40-52s", "52-60s"]
    for i, (exp, slot) in enumerate(zip(expected_ts, ts_list)):
        _chk(f"F-SC2 slot[{i}] timestamp == {exp!r}", slot["timestamp"] == exp, slot["timestamp"])

    # ── F-SC3：缺檔 → 全 fallback + stderr WARN ──
    print("\n[F-SC3] 缺檔 → 全 fallback + WARN（stderr）")
    clear_sop_config_cache()
    import io
    _stderr_buf = io.StringIO()
    _old_err = sys.stderr
    sys.stderr = _stderr_buf
    bs_miss = load_l0_batch_spec(sop_yaml="/nonexistent/sop.yaml")
    sys.stderr = _old_err
    warn_out = _stderr_buf.getvalue()
    _chk("F-SC3 fallback main_scripts == 13", bs_miss.get("main_scripts") == 13, str(bs_miss.get("main_scripts")))
    _chk("F-SC3 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in warn_out, repr(warn_out[:120]))

    # ── F-SC4：缺 key → 單 key fallback + WARN ──
    print("\n[F-SC4] 缺 key/壞 int → 單 key fallback + WARN（stderr）")
    # 建 temp SOP 缺 title_max_chars、actor_interaction_min 填非數字
    tmp_spec = {
        "batch_spec": {
            "main_scripts": 13,
            "fishing_script": 0,
            "threads_posts": 7,
            "visual_aid_scripts": 0,
            "duration_seconds": 60,
            # 刻意缺 title_max_chars
            "traffic_codes_min": 3,
            "actor_interaction_min": "bad_value",  # 非數字
            "school_diversity_min": 3,
            "theme_diversity_min": 4,
        },
        "script_schema": {"time_slots": [
            {"slot": "0-3秒",   "task": "Hook"},
            {"slot": "3-12秒",  "task": "破題"},
            {"slot": "12-25秒", "task": "核心"},
            {"slot": "25-40秒", "task": "案例"},
            {"slot": "40-52秒", "task": "收束"},
            {"slot": "52-60秒", "task": "CTA"},
        ]},
    }
    _tmp_dir = tempfile.mkdtemp()
    _tmp_path = os.path.join(_tmp_dir, "sop_test.yaml")
    with open(_tmp_path, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_spec, f, allow_unicode=True)
    clear_sop_config_cache()
    _stderr_buf2 = io.StringIO()
    sys.stderr = _stderr_buf2
    bs4 = load_l0_batch_spec(sop_yaml=_tmp_path)
    sys.stderr = _old_err
    warn_out2 = _stderr_buf2.getvalue()
    _chk("F-SC4 缺 title_max_chars → fallback 15", bs4.get("title_max_chars") == 15, str(bs4.get("title_max_chars")))
    _chk("F-SC4 壞 actor_interaction_min → fallback 2", bs4.get("actor_interaction_min") == 2, str(bs4.get("actor_interaction_min")))
    _chk("F-SC4 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in warn_out2, repr(warn_out2[:200]))

    # ── F-SC5：time_slots 重疊/倒序 → 全 fallback + WARN ──
    print("\n[F-SC5] time_slots 重疊/倒序 → 全 fallback + WARN")
    tmp_bad_ts = {
        "batch_spec": dict(_FALLBACK_BATCH_SPEC),
        "script_schema": {"time_slots": [
            {"slot": "0-3秒",  "task": "Hook"},
            {"slot": "3-12秒", "task": "破題"},
            {"slot": "10-25秒","task": "核心"},   # 重疊：start=10 < prev_end=12
            {"slot": "25-40秒","task": "案例"},
            {"slot": "40-52秒","task": "收束"},
            {"slot": "52-60秒","task": "CTA"},
        ]},
    }
    _tmp_path5 = os.path.join(_tmp_dir, "sop_overlap.yaml")
    with open(_tmp_path5, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_bad_ts, f, allow_unicode=True)
    clear_sop_config_cache()
    _stderr_buf5 = io.StringIO()
    sys.stderr = _stderr_buf5
    ts5 = load_l0_time_slots(sop_yaml=_tmp_path5)
    sys.stderr = _old_err
    warn_out5 = _stderr_buf5.getvalue()
    _chk("F-SC5 fallback → 6 slots", len(ts5) == 6, str(len(ts5)))
    _chk("F-SC5 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in warn_out5, repr(warn_out5[:200]))

    # ── F-SC6：time_slots 末段非 60 → 全 fallback + WARN ──
    print("\n[F-SC6] time_slots 末段 end != duration_seconds → 全 fallback + WARN")
    tmp_bad_end = {
        "batch_spec": dict(_FALLBACK_BATCH_SPEC),
        "script_schema": {"time_slots": [
            {"slot": "0-3秒",   "task": "Hook"},
            {"slot": "3-12秒",  "task": "破題"},
            {"slot": "12-25秒", "task": "核心"},
            {"slot": "25-40秒", "task": "案例"},
            {"slot": "40-52秒", "task": "收束"},
            {"slot": "52-65秒", "task": "CTA"},   # end=65 != duration=60
        ]},
    }
    _tmp_path6 = os.path.join(_tmp_dir, "sop_badend.yaml")
    with open(_tmp_path6, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_bad_end, f, allow_unicode=True)
    clear_sop_config_cache()
    _stderr_buf6 = io.StringIO()
    sys.stderr = _stderr_buf6
    ts6 = load_l0_time_slots(sop_yaml=_tmp_path6)
    sys.stderr = _old_err
    warn_out6 = _stderr_buf6.getvalue()
    _chk("F-SC6 fallback → 6 slots", len(ts6) == 6, str(len(ts6)))
    _chk("F-SC6 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in warn_out6, repr(warn_out6[:200]))

    # ── F-SC7：normalize_timestamp 各格式 ──
    print("\n[F-SC7] normalize_timestamp 各格式")
    _chk("F-SC7 '0-3秒' → '0-3s'",    normalize_timestamp("0-3秒") == "0-3s",    normalize_timestamp("0-3秒"))
    _chk("F-SC7 '0-3s' → '0-3s'",     normalize_timestamp("0-3s") == "0-3s",     normalize_timestamp("0-3s"))
    _chk("F-SC7 '0–3s' (en-dash)',     normalize_timestamp('0–3s') == '0-3s'",   normalize_timestamp("0–3s") == "0-3s", normalize_timestamp("0–3s"))
    _chk("F-SC7 '0-3 秒' → '0-3s'",   normalize_timestamp("0-3 秒") == "0-3s",  normalize_timestamp("0-3 秒"))
    _chk("F-SC7 '52-60秒' → '52-60s'", normalize_timestamp("52-60秒") == "52-60s", normalize_timestamp("52-60秒"))

    # ── F-SC8（Codex must-fix）：batch_spec 非 dict（list）→ 全 fallback + WARN，不 crash ──
    print("\n[F-SC8] batch_spec 非 dict → 全 fallback + WARN（不 crash）")
    tmp_bs_list = {"batch_spec": [1, 2, 3], "script_schema": {"time_slots": []}}
    _tmp_path8 = os.path.join(_tmp_dir, "sop_bs_list.yaml")
    with open(_tmp_path8, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_bs_list, f, allow_unicode=True)
    clear_sop_config_cache()
    _b8 = io.StringIO(); sys.stderr = _b8
    try:
        bs8 = load_l0_batch_spec(sop_yaml=_tmp_path8)
        _crash8 = False
    except Exception as _e8:
        bs8 = {}; _crash8 = True
    sys.stderr = _old_err
    _chk("F-SC8 非dict batch_spec 不 crash", not _crash8, "crashed")
    _chk("F-SC8 → fallback main_scripts 13", bs8.get("main_scripts") == 13, str(bs8.get("main_scripts")))
    _chk("F-SC8 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in _b8.getvalue(), repr(_b8.getvalue()[:160]))

    # ── F-SC9（Codex must-fix）：time_slots slot 非 dict（str）→ 全 fallback + WARN，不 crash ──
    print("\n[F-SC9] time_slots slot 非 dict → 全 fallback + WARN（不 crash）")
    tmp_slot_str = {"batch_spec": dict(_FALLBACK_BATCH_SPEC),
                    "script_schema": {"time_slots": ["0-3秒", "3-12秒"]}}
    _tmp_path9 = os.path.join(_tmp_dir, "sop_slot_str.yaml")
    with open(_tmp_path9, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_slot_str, f, allow_unicode=True)
    clear_sop_config_cache()
    _b9 = io.StringIO(); sys.stderr = _b9
    try:
        ts9 = load_l0_time_slots(sop_yaml=_tmp_path9)
        _crash9 = False
    except Exception as _e9:
        ts9 = (); _crash9 = True
    sys.stderr = _old_err
    _chk("F-SC9 非dict slot 不 crash", not _crash9, "crashed")
    _chk("F-SC9 → fallback 6 slots", len(ts9) == 6, str(len(ts9)))
    _chk("F-SC9 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in _b9.getvalue(), repr(_b9.getvalue()[:160]))

    # ── F-SC10（Codex should-fix）：time_slots 有 gap（3→4 不連續）→ 全 fallback + WARN ──
    print("\n[F-SC10] time_slots gap → 全 fallback + WARN")
    tmp_gap = {"batch_spec": dict(_FALLBACK_BATCH_SPEC),
               "script_schema": {"time_slots": [
                   {"slot": "0-3秒"}, {"slot": "4-12秒"}, {"slot": "12-25秒"},
                   {"slot": "25-40秒"}, {"slot": "40-52秒"}, {"slot": "52-60秒"}]}}
    _tmp_path10 = os.path.join(_tmp_dir, "sop_gap.yaml")
    with open(_tmp_path10, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_gap, f, allow_unicode=True)
    clear_sop_config_cache()
    _b10 = io.StringIO(); sys.stderr = _b10
    ts10 = load_l0_time_slots(sop_yaml=_tmp_path10)
    sys.stderr = _old_err
    _chk("F-SC10 gap → fallback 6 slots", len(ts10) == 6, str(len(ts10)))
    _chk("F-SC10 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in _b10.getvalue(), repr(_b10.getvalue()[:160]))

    # ── F-SC11（Codex should-fix）：time_slots 首段 start != 0 → 全 fallback + WARN ──
    print("\n[F-SC11] time_slots 首段 start != 0 → 全 fallback + WARN")
    tmp_start = {"batch_spec": dict(_FALLBACK_BATCH_SPEC),
                 "script_schema": {"time_slots": [
                     {"slot": "5-12秒"}, {"slot": "12-25秒"}, {"slot": "25-40秒"},
                     {"slot": "40-52秒"}, {"slot": "52-58秒"}, {"slot": "58-60秒"}]}}
    _tmp_path11 = os.path.join(_tmp_dir, "sop_start.yaml")
    with open(_tmp_path11, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_start, f, allow_unicode=True)
    clear_sop_config_cache()
    _b11 = io.StringIO(); sys.stderr = _b11
    ts11 = load_l0_time_slots(sop_yaml=_tmp_path11)
    sys.stderr = _old_err
    _chk("F-SC11 首段 start!=0 → fallback 6 slots", len(ts11) == 6, str(len(ts11)))
    _chk("F-SC11 stderr 含 [WARN] _sop_config:", "[WARN] _sop_config:" in _b11.getvalue(), repr(_b11.getvalue()[:160]))

    # ── F-SC12（Codex round2）：script_schema 非 dict（list）→ 明確 fallback + WARN，不 crash ──
    print("\n[F-SC12] script_schema 非 dict → 明確 fallback + WARN（不 crash）")
    tmp_ss_list = {"batch_spec": dict(_FALLBACK_BATCH_SPEC), "script_schema": [1, 2]}
    _tmp_path12 = os.path.join(_tmp_dir, "sop_ss_list.yaml")
    with open(_tmp_path12, "w", encoding="utf-8") as f:
        _yaml.dump(tmp_ss_list, f, allow_unicode=True)
    clear_sop_config_cache()
    _b12 = io.StringIO(); sys.stderr = _b12
    try:
        ts12 = load_l0_time_slots(sop_yaml=_tmp_path12)
        _crash12 = False
    except Exception as _e12:
        ts12 = (); _crash12 = True
    sys.stderr = _old_err
    _chk("F-SC12 非dict script_schema 不 crash", not _crash12, "crashed")
    _chk("F-SC12 → fallback 6 slots", len(ts12) == 6, str(len(ts12)))
    _chk("F-SC12 stderr 訊息精準（含 script_schema 非 mapping）",
         "script_schema 非 mapping" in _b12.getvalue(), repr(_b12.getvalue()[:160]))

    # 清理 tempfiles
    import shutil
    shutil.rmtree(_tmp_dir, ignore_errors=True)

    # ── 還原 cache ──
    clear_sop_config_cache()

    # ── 結果 ──
    print(f"\n{'='*60}")
    print(f"  結果：{_pass} PASS / {_fail} FAIL")
    print(f"{'='*60}\n")
    sys.exit(0 if _fail == 0 else 1)
