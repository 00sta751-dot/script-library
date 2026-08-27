#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chxp_registry.py — 陳修平 128 條方法總登記冊的**唯一讀取層**（cxp-enforce-t2 梯 2）

得標定稿骨架＝Codex R1「registry 全登記 + C-CXP-COVERAGE + chxp_receipt 結構層」，
嫁接件＝【愛馬仕】registry 版本遷移緩衝、【龍蝦】兩段式判定 + conditional 機器重算、
【霸告】registry owner 落人。

本模組只做四件事（**零語意品質判斷**，澤君 TG19810 紅線）：
  1. 載入 registry（no-dup 嚴格 loader；壞檔 fail-closed 回錯誤，不回半套資料）
  2. 版本緩衝比對（差一版＝WARN／差兩版以上或格式非法＝FAIL）
  3. 依 registry 的 gate 規則，對一支稿**機器重算** applicable_ids（不看稿內宣告）
  4. 解析 receipt 的證據指標（path: / quote:）能不能解回稿內位置

刻意**不**做：判斷方法用得好不好、內容是否有趣、文字是否自然。
那些屬創作軌，交人工評審；本模組只驗「選了什麼／欄位在不在／證據解不解得回」。

被誰用：
  - validate_script_batch.py（C-CXP-COVERAGE／C-CXP-RECEIPT／C-CXP-0xx 八個閘）
  - yaml_skeleton_generator.py（產 chxp_receipt 骨架欄）
兩邊共用同一份規則 → 不可能分岔（同 T1 F1「單一真源」教訓）。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

import yaml

# ════════════════════════════════════════════════════════════════════
# 版本緩衝（愛馬仕嫁接件：防 registry 單點故障）
# ════════════════════════════════════════════════════════════════════
# 程式端期望的 registry 版本。registry 改一條正典 → 由 owner（霸告）bump
# registry_version，並在下一梯把這個常數同步。兩者：
#   相同                     → OK
#   差一版（registry 宣告的 previous_version 命中本常數，或反之）→ WARN（grace）
#   其餘不符 / 版本欄缺 / 型別非法 → FAIL
# 🔴 設計理由：不得因「改一條方法」就讓所有批次整批 FAIL（改正典＝日常維護，
#    不是事故）。grace window 給一個版本的時間讓程式端跟上。
_REGISTRY_VERSION_EXPECTED = "chxp-128-v1"

# 條目總數硬驗：陳修平方法對照表就是 128 條。
# 只驗連號擋不住「從尾端砍條目」（127 條照樣連號），故總數另立一條硬驗。
_REGISTRY_EXPECTED_COUNT = 128

# ════════════════════════════════════════════════════════════════════
# 正典硬斷言常數（r3／H1①：Codex 終審阻擋 1 — COVERAGE 鎖不住 registry）
# ════════════════════════════════════════════════════════════════════
# 🔴 這些期望值**寫在程式端**，不是讀 registry 自己宣告的 layer_counts。
#    理由（Codex 唯讀記憶體變造實測）：只信 registry 自報，就等於讓被驗的人
#    自己填分數——把一條 excluded 改成 audited（34→33）、把 #041 的 layer 從
#    gate 改成 none（硬閘 8→7）、把 #058 從 blocked_entry 改成 none，
#    三種變造在 r1 全部 COVERAGE PASS。改成程式端硬斷言後三種全翻 FAIL。
#    正典要改分層＝改這裡的常數＋bump registry_version（版本流程一部分）。
# p4exec1 C 區收刀（2026-08-27，澤君殺單 rules_kill_manifest #34-41）：
#   八條 gate（#041/053/055/064/068/069/101/103）判定為殭屍閘（registry 自標
#   「現況: 沒做」＝條件觸發從未命中），整組降 layer: none、gate 規則區塊移除。
#   條目**留在冊**（128 條不變、mode 分佈不變）——退場的是「機器硬閘」這個身分，
#   不是方法本身。故 gate 8→0、none 111→119；excluded 34 與 mode 各類計數零變。
_EXPECTED_LAYER_COUNTS: dict[str, int] = {
    "gate": 0, "receipt": 5, "manual": 3, "blocked_entry": 1, "none": 119,
}
_EXPECTED_EXCLUDED_COUNT = 34
# p4exec1 C 區收刀：原 ("041","053","055","064","068","069","101","103") 全數退場。
# 空 tuple ＝「本層現在零條目」的硬斷言——任何一條偷偷升回 gate 都會被 assert_canon 抓到
# （layer=gate 實際 1 條 ≠ 硬斷言 0 條）。要重新立閘＝改這裡＋bump registry_version。
_EXPECTED_GATE_IDS: tuple[str, ...] = ()
_EXPECTED_RECEIPT_IDS = ("018", "027", "028", "043", "080")
_EXPECTED_MANUAL_IDS = ("021", "022", "109")
_EXPECTED_BLOCKED_IDS = ("058",)
# r4／J3：mode 也是身分維度（layer 之外）。Codex r3 新問題「always／audited 或
# excluded 身分等量互換亦能通過」——只硬斷言 layer 與 excluded 總數擋不住
# 「#010 由 always 降 audited、另一條 audited 升 always」。故 mode 逐類硬斷言。
_EXPECTED_MODE_COUNTS: dict[str, int] = {
    "excluded": 34, "always": 11, "outside": 5, "conditional": 60, "audited": 18,
}
_EXPECTED_ALWAYS_IDS = ("010", "011", "012", "013", "014", "017",
                        "020", "023", "076", "078", "079")

# registry 內容 hash 錨（H1③）：sidecar 檔，內容＝正式 registry yaml 的 sha256。
# 不符＝FAIL。**更新 registry 必須同步重算 sidecar**（版本流程的一部分，
# 與 bump registry_version 同時做）。
# r4／J3：sidecar 再加第二行 `id_mode_map_sha256: <sha256>`＝**條目 id↔mode↔layer
# 映射**的 hash。理由（Codex r3 新問題）：整檔 hash 只要重算就過，
# 「always／audited 或 excluded 身分等量互換」在整檔 hash 重算後照樣成立；
# 身分映射另立一道錨，換身分＝映射 hash 不符＝FAIL。
_REGISTRY_SHA_SIDECAR_NAME = "chxp_method_registry.sha256"
_ID_MODE_MAP_SIDECAR_KEY = "id_mode_map_sha256"

# r6／L3：sidecar 那把鍵的**單一分詞真源**——重複鍵計數與實際取值必須用同一套
# 空白定義，否則「計數看不見、取值看得見」的字元（U+00A0 NBSP、U+3000 全形空格…）
# 就能繞過重複鍵拒載。兩個 regex 共用 `_WS`＝「除換行外的所有 Unicode 空白」
# （`[^\S\n]`：\S 取補集＝全部空白，再扣掉 \n，才不會讓 `\s*` 跨行吃掉整行），
# 差別只在「認不認值的格式」。
_WS = r"[^\S\n]"
_ID_MODE_MAP_KEY_RE = re.compile(
    rf"(?m)^{_WS}*{_ID_MODE_MAP_SIDECAR_KEY}{_WS}*:.*$"
)
_ID_MODE_MAP_VAL_RE = re.compile(
    rf"(?m)^{_WS}*{_ID_MODE_MAP_SIDECAR_KEY}{_WS}*:{_WS}*([0-9a-fA-F]{{64}}){_WS}*$"
)

# r4／J3：**已註冊的 check_id 集合**（程式端常數）。
# 理由（Codex r3 新問題）：r3 的 gate schema 只驗 `C-CXP-<三位數>` 格式，
# 把 #041 的 check_id 改成 `C-CXP-999` 照樣 COVERAGE PASS——那條閘會用一個
# 沒人認得的 id 出現在報表，等於「閘還在但改名換姓」。現在 check_id 必須：
#   ① 在本集合內（未知＝FAIL）② 等於 `C-CXP-<該條目自己的 id>`（張冠李戴＝FAIL）
_REGISTERED_GATE_CHECK_IDS = tuple(f"C-CXP-{mid}" for mid in _EXPECTED_GATE_IDS)
# p4exec1 C 區收刀（2026-08-27）：C-CXP-COVERAGE 隨 128 條登記冊硬閘一併退場
# （殺單 #42），故從已註冊 batch check 集合移除。RECEIPT 與 GATES 留任。
_REGISTERED_BATCH_CHECK_IDS = ("C-CXP-RECEIPT", "C-CXP-GATES")
_REGISTERED_CHECK_IDS = _REGISTERED_GATE_CHECK_IDS + _REGISTERED_BATCH_CHECK_IDS

_REGISTRY_PATH = Path(__file__).resolve().parent / "chxp_method_registry.yaml"

# 快取：(registry_dict_or_None, error_or_None)
_REGISTRY_CACHE: Optional[tuple[Optional[dict], Optional[str]]] = None


class RegistryDuplicateKeyError(yaml.YAMLError):
    """registry YAML 內出現重複鍵（同 allowlist 的 no-dup 防線，T1 r3 教訓）。"""


class _NoDupLoader(yaml.SafeLoader):
    """SafeLoader ＋ 拒絕**任一層級**重複鍵。

    T1 r3 已證實：PyYAML 預設「同名鍵取最後一個」＝可被無聲覆蓋的旁路
    （在 allowlist 上實測 0/33 → 33/33 的翻轉）。registry 是全系統方法真源，
    同一個旁路在這裡的後果更大（偷改一條 mode 就能讓硬閘消失），故照樣封。
    """

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, _ in node.value:
                try:
                    key = self.construct_object(key_node, deep=deep)
                except Exception:
                    key = getattr(key_node, "value", None)
                try:
                    hash(key)
                    hashable = key
                except TypeError:
                    hashable = repr(key)
                if hashable in seen:
                    raise RegistryDuplicateKeyError(f"重複鍵 {key!r}（{node.start_mark}）")
                seen.add(hashable)
        return super().construct_mapping(node, deep=deep)


_VALID_MODES = ("always", "conditional", "audited", "outside", "excluded")
_VALID_LAYERS = ("gate", "receipt", "manual", "blocked_entry", "none")


def load_registry(force_reload: bool = False,
                  path: Optional[Path] = None) -> tuple[Optional[dict], Optional[str]]:
    """讀 chxp_method_registry.yaml → (registry dict, 錯誤訊息)。

    **fail-closed 契約**：檔案不存在／YAML 壞／重複鍵／schema 不符／條目數不足
    → 回 (None, 錯誤訊息)。呼叫端據此對**新世代批**打 FAIL（不是放行）。
    schema 驗（只驗結構，不驗語意）：
      頂層 dict，含 registry_version(str)、methods(list)；
      每條含 id(str, 3 位數字)、mode ∈ 五合法值、layer ∈ 五合法值；
      id 必須 001-128 連號無缺（Codex R1「漏登＝FAIL」）。
    """
    global _REGISTRY_CACHE
    if path is None and _REGISTRY_CACHE is not None and not force_reload:
        return _REGISTRY_CACHE
    target = path or _REGISTRY_PATH
    result: tuple[Optional[dict], Optional[str]]
    try:
        if not target.exists():
            result = (None, f"registry 檔案不存在（{target.name}）")
        else:
            raw = yaml.load(target.read_text(encoding="utf-8"), Loader=_NoDupLoader)
            err = _validate_registry_shape(raw)
            result = (None, err) if err else (raw, None)
    except Exception as e:  # 讀檔/解析任何異常 → fail-closed
        result = (None, f"registry 讀取異常（{type(e).__name__}: {e}）")
    if path is None:
        _REGISTRY_CACHE = result
    return result


def _validate_registry_shape(raw: Any) -> Optional[str]:
    """只驗結構。回錯誤字串或 None。"""
    if not isinstance(raw, dict):
        return "registry 頂層結構非 dict"
    if not isinstance(raw.get("registry_version"), str) or not raw["registry_version"].strip():
        return "registry 缺 registry_version（或型別非字串）"
    methods = raw.get("methods")
    if not isinstance(methods, list) or not methods:
        return "registry 缺 methods 清單（或型別非 list）"
    ids: list[str] = []
    for i, m in enumerate(methods):
        if not isinstance(m, dict):
            return f"registry 第 {i + 1} 條非 mapping"
        mid = m.get("id")
        if not isinstance(mid, str) or not re.fullmatch(r"\d{3}", mid):
            return f"registry 第 {i + 1} 條 id 非三位數字字串（得到 {mid!r}）"
        if m.get("mode") not in _VALID_MODES:
            return f"registry #{mid} mode 缺漏或非法（得到 {m.get('mode')!r}，合法：{list(_VALID_MODES)}）"
        if m.get("layer") not in _VALID_LAYERS:
            return f"registry #{mid} layer 缺漏或非法（得到 {m.get('layer')!r}）"
        ids.append(mid)
    expect = [f"{i:03d}" for i in range(1, len(ids) + 1)]
    if ids != expect:
        missing = sorted(set(expect) - set(ids))
        dup = sorted({x for x in ids if ids.count(x) > 1})
        return (f"registry id 非 001-{len(ids):03d} 連號"
                f"（缺：{missing[:6]}；重複：{dup[:6]}）")
    # 🔴 條目總數硬驗（F-CXP-T2-B-b 抓到的漏洞）：
    #    只驗「連號」擋不住「從尾端砍掉幾條」——127 條照樣 001-127 連號。
    #    陳修平方法表就是 128 條，少一條＝漏登＝FAIL（Codex R1 骨架原文）。
    if len(ids) != _REGISTRY_EXPECTED_COUNT:
        return (f"registry 條目數 {len(ids)}，應為 {_REGISTRY_EXPECTED_COUNT} 條"
                f"（漏登／多登皆 FAIL；從尾端砍條目也擋得住）")
    return None


def check_version(registry: dict) -> tuple[str, str]:
    """版本緩衝比對 → (status, detail)。status ∈ PASS/WARN/FAIL。

    r3／H1④：改成**真實版本鏈**判定（Codex 阻擋 1 實測：r1 只看
    `registry.previous_version == 期望` 一個字串等號，導致
    `current=totally-unrelated / previous=chxp-128-v1` 被判「差一版 WARN」——
    任何亂填的版本只要附上一個正確的 previous 就能矇混）。

    現行規則（雙向 grace，只認相鄰一版）：
      ① current == 程式端期望                         → PASS
      ② current 合法且 family 相同、序號 = 期望+1，
         且 registry.previous_version == 程式端期望   → WARN（registry 前進一版）
      ③ current 合法且 family 相同、序號 = 期望-1     → WARN（registry 落後一版）
      ④ 其餘（格式非法／family 不同／差兩版以上／
         前進一版但版本鏈斷）                          → FAIL
    版本字串合法格式：`<family>-v<正整數>`，family 為 `字母數字-數字`，
    例 `chxp-128-v1`；可帶後綴（`chxp-128-v1-draft`）但後綴不參與相鄰判定。
    """
    cur = registry.get("registry_version")
    prev = registry.get("previous_version")
    if not isinstance(cur, str) or not cur.strip():
        return "FAIL", "registry_version 缺或型別非法"
    cur = cur.strip()
    if cur == _REGISTRY_VERSION_EXPECTED:
        return "PASS", f"registry_version={cur}（與程式端期望一致）"

    cur_parsed = parse_registry_version(cur)
    exp_parsed = parse_registry_version(_REGISTRY_VERSION_EXPECTED)
    owner = registry.get("registry_owner", "未指定")
    if cur_parsed is None or exp_parsed is None:
        return "FAIL", (
            f"registry_version={cur!r} 非合法版本字串（須為 <family>-v<N>，"
            f"例 chxp-128-v1）——版本鏈無從判定，不得走 grace window"
        )
    cur_fam, cur_n, _ = cur_parsed
    exp_fam, exp_n, _ = exp_parsed
    if cur_fam != exp_fam:
        return "FAIL", (
            f"registry_version={cur}，程式端期望 {_REGISTRY_VERSION_EXPECTED}——"
            f"version family 不同（{cur_fam} vs {exp_fam}），**不是相鄰版本**，"
            f"不適用 grace window"
        )
    if cur_n == exp_n + 1:
        # registry 前進一版：版本鏈必須接得上（它的 previous 就是我期望的那版）
        prev_parsed = parse_registry_version(prev) if isinstance(prev, str) else None
        if prev_parsed is not None and prev_parsed[:2] == exp_parsed[:2]:
            return "WARN", (
                f"registry_version={cur}，程式端期望 {_REGISTRY_VERSION_EXPECTED}——"
                f"**registry 前進一版，版本鏈接得上（previous_version={prev}），走 grace window"
                f"（仍照驗內容，不擋批）**；請 registry owner（{owner}）與施工者同步後續版本，"
                f"隔版仍不符即 FAIL"
            )
        return "FAIL", (
            f"registry_version={cur} 雖為期望的下一版，但 previous_version={prev!r} "
            f"接不回 {_REGISTRY_VERSION_EXPECTED}——**版本鏈斷裂**，不得走 grace window"
        )
    if cur_n == exp_n - 1:
        return "WARN", (
            f"registry_version={cur}，程式端期望 {_REGISTRY_VERSION_EXPECTED}——"
            f"**registry 落後一版（程式端已先行），走 grace window（仍照驗內容，不擋批）**；"
            f"請 registry owner（{owner}）補上同版 registry，隔版仍不符即 FAIL"
        )
    return "FAIL", (
        f"registry_version={cur}，程式端期望 {_REGISTRY_VERSION_EXPECTED}，"
        f"序號差 {abs(cur_n - exp_n)} 版（registry.previous_version={prev!r}）——已超出 grace window"
    )


# 版本字串：<family>-v<N>[-後綴]；family＝字母數字段＋「-數字」（例 chxp-128）
_VERSION_RE = re.compile(r"^(?P<fam>[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*?)-v(?P<n>\d+)(?:-(?P<suffix>.+))?$")


def parse_registry_version(v: Any) -> Optional[tuple[str, int, str]]:
    """解析版本字串 → (family, 序號, 後綴)；格式非法回 None。

    r3／H1④：版本必須可解析成「家族＋序號」才談得上「相鄰」。
    亂填字串（`totally-unrelated`、`garbage`）一律解析失敗＝FAIL，
    不得因為附了一個看起來對的 previous_version 就被當成差一版。
    """
    if not isinstance(v, str) or not v.strip():
        return None
    m = _VERSION_RE.match(v.strip())
    if not m:
        return None
    return m.group("fam"), int(m.group("n")), (m.group("suffix") or "")


# ════════════════════════════════════════════════════════════════════
# 正典硬斷言（r3／H1①②③：Codex 終審阻擋 1）
# ════════════════════════════════════════════════════════════════════

def assert_canon(registry: dict) -> list[str]:
    """對 registry 現值做**硬斷言**，回傳問題清單（空 list＝全過）。

    驗三件事（全結構性、零語意判斷）：
      ① 分層計數：硬閘 8／receipt 5／人工 3／BLOCKED 1／none 111／
         excluded 34／總 128 —— 任一不符＝FAIL，且**具名 id 也要對**
         （只驗數量擋不住「把 #041 降級、另抓一條升級」的等量替換）。
      ② 每條 gate 的 schema 結構驗證（見 _validate_gate_schema）。
      ③ 計數來源＝**程式端常數**，不是 registry 自報的 layer_counts；
         registry 若自報 layer_counts 且與實際不符，另記一條（自報不實）。
    """
    problems: list[str] = []
    methods = registry.get("methods", [])
    if len(methods) != _REGISTRY_EXPECTED_COUNT:
        problems.append(f"條目總數 {len(methods)}，應為 {_REGISTRY_EXPECTED_COUNT}")

    layer_ids: dict[str, list[str]] = {}
    for m in methods:
        if not isinstance(m, dict):
            continue
        layer_ids.setdefault(str(m.get("layer")), []).append(str(m.get("id")))

    # ① 分層計數硬斷言
    for layer, expect_n in _EXPECTED_LAYER_COUNTS.items():
        got = layer_ids.get(layer, [])
        if len(got) != expect_n:
            problems.append(
                f"layer={layer} 實際 {len(got)} 條，硬斷言應為 {expect_n} 條"
                f"（現值 {sorted(got)[:10]}）"
            )
    excluded_ids = [str(m.get("id")) for m in methods
                    if isinstance(m, dict) and m.get("mode") == "excluded"]
    if len(excluded_ids) != _EXPECTED_EXCLUDED_COUNT:
        problems.append(
            f"excluded 實際 {len(excluded_ids)} 條，硬斷言應為 {_EXPECTED_EXCLUDED_COUNT} 條"
            f"（34 條「刻意不做」不准消失）"
        )

    # ①b 具名 id 硬斷言（防等量替換）
    for layer, expect_ids in (("gate", _EXPECTED_GATE_IDS),
                              ("receipt", _EXPECTED_RECEIPT_IDS),
                              ("manual", _EXPECTED_MANUAL_IDS),
                              ("blocked_entry", _EXPECTED_BLOCKED_IDS)):
        got = sorted(layer_ids.get(layer, []))
        if got != sorted(expect_ids):
            missing = sorted(set(expect_ids) - set(got))
            extra = sorted(set(got) - set(expect_ids))
            problems.append(
                f"layer={layer} 具名 id 不符硬斷言（缺 {missing}；多 {extra}）"
            )

    # ② gate schema 結構驗證
    by_id = {str(m.get("id")): m for m in methods if isinstance(m, dict)}
    for mid in _EXPECTED_GATE_IDS:
        m = by_id.get(mid)
        if not isinstance(m, dict):
            problems.append(f"#{mid} 不在冊（硬閘條目消失）")
            continue
        if m.get("layer") != "gate":
            problems.append(f"#{mid} layer={m.get('layer')!r}，硬斷言應為 gate")
            continue
        problems.extend(f"#{mid} {e}" for e in _validate_gate_schema(m.get("gate"), mid))

    # ②b r4／J3：mode 分層計數硬斷言（layer 已驗，mode 是另一個身分維度）
    #     Codex r3 新問題：「always／audited 或 excluded 身分等量互換亦能通過」——
    #     r3 只硬斷言 excluded 總數與各 layer，把 #010 由 always 改 audited、
    #     另一條 audited 改 always，兩個計數都不動。故 mode 也逐類硬斷言。
    mode_ids: dict[str, list[str]] = {}
    for m in methods:
        if isinstance(m, dict):
            mode_ids.setdefault(str(m.get("mode")), []).append(str(m.get("id")))
    for mode, expect_n in _EXPECTED_MODE_COUNTS.items():
        got_n = len(mode_ids.get(mode, []))
        if got_n != expect_n:
            problems.append(f"mode={mode} 實際 {got_n} 條，硬斷言應為 {expect_n} 條")
    got_always = sorted(mode_ids.get("always", []))
    if got_always != sorted(_EXPECTED_ALWAYS_IDS):
        problems.append(
            f"mode=always 具名 id 不符硬斷言"
            f"（缺 {sorted(set(_EXPECTED_ALWAYS_IDS) - set(got_always))}；"
            f"多 {sorted(set(got_always) - set(_EXPECTED_ALWAYS_IDS))}）——"
            f"11 條「一律適用」不准被換人"
        )

    # ③ registry 自報 layer_counts 與實際對照（自報不實也要抓）
    declared = registry.get("layer_counts")
    if isinstance(declared, dict):
        actual = {k: len(v) for k, v in layer_ids.items()}
        mismatch = {k: (declared.get(k), actual.get(k, 0))
                    for k in set(declared) | set(_EXPECTED_LAYER_COUNTS)
                    if declared.get(k) != actual.get(k, 0)}
        if mismatch:
            problems.append(f"registry 自報 layer_counts 與實際不符（宣告 vs 實際）：{mismatch}")
    return problems


_GATE_TRIGGER_KINDS = ("enum", "bool_true", "duration_60s")


def _validate_gate_schema(gate: Any, method_id: Optional[str] = None) -> list[str]:
    """單一 gate 規則的結構驗證（H1②＋r4／J3 收緊）。回問題清單。

    要求：
      - gate 為 mapping，check_id **必須在已註冊集合內**且等於
        `C-CXP-<本條目 id>`（r4／J3：未知 id＝FAIL、張冠李戴＝FAIL）
      - trigger 為 mapping，kind ∈ 三種合法值
      - kind=enum → 須有 field(str) 與非空 enum(list of str)
      - kind=bool_true → 須有 field(str)
      - kind=duration_60s → 不需 field
      - require_fields（若有）須為 list of 非空 str；**空 list＝FAIL**
        （r4／J3：硬閘寫 `require_fields: []` ＝ 無欄可驗，等於閘還掛著但
        什麼都不驗——Codex 實測「缺段落安排的稿照樣 gate PASS」就是這條）
      - **每條硬閘至少要有一項實質驗法**：非空 require_fields ／
        require_evidence=true ／ kind=char_count，三者全無＝無效條目＝FAIL
      - require_evidence（若有）須為 bool
      - kind=char_count（gate 層）→ char_count.min/max 須為 int 且 min<=max
    """
    out: list[str] = []
    if not isinstance(gate, dict):
        return ["gate 規則缺漏或非 mapping"]
    cid = gate.get("check_id")
    if not isinstance(cid, str) or not re.fullmatch(r"C-CXP-\d{3}", cid):
        out.append(f"gate.check_id 格式非法（得到 {cid!r}，須為 C-CXP-<三位數>）")
    elif cid not in _REGISTERED_CHECK_IDS:
        out.append(
            f"gate.check_id={cid} **不在已註冊 check_id 集合**"
            f"（合法：{list(_REGISTERED_GATE_CHECK_IDS)}）——"
            f"改名換姓的閘等於無人認得，不得放行"
        )
    elif method_id is not None and cid != f"C-CXP-{method_id}":
        out.append(
            f"gate.check_id={cid} 與條目 id #{method_id} 不對應"
            f"（應為 C-CXP-{method_id}）——check_id 張冠李戴"
        )
    trig = gate.get("trigger")
    if not isinstance(trig, dict):
        out.append("gate.trigger 缺漏或非 mapping")
    else:
        kind = trig.get("kind")
        if kind not in _GATE_TRIGGER_KINDS:
            out.append(f"gate.trigger.kind 非法（得到 {kind!r}，合法：{list(_GATE_TRIGGER_KINDS)}）")
        elif kind in ("enum", "bool_true"):
            fld = trig.get("field")
            if not isinstance(fld, str) or not fld.strip():
                out.append(f"gate.trigger.field 缺漏或非字串（kind={kind}）")
            if kind == "enum":
                allowed = trig.get("enum")
                if (not isinstance(allowed, list) or not allowed
                        or not all(isinstance(x, str) and x.strip() for x in allowed)):
                    out.append("gate.trigger.enum 須為非空的字串清單")
    rf = gate.get("require_fields")
    if rf is not None:
        if not isinstance(rf, list):
            out.append(f"gate.require_fields 型別非 list（得到 {type(rf).__name__}）")
        elif not rf:
            out.append(
                "gate.require_fields 是**空列表**——硬閘無欄可驗＝無效條目"
                "（要取消必填欄請整個拿掉本鍵並保留其他驗法，不得留空殼）"
            )
        elif not all(isinstance(x, str) and x.strip() for x in rf):
            out.append("gate.require_fields 須為非空字串清單")
    re_ = gate.get("require_evidence")
    if re_ is not None and not isinstance(re_, bool):
        out.append(f"gate.require_evidence 須為 bool（得到 {type(re_).__name__}）")
    if gate.get("kind") == "char_count":
        rng = gate.get("char_count")
        if not isinstance(rng, dict):
            out.append("gate.char_count 缺漏或非 mapping")
        else:
            lo, hi = rng.get("min"), rng.get("max")
            if type(lo) is not int or type(hi) is not int or lo > hi or lo < 0:
                out.append(f"gate.char_count 區間非法（min={lo!r}, max={hi!r}）")
    # r4／J3：硬閘至少要有一項實質驗法，否則掛著也驗不到任何東西
    has_fields = isinstance(rf, list) and bool(rf)
    if not (has_fields or re_ is True or gate.get("kind") == "char_count"):
        out.append(
            "本硬閘沒有任何實質驗法（require_fields 空／無、require_evidence 非 true、"
            "亦非 char_count 型）——**硬閘無欄可驗＝無效條目**"
        )
    return out


def id_mode_map_sha256(registry: dict) -> str:
    """算「條目 id↔mode↔layer 映射」的 sha256（r4／J3 身分錨）。

    定義（機械可重算）：把每條的 `<id>:<mode>:<layer>` 排序後以 `\\n` 接起來，
    取 sha256。**只涵蓋身分欄**——改註解、改名稱、改適用條件都不影響本值，
    但把 #010 從 always 改成 audited、或把 excluded 換成別條，值就會變。
    重算指令：`python3 chxp_registry.py --sha`（會一併印出本值）。
    """
    lines = sorted(
        f"{m.get('id')}:{m.get('mode')}:{m.get('layer')}"
        for m in registry.get("methods", []) if isinstance(m, dict)
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def check_id_mode_map(registry: dict, path: Optional[Path] = None) -> tuple[str, str]:
    """身分映射錨比對（r4／J3）→ (status, detail)，status ∈ PASS/FAIL。

    sidecar 第二行 `id_mode_map_sha256: <64 hex>`。缺／格式非法／不符皆 FAIL。
    r5／K4（Codex r4 新問題）：**同一個鍵出現多次＝拒載 FAIL**（不再只取第一條）。
      sidecar 若同時寫著兩個互相矛盾的 `id_mode_map_sha256`，「取第一條」等於
      讓寫檔的人自己挑要哪個答案——身分錨的意義就沒了。這與 registry 本體的
      no-dup loader 慣例一致（重複鍵＝壞檔，fail-closed，不猜）。
      註：格式非法的重複行也算——先數**所有** `id_mode_map_sha256:` 開頭的行，
      >1 就拒，避免「一行合法＋一行垃圾」被當成只有一條。
    🔴 這道錨補的是整檔 hash 的盲區：Codex r3 實測「always／audited 或
       excluded 身分等量互換」——只要改完 registry 順手重算整檔 sidecar，
       整檔 hash 就對得上；身分映射另存一值，等量互換照樣翻紅。
    """
    target = path or _REGISTRY_PATH
    side = target.parent / _REGISTRY_SHA_SIDECAR_NAME
    actual = id_mode_map_sha256(registry)
    if not side.exists():
        return "FAIL", (
            f"id↔mode 映射錨 sidecar 不存在（{side.name}）——"
            f"條目身分未被錨定；請重算：python3 chxp_registry.py --sha > {side.name}"
        )
    try:
        raw = side.read_text(encoding="utf-8")
    except Exception as e:
        return "FAIL", f"id↔mode 映射錨 sidecar 讀取異常（{type(e).__name__}: {e}）"
    # r5／K4：先數重複鍵（含格式非法的行），任何重複一律拒載
    # r6／L3：計數與取值**統一同一套分詞**——兩者都認 `\s`（含 NBSP／全形空格等
    #   非 ASCII 空白）。r5 的計數只認 `[ \t]`、取值卻用 `\s*`，於是第二鍵前放
    #   一個 U+00A0 就「計數看不見、取值看得見」，重複鍵拒載被繞過。
    key_lines = _ID_MODE_MAP_KEY_RE.findall(raw)
    if len(key_lines) > 1:
        return "FAIL", (
            f"sidecar 出現 {len(key_lines)} 條 `{_ID_MODE_MAP_SIDECAR_KEY}`——"
            f"重複鍵＝身分錨歧義，**拒載（fail-closed，不取第一條）**；"
            f"請重算成唯一一行：python3 chxp_registry.py --sha > {side.name}"
        )
    m = _ID_MODE_MAP_VAL_RE.search(raw)
    if not m:
        return "FAIL", (
            f"sidecar 缺 `{_ID_MODE_MAP_SIDECAR_KEY}: <sha256>` 行（或格式非法）——"
            f"條目 id↔mode↔layer 映射未錨定，身分等量互換驗不出來"
        )
    expect = m.group(1).lower()
    if expect != actual:
        return "FAIL", (
            f"條目 id↔mode↔layer 映射 hash 不符錨定值——sidecar={expect[:12]}…，"
            f"實際={actual[:12]}…；有條目被換了身分（mode／layer 互換）但未走版本流程"
        )
    return "PASS", f"id↔mode 映射 hash 與錨定值相符（{actual[:12]}…）"


def registry_file_sha256(path: Optional[Path] = None) -> Optional[str]:
    """算正式 registry 檔的 sha256（讀不到回 None）。"""
    target = path or _REGISTRY_PATH
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except Exception:
        return None


def check_registry_hash(path: Optional[Path] = None) -> tuple[str, str]:
    """registry 內容 hash 錨定（H1③）→ (status, detail)，status ∈ PASS/FAIL。

    sidecar `chxp_method_registry.sha256` 內容＝正式 registry yaml 的 sha256
    （允許 `<hash>  <檔名>` 的 shasum 格式，取第一段）。
      sidecar 缺／格式非法／hash 不符 → FAIL（fail-closed）。
    🔴 **更新 registry 必須同步重算 sidecar**——這是版本流程的一部分：
       改條目 → bump registry_version → 重算 sidecar → 同步程式端期望常數。
    """
    target = path or _REGISTRY_PATH
    side = target.parent / _REGISTRY_SHA_SIDECAR_NAME
    actual = registry_file_sha256(target)
    if actual is None:
        return "FAIL", f"registry 檔讀不到，無從算 hash（{target.name}）"
    if not side.exists():
        return "FAIL", (
            f"registry hash 錨 sidecar 不存在（{side.name}）——"
            f"registry 內容未被錨定，任何人改內容都驗不出來；"
            f"請重算：shasum -a 256 {target.name} > {side.name}"
        )
    try:
        raw = side.read_text(encoding="utf-8").strip()
    except Exception as e:
        return "FAIL", f"registry hash sidecar 讀取異常（{type(e).__name__}: {e}）"
    expect = raw.split()[0].lower() if raw.split() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", expect):
        return "FAIL", f"registry hash sidecar 內容非合法 sha256（{raw[:40]!r}）"
    if expect != actual:
        return "FAIL", (
            f"registry 內容 hash 不符錨定值——sidecar={expect[:12]}…，"
            f"實際={actual[:12]}…；registry 已被改動但未走版本流程"
            f"（改條目須 bump registry_version＋重算 sidecar）"
        )
    return "PASS", f"registry 內容 hash 與錨定值相符（{actual[:12]}…）"



# ════════════════════════════════════════════════════════════════════
# gate 規則的**泛用執行器**（規則資料在 registry，程式不硬編任何一條方法）
# ════════════════════════════════════════════════════════════════════

def iter_gates(registry: dict) -> list[dict]:
    """回傳所有 layer=gate 的條目（含 gate 規則）。順序＝registry 順序。"""
    out = []
    for m in registry.get("methods", []):
        if m.get("layer") == "gate" and isinstance(m.get("gate"), dict):
            out.append(m)
    return out


def get_field(data: dict, dotted: str) -> Any:
    """用 'a.b.c' 取巢狀值；任一層不是 dict 或不存在 → None。

    註：registry 的欄位路徑刻意只用「點分隔的 mapping 路徑」，
    不支援索引／萬用字元——路徑語法越簡單，越不會被寫成隱形的語意判斷。
    """
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# r5／K2：不可見字元清洗（單一真源，供 is_nonempty_text 與所有「有沒有填」判定用）
#   刪除對象＝**零寬與格式控制字元**：Cf（U+200B/200C/200D/FEFF/200E/200F/2060/
#   00AD…）與 Cc（\x00-\x1f、\x7f-\x9f，但保留 \t\n\r）。
# r6／L4：**改為純 Unicode 類別法，加收 Mn（非間距組合標記）**。Codex r5 新問題：
#   r5 的「類別集合＋顯式碼點清單」漏了 U+034F（COMBINING GRAPHEME JOINER，
#   類別 Mn）——它不在清單裡、類別也不是 Cf/Cc，於是「一個看不見的組合標記」
#   又變成「寫了一句話」。逐字元列舉本質上永遠追不完，所以廢掉清單、
#   改成**移除全部 Cf/Cc/Mn 類**（顯式清單只留作註解說明，不再是判定依據）。
#   ⚠️ **不刪 Zs 類空白**（一般空格、U+00A0、U+3000…）：那些 Python 的 str.strip()
#      本來就會從頭尾去掉（`'\xa0'.isspace()` 為真），而字串**中間**的空白是
#      可見排版的一部分，刪掉等於竄改編劇寫的內容。K2h fixture 就是鎖這件事。
#   ⚠️ Mn 的代價（明講）：注音符號的聲調、越南文／泰文的附加符號屬 Mn 類，
#      若某天要驗的欄位是「只有一個聲調符號」，會被判成沒填。正典全中文，
#      現況零影響；而讓「看不見的字元＝有填」通過的風險嚴重得多，故取 fail-closed。
#   全部處理完之後若字串為空 → 這欄等於沒填。
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Cc", "Mn"})
_INVISIBLE_KEEP = frozenset("\t\n\r")
# r5 遺留的顯式碼點清單——r6／L4 後**不再是判定依據**（類別法已全涵蓋），
# 保留純為文件用途：這些就是實務上最常被拿來冒充「有填」的碼點。
# U+115F/1160/3164/FFA0（韓文填充字元，類別 Lo）本身可見寬度為零但不屬
# Cf/Cc/Mn，故仍保留在清單並實際參與清洗，避免類別法漏掉它們。
_INVISIBLE_CODEPOINTS = frozenset(
    "\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064"
    "\ufeff\u00ad\u180e\u061c\u115f\u1160\u3164\uffa0\u034f"
)


def strip_invisible_keep_layout(s: str) -> str:
    """移除不可見／零寬字元，但**保留頭尾空白**（r6／L4）。

    給「稿內文字比對」用（quote: 證據的 haystack）：清洗後才能讓
    「證據字串」與「稿內文字」在同一個基準上比對——否則編劇在稿裡打了
    一個零寬字元，證據就永遠對不上；反過來，證據裡塞零寬字元也不該
    因為字面不同而被判找不到。**不 strip 頭尾**，因為 haystack 是多段
    文字串接，頭尾空白是段落邊界的一部分。
    """
    if not isinstance(s, str):
        return ""
    return "".join(
        ch for ch in s
        if ch in _INVISIBLE_KEEP
        or (ch not in _INVISIBLE_CODEPOINTS
            and unicodedata.category(ch) not in _INVISIBLE_CATEGORIES)
    )


def strip_invisible(s: str) -> str:
    """去掉頭尾空白**與所有不可見／零寬字元**，回傳清洗後的字串（r5／K2）。

    Codex r4 新問題：只含 `U+200B` 的 sources／waiver 會被當有效文字——
    `str.strip()` 只認 whitespace，零寬字元不在其列，於是「一個看不見的
    字元」＝「寫了一句話」。本函式是這件事的**單一清洗真源**。
    r6／L4：判定改為 Unicode 類別法（Cf/Cc/Mn 全刪），不再倚賴逐字元清單
    ——Codex r5 指出 U+034F（Mn）漏網，逐字元列舉本質上追不完。
    注意：只刪除零寬／格式控制／組合標記字元，**不改動任何可見內容**
    （不做正規化、不折疊空白、不刪字串中間的一般空白），因此不會把有意義
    的文字洗掉。
    """
    if not isinstance(s, str):
        return ""
    return strip_invisible_keep_layout(s).strip()


def is_nonempty_text(v: Any) -> bool:
    """**單一非空字串驗證器**（r4／J4；r5／K2 補 Unicode 清洗）——證據／理由／
    來源欄一律走這一個函式。

    回 True 的唯一條件：`v` 是字串、**去空白與不可見字元後**非空、
    且不是 `[編劇填…]` 佔位。
    明確回 False（Codex r3 新問題「空值仍可用錯誤型別繞過」）：
      None ／ False ／ True ／ 0 ／ 1 ／ 0.0 ／ 空字串 ／ 全空白 ／ 佔位字串。
    r5／K2（Codex r4 新問題）：**零寬與不可見字元清洗**——`"\\u200b"`、
      `"\\ufeff"` 這類字元 `str.strip()` 動不到（它們不是 whitespace），
      於是 `sources: ["\\u200b"]`、waiver 理由填一個零寬空格就被當成
      「有填一句話」，gate 與 receipt 全部 PASS。現在先刪除零寬／格式控制
      字元（Cf、Cc，見 strip_invisible）再 strip()，清完為空＝FAIL。
      Zs 類空白（U+00A0、U+3000…）本來就會被 str.strip() 去掉，故不另刪，
      以免把字串中間的可見排版洗掉。
      註：U+200B 的 Unicode 分類歷史上曾是 Zs、自 Unicode 4.0.1 起改為 Cf，
      不同執行環境未必一致；故本函式**不倚賴單一類別**，改用「類別集合＋
      顯式碼點清單」雙保險，避免版本差異造成漏網。
    🔴 為什麼是「字串限定」：這些欄位（來源、理由、回憶點、同意紀錄…）
       在正典裡全是**要人寫一句話**的欄位。允許 bool／數字通過，等於
       `sources: [false]`、`waiver: {"010": false}` 就能交差——那是把
       「沒填」寫成另一種型別而已。純型別與空值檢查，不判內容品質（K0 不豁免）。
    🔴 **禁止各欄自寫判定**：任何新欄位要驗「有沒有填」，一律呼叫本函式
       （容器欄請用 _is_filled，它對每個元素也是呼叫本函式）。
    """
    if not isinstance(v, str):
        return False
    s = strip_invisible(v)
    if not s:
        return False
    return not _is_placeholder_text(s)


def _is_filled(v: Any) -> bool:
    """欄位視為「有填」：**純量走 is_nonempty_text，容器看內容**。

    r3／H3（Codex 阻擋 3）：**容器要看內容**。r1 只驗 `len(v) > 0`，
    導致 `#101 sources: [null] / [""] / ["[編劇填]"]` 三種空帳全部 PASS。
    r4／J4（Codex r3 新問題）：**純量改走單一非空字串驗證器**。r3 的
    `return True` 尾巴讓 `sources: [False]`／`[0]`／scalar `False`／`0`
    以及 11 條 waiver 理由全填 YAML `false` 都算「有填」——同一個空帳，
    換個型別就繞過去了。現在：list/tuple/set 至少要有一個元素通過
    is_nonempty_text（或本身是有內容的容器）；dict 同理看 value。
    """
    if isinstance(v, (list, tuple, set)):
        return any(_is_filled(x) for x in v)
    if isinstance(v, dict):
        return any(_is_filled(x) for x in v.values())
    return is_nonempty_text(v)



def resolve_duration_seconds(data: dict) -> Optional[int]:
    """從稿件取宣告時長（秒）。支援 duration_seconds: 60 或 duration: '60s'。

    取不到＝None（呼叫端一律當「不適用」，不猜）。
    """
    v = data.get("duration_seconds")
    if type(v) is int and v > 0:
        return v
    d = data.get("duration")
    if type(d) is int and d > 0:
        return d
    if isinstance(d, str):
        m = re.fullmatch(r"\s*(\d+)\s*(s|秒)?\s*", d)
        if m:
            n = int(m.group(1))
            return n if n > 0 else None
    return None


def gate_trigger_state(data: dict, gate: dict) -> tuple[str, str]:
    """兩段式判定的**第一段（三態版）** → (state, 說明)。

    state ∈:
      HIT       — 選了該型（進第二段驗結構）
      MISS      — 沒選（不適用 → SKIP，不當缺失）
      MALFORMED — **選型欄本身型別錯**（r3／H3，Codex 阻擋 3）

    🔴 MALFORMED 存在的理由：r1 只有 HIT/MISS 兩態，`used: "true"`（字串而非
       bool）被歸為「沒選」→ SKIP，等於填錯型別就自動免驗＝結構性 fail-open。
       Codex 實測 #053/#064/#069 三條全中。型別錯**不是沒選**，是宣告寫壞了，
       必須 FAIL。這是型別檢查，不是語意品質判斷，K0 不豁免。
    """
    trig = gate.get("trigger")
    if not isinstance(trig, dict):
        return "MISS", "gate 規則缺 trigger（不觸發，據實記載）"
    kind = trig.get("kind")
    if kind == "duration_60s":
        dur = resolve_duration_seconds(data)
        if dur == 60:
            return "HIT", "本支宣告 60 秒"
        return "MISS", f"本支時長宣告={dur!r}（非 60 秒，不驗字數區間）"
    field = trig.get("field")
    if not isinstance(field, str):
        return "MISS", "gate trigger 缺 field"
    val = get_field(data, field)
    if kind == "enum":
        allowed = trig.get("enum") or []
        if isinstance(val, str) and val.strip() in allowed:
            return "HIT", f"{field}={val.strip()!r}（命中選型）"
        if val is not None and not isinstance(val, str):
            # 選型欄不是字串（list／dict／數字）＝型別錯，不是沒選
            return "MALFORMED", (
                f"{field} 型別非法（得到 {type(val).__name__}，enum 選型欄須為字串）"
            )
        if _is_filled(val):
            # 有填但不在 enum：這是**選了但選錯**，視為觸發 → 讓第二段報非法值
            return "HIT", f"{field}={val!r}（非合法選項：{allowed}）"
        return "MISS", f"{field} 未宣告（未選此型，不適用）"
    if kind == "bool_true":
        if val is True:
            return "HIT", f"{field}=true（宣告使用）"
        if val is False or val is None:
            return "MISS", f"{field}={val!r}（未宣告使用，不適用）"
        return "MALFORMED", (
            f"{field}={val!r} 型別非法（得到 {type(val).__name__}，須為 YAML bool "
            f"true/false，不接受字串 \"true\"／數字 1）——填錯型別不得換成免驗"
        )
    return "MISS", f"gate trigger kind 不支援：{kind!r}"


def gate_triggered(data: dict, gate: dict) -> tuple[bool, str]:
    """兩段式判定第一段的**相容包裝**：只回「有沒有觸發」。

    ⚠️ MALFORMED 在這裡併入「觸發」（True）——因為型別錯必須進第二段被 FAIL，
       絕不能被當成「沒選」而 SKIP。需要區分三態請直接用 gate_trigger_state。
    """
    state, why = gate_trigger_state(data, gate)
    return (state in ("HIT", "MALFORMED")), why



# ════════════════════════════════════════════════════════════════════
# applicable_ids：**由機器重算**（龍蝦嫁接件：conditional 不准編劇自填 N/A）
# ════════════════════════════════════════════════════════════════════

def compute_applicable_ids(data: dict, registry: dict) -> list[str]:
    """對一支稿重算「本稿適用哪些 method_id」。

    規則（全部可機器判定，零語意判斷）：
      ① mode=always 的條 → 一律適用
      ② layer=gate 且 trigger 成立 → 適用
    其餘（conditional 未選型／audited／outside／excluded）→ 不適用。

    🔴 本函式的回傳值是**唯一權威**。稿內若寫了 applicable_ids，validator
       不採信、只當留痕（防「把自己不想被驗的條目填成 N/A」）。
    """
    out: list[str] = []
    for m in registry.get("methods", []):
        mid = m.get("id")
        if not isinstance(mid, str):
            continue
        if m.get("mode") == "always":
            out.append(mid)
            continue
        if m.get("layer") == "gate" and isinstance(m.get("gate"), dict):
            hit, _ = gate_triggered(data, m["gate"])
            if hit:
                out.append(mid)
    return sorted(set(out))


# ════════════════════════════════════════════════════════════════════
# 證據指標：可不可以解回稿內位置（C-quote-source 範式＝宣告必須兌現）
# ════════════════════════════════════════════════════════════════════

def always_applicable_ids(registry: dict) -> list[str]:
    """mode=always 的條目 id（r3／H2③：11 條「一律適用」）。

    這 11 條不需要選型就適用 → receipt 必須**每條都有交代**：
    要嘛在 used 具名（帶可解回的證據），要嘛在 waiver 欄寫明為何本支沒用。
    只驗「有沒有申報」，不判「用得好不好」（TG19810 紅線）。
    """
    return sorted({str(m.get("id")) for m in registry.get("methods", [])
                   if isinstance(m, dict) and m.get("mode") == "always"
                   and isinstance(m.get("id"), str)})


def compute_receipt_hash(data: dict) -> str:
    """算 receipt 的新鮮度 hash（r3／H2⑤，得標骨架 `receipt_hash` 欄）。

    定義（機械、可重算）：對**去掉 chxp_receipt 之後的稿件本體**做
    正規化 JSON（sort_keys、ensure_ascii=False）再取 sha256。
    → 稿件內容改了、receipt 沒重算＝hash 對不上＝**收據過期**，
      這就是「新鮮度」的機器定義（不判內容對不對，只判是不是同一份稿）。
    """
    body = {k: v for k, v in data.items() if k != "chxp_receipt"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_EVIDENCE_PREFIXES = ("path:", "quote:")


def collect_script_text(data: dict) -> str:
    """收本稿的**稿件內容**字串葉節點，供 quote: 證據比對。

    🔴 **必須排除 chxp_receipt 自身**（F-CXP-T2-RC-d 抓到的自我兌現漏洞）：
       若把 receipt 區塊也收進來，`evidence_ref: "quote:隨便一句"` 的那串字
       本身就在 data 裡 → 任何 quote 都能「找到自己」，證據驗形同虛設。
       同理排除 chxp_method_selection（那是選型宣告，不是稿件內容——
       用選型欄當證據請寫 path:，那條路徑會另外驗欄位確實有值）。
    其餘欄位一律收（證據指到哪一欄都算數，重點是「這句話真的在稿裡」）。
    """
    parts: list[str] = []
    skip_keys = _EVIDENCE_EXCLUDED_TOP_KEYS

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if depth == 0 and str(k) in skip_keys:
                    continue
                walk(v, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v, depth + 1)

    walk(data)
    return "\n".join(parts)


# quote: 證據比對時排除的頂層鍵（防證據自我兌現）
_EVIDENCE_EXCLUDED_TOP_KEYS = ("chxp_receipt", "chxp_method_selection")


def resolve_evidence_ref(data: dict, ref: Any) -> tuple[bool, str]:
    """驗一條證據指標能不能解回稿內位置 → (是否解得回, 說明)。

    只認兩種寫法（不認自由文字——自由文字＝宣告不兌現的溫床）：
      path:<點分隔欄位路徑>   例 path:scenes.0 不支援；請指到 mapping 欄位，
                              如 path:chxp_method_selection.041.段落安排
      quote:<稿內原文片段>     例 quote:貸不下來（須真的出現在本稿文字中）
    """
    if not isinstance(ref, str) or not ref.strip():
        return False, "evidence_ref 缺或非字串"
    s = ref.strip()
    if not s.startswith(_EVIDENCE_PREFIXES):
        return False, (f"evidence_ref 格式不合（須以 path: 或 quote: 開頭）：{s[:40]!r}")
    if s.startswith("path:"):
        dotted = s[len("path:"):].strip()
        if not dotted:
            return False, "evidence_ref path: 後為空"
        # 🔴 r3／H2：path: 一樣不准指回 receipt 自身（Codex 終審：t2b 只封了
        #    quote 自指，`path:chxp_receipt.used` 仍讓 C-CXP-RECEIPT 與 C-CXP-069
        #    同時 PASS＝收據拿自己當自己的證據）。同理排除 chxp_method_selection
        #    以外？——不，選型欄是**稿內宣告**，正是本閘要求的落點，照舊允許。
        top = dotted.split(".", 1)[0]
        if top == "chxp_receipt":
            return False, (
                f"evidence_ref path:{dotted} 指回收據自身（chxp_receipt.*）——"
                f"收據不能當自己的證據，請指向稿件內容或選型欄"
            )
        val = get_field(data, dotted)
        if not _is_filled(val):
            return False, f"evidence_ref path:{dotted} 在稿內解不到內容（缺欄／空值／仍是 placeholder）"
        return True, f"path:{dotted} → 解得回（{str(val)[:24]}…）"
    quote = strip_invisible(s[len("quote:"):])
    if len(quote) < 4:
        return False, (
            f"evidence_ref quote: 太短（{quote!r}，至少 4 字才有辨識度）"
            f"——註：不可見字元（零寬／組合標記）不計入長度"
        )
    if quote in strip_invisible_keep_layout(collect_script_text(data)):
        return True, f"quote:{quote[:16]}… → 在稿內找到"
    return False, f"evidence_ref quote:{quote[:20]}… 在本稿文字中找不到（宣告未兌現）"


def count_chinese_chars(text: str) -> int:
    """中文字數（CJK 基本區塊）——#103 字數區間用。"""
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def script_body_text(data: dict) -> str:
    """#103 字數用的本文＝**可播口白**（唸出來的字），非全部欄位。

    得標定稿字面（Codex 提案）：「60 秒稿的**可播中文字**硬驗 240–300」。
    因此計法＝只收會被唸出來的欄位：
      收：台詞_*（各業主前綴）／台詞／口白／旁白／獨白／OS／藏鏡人／藏鏡人接球／offscreen_*
      不收：翠文（字幕，是台詞的濃縮，計進去會雙倍）、畫面／鏡位／道具（拍攝指示，不唸）、
            備註（給人看的註）、timestamp／type（結構欄）、藏鏡人酸度（S0-S2 標籤非台詞）
    **這是「哪些欄算數」的機械定義，不含任何品質判斷。**
    """
    parts: list[str] = []
    scenes = data.get("scenes")
    if not isinstance(scenes, list):
        return ""
    for sc in scenes:
        if not isinstance(sc, dict):
            continue
        for k, v in sc.items():
            if not isinstance(v, str):
                continue
            key = str(k).strip()
            if not _is_spoken_key(key):
                continue
            s = v.strip()
            if not s or _is_placeholder_text(s):
                continue
            parts.append(s)
    return "".join(parts)


# 可播口白欄位鍵（前綴比對）／明確排除鍵
_SPOKEN_PREFIXES = ("台詞", "口白", "旁白", "獨白", "OS", "藏鏡人", "offscreen_reply",
                    "業主接球", "接球", "dialogue")
_SPOKEN_EXCLUDE = ("藏鏡人酸度", "offscreen_sourness", "酸度")


def _is_spoken_key(key: str) -> bool:
    if key in _SPOKEN_EXCLUDE:
        return False
    return any(key.startswith(p) for p in _SPOKEN_PREFIXES)


def _is_placeholder_text(s: str) -> bool:
    return s.startswith("[") and ("填" in s or "編劇" in s)


def check_receipt_registry_version(rv: Any, prev: Any,
                                   loaded_registry: Optional[dict]) -> tuple[str, str]:
    """receipt.registry_version 對照**實際載入的 registry 版本**（r4／J2）。

    r3 的做法是把 receipt 的版本丟給 check_version()，那是跟**程式端期望常數**
    比——Codex 判定：「沒有對實際載入的 registry 版本建立關聯」。差別在於
    registry 走 grace 前進一版時，程式端常數還停在舊值，receipt 填新值會被
    判成 WARN，但它其實跟現役 registry 完全一致（應該 PASS）；反之 receipt
    填舊值時，才是真正的「收據比現役正典舊一版」。

    規則（loaded＝實際載入的 registry_version）：
      ① rv **字面全等** loaded                          → PASS
      ② rv **字面全等** loaded 的 previous_version，且該版本鏈自洽
         （同 family、序號差 0 或 1）                    → WARN（grace）
      ③ 其餘一律 FAIL——含**未來版**（rv 比現役新）、跳版、異 family、
         格式非法、後綴不同的冒充版、以及現役自報版本鏈斷掉的情形
      ④ 載入的 registry 版本本身讀不到 → 退回與程式端常數比（fail-closed 較嚴）

    r5／K1（Codex r4 阻擋 1）：r4 用 `abs(rv_n - ld_n) == 1`，**把未來一版也放成
    WARN**——收據宣稱用了一個「還沒發布」的正典版本，那不是時間差，是造假或
    工具鏈錯亂，沒有 grace 的理由。grace window 的存在只為「registry 已前進、
    某支稿的收據還停在前一版」這一個方向，因此判定基準改成**現役 registry 自己
    宣告的 previous_version**（版本鏈的唯一權威），不再用序號距離的絕對值。

    r6／L1（Codex r5 阻擋 1）：r5 仍用 `(family, 序號)` 推導「同一版位」，於是
    **`chxp-128-v1-evil` 可以冒充 `chxp-128-v1-draft` 取得 WARN**（序號相同、
    family 相同，後綴被忽略）；而「現役 v3、previous 自報 v1」時，收據填 v1
    也照樣 WARN——registry 自報的版本鏈本身斷了兩版，那個錨不可信。
    現在改成**字面全等**，並加一道版本鏈自洽檢查：
      ① rv 與現役 registry_version **字串完全相等** → PASS
      ② rv 與現役 previous_version **字串完全相等**，且該 previous_version
         與現役同 family、序號差 0 或 1（`v1-draft → v1` 這種同版位換後綴
         算差 0）→ WARN（grace）
      ③ 其餘一律 FAIL——含未來版、跳版、異 family、格式非法、後綴不同的
         冒充版（`v1-evil`）、以及「現役自報的 previous 與自己差 ≥2 版」
         這種鏈斷情境（錨不可信 → 不給 grace）
    也就是說：**再也沒有任何「推導」出來的 WARN，只有字面對得上的 WARN。**
    """
    if not is_nonempty_text(rv):
        return "FAIL", "receipt.registry_version 缺或型別非法（須為非空字串）"
    rv_s = str(rv).strip()
    loaded = (loaded_registry or {}).get("registry_version")
    if not isinstance(loaded, str) or not loaded.strip():
        st, detail = check_version({"registry_version": rv_s, "previous_version": prev})
        return st, f"{detail}（註：實際載入的 registry 版本讀不到，退回與程式端期望常數比對）"
    loaded = loaded.strip()
    if rv_s == loaded:
        return "PASS", f"receipt.registry_version={rv_s}（與實際載入的 registry 一致）"
    rv_p, ld_p = parse_registry_version(rv_s), parse_registry_version(loaded)
    if rv_p is None:
        return "FAIL", (
            f"receipt.registry_version={rv_s!r} 非合法版本字串（須 <family>-v<N>）——"
            f"無從與實際載入的 registry（{loaded}）比對版本鏈"
        )
    if ld_p is None:
        return "FAIL", (
            f"實際載入的 registry_version={loaded!r} 非合法版本字串，"
            f"收據版本（{rv_s}）無從錨定"
        )
    if rv_p[0] != ld_p[0]:
        return "FAIL", (
            f"receipt.registry_version={rv_s} 與實際載入的 registry（{loaded}）"
            f"version family 不同（{rv_p[0]} vs {ld_p[0]}）——不是相鄰版本"
        )
    # 同 family：先擋「未來版」——版本鏈只往回 grace，不往前預支
    if rv_p[1] > ld_p[1]:
        return "FAIL", (
            f"receipt.registry_version={rv_s}，實際載入的 registry={loaded}——"
            f"**收據宣稱的版本比現役正典新（未來版），版本鏈方向性不允許**；"
            f"grace window 只給「收據停在現役的前一版」，不給尚未發布的版本"
        )
    # 同 family、非未來版：唯一的 WARN 路徑＝**字面全等**於現役 registry 自己
    # 宣告的 previous_version，且那條版本鏈自洽（r6／L1：不再做任何推導）
    live_prev = (loaded_registry or {}).get("previous_version")
    live_prev_s = live_prev.strip() if isinstance(live_prev, str) else None
    lp_p = parse_registry_version(live_prev_s)
    if lp_p is None:
        return "FAIL", (
            f"receipt.registry_version={rv_s}，實際載入的 registry={loaded}，"
            f"但現役 registry 的 previous_version={live_prev!r} 缺或格式非法——"
            f"沒有可信的「前一版」錨，不得走 grace window（fail-closed）"
        )
    if lp_p[0] != ld_p[0] or not 0 <= ld_p[1] - lp_p[1] <= 1:
        return "FAIL", (
            f"receipt.registry_version={rv_s}，實際載入的 registry={loaded}，"
            f"現役自報 previous_version={live_prev_s}——**該版本鏈本身不自洽**"
            f"（前一版與現役非同 family 或序號差 >1），錨不可信，不給 grace"
        )
    if rv_s == live_prev_s:
        return "WARN", (
            f"receipt.registry_version={rv_s}，實際載入的 registry={loaded}——"
            f"**收據字面全等於現役 registry 宣告的前一版"
            f"（previous_version={live_prev_s}），走 grace window"
            f"（仍照驗內容，不擋批）**；再舊一版即 FAIL"
        )
    return "FAIL", (
        f"receipt.registry_version={rv_s}，實際載入的 registry={loaded}，"
        f"現役宣告的前一版為 {live_prev_s}——收據版本字面不等於現役、"
        f"也不等於前一版，**不在版本鏈上**（後綴不同的冒充版亦在此列）"
    )


__all__ = [
    "load_registry", "check_version", "iter_gates", "gate_triggered",
    "gate_trigger_state", "compute_applicable_ids", "resolve_evidence_ref", "get_field",
    "count_chinese_chars", "script_body_text", "collect_script_text",
    "resolve_duration_seconds", "RegistryDuplicateKeyError",
    "assert_canon", "check_registry_hash", "registry_file_sha256",
    "parse_registry_version", "always_applicable_ids", "compute_receipt_hash",
    "is_nonempty_text", "strip_invisible", "strip_invisible_keep_layout",
    "id_mode_map_sha256", "check_id_mode_map",
    "check_receipt_registry_version",
    "_REGISTRY_VERSION_EXPECTED", "_REGISTRY_PATH", "_REGISTRY_SHA_SIDECAR_NAME",
]


# ════════════════════════════════════════════════════════════════════
# CLI：兩個機械工具（不做任何判斷，只算 hash）
# ════════════════════════════════════════════════════════════════════
#   --stamp <稿件.yaml>   重算並寫回該稿的 chxp_receipt.receipt_hash（新鮮度錨）
#   --sha                 印出正式 registry 的 sha256 ＋ id↔mode 映射 hash（供更新 sidecar）
# 🔴 --stamp 只改 receipt_hash 那一行，不動稿件任何其他內容（正則定位，
#    不做 YAML round-trip，避免把編劇的排版與註解洗掉）。

# r4／J5：hash 行的**完整值**鎖定（Codex r3 新問題：`{0,64}` 可零長匹配且
# 未鎖到行尾，`receipt_hash: NOT_A_HASH` 被改寫成 `"64位hash"NOT_A_HASH`
# 卻回報成功＝把稿寫壞還說沒事）。現在分兩個正則：
#   _STAMP_LINE_RE  — 抓到「receipt_hash: 」這一行（不論現值長怎樣），用來定位
#   _STAMP_OK_RE    — 現值必須長這樣才准覆寫：空字串／64 位 hex（可帶引號），
#                     並且**鎖到行尾**（$）。其餘現值＝非法 → 報錯拒 stamp、不寫檔。
# r5／K3：**行錨定改結構化**（Codex r4 新問題：不確認匹配行屬於
#   `chxp_receipt.receipt_hash`，可寫到別的區塊的同名欄，真正的收據 hash
#   還是空的卻回報成功）。現在先用縮排結構找出 `chxp_receipt:` 區塊的行範圍，
#   只在該範圍內找 receipt_hash 行；**找不到或多義（區塊內 >1 行）＝報錯不寫**。
# r6／L2：**改用 YAML 解析定位**（Codex r5 新問題：縮排推區塊只看「在不在區塊內」，
#   於是 `chxp_receipt` 裡只有巢狀的 `source_artifact_hashes.receipt_hash` 時，
#   仍會寫進那個子層欄位、還宣稱定位到 `chxp_receipt.receipt_hash`）。現在：
#   ① 先用 yaml 解析確認**頂層 chxp_receipt 有 receipt_hash 這個直屬鍵**
#      （僅此路徑；巢狀同名鍵一律不算）——沒有＝報錯不寫；
#   ② 再在文字面上鎖定「頂層 chxp_receipt 區塊的**直屬縮排層**」那一行，
#      仍以逐行替換寫入（不做 YAML round-trip，才不會洗掉編劇的排版與註解）。
_STAMP_LINE_RE = re.compile(r"(?m)^(?P<indent>\s*receipt_hash:[ \t]*)(?P<val>.*?)[ \t]*$")
# r6／L2：現值合法性——引號**必須成對**。r5 的 `["']?…["']?` 兩端獨立可選，
#   於是 `<64hex>"`（單邊引號）被當合法現值覆寫，等於把稿寫成壞 YAML 還回報成功。
_STAMP_OK_RE = re.compile(
    r"""^(?:"(?:[0-9a-fA-F]{64})?"|'(?:[0-9a-fA-F]{64})?'|[0-9a-fA-F]{64}|)$"""
)
# chxp_receipt 區塊的起始行（**只認頂層＝縮排 0**；值必須是區塊而非同行純量）
_STAMP_BLOCK_RE = re.compile(r"^(?P<indent>)chxp_receipt:[ \t]*(?P<inline>\S.*)?$")


def _indent_width(line: str) -> int:
    """行首縮排寬度（tab 當 1 格；YAML 本來就不該用 tab，只求穩定不當機）。"""
    return len(line) - len(line.lstrip(" \t"))


def _find_receipt_hash_line(text: str, data: Optional[dict] = None) -> tuple[Optional[int], str]:
    """定位**頂層** `chxp_receipt.receipt_hash` 那一行（r5／K3；r6／L2 改 YAML 定位）。

    回傳 (行索引, 說明)；定位失敗時行索引為 None，說明帶原因。
    做法：
      ① **YAML 解析**：頂層 `chxp_receipt` 必須是 mapping，且**直屬鍵**含
         `receipt_hash`——只有這條路徑算數，巢狀的同名鍵（例
         `chxp_receipt.source_artifact_hashes.receipt_hash`）一律不算。
      ② 文字面找 `chxp_receipt:` 起始行（縮排 0）——多於一個＝多義，拒寫
      ③ 以縮排界定該區塊範圍，只取**直屬縮排層**的 `receipt_hash:` 行；
         0 行或 >1 行皆拒寫
    這樣「別的區塊有同名欄」「區塊內只有巢狀同名鍵」都再也騙不到 stamp。
    """
    if data is not None:
        blk = data.get("chxp_receipt")
        if not isinstance(blk, dict):
            return None, "頂層 chxp_receipt 不是 mapping（YAML 解析）"
        if "receipt_hash" not in blk:
            nested = sorted(k for k, v in blk.items()
                            if isinstance(v, dict) and "receipt_hash" in v)
            extra = f"（只在子層 {nested} 找到同名鍵，那不是本欄）" if nested else ""
            return None, (f"頂層 chxp_receipt 沒有直屬的 receipt_hash 鍵{extra}"
                          f"——請先在該區塊直屬層加 `receipt_hash: \"\"` 再重跑")
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if _STAMP_BLOCK_RE.match(ln)]
    if not starts:
        return None, "找不到頂層 chxp_receipt: 區塊起始行（縮排 0）"
    if len(starts) > 1:
        return None, (f"找到 {len(starts)} 個 chxp_receipt: 區塊"
                      f"（行 {[i + 1 for i in starts]}）——多義，拒寫")
    start = starts[0]
    m_blk = _STAMP_BLOCK_RE.match(lines[start])
    if (m_blk.group("inline") or "").strip() and not (m_blk.group("inline") or "").lstrip().startswith("#"):
        return None, "chxp_receipt 同行帶純量值（非 mapping 區塊），拒寫"
    base = _indent_width(lines[start])
    end = len(lines)
    child_indent: Optional[int] = None
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        w = _indent_width(ln)
        if w <= base:
            end = i
            break
        if child_indent is None:
            child_indent = w
    if child_indent is None:
        return None, "chxp_receipt 區塊內沒有任何欄位，拒寫"
    hits_all = [i for i in range(start + 1, end)
                if _STAMP_LINE_RE.match(lines[i])
                and not lines[i].lstrip().startswith("#")]
    if len(hits_all) > 1:
        # r5／K3e 的保守鎖保留：區塊內任何層級出現多個 receipt_hash 行都拒寫。
        # YAML 已經能分辨路徑，但「稿裡同時有直屬欄與子層同名欄」本身就是
        # 寫檔的人搞混了，寧可要人釐清，也不默默只挑一個寫。
        return None, (f"chxp_receipt 區塊內有 {len(hits_all)} 行 receipt_hash"
                      f"（行 {[i + 1 for i in hits_all]}，含子層同名鍵）——多義，拒寫")
    hits = [i for i in hits_all if _indent_width(lines[i]) == child_indent]
    if not hits:
        return None, (f"chxp_receipt 區塊（行 {start + 1}-{end}）的**直屬層**"
                      f"找不到 receipt_hash 行"
                      f"——請先在該層加 `receipt_hash: \"\"` 再重跑")
    return hits[0], f"chxp_receipt.receipt_hash 定位於第 {hits[0] + 1} 行"


def _cli_stamp(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    # r6／L2：YAML 本身解析不了（例如 receipt_hash 現值帶單邊引號把整份稿弄壞）
    #   要給**乾淨的 rc=2 拒寫**，不是丟一個未捕捉的 traceback（rc=1）。
    #   拒寫的理由要說得出口：稿都壞了，這時候寫進去只會更糟。
    try:
        docs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except Exception as e:
        print(f"[stamp] {path.name}：**YAML 解析失敗，拒絕 stamp、未寫檔** — "
              f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
              f"（請先修好稿件語法——常見原因：receipt_hash 現值只有單邊引號）")
        return 2
    if not docs:
        print(f"[stamp] {path.name}：解析不到 mapping 文件，未改動")
        return 2
    data = docs[-1] if len(docs) > 1 else docs[0]
    if not isinstance(data.get("chxp_receipt"), dict):
        print(f"[stamp] {path.name}：無 chxp_receipt 欄，未改動")
        return 2
    # r5／K3：只認 chxp_receipt 區塊內的那一行（結構化定位，非全文 regex）
    # r6／L2：改以 YAML 解析確認「頂層 chxp_receipt 的直屬 receipt_hash 鍵」存在
    idx, why = _find_receipt_hash_line(text, data)
    if idx is None:
        print(f"[stamp] {path.name}：**無法唯一錨定 chxp_receipt.receipt_hash，拒絕 stamp、未寫檔** — {why}")
        return 2
    lines = text.splitlines(keepends=True)
    line = lines[idx]
    m = _STAMP_LINE_RE.match(line.rstrip("\r\n"))
    if m is None:  # pragma: no cover - 定位函式已保證匹配
        print(f"[stamp] {path.name}：定位行無法解析，未改動（{why}）")
        return 2
    cur_val = m.group("val").strip()
    # 去掉行內註解後再判定現值（骨架機產的那行帶 `# 佔位；…` 註解）
    bare = re.split(r"\s+#", cur_val, maxsplit=1)[0].strip()
    if not _STAMP_OK_RE.match(bare):
        print(f"[stamp] {path.name}：**現值非法，拒絕 stamp、未寫檔** — "
              f"receipt_hash 現值 {bare[:40]!r} 既不是 64 位 sha256 也不是空值；"
              f"請先把該行改成 receipt_hash: \"\" 再重跑（避免把稿寫成壞值）")
        return 2
    fresh = compute_receipt_hash(data)
    tail = cur_val[len(bare):]  # 保留原行內註解
    eol = line[len(line.rstrip("\r\n")):]
    lines[idx] = f'{m.group("indent")}"{fresh}"{tail}{eol}'
    path.write_text("".join(lines), encoding="utf-8")
    print(f"[stamp] {path.name}：receipt_hash = {fresh}（{why}）")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手動工具
    import sys as _sys
    if "--sha" in _sys.argv:
        # 兩行輸出＝sidecar 的完整內容（第一行 shasum 格式、第二行身分映射錨）
        print(f"{registry_file_sha256()}  {_REGISTRY_PATH.name}")
        _reg, _err = load_registry(force_reload=True)
        if _reg is None:
            print(f"# registry 讀取失敗，無法算 {_ID_MODE_MAP_SIDECAR_KEY}：{_err}")
            raise SystemExit(2)
        print(f"{_ID_MODE_MAP_SIDECAR_KEY}: {id_mode_map_sha256(_reg)}")
        raise SystemExit(0)
    if "--stamp" in _sys.argv:
        _i = _sys.argv.index("--stamp")
        if _i + 1 >= len(_sys.argv):
            print("用法：python3 chxp_registry.py --stamp <稿件.yaml>")
            raise SystemExit(2)
        raise SystemExit(_cli_stamp(Path(_sys.argv[_i + 1])))
    print("用法：python3 chxp_registry.py --stamp <稿件.yaml> | --sha")
    raise SystemExit(2)
