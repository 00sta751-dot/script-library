#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_taste_panel_stability.py — taste_panel_gate A1(快取)/A2(TECHNICAL_RETRY) 驗收

2026-07-07 W2 品管工單。禁真呼 GPT：全程 monkeypatch review_script（測試樁）。
跑法：python test_taste_panel_stability.py  （exit 0 = 全過）
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml as _yaml

import taste_panel_gate as g
from taste_panel_relative import STATUS_REJECT, compute_deploy_decision

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        print(f"  [PASS] {label}")
        PASS += 1
    else:
        print(f"  [FAIL] {label}{(' — ' + detail) if detail else ''}")
        FAIL += 1


RUBRIC = {"meta": {"version": "test", "model": "gpt-test"},
          "dimensions": [{"id": d} for d in g.REQUIRED_DIMS]}
RH, PH, RV, MID = "rh-test", "ph-test", "test", "gpt-test"


class FakeTP:
    """測試樁：可控 review_script 回應 + 呼叫計數（絕不真呼 GPT）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def review_script(self, path, rubric, mock=False):
        self.calls += 1
        r = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(r, BaseException):
            raise r
        return r


def set_fake(fake: FakeTP) -> None:
    g.load_existing_taste_panel_module = lambda: fake


def make_yaml(dirpath: Path, sid: str, tail: str = "end") -> tuple[Path, dict]:
    data = {
        "script_id": sid,
        "content_axis": "offpro",
        "lane": "voice_first",
        "topic_category": "人生",
        "scenes": [{"timestamp": "0-3s", "台詞": "hook"},
                   {"timestamp": "52-60s", "台詞": tail}],
        "caption": "cap",
        "title": "t-" + tail,
    }
    p = dirpath / f"script_{sid}.yaml"
    p.write_text("---\n" + _yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
    return p, data


def scores_full(v=95):
    return {d: v for d in g.REQUIRED_DIMS}


# ── A2: 解析失敗 → 重呼 1 次 → TECHNICAL_RETRY ──────────────────────────
print("[A2] 解析失敗重呼 + TECHNICAL_RETRY 不填 0")
d = Path(tempfile.mkdtemp())
p, data = make_yaml(d, "a2fail")
fake = FakeTP([{"scores": {"D1": 95, "D2": 95, "D3": 95}, "final_verdict": "pass"}])  # 永遠缺 D4/D5
set_fake(fake)
rep = g.make_real_report(p, data, RUBRIC, RH, PH, RV, MID)
check("A2-retry: review_script 恰呼 2 次（初呼+1重呼）", fake.calls == 2, f"calls={fake.calls}")
check("A2-tech: technical_failure=True", rep.get("technical_failure") is True, str(rep.get("technical_failure")))
check("A2-tech: execution_status=TECHNICAL_RETRY", rep.get("execution_status") == "TECHNICAL_RETRY", str(rep.get("execution_status")))
check("A2-tech: retry_count=2", rep.get("retry_count") == 2, str(rep.get("retry_count")))
check("A2-tech: verdict=pending_review（非 REJECT/PASS）", rep.get("verdict") == "pending_review", str(rep.get("verdict")))
check("A2-noZero: 缺維 D4=None（非 0）", rep["scores"]["D4"] is None, str(rep["scores"]))
check("A2-noZero: 缺維 D5=None（非 0）", rep["scores"]["D5"] is None, str(rep["scores"]))
check("A2-noZero: 已解析維 D1=95 保留", rep["scores"]["D1"] == 95, str(rep["scores"]))
rep_dec = g._attach_deploy_decision(dict(rep))
check("A2-deploy: 技術失敗 deploy_decision=TECHNICAL_RETRY（非 REJECT）",
      rep_dec["deploy_decision"]["status"] == "TECHNICAL_RETRY", str(rep_dec.get("deploy_decision")))

# ── A2: 解析失敗後重呼成功 → 正常報告（不誤標技術失敗）──────────────────
print("[A2] 重呼一次成功 → 正常內容路徑")
p2, data2 = make_yaml(d, "a2recover")
fake_r = FakeTP([{"scores": {"D1": 95, "D2": 95}},  # 第1呼缺
                 {"scores": scores_full(95), "final_verdict": "pass"}])  # 第2呼齊
set_fake(fake_r)
rep_r = g.make_real_report(p2, data2, RUBRIC, RH, PH, RV, MID)
check("A2-recover: 恰呼 2 次", fake_r.calls == 2, f"calls={fake_r.calls}")
check("A2-recover: technical_failure=False", rep_r.get("technical_failure") is False, str(rep_r.get("technical_failure")))
check("A2-recover: verdict=pass", rep_r.get("verdict") == "pass", str(rep_r.get("verdict")))

# ── A1: hash 相同 → 快取命中、不呼 GPT、沿用舊 verdict ─────────────────
print("[A1] hash 相同免重評（快取命中）")
dc = Path(tempfile.mkdtemp())
panel = dc / ".taste_panel"
panel.mkdir(parents=True, exist_ok=True)
pc, datac = make_yaml(dc, "a1cache")
fake_first = FakeTP([{"scores": scores_full(95), "final_verdict": "pass"}])
set_fake(fake_first)
first = g.make_real_report(pc, datac, RUBRIC, RH, PH, RV, MID)
g.atomic_write_json(panel / f"{first['script_id']}_taste_panel_report.json", g._attach_deploy_decision(dict(first)))
fake_noop = FakeTP([RuntimeError("cache hit 不應呼 GPT")])
set_fake(fake_noop)
cached = g.evaluate_one(pc, datac, RUBRIC, RH, PH, RV, MID, panel, False, {})
check("A1-hit: 標 cached=True", cached.get("cached") is True, str(cached.get("cached")))
check("A1-hit: review_script 完全未呼（0 次）", fake_noop.calls == 0, f"calls={fake_noop.calls}")
check("A1-hit: 沿用舊 verdict=pass", cached.get("verdict") == "pass", str(cached.get("verdict")))
check("A1-hit: 帶 cache_note", "hash 相同免重評" in str(cached.get("cache_note")), str(cached.get("cache_note")))

# ── A1: hash 變了 → 快取失效、照常重評 ─────────────────────────────────
print("[A1] hash 變了照常重評（快取失效）")
pc2, datac2 = make_yaml(dc, "a1cache", tail="CHANGED-CONTENT")  # 同 sid、內容變 → hash 變
fake_reeval = FakeTP([{"scores": scores_full(95), "final_verdict": "pass"}])
set_fake(fake_reeval)
reeval = g.evaluate_one(pc2, datac2, RUBRIC, RH, PH, RV, MID, panel, False, {})
check("A1-miss(hash變): review_script 有呼（1 次）", fake_reeval.calls == 1, f"calls={fake_reeval.calls}")
check("A1-miss(hash變): 非 cached", reeval.get("cached") is not True, str(reeval.get("cached")))

# ── A1: 技術失敗報告永不快取（必重跑）──────────────────────────────────
print("[A1] 技術失敗報告不快取")
dt = Path(tempfile.mkdtemp())
panelt = dt / ".taste_panel"
panelt.mkdir(parents=True, exist_ok=True)
pt, datat = make_yaml(dt, "a1tech")
rh_, sh_ = g.compute_hashes(pt, datat)
techrep = g._make_technical_retry_report(pt, datat, {"D1": 95}, 2, "stub", rh_, sh_, RH, PH, RV, MID)
g.atomic_write_json(panelt / f"{techrep['script_id']}_taste_panel_report.json", techrep)
cached_tech = g.load_cached_report(panelt, techrep["script_id"], rh_, sh_, RH, PH, MID)
check("A1-tech: 技術失敗報告 load_cached_report=None（必重跑）", cached_tech is None, str(cached_tech))

# ── A3: 真低分/REJECT 照樣擋（守門強度不變）──────────────────────────────
print("[A3] 真 REJECT 照樣擋")
dr = Path(tempfile.mkdtemp())
pr, datar = make_yaml(dr, "a3reject")
fake_rej = FakeTP([{"scores": {d: 10 for d in g.REQUIRED_DIMS}, "final_verdict": "reject"}])
set_fake(fake_rej)
rep_rej = g.make_real_report(pr, datar, RUBRIC, RH, PH, RV, MID)
check("A3: 5 維齊低分 → 非技術失敗（走內容路徑）", rep_rej.get("technical_failure") is False, str(rep_rej.get("technical_failure")))
dec = compute_deploy_decision(rep_rej["scores"], False, True, legacy_verdict=rep_rej["verdict"])
check("A3: 真低分內容 → deploy_decision=REJECT（擋批）", dec["status"] == STATUS_REJECT, str(dec))
check("A3: 缺分未被 0-fill 混淆（5 維皆 10）", all(rep_rej["scores"][d] == 10 for d in g.REQUIRED_DIMS), str(rep_rej["scores"]))

# ── 整合：gate 技術失敗報告 → completeness 擋批（execution-incomplete，非 0-fill REJECT）──
print("[整合] A2 端到端：技術失敗 → completeness 擋批不 0-fill")
try:
    import validate_script_batch as vsb
    rubric_path = g.DEFAULT_RUBRIC_PATH
    if not rubric_path.exists():
        print("  [SKIP] 真 rubric 不存在，跳過整合測（單元測已涵蓋核心）")
    else:
        _rt = rubric_path.read_text(encoding="utf-8")
        _rh = g.sha256_text(_rt)
        _rub = _yaml.safe_load(_rt) or {}
        _ph = g.prompt_template_hash(_rub)
        _mid = str((_rub.get("meta") or {}).get("model", g.DEFAULT_MODEL_ID))
        _rver = str((_rub.get("meta") or {}).get("version", "unknown"))
        di = Path(tempfile.mkdtemp())
        # 靠 yaml content_axis 自偵 hybrid（不宣告 _batch_flags，免 declared-but-not-built 短路）
        panel_i = di / ".taste_panel"
        panel_i.mkdir(parents=True, exist_ok=True)
        sids = []
        for i in range(1, 14):
            sid = f"ig_{i:02d}"
            sids.append(sid)
            dta = {"script_id": sid, "content_axis": "offpro", "lane": "voice_first",
                   "topic_category": "人生",
                   "scenes": [{"timestamp": "0-3s", "台詞": "h"}, {"timestamp": "52-60s", "台詞": f"e{i}"}],
                   "caption": "c"}
            pth = di / f"script_{sid}.yaml"
            pth.write_text("---\n" + _yaml.safe_dump(dta, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
            if i == 3:
                set_fake(FakeTP([{"scores": {"D1": 95, "D2": 95, "D3": 95}}]))  # 缺 D4/D5 → 技術失敗
            else:
                set_fake(FakeTP([{"scores": scores_full(95), "final_verdict": "pass"}]))
            rr = g._attach_deploy_decision(g.make_real_report(pth, dta, _rub, _rh, _ph, _rver, _mid))
            g.atomic_write_json(panel_i / f"{sid}_taste_panel_report.json", rr)
        summary = {"schema_version": 1, "gate_version": g.GATE_VERSION, "rubric_hash": _rh,
                   "rubric_version": _rver, "prompt_template_hash": _ph, "model_id": _mid,
                   "required_dims": list(g.REQUIRED_DIMS), "script_count": 13,
                   "script_ids": sids, "mock_report": False, "no_llm_mode": False}
        g.atomic_write_json(panel_i / "_taste_panel_summary.json", summary)
        valid_i = [(p, d) for p, d in vsb.load_yamls(di) if isinstance(d, dict) and "__parse_error__" not in d]
        status_i, reason_i = vsb.chk_taste_panel_completeness(valid_i, di)
        check("整合: completeness 擋批（非 PASS）", status_i != "PASS", f"{status_i}: {reason_i[:120]}")
        check("整合: ig_03 標『評審未跑完/execution incomplete』", ("評審未跑完" in reason_i) or ("execution" in reason_i), reason_i[:200])
        check("整合: 無 0-fill 假象（reason 不含 missing_scores / =0.0）",
              "missing_scores" not in reason_i and "=0.0" not in reason_i and "D4=0 " not in reason_i, reason_i[:200])
except Exception as e:
    check("整合: 執行未拋例外", False, f"{type(e).__name__}: {e}")

print(f"\n=== taste_panel_stability 結果：{PASS}/{PASS + FAIL} PASS ===")
if FAIL:
    print(f"FAIL {FAIL} 件")
    sys.exit(1)
print("全部 PASS")
sys.exit(0)
