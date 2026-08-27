#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_distributor.py — 題目分配機 v1.0

Canonical machine source for the hybrid content-axis allocation contract.
Consumers must call ``evaluate_hybrid_allocation(plan)`` instead of mirroring
the constants or acceptance rules declared in this module.

自動分 14 題目方向（Q1-Q8 配額 + 去重已用主題）

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
import hashlib
import unicodedata
import yaml
from pathlib import Path
from typing import Optional

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
L2_BASE = Path(r"/Users/chenzejun/Documents/Claude/Projects/短影音系統/L2_業主層")
SOP_YAML = Path(r"/Users/chenzejun/Documents/Claude/Projects/短影音系統/L0_跨行業公版/_腳本生產SOP_v3.0.yaml")

# ── Hybrid allocation canonical contract（W2-D27）──
CONTENT_AXIS_VALUES = ("offpro", "personal_anchor", "professional")
CONTENT_AXIS_TARGET_COUNTS = {
    "offpro": 9,
    "personal_anchor": 2,
    "professional": 2,
}
# Q1-Q8 是 2026-08-26 起的新批次主題配額。content_axis 契約保留在上方，
# 只供已寫入舊 plan hash 的批次驗證；新批不得再以它分配槽位。
TOPIC_TYPE_VALUES = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8")
TOPIC_TYPE_TARGET_COUNTS = {
    "Q1": 2,
    "Q2": 2,
    "Q3": 2,
    "Q4": 2,
    "Q5": 2,
    "Q6": 2,
    "Q7": 1,
    "Q8": 1,
}
LANE_GENERATION_DEFAULT_COUNTS = {
    "voice_first": 7,
    "demand_first": 2,
    "anchor_first": 2,
    "professional": 2,
}
LANE_FEASIBLE_RANGES = {
    "voice_first": (6, 9),
    "demand_first": (2, 4),
    "anchor_first": (1, 3),
}
LANE_TO_CONTENT_AXIS = {
    "voice_first": "offpro",
    "demand_first": "offpro",
    "anchor_first": "personal_anchor",
    "professional": "professional",
}

# ════════════════════════════════════════
# 題目鎖 canonical contract（cxp-fullimport-s r2，2026-08-12）
#   源＝得標定稿 §4「題目鎖」＋站 0 診斷 §3 假說 5（空題交接·缺陷存在）＋§8-2。
#   舊法真刪：`direction: "[編劇填] — {school}方向 {seq}"` 空題殼已移除。
#   新法：direction 留 TOPIC_UNLOCKED 待鎖；真題資訊一律寫進 topic_lock 五個必填欄。
#   分工邊界（不重做既有閘）：topic_id/provenance 仍由 source_topic_intel 那條路走
#   （validate_script_batch V3-001），本鎖只管「這一槽的題是不是真題」。
# ════════════════════════════════════════
TOPIC_UNLOCKED = "[待鎖題]"   # 題目層尚未鎖題；骨架機/寫稿端看到此值＝不得開工

# 必填真題欄（缺任一＝題未鎖）
# r9 Q4（2026-08-13）：補 topic_id / traffic_candidates 兩欄——得標定稿 §4 原文
#   「龍蝦交 topic_id/真題/題源/受眾場景/能拍∩想拍/流量候選/重複檢查」，
#   原實作只落地五欄，topic_id 與流量候選漏收。
TOPIC_LOCK_REQUIRED_FIELDS = (
    "topic_statement",   # 真題一句話（不是「XX派方向 3」這種殼）
    "topic_source",      # 題從哪來（情報池 topic_id / 業主訪談 / 客戶問題 / 時事）
    "topic_id",          # r9 Q4：情報池 / 題庫的題目識別碼（存在且非占位；真偽比對仍歸 V3-001）
    "audience_scene",    # 受眾＋場景（講給誰、在什麼情境下有用）
    "can_shoot",         # 能拍（業主拍得到的素材／場景）
    "want_shoot",        # 想拍（業主本人願意講）
    "traffic_candidates",  # r9 Q4：流量候選（非空清單；這題打算走哪些流量點）
)
# 清單型必填欄（非空 list／非空字串才算填；空 list＝未鎖）
TOPIC_LOCK_LIST_FIELDS = ("traffic_candidates",)
TOPIC_LOCK_TEMPLATE = {
    f: ([] if f in TOPIC_LOCK_LIST_FIELDS else "")
    for f in TOPIC_LOCK_REQUIRED_FIELDS
}
TOPIC_LOCK_TEMPLATE["locked_by"] = ""    # 誰鎖的（題目層負責人）
TOPIC_LOCK_TEMPLATE["locked_at"] = ""    # 何時鎖的

# 敘述欄（必須是人話，不得是布林／true-false 字面）
_TOPIC_NARRATIVE_FIELDS = ("topic_statement", "topic_source", "audience_scene")

# r11 T1（2026-08-13）型別收緊：以下四欄**型別必須是 str**。
#   舊法漏洞：判定只走 _topic_field_is_placeholder（看「形」不看型別），
#   `topic_id: True` / `topic_source: 123` / `audience_scene: {}` 皆判已鎖 →
#   骨架機 str() 一轉就落地成 "True"/"123"/"{}"，題目層等於沒鎖。
#   新法：非 str（bool／int／float／dict／list／None）一律未鎖，不做型別轉換救援。
_TOPIC_STR_FIELDS = ("topic_statement", "topic_source", "topic_id", "audience_scene")
# 能拍／想拍：型別限 **bool 或 str**（bool 須為 True；str 走真值判定＝非空非占位非否定字樣）。
#   非此兩型（數字／dict／list／None）一律未鎖——「1」「{}」不是「業主願意講」的宣告。
_TOPIC_BOOLSTR_FIELDS = ("can_shoot", "want_shoot")

# 寫稿端（愛馬仕）拿到未鎖/不合用題目時的唯一合法回應：不得自行換題
TOPIC_REJECT = "TOPIC_REJECT"


# 占位／空殼字樣（r6 P5 收緊）：命中任一＝該欄視同未填。
# 依據＝Codex 三審阻擋項 1：舊法只驗「轉字串後非空」，`[待填]`／`[編劇填]` 全被判已鎖。
_TOPIC_PLACEHOLDER_TOKENS = (
    "[待填]", "[待定]", "[編劇填]", "[題目層填]", "[填]", "[TBD]", "TBD",
    "待填", "待定", "未定", "N/A", "NA", "-", "—", "?", "？",
)
# can_shoot／want_shoot 的否定值（＝業主拍不到／不想講）：不是「已鎖」，該題應退回題目層。
_TOPIC_SHOOT_NEGATIVE = (
    "不能拍", "不可拍", "拍不到", "不想拍", "不願", "不行", "否", "無", "沒有",
    "no", "false", "n",
)
# r11 T1：布林字面字串（值本身在講 true/false 而不是在描述素材）。
#   命中此集合者一律走白名單判定，不吃「非否定即真」那條寬鬆路。
_TOPIC_SHOOT_BOOL_LITERALS = frozenset({
    "true", "false", "yes", "no", "y", "n", "1", "0", "t", "f",
    "是", "否", "有", "無", "能", "不能", "可", "不可", "要", "不要",
})
# 真值白名單（僅適用於上面那組布林字面）
_TOPIC_SHOOT_TRUE_TOKENS = frozenset({
    "true", "yes", "y", "1", "t", "是", "有", "能", "可", "要",
})


def _topic_field_is_placeholder(value) -> bool:
    """欄值是否為空／占位殼（不看語意，只看形）。布林 True 不算占位。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return not value          # True＝有宣告；False＝等同未填
    s = str(value).strip()
    if not s:
        return True
    if s == TOPIC_UNLOCKED:
        return True
    su = s.upper()
    for tok in _TOPIC_PLACEHOLDER_TOKENS:
        t = tok.upper()
        if su == t or su.startswith(t):
            return True
    # 純方括號殼：[任何內容] 且長度不超過 20 → 視同占位（例：[編劇自己想]）
    if s.startswith("[") and s.endswith("]") and len(s) <= 20:
        return True
    return False


def _topic_shoot_is_truthy(value) -> bool:
    """can_shoot／want_shoot 是否為真值（能拍／想拍）。

    False、否定字樣（不能拍／不想拍／否…）皆判非真值＝題未鎖（r6 P5）。
    r11 T1：型別已由 topic_lock_status 先擋（限 bool／str）；本函式再管內容。
      - bool → 只有 True 算真值
      - 布林字面字串（true/false/yes/no/1/0/是/否…）→ 走 **真值白名單** _TOPIC_SHOOT_TRUE_TOKENS，
        不在白名單的布林字面（"false"/"0"/"no"）＝非真值
      - 敘述字串（「自家車庫」「願意講」）→ 非占位且非否定字樣即算真值
        （敘述欄本來就是講「拍得到什麼素材」，不能要求逐字命中白名單；
         r6 契約與既有 fixtures 皆為敘述值）
    """
    if _topic_field_is_placeholder(value):
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip()
    sl = s.lower()
    if sl in _TOPIC_SHOOT_BOOL_LITERALS:
        return sl in _TOPIC_SHOOT_TRUE_TOKENS
    for neg in _TOPIC_SHOOT_NEGATIVE:
        n = neg.lower()
        if sl == n or sl.startswith(n):
            return False
    return True


def _topic_list_field_is_empty(value) -> bool:
    """清單型必填欄（traffic_candidates）是否視同未填。

    r9 Q4：非空 list/tuple 且至少一個元素非占位＝已填。
    r11 T1 型別收緊：**必須是 list/tuple**，且**每個元素都要是非空非占位 str**。
      - 0 / True / {} / "字串" → 未填（非清單型別，不做單值救援；舊法接受單一字串）
      - [] / [""] / ["待填"] / [1] / [{}] → 未填（元素型別或內容不合格）
    理由：流量候選是「要打哪些流量點」的清單，數字／布林／dict 進來一定是資料錯，
    舊法 str() 一轉就會落地成 "1"、"True"，等於用假值騙過鎖。
    """
    if not isinstance(value, (list, tuple)):
        return True
    if not value:
        return True
    for v in value:
        if not isinstance(v, str) or _topic_field_is_placeholder(v):
            return True
    return False


def normalize_topic_statement(value) -> str:
    """真題正規化（供同批重複檢查用）。

    r9 Q4：全形→半形（NFKC）、去頭尾空白、去所有空白字元、去常見標點、轉小寫。
    僅供 exact-match 去重；不做語意比對。
    """
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[，,。.、；;：:！!？?「」『』\"'（）()\[\]【】~～\-—_/\\|]+", "", s)
    return s


def topic_lock_status(item) -> tuple[bool, list]:
    """判斷 plan 單槽的題是否已鎖 →（is_locked, 缺欄清單）。

    已鎖條件（全滿足）：
      ① direction 非 TOPIC_UNLOCKED、非空、非占位殼（[待填]／[編劇填]…）
      ② TOPIC_LOCK_REQUIRED_FIELDS 各欄逐一非空且非占位
         （r9 Q4 起含 topic_id 存在、traffic_candidates 非空清單）
      ③ can_shoot／want_shoot 需為真值（False／「不能拍」「不想拍」＝未鎖）
      ④ **型別逐欄驗**（r11 T1，2026-08-13）：
         topic_id／topic_statement／topic_source／audience_scene → 限 str
         can_shoot／want_shoot → 限 bool（須 True）或 str（真值判定）
         traffic_candidates → 限非空 list/tuple 且每元素為非空非占位 str
         非法型別（bool／dict／數字／None）一律**未鎖**，不做 str() 轉換救援
         ——舊法只驗「形」不驗「型」，`topic_id: True`、`traffic_candidates: 0`
         會被判已鎖，骨架機再 str() 一轉就落地成假值。

    **不驗**（r9 Q4 明標）：direction 與 topic_lock.topic_statement 的**語意一致性**
    ＝人工把關（題目層鎖題人／審查席）。程式只驗「欄位是否為真題形狀」，
    不做語意比對——避免用字串相似度假裝語意驗證（誤判會擋掉合法改寫）。

    r6 P5 收緊（Codex 阻擋項 1）：非 dict 的 item／topic_lock **不拋例外**，一律判未鎖。
    純判定函式，不改資料、不擲例外（供 distributor / 骨架機 / 審查共用一套判準）。
    """
    missing: list[str] = []
    if not isinstance(item, dict):
        return False, [f"plan item 型別非 dict（{type(item).__name__}）＝未鎖"]

    direction = item.get("direction", "")
    if _topic_field_is_placeholder(direction):
        missing.append("direction（真題未寫回／仍是占位殼）")

    lock = item.get("topic_lock")
    if not isinstance(lock, dict):
        missing.append(f"topic_lock（整塊缺或型別非 dict：{type(lock).__name__}）")
        return False, missing

    for field in TOPIC_LOCK_REQUIRED_FIELDS:
        v = lock.get(field)
        if field in TOPIC_LOCK_LIST_FIELDS:
            # r9 Q4：流量候選必須非空（空清單＝這題還沒想過怎麼吃流量＝未鎖）
            # r11 T1：型別亦收緊（非 list／元素非 str 皆未鎖，見 _topic_list_field_is_empty）
            if _topic_list_field_is_empty(v):
                missing.append(
                    f"topic_lock.{field}（流量候選須為非空 list 且每元素為非空 str；"
                    f"實得 {type(v).__name__}={str(v)[:20]!r}＝未鎖）")
            continue
        # ── r11 T1 型別閘（先於「形」的判定）──
        if field in _TOPIC_STR_FIELDS and not isinstance(v, str):
            missing.append(
                f"topic_lock.{field}（型別須為 str，實得 {type(v).__name__}="
                f"{str(v)[:20]!r}＝未鎖）")
            continue
        if field in _TOPIC_BOOLSTR_FIELDS and not isinstance(v, (bool, str)):
            missing.append(
                f"topic_lock.{field}（型別須為 bool 或 str，實得 {type(v).__name__}="
                f"{str(v)[:20]!r}＝未鎖）")
            continue
        if _topic_field_is_placeholder(v):
            missing.append(f"topic_lock.{field}（空／占位）")
        elif field in ("can_shoot", "want_shoot"):
            if not _topic_shoot_is_truthy(v):
                missing.append(f"topic_lock.{field}（非真值：{str(v)[:20]!r}＝業主拍不到/不想講，請退回題目層換題）")
        elif field in _TOPIC_NARRATIVE_FIELDS:
            if isinstance(v, bool) or str(v).strip().lower() in ("true", "false", "yes", "no"):
                # r6 P5：敘述欄（真題一句話／題從哪來／受眾場景）必須是敘述，
                # 布林或 true/false 字面＝殼（Codex 阻擋項 1 實測案例）。
                missing.append(f"topic_lock.{field}（布林／true-false 字面不是敘述：{str(v)[:20]!r}）")
    return (not missing), missing


def duplicate_topic_statements(plan) -> list:
    """同批重複真題檢查 →[(normalized, [seq, ...]), ...]（r9 Q4）。

    得標定稿 §4 原文含「重複檢查」：同一批兩槽鎖同一句真題＝題目層失誤，
    照樣派工會產出兩支同題腳本。判準＝topic_statement 正規化後 **exact-match**
    （全形/空白/標點差異視為同一句）；語意近似**不驗**（人工把關）。
    空／占位的 topic_statement 不納入比對（那由必填欄檢查擋）。
    """
    if not isinstance(plan, list):
        return []
    seen: dict[str, list] = {}
    for idx, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            continue
        lock = item.get("topic_lock")
        raw = lock.get("topic_statement") if isinstance(lock, dict) else None
        if _topic_field_is_placeholder(raw):
            continue
        key = normalize_topic_statement(raw)
        if not key:
            continue
        seen.setdefault(key, []).append(item.get("seq", idx))
    return [(k, seqs) for k, seqs in seen.items() if len(seqs) > 1]


def assert_topics_locked(plan) -> tuple[bool, list]:
    """整份 plan 的題目鎖檢查 →（all_locked, [(seq, 缺欄), ...]）。
    消費端（骨架機 / 寫稿派工）在開工前呼叫；未鎖＝退回題目層，禁自行補題。
    r6 P5：plan 非 list 或元素非 dict 皆判未鎖（不拋例外）。
    r9 Q4：同批重複真題＝**未鎖級**（與缺欄同級，消費端一律非零退出），
           以 seq=None 的合成項回報，避免消費端要多接一個 API。"""
    if not isinstance(plan, list):
        return False, [(None, [f"plan 型別非 list（{type(plan).__name__}）"])]
    unlocked = []
    for idx, item in enumerate(plan, start=1):
        ok, missing = topic_lock_status(item)
        if not ok:
            seq = item.get("seq") if isinstance(item, dict) else idx
            unlocked.append((seq, missing))
    for key, seqs in duplicate_topic_statements(plan):
        unlocked.append((
            None,
            [f"同批重複真題（正規化後 exact-match）：seq {seqs} 鎖到同一句「{key[:30]}…」"
             f"＝未鎖級，請題目層換題後重跑"],
        ))
    return (not unlocked), unlocked


# ════════════════════════════════════════════════════════════════════
# W3（cxp-gapfix-w1／2026-08-13）：topic_id 題源真實性解析（假 topic_id 關死）
# 規格＝龍蝦堵法表 P0-1：「在 plan 的七欄填自造值與假 topic_id，再直接進骨架」
#   實測 forged_rc=0（骨架機不會發現）。根因：topic_lock_status 只驗「形」與
#   「型」，不驗 topic_id 是否真的存在於題池／projection record。
# 修法：新增本解析器，骨架機開工前逐槽呼叫，無命中 → exit 2。
#
# 兩條合法來源（其一）：
#   ① projection record：topic_id 命中 owner 的 _projections/by_owner/<code>/active.json
#      candidates[].topic_id（不可手填——該檔由 gen_topic_intel_projection.py 產）。
#   ② typed 人工 namespace：topic_id 以 `MANUAL-` 前綴開頭（工單 W3 明訂），
#      且 topic_lock.locked_by 有具名鎖定人（非空、非占位）。人工題留給
#      「業主訪談／客戶當場問的問題」這類本來就不在情報池的題，但必須具名負責。
# 其餘一律 unresolved＝假 topic_id。
# ════════════════════════════════════════════════════════════════════

MANUAL_TOPIC_ID_PREFIX = "MANUAL-"


def _projection_active_path(owner: str):
    """回傳 owner 的 projection active.json 路徑（Path）或 None（owner 未知／設定缺）。"""
    try:
        rec = _OWNER_PROJECTION.get(owner) if owner else None
    except SystemExit:
        raise
    except Exception:
        return None
    if not rec:
        return None
    owner_code = str(rec.get("owner_code", "") or "")
    if not owner_code:
        return None
    cfg_path = Path("/Users/chenzejun/claude-state/topic_intel_paths.json")
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    proj_dir = cfg.get("topic_intel_projection_dir", "")
    if not proj_dir:
        return None
    return Path(proj_dir) / "by_owner" / owner_code / "active.json"


def load_projection_topic_ids(owner: str) -> tuple[Optional[set], Optional[str]]:
    """載 owner 的 projection topic_id 集合 →(ids_set, error)。

    (set, None)   ＝ cache 在場且可解析（可能為空集合）
    (None, error) ＝ cache 不在場／不可解析（呼叫端 fail-closed，禁當作「無限制」）
    """
    active = _projection_active_path(owner)
    if active is None:
        return None, f"owner={owner!r} 無法解析 projection 路徑（owner 未登錄或 topic_intel_paths.json 缺）"
    if not active.exists():
        return None, f"owner={owner!r} projection cache 不存在：{active}"
    try:
        data = json.loads(active.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"owner={owner!r} projection cache 解析失敗：{e}"
    cands = data.get("candidates")
    if not isinstance(cands, list):
        return None, f"owner={owner!r} projection cache candidates 非 list"
    ids = {
        str(c.get("topic_id", "") or "")
        for c in cands
        if isinstance(c, dict) and c.get("topic_id")
    }
    return ids, None


def resolve_topic_id_source(topic_id, owner: str, lock=None,
                            projection_ids: Optional[set] = None,
                            projection_error: Optional[str] = None) -> tuple[bool, str, str]:
    """單一 topic_id 的題源真實性解析 →(ok, kind, detail)。

    kind ∈ {"projection", "manual", "unresolved"}。
    projection_ids/projection_error 可由呼叫端先載一次再逐槽傳入（省 IO）；
    未傳則本函式自行載入。
    fail-closed：cache 不在場 → 一律 unresolved（不放行），因為此時無法證明題真。
    """
    tid = topic_id if isinstance(topic_id, str) else None
    if not tid or not tid.strip():
        return False, "unresolved", "topic_id 為空或型別非 str"
    tid = tid.strip()

    # ① typed 人工 namespace
    if tid.startswith(MANUAL_TOPIC_ID_PREFIX):
        body = tid[len(MANUAL_TOPIC_ID_PREFIX):].strip()
        if not body:
            return False, "unresolved", f"topic_id={tid!r} 只有 {MANUAL_TOPIC_ID_PREFIX} 前綴、無識別碼本體"
        locked_by = (lock or {}).get("locked_by") if isinstance(lock, dict) else None
        if not isinstance(locked_by, str) or _topic_field_is_placeholder(locked_by):
            return False, "unresolved", (
                f"topic_id={tid!r} 為人工題（{MANUAL_TOPIC_ID_PREFIX} namespace）"
                f"但 topic_lock.locked_by 未具名鎖定人（實得 {locked_by!r}）"
            )
        return True, "manual", f"人工題 namespace 合法（locked_by={locked_by!r}）"

    # ② projection record
    if projection_ids is None and projection_error is None:
        projection_ids, projection_error = load_projection_topic_ids(owner)
    if projection_error:
        return False, "unresolved", (
            f"topic_id={tid!r} 無法驗真來源（{projection_error}）；"
            f"若為人工題請改用 {MANUAL_TOPIC_ID_PREFIX} 前綴＋具名 locked_by"
        )
    if tid in (projection_ids or set()):
        return True, "projection", f"topic_id={tid!r} 命中 owner={owner!r} projection record"
    return False, "unresolved", (
        f"topic_id={tid!r} 不在 owner={owner!r} 的 projection record 中（假題／已失效／打錯）；"
        f"人工題請用 {MANUAL_TOPIC_ID_PREFIX} 前綴＋具名 locked_by"
    )


def assert_topic_ids_resolvable(plan, owner: str) -> tuple[bool, list]:
    """整份 plan 的 topic_id 題源解析 →(all_ok, [(seq, detail), ...])。

    骨架機在 assert_topics_locked 通過後呼叫；任一槽 unresolved → 消費端 exit 2。
    """
    if not isinstance(plan, list):
        return False, [(None, f"plan 型別非 list（{type(plan).__name__}）")]
    proj_ids, proj_err = load_projection_topic_ids(owner)
    bad: list = []
    for idx, item in enumerate(plan, start=1):
        seq = item.get("seq", idx) if isinstance(item, dict) else idx
        lock = item.get("topic_lock") if isinstance(item, dict) else None
        tid = lock.get("topic_id") if isinstance(lock, dict) else None
        ok, _kind, detail = resolve_topic_id_source(
            tid, owner, lock, projection_ids=proj_ids, projection_error=proj_err
        )
        if not ok:
            bad.append((seq, detail))
    return (not bad), bad


# ════════════════════════════════════════════════════════════════════
# W1（cxp-gapfix-w1／2026-08-13）：topic_lock 正典雜湊
# 用途＝把「plan 鎖到的題」綁死，validator C-TOPIC-LOCK 重算比對，
#   任何人事後手改 plan 或稿件的 topic_lock 都會 hash mismatch。
# 設計注意（不打紅現役）：**另立 `topic_lock_hash` 欄位**，不改既有
#   `_plan_lock_hash`（hybrid 5-key）算式——現役 18 份 plan 皆已寫入舊 hash，
#   改算式會讓它們全部 mismatch。舊 plan 無本欄 → validator SKIP（grandfather）。
# ════════════════════════════════════════════════════════════════════

# 納入雜湊的鎖欄（順序固定；locked_by/locked_at 屬簽署欄，一併納入防事後改人）
TOPIC_LOCK_HASH_FIELDS = TOPIC_LOCK_REQUIRED_FIELDS + ("locked_by", "locked_at")


def _canonical_lock_value(v):
    """雜湊用正規化：list → 逐元素字串化後保序；bool/str/None → 字串化（None→""）。"""
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    return str(v)


def topic_lock_hash(plan) -> str:
    """整份 plan 的 topic_lock 正典雜湊（sha256 hex）。

    對每槽取 script_id ＋ TOPIC_LOCK_HASH_FIELDS 逐欄正規化值，按 script_id 排序後
    canonical JSON → sha256。plan 非 list／槽非 dict → 該槽以空鎖計（不拋例外）。
    """
    rows = []
    if isinstance(plan, list):
        for idx, item in enumerate(plan, start=1):
            if not isinstance(item, dict):
                rows.append({"script_id": f"__invalid_{idx}", "lock": {}})
                continue
            lock = item.get("topic_lock")
            lock = lock if isinstance(lock, dict) else {}
            rows.append({
                "script_id": str(item.get("script_id", "") or ""),
                "lock": {f: _canonical_lock_value(lock.get(f)) for f in TOPIC_LOCK_HASH_FIELDS},
            })
    rows.sort(key=lambda r: r["script_id"])
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def script_topic_lock_hash(script_id, lock) -> str:
    """單支腳本的 topic_lock 雜湊（與 topic_lock_hash 同一正規化契約，單槽版）。"""
    lock = lock if isinstance(lock, dict) else {}
    row = {
        "script_id": str(script_id or ""),
        "lock": {f: _canonical_lock_value(lock.get(f)) for f in TOPIC_LOCK_HASH_FIELDS},
    }
    raw = json.dumps([row], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
        return {"main_scripts": 14, "cta_distribution": {}}


# ════════════════════════════════════════
# 7. 分配題目方向
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
    按流派比例分配 batch_spec.main_scripts 個題目方向（skeleton）
    每題只含：方向 + 流派 + 雙身份 — 不寫內文
    """
    main_count = batch_spec.get("main_scripts", 14)

    # ── 正規化流派比例（只計非禁用派系）──
    total_pct = sum(school_ratios.values())
    if total_pct == 0:
        print("[WARN] 流派比例加總 = 0，改用均等分配")
        schools = list(school_ratios.keys()) or ["故事戲劇派", "人間觀察派", "直球派"]
        school_ratios = {s: 100 // len(schools) for s in schools}
        total_pct = 100

    # 最大餘數法：先取整數部分，再按餘數補格，嚴格保證總數恰為 main_count。
    # 舊 round()+只調最高派在 8 派等權時會因最低 1 格限制多出第 15 槽。
    raw_slots = {
        name: main_count * pct / total_pct
        for name, pct in school_ratios.items()
    }
    slots = {name: int(raw) for name, raw in raw_slots.items()}
    remaining = main_count - sum(slots.values())
    for name in sorted(
        slots,
        key=lambda key: (-(raw_slots[key] - slots[key]), -school_ratios[key], key),
    )[:remaining]:
        slots[name] += 1

    # ── 正規化雙身份比例 ──
    id_total = sum(identity_ratios.values())
    if id_total == 0 or not identity_ratios:
        # fallback：均等
        identity_ratios = {"觀點分享": 40, "生活日常": 30, "業務": 15, "開箱": 5}
        id_total = 90

    # ── 產 plan list ──
    # 依流派 slot 展開
    #
    # 題目鎖（cxp-fullimport-s r2，2026-08-12）：舊法真刪。
    #   舊：direction = "[編劇填] — {school}方向 {seq}" —— 派工出去就是一個空題殼，
    #       編劇拿到「拆解派方向 3」等於沒題目，題從寫稿當下才生，四錨點第一錨（題目）落空。
    #   新：direction 一律留白待鎖（TOPIC_UNLOCKED），另立 topic_lock 必填真題欄。
    #       骨架機／validator 只接受已鎖真題；愛馬仕（寫稿端）不可自行換題，
    #       題目對不上只能回 TOPIC_REJECT 退回題目層，不得就地改題（得標定稿 §4）。
    #   保留：既有 topic_id / provenance 閘（source_topic_intel）不重做、不改行為。
    plan: list[dict] = []
    seq = 1
    for school, count in slots.items():
        for i in range(count):
            # 計算雙身份（按比例循環）
            id_choice = _pick_identity(identity_ratios, id_total, seq, main_count)
            plan.append({
                "seq": seq,
                "script_id": f"{_owner_code(owner)}_{_batch_code(batch)}_{seq:02d}",
                "direction": TOPIC_UNLOCKED,
                "topic_lock": dict(TOPIC_LOCK_TEMPLATE),
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


HYBRID_BATCH_PROFILE = "hybrid_70_15_15"
_BATCH_FLAGS_PROFILE_PARSE_ERROR = "[topic_distributor] _batch_flags.yml 存在但解析失敗，fail-closed（無法確認 batch_profile）"


def _read_batch_profile_from_flags(batch_dir: Optional[str]) -> Optional[str]:
    """Read batch_profile from <batch_dir>/_batch_flags.yml without affecting legacy runs."""
    if not batch_dir:
        return None
    p = Path(batch_dir)
    flag_path = p if p.name == "_batch_flags.yml" else p / "_batch_flags.yml"
    if not flag_path.exists():
        return None
    try:
        raw = yaml.safe_load(flag_path.read_text(encoding="utf-8"))
    except Exception:
        raise SystemExit(_BATCH_FLAGS_PROFILE_PARSE_ERROR)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit(_BATCH_FLAGS_PROFILE_PARSE_ERROR)
    profile = raw.get("batch_profile")
    if profile is None:
        return None
    return str(profile).strip()


def _resolve_batch_profile(cli_profile: Optional[str], batch_dir: Optional[str]) -> Optional[str]:
    profile = (cli_profile or "").strip() or _read_batch_profile_from_flags(batch_dir)
    if not profile:
        return None
    if profile != HYBRID_BATCH_PROFILE:
        raise SystemExit(f"[topic_distributor] unsupported batch_profile: {profile!r}")
    return profile


def _load_owner_content_profile() -> dict:
    path = Path(__file__).resolve().parent / "owner_content_profile.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_offpro_topic_pillars() -> tuple[list[str], str]:
    path = Path(__file__).resolve().parent / "offpro_topic_pillar_map.yaml"
    fallback = (["人生", "金錢", "感情"], "熱門")
    if not path.exists():
        return fallback
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return fallback
    cats = data.get("offpro_topic_categories") if isinstance(data, dict) else None
    if not isinstance(cats, list):
        return fallback
    values = [str(c).strip() for c in cats if str(c).strip()]
    wildcard = "熱門" if "熱門" in values else (values[-1] if values else fallback[1])
    pillars = [c for c in values if c not in {"時事", wildcard}]
    if len(pillars) < 3:
        pillars = [c for c in values if c != wildcard]
    pillars = pillars[:3]
    if len(pillars) < 3:
        return fallback
    return pillars, wildcard


def _profile_lanes(profile_data: dict) -> dict[str, int]:
    default = dict(LANE_GENERATION_DEFAULT_COUNTS)
    profiles = profile_data.get("profiles") if isinstance(profile_data, dict) else None
    strong = profiles.get("strong_default") if isinstance(profiles, dict) else None
    lanes = strong.get("lanes") if isinstance(strong, dict) else None
    if not isinstance(lanes, dict):
        return default
    resolved = dict(default)
    for key in default:
        try:
            resolved[key] = int(lanes.get(key, default[key]))
        except (TypeError, ValueError):
            resolved[key] = default[key]
    return resolved


def _count_by(plan: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in plan:
        val = item.get(key)
        if isinstance(val, str) and val:
            counts[val] = counts.get(val, 0) + 1
    return counts


def _plan_lock_hash(plan: list[dict]) -> str:
    pairs = [
        {
            "script_id": item.get("script_id", ""),
            "content_axis": item.get("content_axis", ""),
            "lane": item.get("lane", ""),
            "derived_flags": sorted(str(x) for x in (item.get("derived_flags") or [])),
            "proof_mode": item.get("proof_mode", ""),  # W4-K10（2026-07-16）：proof_mode 納入 hash，逐字鏡像 validate_script_batch.py:7167-7179
        }
        for item in plan
    ]
    raw = json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evaluate_hybrid_allocation(plan: list[dict]) -> dict:
    """Return the deterministic hybrid-allocation verdict for ``plan``.

    This public evaluator is pure: it performs no I/O, mutates neither the
    input nor module state, and derives every result from the canonical
    constants above.
    """
    content_axis_count = _count_by(plan, "content_axis")
    lane_count = _count_by(plan, "lane")
    topic_category_count = _count_by(plan, "topic_category")
    identity_bridge_count = sum(
        1 for item in plan if "identity_bridge" in (item.get("derived_flags") or [])
    )
    pure_emotion_count = sum(
        1 for item in plan if "pure_emotion" in (item.get("derived_flags") or [])
    )
    offpro_categories = [
        item.get("topic_category")
        for item in plan
        if item.get("content_axis") == "offpro" and item.get("topic_category")
    ]
    offpro_pillar_count = len(set(offpro_categories))
    news_count = sum(1 for c in offpro_categories if c == "時事")

    infeasible: list[str] = []
    non_professional = content_axis_count.get("offpro", 0) + content_axis_count.get("personal_anchor", 0)
    expected_slots = sum(CONTENT_AXIS_TARGET_COUNTS.values())
    if len(plan) != expected_slots:
        infeasible.append(f"slot_count={len(plan)} expected={expected_slots}")
    for axis in CONTENT_AXIS_VALUES:
        actual = content_axis_count.get(axis, 0)
        expected = CONTENT_AXIS_TARGET_COUNTS[axis]
        if actual != expected:
            infeasible.append(f"{axis}={actual} expected={expected}")
    expected_non_professional = (
        CONTENT_AXIS_TARGET_COUNTS["offpro"]
        + CONTENT_AXIS_TARGET_COUNTS["personal_anchor"]
    )
    if non_professional != expected_non_professional:
        infeasible.append(
            f"non_professional={non_professional} "
            f"expected={expected_non_professional}"
        )
    for lane, (minimum, maximum) in LANE_FEASIBLE_RANGES.items():
        actual = lane_count.get(lane, 0)
        if not minimum <= actual <= maximum:
            infeasible.append(
                f"{lane}={actual} expected_range={minimum}..{maximum}"
            )
    if identity_bridge_count != 1:
        infeasible.append(f"identity_bridge={identity_bridge_count} expected=1")
    if pure_emotion_count < 1:
        infeasible.append(f"pure_emotion={pure_emotion_count} expected_min=1")
    if not 3 <= offpro_pillar_count <= 4:
        infeasible.append(f"offpro_pillar_count={offpro_pillar_count} expected_range=3..4")
    if news_count > 2:
        infeasible.append(f"時事={news_count} expected_max=2")

    return {
        "content_axis_count": content_axis_count,
        "lane_count": lane_count,
        "topic_category_count": topic_category_count,
        "offpro_pillar_count": offpro_pillar_count,
        "offpro_news_count": news_count,
        "identity_bridge_present": identity_bridge_count == 1,
        "emotional_slot_present": pure_emotion_count >= 1,
        "business_leak_check": "placeholder:not_run",
        "infeasible_constraints": infeasible,
    }


def evaluate_q8_allocation(plan: list[dict]) -> dict:
    """Return the deterministic Q1-Q8 quota verdict for a new batch plan."""
    topic_type_count = _count_by(plan, "topic_type")
    infeasible: list[str] = []
    expected_slots = sum(TOPIC_TYPE_TARGET_COUNTS.values())
    if len(plan) != expected_slots:
        infeasible.append(f"slot_count={len(plan)} expected={expected_slots}")
    for topic_type in TOPIC_TYPE_VALUES:
        actual = topic_type_count.get(topic_type, 0)
        expected = TOPIC_TYPE_TARGET_COUNTS[topic_type]
        if actual != expected:
            infeasible.append(f"{topic_type}={actual} expected={expected}")
    invalid = sorted(set(topic_type_count) - set(TOPIC_TYPE_VALUES))
    if invalid:
        infeasible.append(f"invalid_topic_types={invalid}")
    return {
        "topic_type_count": topic_type_count,
        "expected_topic_type_count": dict(TOPIC_TYPE_TARGET_COUNTS),
        "infeasible_constraints": infeasible,
    }


def apply_q8_quota(plan: list[dict]) -> tuple[list[dict], dict]:
    """Annotate a new plan with the canonical Q1-Q8 slot sequence.

    This deliberately does not touch content_axis/lane or _plan_lock_hash: those
    are the legacy hybrid contract and old plans must keep validating unchanged.
    """
    sequence = [
        topic_type
        for topic_type in TOPIC_TYPE_VALUES
        for _ in range(TOPIC_TYPE_TARGET_COUNTS[topic_type])
    ]
    annotated: list[dict] = []
    for idx, item in enumerate(plan):
        out = dict(item)
        out["topic_type"] = sequence[idx] if idx < len(sequence) else ""
        annotated.append(out)
    return annotated, evaluate_q8_allocation(annotated)


def _hybrid_allocation_report(plan: list[dict]) -> dict:
    """Backward-compatible private entry point for allocator callers."""
    return evaluate_hybrid_allocation(plan)


def _proof_mode_for_hybrid_lane(item: dict) -> str | None:
    """lane → proof_mode 映射（W4-K10 2026-07-16：同義複製
    ``yaml_skeleton_generator.py:280-289`` 的 ``_proof_mode_for_hybrid_lane``；
    值語義與該函式逐一等值，禁自行發明新 lane 或改映射值）。

    回傳 None＝該 item 不寫 proof_mode 欄（未知 lane 或缺 content_axis 欄）。
    """
    if "content_axis" not in item:
        return None
    lane = str(item.get("lane", "") or "").strip()
    return {
        "voice_first": "voice_first",
        "demand_first": "demand_first",
        "anchor_first": "anchor_first",
        "professional": "proof_first",
    }.get(lane)


def apply_hybrid_profile(plan: list[dict], profile_data: dict) -> tuple[list[dict], str, dict]:
    lanes = _profile_lanes(profile_data)
    lane_sequence = (
        ["voice_first"] * lanes["voice_first"]
        + ["demand_first"] * lanes["demand_first"]
        + ["anchor_first"] * lanes["anchor_first"]
        + ["professional"] * lanes["professional"]
    )
    pillars, wildcard_category = _load_offpro_topic_pillars()
    offpro_category_index = 0

    annotated: list[dict] = []
    for idx, item in enumerate(plan):
        out = dict(item)
        lane = lane_sequence[idx] if idx < len(lane_sequence) else "unassigned"
        axis = LANE_TO_CONTENT_AXIS.get(lane, "unassigned")
        flags: list[str] = []
        if idx == 0 and lane == "voice_first":
            flags.append("identity_bridge")
        if idx == 1 and lane in {"voice_first", "anchor_first"}:
            flags.append("pure_emotion")
        if idx == 2 and axis == "offpro":
            flags.append("wildcard")
            out["wildcard"] = True
            out["wildcard_reason"] = (
                "料源=topic_intel_closure active candidate（closure-only）"
            )
            topic_category = wildcard_category
        elif axis == "offpro":
            topic_category = pillars[offpro_category_index % len(pillars)]
            offpro_category_index += 1
        elif axis == "personal_anchor":
            topic_category = "personal_story"
        elif axis == "professional":
            topic_category = "professional"
        else:
            topic_category = "unassigned"
        out["content_axis"] = axis
        out["lane"] = lane
        out["derived_flags"] = flags
        out["topic_category"] = topic_category
        proof_mode = _proof_mode_for_hybrid_lane(out)
        if proof_mode is not None:
            out["proof_mode"] = proof_mode  # W4-K10（2026-07-16）：annotated 寫入 proof_mode，供 5-key hash 與 validate derive-lock 對齊
        annotated.append(out)

    lock_hash = _plan_lock_hash(annotated)
    report = _hybrid_allocation_report(annotated)
    return annotated, lock_hash, report


# ════════════════════════════════════════
# parity 自測（W4-K10 2026-07-16；規格＝decision_cards/W4/K10_diff_packet_20260716.md
# parity 規格 v4，兩級判準＋容忍集）
# ════════════════════════════════════════

def _extract_lane_to_proof_from_validate(source_path) -> dict:
    """執行時解析 ``validate_script_batch.py`` 原始碼，抽取 ``_LANE_TO_PROOF``
    dict 字面量（W4-K10 霸告裁定修正 2026-07-16：改識別字定位，不釘行號快照
    ——行號會漂、快照本身是第四份會失真的拷貝）。

    做法：讀原始碼 → ``ast.parse`` → 全樹 walk 找 ``Assign`` 節點，target 為
    ``Name(id="_LANE_TO_PROOF")`` 且 value 為 ``Dict`` 字面量 → ``ast.literal_eval``
    還原成真實 dict。不論該指派巢狀在哪個函式/區塊內都能找到（AST walk 不看
    scope，只看語法樹結構）。

    找不到該識別字、或找到但不是 dict 字面量、或原始碼解析失敗 → raise
    ValueError（呼叫端視為「validate 端表消失/改形——人工查」，selftest 該
    情況一律 exit non-zero）。
    """
    import ast

    source = Path(source_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_LANE_TO_PROOF":
                    if not isinstance(node.value, ast.Dict):
                        raise ValueError(
                            "_LANE_TO_PROOF 識別字找到但賦值非 dict 字面量（validate 端改形）"
                        )
                    return ast.literal_eval(node.value)
    raise ValueError("_LANE_TO_PROOF 識別字未找到（validate 端表消失或改名）")


def _parity_selftest() -> int:
    """驗證本檔 ``_proof_mode_for_hybrid_lane`` 與 sibling 兩處映射同義。

    Level ① — 嚴格全等：本檔映射 ≡ ``yaml_skeleton_generator.py:280-289``
    的 ``_proof_mode_for_hybrid_lane``（4 已知 lane 逐一等值 + unknown-lane
    探針，探針 item 必含 ``content_axis`` 欄以避免踩 generator 的提前 None
    分支；已知 lane 與 unknown 探針兩者皆應與 generator 完全一致）。

    Level ② — 對 ``validate_script_batch.py`` 的 ``_LANE_TO_PROOF``（函式內
    區域變數、非模組層可 import 物件，本刀禁動該檔）：**執行時解析該檔原始
    碼抽表**（見 ``_extract_lane_to_proof_from_validate``，靠識別字定位、不
    靠行號——防漂移也防「快照即第四份拷貝」問題）。交集鍵逐一等值（不等＝
    FAIL）；容忍集僅兩個**具名**已知不對稱——validate 獨有鍵 ``stance``
    （legacy alias，本檔永不產出）＝容忍＋列印；本檔獨有鍵 ``professional``
    （validate 未鎖，已知 K11 缺口）＝容忍＋列印「K11 pending」。**任何其他
    不在此兩個具名容忍集內的不對稱鍵（例如 validate 端某已知 lane 憑空消失）
    一律 FAIL**——防止「非交集鍵一律放行」把真實漂移吃掉。抽表失敗（識別字
    消失/改形）＝exit non-zero。

    回傳 process exit code：0＝全通過；非 0＝任一級不符或 sibling 解析失敗。
    """
    ok = True
    messages: list[str] = []

    try:
        from yaml_skeleton_generator import _proof_mode_for_hybrid_lane as _gen_proof_mode
    except Exception as exc:
        print(f"[parity-selftest] FAIL — yaml_skeleton_generator import error: {type(exc).__name__}: {exc}")
        return 1

    known_lanes = ["voice_first", "demand_first", "anchor_first", "professional"]
    local_map: dict[str, str] = {}
    for lane in known_lanes:
        probe = {"content_axis": "offpro", "lane": lane}
        local_val = _proof_mode_for_hybrid_lane(probe)
        gen_val = _gen_proof_mode(probe)
        if local_val != gen_val:
            ok = False
            messages.append(
                f"[parity-selftest] FAIL — Level1 lane={lane} distributor={local_val!r} generator={gen_val!r}"
            )
        if local_val is not None:
            local_map[lane] = local_val

    unknown_probe = {"content_axis": "offpro", "lane": "__unknown_lane_sentinel__"}
    local_unknown = _proof_mode_for_hybrid_lane(unknown_probe)
    gen_unknown = _gen_proof_mode(unknown_probe)
    if local_unknown is not None or gen_unknown is not None:
        ok = False
        messages.append(
            f"[parity-selftest] FAIL — Level1 unknown-lane probe 非 None：distributor={local_unknown!r} generator={gen_unknown!r}"
        )

    validate_path = Path(__file__).resolve().parent / "validate_script_batch.py"
    try:
        validate_lane_to_proof = _extract_lane_to_proof_from_validate(validate_path)
    except Exception as exc:
        print(f"[parity-selftest] FAIL — validate _LANE_TO_PROOF 解析失敗（人工查）：{type(exc).__name__}: {exc}")
        return 1

    # 容忍集＝packet 明文點名的兩個已知不對稱（非「任何不交集鍵都容忍」——
    # 其他不對稱一律視為漂移訊號，FAIL 讓人工查）。
    _KNOWN_VALIDATE_ONLY = {"stance"}       # legacy alias，distributor 永不產出
    _KNOWN_DISTRIBUTOR_ONLY = {"professional"}  # validate 未鎖，已知 K11 缺口

    shared_keys = set(local_map) & set(validate_lane_to_proof)
    for key in sorted(shared_keys):
        if local_map[key] != validate_lane_to_proof[key]:
            ok = False
            messages.append(
                f"[parity-selftest] FAIL — Level2 交集鍵 {key} distributor={local_map[key]!r} validate={validate_lane_to_proof[key]!r}"
            )

    validate_only = set(validate_lane_to_proof) - set(local_map)
    for key in sorted(validate_only & _KNOWN_VALIDATE_ONLY):
        messages.append(f"[parity-selftest] TOLERATE — validate 獨有鍵 {key!r}（legacy alias，distributor 永不產出）")
    for key in sorted(validate_only - _KNOWN_VALIDATE_ONLY):
        ok = False
        messages.append(
            f"[parity-selftest] FAIL — Level2 validate 獨有鍵 {key!r} 不在已知容忍清單 {sorted(_KNOWN_VALIDATE_ONLY)}"
            "（疑似 validate 端表結構變動或本檔遺漏 lane——人工查）"
        )

    distributor_only = set(local_map) - set(validate_lane_to_proof)
    for key in sorted(distributor_only & _KNOWN_DISTRIBUTOR_ONLY):
        messages.append(f"[parity-selftest] TOLERATE — distributor 獨有鍵 {key!r}（validate 未鎖，K11 pending）")
    for key in sorted(distributor_only - _KNOWN_DISTRIBUTOR_ONLY):
        ok = False
        messages.append(
            f"[parity-selftest] FAIL — Level2 distributor 獨有鍵 {key!r} 不在已知容忍清單 {sorted(_KNOWN_DISTRIBUTOR_ONLY)}"
            "（疑似 validate 端表結構變動——人工查）"
        )

    for msg in messages:
        print(msg)

    if ok:
        print("[parity-selftest] PASS")
        return 0
    print("[parity-selftest] FAIL")
    return 1


# ════════════════════════════════════════
# 主程式
# ════════════════════════════════════════

def main():
    # UTF-8 CLI output防亂碼（Windows cp950）；import 不改呼叫端 streams。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # W4-K10（2026-07-16）：--parity-selftest 於正常生成路徑之前攔截退出，
    # 不吃下方 --owner/--batch 必填檢查（parity 規格 v4 ③ CLI 語義）。
    if "--parity-selftest" in sys.argv[1:]:
        try:
            exit_code = _parity_selftest()
        except Exception as exc:
            print(f"[parity-selftest] FAIL — unexpected error: {type(exc).__name__}: {exc}")
            exit_code = 1
        sys.exit(exit_code)

    parser = argparse.ArgumentParser(description="題目分配機 — 自動分 14 題目方向（Q1-Q8 配額）")
    parser.add_argument("--owner",  required=True, help="業主名（瑞祥/仲豪/昀臻/叭噗_小C/阿奇）")
    parser.add_argument("--batch",  required=True, help="批次名，e.g. 第02批_2026-05-25")
    parser.add_argument("--output", help="輸出 JSON 路徑（預設同目錄 topic_plan_<owner>_<batch>.json）")
    parser.add_argument(
        "--batch-dir",
        help="批次目錄路徑（WP-B：讀 _batch_flags.yml topic_intel_closure policy；缺省=off）",
        default=None,
    )
    parser.add_argument(
        "--batch-profile",
        help="optional allocator profile; supported MVP value: hybrid_70_15_15",
        default=None,
    )
    args = parser.parse_args()

    owner = args.owner
    batch = args.batch
    batch_profile = _resolve_batch_profile(args.batch_profile, args.batch_dir)

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
    main_count = batch_spec.get("main_scripts", 14)
    print(f"[OK] SOP batch_spec.main_scripts = {main_count}")

    # 分配題目方向，並為新批次固定填入 Q1-Q8 配額。
    plan, dedup_info = distribute_topics(
        school_ratios, identity_ratios, used_topics, batch_spec, owner, batch
    )
    plan, q8_allocation_report = apply_q8_quota(plan)
    if q8_allocation_report["infeasible_constraints"]:
        print(
            "[ERROR] Q1-Q8 配額不合，拒絕寫入 topic plan："
            + "; ".join(q8_allocation_report["infeasible_constraints"]),
            file=sys.stderr,
        )
        sys.exit(1)
    ratio_validation = build_ratio_validation(plan, school_ratios, identity_ratios)

    plan_lock_hash: Optional[str] = None
    allocation_report: Optional[dict] = None
    if batch_profile == HYBRID_BATCH_PROFILE:
        # 舊 hybrid profile 僅保留 CLI 相容性；新批一律走 Q1-Q8，不重新套
        # content_axis 9/2/2（該函式仍保留供既有 plan grandfather 驗證）。
        allocation_report = q8_allocation_report

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
                _ti_cfg_path = Path(r"/Users/chenzejun/claude-state/topic_intel_paths.json")
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
        "q8_allocation_report": q8_allocation_report,
    }
    if batch_profile == HYBRID_BATCH_PROFILE:
        output_data["meta"]["batch_profile"] = batch_profile
        output_data["allocation_report"] = allocation_report
    # W1（cxp-gapfix-w1 2026-08-13）：題目鎖正典雜湊。
    # 只有整份 plan 都已鎖題才寫入——寫了本欄＝宣告「新格式（題目鎖世代）」，
    # validator C-TOPIC-LOCK 會逐欄比對＋重算 hash；未鎖的 plan 不寫（維持舊格式
    # grandfather 路徑，不打紅 351 支歷史稿）。
    try:
        _all_locked, _ = assert_topics_locked(plan)
    except Exception:
        _all_locked = False
    if _all_locked:
        output_data["topic_lock_hash"] = topic_lock_hash(plan)
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

    # ── 題目鎖狀態（cxp r2 2026-08-12）：新產 plan 一律未鎖，明講下一步是誰的事 ──
    _all_locked, _unlocked = assert_topics_locked(plan)
    if _all_locked:
        print(f"  題目鎖：全 {len(plan)} 槽已鎖真題（topic_lock 五欄齊）")
    else:
        print(f"  🔒 題目鎖：{len(_unlocked)}/{len(plan)} 槽未鎖題 — 本 plan **尚不可派去寫稿**。")
        print(f"     下一步＝題目層逐槽補 direction 真題 + topic_lock 五欄"
              f"（{'/'.join(TOPIC_LOCK_REQUIRED_FIELDS)}）。")
        print(f"     寫稿端不得自行補題或換題；題不合用只能回 {TOPIC_REJECT} 退回題目層。\n")

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
    # bind_scope="all_offpro" → 綁滿 plan 中所有 offpro slot；"" → legacy max_slots 行為
    bind_scope: str = str(policy.get("bind_scope", "") or "")

    warnings: list[str] = []
    assign_report_base: dict = {
        "mode": mode,
        "enabled": True,
        "min_slots": min_slots,
        "max_slots": max_slots,
    }
    # bind_scope 只在非空時加入（legacy 無此欄，不打破舊 assign_report byte-compat）
    if bind_scope:
        assign_report_base["bind_scope"] = bind_scope

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
            warnings.append(
                f"[WARN] {_expires_at_err}，shadow 本批不綁趨勢題"
            )
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "batch_id": batch_id,
                "error": None,
                "warnings": warnings,
                "detail": (
                    "assign skip（shadow stale projection，本批不綁趨勢題）: "
                    f"{_expires_at_err}"
                ),
            }

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

    # bind_scope=all_offpro → 只綁 offpro slot，以 plan 中 offpro 數量為上限
    # bind_scope="" (legacy) → 綁前 max_slots 個 slot，不看 content_axis（向後相容）
    if bind_scope == "all_offpro":
        eligible_slot_indices = [
            i for i, item in enumerate(plan)
            if item.get("content_axis") == "offpro"
        ]
        effective_max_slots = len(eligible_slot_indices)
        if effective_max_slots == 0:
            # 此批無 offpro slot → 無可綁定（不是候選不足）→ 清楚 WARN + 乾淨結束（§22.9 不擋批）
            warnings.append("[WARN] 此批無 off-pro slot，bind_scope=all_offpro 無可綁定，略過（不擋批）")
            return plan, {
                **assign_report_base,
                "selected_count": 0,
                "assigned_slots": [],
                "qualified_count": qualified_count,
                "batch_id": batch_id,
                "error": None,
                "warnings": warnings,
                "detail": "assign skip: bind_scope=all_offpro 但此批無 off-pro slot（不擋批）",
            }
    else:
        # legacy：全 slot 候補，effective_max_slots = max_slots
        eligible_slot_indices = list(range(len(plan)))
        effective_max_slots = max_slots

    # 計算 selected_count（用 effective_max_slots）
    if qualified_count < min_slots:
        selected_count = 0
    else:
        selected_count = min(effective_max_slots, qualified_count)

    # enforce 不足 min → 不綁 + error；shadow → 綁得到的就綁（§22.9 絕不擋批、絕不退題）
    if selected_count == 0:
        msg = (
            f"合格候選 {qualified_count} 支 < min_slots={min_slots}，"
            f"enforce 不綁（需補充選題情報池 pending 料）"
        )
        if mode == "shadow":
            # shadow：候選不足時綁 qualified_count 個觀察，絕不擋批（§22.9 紅線）
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

    # pool-thin WARN（bind_scope=all_offpro + 有候選但不足 offpro slot 數）§22.9 絕不擋批
    if bind_scope == "all_offpro" and 0 < len(selected) < len(eligible_slot_indices):
        warnings.append(
            f"[WARN] pool thin: 綁了 {len(selected)}/{len(eligible_slot_indices)} 個 off-pro slot，"
            f"剩 {len(eligible_slot_indices) - len(selected)} 個 slot 留給編劇走正常 off-pro（不擋批）"
        )

    # 綁進 eligible_slot_indices 的前 N 個 slot
    # bind_scope=all_offpro → eligible_slot_indices 只含 offpro 位置
    # legacy → eligible_slot_indices = [0,1,...,N-1]（與舊行為 byte-identical）
    assigned_slots: list[int] = []
    plan_copy = [dict(item) for item in plan]  # 不 mutate 原 plan

    for i, candidate in enumerate(selected):
        # 取目標 slot index
        if i >= len(eligible_slot_indices):
            warnings.append(
                f"eligible_slot_indices 長度 {len(eligible_slot_indices)} < selected {len(selected)}，截斷"
            )
            break
        target_slot = eligible_slot_indices[i]

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
        plan_copy[target_slot]["source_topic_intel"] = {
            "topic_id": candidate.get("topic_id", ""),
            "source_kind": "cyborg_yaml",
            "evidence_path": _ev_path,       # Fix G+Fix5：assign 端必填 canonical path
            "evidence_sha256": candidate.get("source_sha256", ""),
            "adopted_topic_statement": "",   # 編劇填
            "assigned_by": "topic_distributor",
            "assignment_mode": mode,
        }
        assigned_slots.append(target_slot)

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
