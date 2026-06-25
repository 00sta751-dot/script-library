# -*- coding: utf-8 -*-
"""
taste_panel_relative.py — 評審團「相對放行線 + 兩軌」決策 helper（v6 設計）

定位：純函式、無副作用、無外部 import。被 taste_panel_gate.py + validate_script_batch.py 共用。
鐵律：default-OFF。env `TASTE_PANEL_RELATIVE` 未開（預設 false）→ deploy 決策鏡射舊 90 行為（legacy_mirror），
      整檔 dormant、對 production 零影響。開啟才走相對線。
來源：澤君 2026-06-24「評審團+編劇都處理好」directive + GPT 7 輪 codex 設計（thread 019efb1d）。
門檻為 PROVISIONAL（12 seed 樣本導出、未滿 30 不切 holdout、enforce flip 前須人工盲評一致率≥80）。
誠實：deploy 線量「文字 craft 能不能上線」、非預測 virality；strict craft 分另由 rubric verdict 給編劇。
"""

import os

DIMENSIONS = ("D1", "D2", "D3", "D4", "D5")

STATUS_PASS = "PASS_WITH_NOTES"
STATUS_HUMAN = "HUMAN_REVIEW"
STATUS_REJECT = "REJECT"

WEIGHTS = {
    "D1": 0.30,
    "D2": 0.25,
    "D3": 0.15,
    "D4": 0.15,
    "D5": 0.15,
}

PASS_FLOORS = {
    "D1": 50.0,
    "D2": 48.0,
    "D3": 40.0,
    "D4": 40.0,
    "D5_ONPRO": 42.0,
    "D5_OFFPRO_AUTO_PASS": 40.0,
}

PASS_MIN_AVG = 68.0
PASS_MIN_DEPLOY_INDEX = 68.0
PASS_MIN_DIMS_AT_60 = 3

GRAY = {
    "LOW": 52.0,
    "HIGH": 68.0,
    "BORDERLINE_HIGH": 72.0,
    "NEAR_FLOOR_POINTS": 8.0,
}

REJECT = {
    "AVG_LT": 52.0,
    "D1_LT": 35.0,
    "D2_LT": 35.0,
    "D5_ONPRO_LT": 30.0,
    "ANY_DIM_LT": 25.0,
}


# 旗標檔：pre-commit / deploy 環境 env var 不可靠 → 另支援 flag 檔（對齊 claude-state/flags 慣例）。
# 開啟＝建此檔；關回＝刪此檔（一鍵 reversible）。
FLAG_FILE = r"C:\Users\00sta\claude-state\flags\taste_panel_relative"


def is_relative_enabled(env=None):
    if env is None:
        env = os.environ
    raw = str(env.get("TASTE_PANEL_RELATIVE", "")).strip().lower()
    if raw in ("1", "true", "yes", "y", "on", "relative"):
        return True
    try:
        return os.path.exists(FLAG_FILE)
    except Exception:
        return False


def is_offpro_report(report):
    """單一真理源：gate + validate 共用的 off-pro 判定（防兩邊邏輯漂移、給不同 deploy 決策）。
    off-pro = content_axis=='offpro' OR lane=='stance' OR upstream_report.proof_mode=='voice_first'。"""
    if not isinstance(report, dict):
        return False
    if str(report.get("content_axis") or "").strip().lower() == "offpro":
        return True
    if str(report.get("lane") or "").strip().lower() == "stance":
        return True
    up = report.get("upstream_report")
    if isinstance(up, dict) and str(up.get("proof_mode") or "").strip().lower() == "voice_first":
        return True
    return False


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_scores(scores):
    clean = {}
    missing = []
    for dim in DIMENSIONS:
        value = _to_float((scores or {}).get(dim))
        if value is None:
            missing.append(dim)
            clean[dim] = 0.0
        else:
            clean[dim] = max(0.0, min(100.0, value))
    return clean, missing


def _avg(clean):
    return sum(clean[dim] for dim in DIMENSIONS) / float(len(DIMENSIONS))


def _deploy_index(clean):
    return sum(clean[dim] * WEIGHTS[dim] for dim in DIMENSIONS)


def _weakest_dim(clean):
    return min(DIMENSIONS, key=lambda dim: clean[dim])


def _dims_at_or_above(clean, floor):
    return sum(1 for dim in DIMENSIONS if clean[dim] >= floor)


def _round2(value):
    return round(float(value), 2)


def mirror_legacy_decision(scores, verdict, is_offpro=False):
    """flag OFF：deploy_decision 鏡射舊 verdict（pass→PASS_WITH_NOTES、其餘→REJECT）。validator 在 OFF 時不讀它。"""
    clean, missing = _clean_scores(scores)
    avg = _avg(clean)
    deploy_index = _deploy_index(clean)
    weakest = _weakest_dim(clean)

    if str(verdict).lower() == "pass":
        status = STATUS_PASS
        reject_reasons = []
        note = "legacy verdict mirrored as deploy pass"
    else:
        status = STATUS_REJECT
        reject_reasons = ["legacy_verdict_not_pass"]
        note = "legacy verdict mirrored as deploy reject"

    if missing:
        reject_reasons.append("missing_scores:" + ",".join(missing))
        status = STATUS_REJECT
        note = "legacy mirror found missing score dimensions"

    return {
        "status": status,
        "deploy_index": _round2(deploy_index),
        "avg": _round2(avg),
        "weakest_dim": weakest,
        "reject_reasons": reject_reasons,
        "note": note,
        "mode": "legacy_mirror",
        "is_offpro": bool(is_offpro),
    }


def compute_deploy_decision(scores, is_offpro, enabled, legacy_verdict=None):
    """relative 放行決策。enabled=False→鏡射舊 90 全維硬閘；enabled=True→相對線（avg/deploy_index/floor/gray）。
    legacy_verdict：panel 最終 verdict。relative 只放寬「<90 的 revise」案；panel 硬退（reject / reject_generic
    ＝D1 generic 角度硬閘 / 觀眾否決 won't-finish）一律保留 REJECT，避免 generic 高分稿漏網。"""
    clean, missing = _clean_scores(scores)
    avg = _avg(clean)
    deploy_index = _deploy_index(clean)
    weakest = _weakest_dim(clean)

    if not enabled:
        legacy_pass = all(clean[dim] >= 90.0 for dim in DIMENSIONS) and not missing
        return {
            "status": STATUS_PASS if legacy_pass else STATUS_REJECT,
            "deploy_index": _round2(deploy_index),
            "avg": _round2(avg),
            "weakest_dim": weakest,
            "reject_reasons": [] if legacy_pass else ["legacy_threshold_not_met"],
            "note": "relative mode disabled; legacy threshold mirror",
            "mode": "legacy_mirror",
            "is_offpro": bool(is_offpro),
        }

    reject_reasons = []
    # panel 硬退保留：relative 只放寬 <90 的 revise 案、不放寬 panel 硬退（generic 角度/觀眾否決）。
    _lv = str(legacy_verdict or "").strip().lower()
    if _lv in ("reject", "reject_generic"):
        reject_reasons.append("panel_hard_reject:" + _lv)
    if missing:
        reject_reasons.append("missing_scores:" + ",".join(missing))
    if avg < REJECT["AVG_LT"]:
        reject_reasons.append("avg_lt_52")
    if clean["D1"] < REJECT["D1_LT"]:
        reject_reasons.append("D1_lt_35")
    if clean["D2"] < REJECT["D2_LT"]:
        reject_reasons.append("D2_lt_35")
    if clean["D5"] < REJECT["D5_ONPRO_LT"] and not is_offpro:
        reject_reasons.append("D5_onpro_lt_30")
    for dim in DIMENSIONS:
        if clean[dim] < REJECT["ANY_DIM_LT"]:
            reject_reasons.append(dim + "_lt_25")

    if reject_reasons:
        return {
            "status": STATUS_REJECT,
            "deploy_index": _round2(deploy_index),
            "avg": _round2(avg),
            "weakest_dim": weakest,
            "reject_reasons": reject_reasons,
            "note": "reject by provisional relative floor",
            "mode": "relative_v1",
            "is_offpro": bool(is_offpro),
        }

    pass_reasons = []
    if avg < PASS_MIN_AVG:
        pass_reasons.append("avg_lt_68")
    if deploy_index < PASS_MIN_DEPLOY_INDEX:
        pass_reasons.append("deploy_index_lt_68")
    if clean["D1"] < PASS_FLOORS["D1"]:
        pass_reasons.append("D1_lt_50")
    if clean["D2"] < PASS_FLOORS["D2"]:
        pass_reasons.append("D2_lt_48")
    if clean["D3"] < PASS_FLOORS["D3"]:
        pass_reasons.append("D3_lt_40")
    if clean["D4"] < PASS_FLOORS["D4"]:
        pass_reasons.append("D4_lt_40")
    # D4（角度/翻案）＝off-pro「不一般」主軸：D4<50 須 D1/D3/index 真強（數據論述型例外）才 auto-PASS；
    # 否則降 HUMAN_REVIEW（防「有 hook 有料但無真翻案」的普通稿混進乾淨 PASS）。GPT 上線後驗證 round6。
    if clean["D4"] < 50.0 and not (clean["D1"] >= 72.0 and clean["D3"] >= 80.0 and deploy_index >= 70.0):
        pass_reasons.append("D4_lt_50_weak_angle")

    if is_offpro:
        if clean["D5"] < PASS_FLOORS["D5_OFFPRO_AUTO_PASS"]:
            pass_reasons.append("D5_offpro_lt_40_review")
    else:
        if clean["D5"] < PASS_FLOORS["D5_ONPRO"]:
            pass_reasons.append("D5_onpro_lt_42")

    if _dims_at_or_above(clean, 60.0) < PASS_MIN_DIMS_AT_60:
        pass_reasons.append("fewer_than_3_dims_ge_60")

    if pass_reasons:
        return {
            "status": STATUS_HUMAN,
            "deploy_index": _round2(deploy_index),
            "avg": _round2(avg),
            "weakest_dim": weakest,
            "reject_reasons": [],
            "note": "human review: " + ",".join(pass_reasons),
            "mode": "relative_v1",
            "is_offpro": bool(is_offpro),
        }

    return {
        "status": STATUS_PASS,
        "deploy_index": _round2(deploy_index),
        "avg": _round2(avg),
        "weakest_dim": weakest,
        "reject_reasons": [],
        "note": "provisional relative pass; weakest_dim=" + weakest,
        "mode": "relative_v1",
        "is_offpro": bool(is_offpro),
    }


def aggregate_median(score_dicts):
    """邊界稿 N=3 重跑取每維中位數（降 GPT 打分變異）。"""
    if not score_dicts:
        return {}

    out = {}
    for dim in DIMENSIONS:
        values = []
        for scores in score_dicts:
            value = _to_float((scores or {}).get(dim))
            if value is not None:
                values.append(max(0.0, min(100.0, value)))

        if not values:
            continue

        values.sort()
        n = len(values)
        mid = n // 2
        if n % 2:
            out[dim] = values[mid]
        else:
            out[dim] = (values[mid - 1] + values[mid]) / 2.0

    return out
