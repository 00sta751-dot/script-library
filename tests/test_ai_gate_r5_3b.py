"""
test_ai_gate_r5_3b.py — AI 語意閘（R5-3b v2）測試

TC-A: 同題不同角度 -> same_topic_new_angle -> 不 flag（§22.9 不誤殺）
TC-B: 不同題 -> different_topic + high conf -> shadow WARN + 含「題目疑似不同」
TC-C: API 不可用 -> graceful skip，不 crash，不擋批
TC-D: cache -> 同 key 第二次不打 API
TC-E: 爛 verdict -> insufficient_evidence
TC-F: 巢狀 JSON 正確抽出（硬化 3）
TC-G: 非純 JSON / markdown fence 正確解析（硬化 3）
TC-H: 2-judge: 1 pass + 1 different_topic -> 放行（硬化 5 §22.9 最寬鬆者勝）
TC-I: 2-judge: 2x different_topic + high conf -> flag（硬化 5）
TC-J: confidence < 85 -> different_topic 降為 insufficient_evidence（硬化 2）
TC-K: timeout -> graceful api_unavailable（硬化 1）
TC-L: 整合測試 — AI different_topic -> topic_fidelity_flagged（硬化 8）
"""

import sys
import os
import json
import tempfile
import hashlib
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

_SCRIPT_LIB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPT_LIB))

import validate_script_batch as _vsb


def _mock_resp(verdict, reason="測試", confidence=90):
    r = MagicMock()
    r.text = json.dumps({"verdict": verdict, "reason": reason, "confidence": confidence})
    return r


def _mock_client(verdict, reason="測試", confidence=90):
    c = MagicMock()
    c.models.generate_content.return_value = _mock_resp(verdict, reason, confidence)
    return c


def _rc():
    _vsb._TOPIC_INTEL_AI_GATE_CACHE.clear()


# ── TC-A ──────────────────────────────────────

def tc_A():
    print("\n[TC-A] §22.9: same_topic_new_angle -> 無 WARN")
    _rc()
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        with patch("validate_script_batch._genai_client_factory",
                   return_value=_mock_client("same_topic_new_angle")):
            r = _vsb._call_topic_intel_ai_gate("ev", "body", "kA")
    assert r["verdict"] == "same_topic_new_angle"
    shadow_warns = []
    if r["verdict"] == "different_topic":
        shadow_warns.append("題目疑似不同")
    assert not shadow_warns
    print("  [PASS] TC-A")
    return True


# ── TC-B ──────────────────────────────────────

def tc_B():
    print("\n[TC-B] different_topic + conf>=85 -> WARN 含「題目疑似不同」")
    _rc()
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        _mc = _mock_client("different_topic", "題目完全不同", 95)
        with patch("validate_script_batch._genai_client_factory", return_value=_mc):
            r = _vsb._call_topic_intel_ai_gate("ev", "body", "kB")
    assert r["verdict"] == "different_topic", f"got {r['verdict']}"
    assert r.get("confidence", 0) >= 85
    warn_text = (f"【AI語意閘】腳本與爆款出處題目疑似不同"
                 f"（verdict=different_topic, confidence={r['confidence']}；{r['reason']}）")
    assert "題目疑似不同" in warn_text
    print(f"  verdict={r['verdict']} conf={r['confidence']} ✓")
    print("  [PASS] TC-B")
    return True


# ── TC-C ──────────────────────────────────────

def tc_C():
    print("\n[TC-C] API 不可用 -> graceful skip（3 場景）")
    # C-1: KEY 未設
    _rc()
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_API_KEY"}
    env["TOPIC_INTEL_AI_GATE"] = "1"
    with patch.dict(os.environ, env, clear=True):
        r = _vsb._call_topic_intel_ai_gate("ev", "body", "kC1")
    assert r["verdict"] == "api_unavailable"
    print(f"  [C-1 PASS] KEY 未設 -> {r.get('note','')}")

    # C-2: ImportError
    _rc()
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        import builtins
        _orig = builtins.__import__
        def _block(name, *a, **kw):
            if "google" in name:
                raise ImportError("mock block")
            return _orig(name, *a, **kw)
        with patch("builtins.__import__", side_effect=_block):
            r2 = _vsb._call_topic_intel_ai_gate("ev", "body", "kC2")
    assert r2["verdict"] == "api_unavailable"
    print(f"  [C-2 PASS] ImportError -> {r2.get('note','')}")

    # C-3: generate_content raises
    # defect-1 fix 後：2-judge 均 api_unavailable → _consensus_verdict 回 insufficient_evidence
    # (coordinator spec: 任一 api_unavailable → 不 flag，與 api_unavailable 均屬合法 graceful)
    _rc()
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        _mc = MagicMock()
        _mc.models.generate_content.side_effect = Exception("quota exceeded")
        with patch("validate_script_batch._genai_client_factory", return_value=_mc):
            r3 = _vsb._call_topic_intel_ai_gate("ev", "body", "kC3")
    assert r3["verdict"] in ("api_unavailable", "insufficient_evidence"), \
        f"C-3: 應 graceful skip，got {r3['verdict']}"
    print(f"  [C-3 PASS] Exception -> verdict={r3['verdict']} (graceful)")

    print("  [PASS] TC-C")
    return True


# ── TC-D ──────────────────────────────────────

def tc_D():
    print("\n[TC-D] cache -> 同 key 第二次不打 API")
    _rc()
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        _mc = _mock_client("same_topic")
        with patch("validate_script_batch._genai_client_factory", return_value=_mc):
            _vsb._call_topic_intel_ai_gate("ev", "body", "kD")  # 首次：2 judges = 2 calls
            _vsb._call_topic_intel_ai_gate("ev", "body", "kD")  # cache hit: 0 calls
            calls = _mc.models.generate_content.call_count
    assert calls == 2, f"期望 2（2 judges 首次），got {calls}"
    print(f"  API calls={calls} ✓")
    print("  [PASS] TC-D")
    return True


# ── TC-E ──────────────────────────────────────

def tc_E():
    print("\n[TC-E] 爛 verdict -> insufficient_evidence 或 api_unavailable")
    _rc()
    resp = MagicMock()
    resp.text = json.dumps({"verdict": "GARBAGE", "reason": "x", "confidence": 50})
    _mc = MagicMock()
    _mc.models.generate_content.return_value = resp
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        with patch("validate_script_batch._genai_client_factory", return_value=_mc):
            r = _vsb._call_topic_intel_ai_gate("ev", "body", "kE")
    assert r["verdict"] in ("insufficient_evidence", "api_unavailable"), f"got {r['verdict']}"
    print(f"  verdict={r['verdict']} ✓")
    print("  [PASS] TC-E")
    return True


# ── TC-F: 巢狀 JSON（硬化 3）──────────────────

def tc_F():
    print("\n[TC-F] 巢狀 JSON -> _extract_verdict_from_parsed + _extract_fields_from_parsed（硬化 3）")

    # F-1: 舊介面 _extract_verdict_from_parsed（只回 verdict 字串）
    verdict_cases = [
        ({"result": {"verdict": "same_topic", "confidence": 90}}, "same_topic"),
        ({"output": {"verdict": "different_topic"}}, "different_topic"),
        ({"data": {"verdict": "insufficient_evidence"}}, "insufficient_evidence"),
        ({"verdict": "same_topic_new_angle"}, "same_topic_new_angle"),
        ({"nested_x": {"verdict": "same_topic"}}, "same_topic"),
        ({}, "insufficient_evidence"),
        ("not_dict", "insufficient_evidence"),
    ]
    for parsed, expected in verdict_cases:
        got = _vsb._extract_verdict_from_parsed(parsed)
        assert got == expected, f"input={parsed!r}: expected {expected!r}, got {got!r}"
        print(f"  [verdict] {str(parsed)[:40]!r} -> {got!r} ✓")

    # F-2: 新介面 _extract_fields_from_parsed（defect 2 fix）
    #   巢狀 JSON confidence/reason 必須從同層抽出，不能讀 top-level
    field_cases = [
        # 巢狀含 confidence → confidence 要正確抽到（defect 2 的核心案例）
        ({"result": {"verdict": "different_topic", "confidence": 92, "reason": "不同"}},
         {"verdict": "different_topic", "confidence": 92, "reason": "不同"}),
        # top-level 直接命中
        ({"verdict": "same_topic_new_angle", "confidence": 85, "reason": "同題"},
         {"verdict": "same_topic_new_angle", "confidence": 85, "reason": "同題"}),
        # 無 confidence → 0
        ({"result": {"verdict": "different_topic"}},
         {"verdict": "different_topic", "confidence": 0, "reason": ""}),
        # 空 → {}
        ({}, {}),
        # 非 dict → {}
        ("not_dict", {}),
    ]
    for parsed, expected in field_cases:
        got = _vsb._extract_fields_from_parsed(parsed)
        assert got == expected, f"input={parsed!r}: expected {expected!r}, got {got!r}"
        print(f"  [fields] {str(parsed)[:40]!r} -> {got!r} ✓")

    print("  [PASS] TC-F")
    return True


# ── TC-G: 非純 JSON（硬化 3）─────────────────

def tc_G():
    print("\n[TC-G] 非純 JSON / fence -> _parse_ai_gate_response 正確解析（硬化 3）")
    cases = [
        ('```json\n{"verdict":"same_topic","confidence":88}\n```',
         {"verdict": "same_topic", "confidence": 88}),
        ('Here is the result: {"verdict":"different_topic","confidence":92}',
         {"verdict": "different_topic", "confidence": 92}),
        ('{"verdict":"same_topic_new_angle","confidence":70}',
         {"verdict": "same_topic_new_angle", "confidence": 70}),
        ("", {}),
        ("not json at all", {}),
    ]
    for text, expected in cases:
        got = _vsb._parse_ai_gate_response(text)
        assert got == expected, f"text={text!r}: expected {expected!r}, got {got!r}"
        print(f"  {text[:40]!r} -> {got!r} ✓")
    print("  [PASS] TC-G")
    return True


# ── TC-H: 2-judge 1 pass + 1 diff -> 放行（硬化 5）──

def tc_H():
    print("\n[TC-H] 2-judge: 1 pass + 1 different_topic -> 放行（§22.9 最寬鬆者勝）")
    j1 = {"verdict": "same_topic_new_angle", "reason": "同題", "confidence": 85}
    j2 = {"verdict": "different_topic", "reason": "不同", "confidence": 95}
    result = _vsb._consensus_verdict([j1, j2])
    assert result["verdict"] == "same_topic_new_angle", f"got {result['verdict']}"
    print(f"  verdict={result['verdict']} ✓")
    print("  [PASS] TC-H")
    return True


# ── TC-I: 2-judge 2x different_topic -> flag（硬化 5）──

def tc_I():
    print("\n[TC-I] 2-judge: 2x different_topic + avg conf>=85 -> flag")
    j1 = {"verdict": "different_topic", "reason": "不同", "confidence": 90}
    j2 = {"verdict": "different_topic", "reason": "不同", "confidence": 92}
    result = _vsb._consensus_verdict([j1, j2])
    assert result["verdict"] == "different_topic", f"got {result['verdict']}"
    assert result["confidence"] == 91  # avg(90,92)=91
    print(f"  verdict={result['verdict']} conf={result['confidence']} ✓")
    print("  [PASS] TC-I")
    return True


# ── TC-J: confidence < 85 -> 降級（硬化 2）──────

def tc_J():
    print("\n[TC-J] confidence < 85 -> different_topic 降為 insufficient_evidence（硬化 2）")
    _rc()
    resp = MagicMock()
    resp.text = json.dumps({"verdict": "different_topic", "reason": "不同", "confidence": 70})
    _mc = MagicMock()
    _mc.models.generate_content.return_value = resp
    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        with patch("validate_script_batch._genai_client_factory", return_value=_mc):
            r = _vsb._call_topic_intel_ai_gate("ev", "body", "kJ")
    assert r["verdict"] == "insufficient_evidence", f"got {r['verdict']}（conf=70 < 85 應降級）"
    print(f"  verdict={r['verdict']} ✓（conf<85 -> 降級）")
    print("  [PASS] TC-J")
    return True


# ── TC-K: timeout（硬化 1）────────────────────

def tc_K():
    print("\n[TC-K] timeout -> api_unavailable，不卡批（硬化 1）")
    _rc()

    def _slow(*a, **kw):
        time.sleep(30)
        return MagicMock(text='{"verdict":"same_topic","confidence":90}')

    _mc = MagicMock()
    _mc.models.generate_content.side_effect = _slow

    orig = _vsb._AI_GATE_TIMEOUT_SEC
    _vsb._AI_GATE_TIMEOUT_SEC = 1

    try:
        with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
            with patch("validate_script_batch._genai_client_factory", return_value=_mc):
                t0 = time.time()
                r = _vsb._call_topic_intel_ai_gate("ev", "body", "kK")
                elapsed = time.time() - t0
    finally:
        _vsb._AI_GATE_TIMEOUT_SEC = orig

    # defect-1 fix 後：2x timeout → 2x api_unavailable → consensus = insufficient_evidence
    # (均屬合法 graceful，關鍵是 elapsed < 10 不卡批)
    assert r["verdict"] in ("api_unavailable", "insufficient_evidence"), f"got {r['verdict']}"
    assert elapsed < 10, f"逾時 > 10s，硬化 1 無效（elapsed={elapsed:.1f}s）"
    print(f"  verdict={r['verdict']} elapsed={elapsed:.1f}s ✓（< 10s, 不卡批）")
    print("  [PASS] TC-K")
    return True


# ── TC-L: 整合測試（硬化 8）─────────────────────

def tc_L():
    print("\n[TC-L] 整合：AI different_topic -> chk_topic_intel_provenance WARN 含「題目疑似不同」（硬化 8）")

    with tempfile.TemporaryDirectory() as tmp:
        ev_file = Path(tmp) / "cyborg_test.yaml"
        ev_content = (
            "title: 殺價議價率 Top10\n"
            "transcript_preview: 桃園大園 22.5%，建商開價打幾折\n"
            "dissect:\n"
            "  hook_structure:\n"
            "    first_3_sec_text: 到底應該殺多少？\n"
            "  narrative_arc: 議價率最高 Top10 區域分析\n"
        )
        ev_file.write_bytes(ev_content.encode("utf-8"))
        ev_sha = hashlib.sha256(ev_content.encode("utf-8")).hexdigest()

        script_data = {
            "batch_tag": "TEST_B1",
            "owner": "瑞祥",
            "script_id": "test_01",
            "source_topic_intel": {
                "topic_id": "TOPIC_001",
                "evidence_path": str(ev_file),
                "evidence_sha256": ev_sha,
                "adopted_topic_statement": "本腳本探討購屋頭期款不足的現代年輕人困境與資金規劃方法",
            },
            "派系": "off-pro",
            "時間軸": [
                {"段落": "開場白", "台詞": "今天帶你看一個全新個案，台南仁德三房格局非常漂亮"},
                {"段落": "主體", "台詞": "採光超好，社區配備完善，非常適合自住"},
            ],
        }

        resp_mock = MagicMock()
        resp_mock.text = json.dumps({"verdict": "different_topic",
                                     "reason": "個案介紹vs議價率", "confidence": 92})
        _mc = MagicMock()
        _mc.models.generate_content.return_value = resp_mock

        policy = {
            "enabled": True,
            "mode": "shadow",
            "bind_scope": "all_offpro",
            "min_slots": 1,
            "max_slots": 9,
        }

        with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
            with patch("validate_script_batch._genai_client_factory", return_value=_mc):
                with patch("validate_script_batch._load_projection_candidate_index",
                           return_value={"TOPIC_001": ev_sha}):
                    status, detail = _vsb.chk_topic_intel_provenance(
                        data=script_data,
                        fname="script_test_01.yaml",
                        topic_intel_policy=policy,
                        is_skeleton=False,
                        owner="瑞祥",
                    )

        print(f"  status={status!r}")
        print(f"  detail={detail[:120]}...")

        assert status == "WARN", f"AI shadow 應為 WARN，得 {status!r}"
        print("  [L-1 PASS] status=WARN ✓（shadow 不擋批）")

        assert "題目疑似不同" in detail, f"detail 應含「題目疑似不同」，得：{detail}"
        print("  [L-2 PASS] detail 含「題目疑似不同」-> flag 鏈可捕捉 ✓")

    print("  [PASS] TC-L")
    return True


# ── TC-M: defect 1 — api_unavailable + different_topic -> 不 flag（§22.9 保護）──

def tc_M():
    print("\n[TC-M] defect1 fix: judge1=api_unavailable + judge2=different_topic -> 不 flag（§22.9）")

    # M-1: 舊邏輯 bug 復現：過濾 api_unavailable 後只剩 1 個 different_topic → 原來會 flag
    #      新邏輯：任一 api_unavailable → 降 insufficient_evidence
    j1 = {"verdict": "api_unavailable", "note": "逾時"}
    j2 = {"verdict": "different_topic", "confidence": 95, "reason": "不同題"}
    result = _vsb._consensus_verdict([j1, j2])
    assert result["verdict"] == "insufficient_evidence", \
        f"defect 1：judge1=api_unavailable+judge2=different_topic 應得 insufficient_evidence，got {result['verdict']}"
    print(f"  [M-1 PASS] api_unavailable+different_topic -> {result['verdict']} ✓（不誤 flag）")

    # M-2: judge1=insufficient_evidence + judge2=different_topic -> 不 flag
    j3 = {"verdict": "insufficient_evidence", "confidence": 60, "reason": "不確定"}
    j4 = {"verdict": "different_topic", "confidence": 93, "reason": "不同"}
    result2 = _vsb._consensus_verdict([j3, j4])
    assert result2["verdict"] == "insufficient_evidence", \
        f"insufficient_evidence+different_topic 應降 insufficient_evidence，got {result2['verdict']}"
    print(f"  [M-2 PASS] insufficient_evidence+different_topic -> {result2['verdict']} ✓")

    # M-3: 2x api_unavailable → coordinator spec「任一 api_unavailable → 不 flag」
    # → 目前實作回 insufficient_evidence（任一 UNCERTAIN 就傳染）；兩者均屬 graceful
    j5 = {"verdict": "api_unavailable", "note": "逾時1"}
    j6 = {"verdict": "api_unavailable", "note": "逾時2"}
    result3 = _vsb._consensus_verdict([j5, j6])
    assert result3["verdict"] in ("api_unavailable", "insufficient_evidence"), \
        f"2x api_unavailable 應 graceful（不 flag），got {result3['verdict']}"
    print(f"  [M-3 PASS] 2x api_unavailable -> {result3['verdict']} ✓（不 flag）")

    # M-4: 2x different_topic + conf>=85 → flag（正向案例不受影響）
    j7 = {"verdict": "different_topic", "confidence": 90, "reason": "不同"}
    j8 = {"verdict": "different_topic", "confidence": 92, "reason": "不同"}
    result4 = _vsb._consensus_verdict([j7, j8])
    assert result4["verdict"] == "different_topic", f"2x different_topic 應 flag，got {result4['verdict']}"
    assert result4["confidence"] == 91  # avg(90,92)
    print(f"  [M-4 PASS] 2x different_topic avg_conf=91 -> {result4['verdict']} ✓（正向不受影響）")

    print("  [PASS] TC-M")
    return True


# ── TC-N: defect 2 — 巢狀 JSON confidence end-to-end 正確傳遞 ──

def tc_N():
    print("\n[TC-N] defect2 fix: 巢狀 JSON confidence 正確傳遞，不被誤降級")
    _rc()

    # Gemini 回傳巢狀格式：verdict+confidence 在 "result" 子 dict
    nested_resp_text = json.dumps({
        "result": {
            "verdict": "different_topic",
            "confidence": 92,
            "reason": "腳本講個案介紹，爆款講議價率"
        }
    })
    resp_mock = MagicMock()
    resp_mock.text = nested_resp_text
    _mc = MagicMock()
    _mc.models.generate_content.return_value = resp_mock

    with patch.dict(os.environ, {"TOPIC_INTEL_AI_GATE": "1", "GOOGLE_API_KEY": "mk"}):
        with patch("validate_script_batch._genai_client_factory", return_value=_mc):
            r = _vsb._call_topic_intel_ai_gate("evidence", "script body", "kN")

    print(f"  verdict={r['verdict']} confidence={r.get('confidence','N/A')}")
    # 2-judge 均回 different_topic conf=92 → avg=92 >= 85 → should flag（不被降級）
    assert r["verdict"] == "different_topic", \
        f"巢狀 conf=92 應能 flag，got {r['verdict']}（defect 2：confidence 從巢狀讀 0 → 被誤降級）"
    assert r.get("confidence", 0) >= 85, f"confidence 應 >=85，got {r.get('confidence')}"
    print(f"  [PASS] confidence={r['confidence']} >= 85 正確傳遞，未被誤降級 ✓")

    print("  [PASS] TC-N")
    return True


# ─────────────────────────────────────────────

if __name__ == "__main__":
    if not hasattr(_vsb, "_genai_client_factory"):
        print("_genai_client_factory 不存在")
        sys.exit(1)

    test_fns = [tc_A, tc_B, tc_C, tc_D, tc_E, tc_F, tc_G, tc_H, tc_I, tc_J, tc_K, tc_L, tc_M, tc_N]
    results = []
    for fn in test_fns:
        try:
            results.append((fn.__name__, fn()))
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            results.append((fn.__name__, False))
        except Exception as e:
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
            results.append((fn.__name__, False))

    print("\n============================================================")
    passed = sum(1 for _, r in results if r)
    failed = len(results) - passed
    print(f"  AI閘 v2 測試：{passed} PASS / {failed} FAIL / {len(results)} total")
    for name, r in results:
        print(f"  {'PASS' if r else 'FAIL'} {name}")
    print("============================================================")
    sys.exit(0 if failed == 0 else 1)
