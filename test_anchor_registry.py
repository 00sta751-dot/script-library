"""
test_anchor_registry.py — chk_anchor_registry_ref fixture 測試（2026-06-20）

4 個 case：
  Case 1: 同 owner registry-id 存在 + usable_for 含 anchor_first → PASS
  Case 2: 跨 owner（楷甯稿填 fake_realtor_01_a01）→ WARN（跨業主 anchor 污染）
  Case 3: owner_unresolved（owner 解析不到）→ WARN（owner_unresolved，fail-closed）
  Case 4: usable_for 不含 anchor_first（kaining_a08 僅 voice_lock）→ WARN

依賴：
  - validate_script_batch.py（chk_anchor_registry_ref 從此 import）
  - L2_業主層/房仲_楷甯/00_業主核心檔/derived/_楷甯_anchor_registry.yaml
    owner_id=kaining，kaining_a01~a07 usable_for=[anchor_first,...]，
    kaining_a08 usable_for=[voice_lock]（不含 anchor_first）

執行方式（PYTHONUTF8=1 防 cp950 亂碼）：
  PYTHONUTF8=1 python test_anchor_registry.py
"""

import os
import sys

# ── PYTHONUTF8 保護 ──
if os.environ.get("PYTHONUTF8") != "1":
    print("[WARN] 建議加 PYTHONUTF8=1 避免 cp950 亂碼", file=sys.stderr)

# ── import chk_anchor_registry_ref ──
from validate_script_batch import chk_anchor_registry_ref

PASS_COUNT = 0
FAIL_COUNT = 0


def _assert(label: str, got_status: str, got_msg: str,
            expect_status: str, expect_token: str) -> None:
    global PASS_COUNT, FAIL_COUNT
    ok = (got_status == expect_status) and (expect_token in got_msg)
    if ok:
        PASS_COUNT += 1
        print(f"  PASS  {label}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL  {label}")
        print(f"         expect_status={expect_status!r}  got={got_status!r}")
        print(f"         expect_token={expect_token!r}  in msg={expect_token in got_msg}")
        print(f"         msg={got_msg!r}")


print("=" * 60)
print("chk_anchor_registry_ref fixture（4 case）")
print("=" * 60)

# ────────────────────────────────────────────
# Case 1：同 owner registry-id 存在 + usable_for 含 anchor_first → PASS
# 楷甯稿 anchor_ref=kaining_a01，usable_for=[anchor_first, voice_lock]
# ────────────────────────────────────────────
print("\nCase 1: 同 owner registry-id 存在 + anchor_first ∈ usable_for → PASS")
data_c1 = {
    "proof_mode": "anchor_first",
    "anchor_ref": "kaining_a01",
    "anchor_cost": "第一次被屋主罵，當場愣住",
    "because_bridge": "因為那次才懂客訴不是針對我",
}
s1, m1 = chk_anchor_registry_ref(data_c1, "case1.yaml", "楷甯")
_assert("同 owner kaining_a01 存在 + anchor_first ∈ usable_for", s1, m1, "PASS", "chk_anchor_registry_ref PASS")


# ────────────────────────────────────────────
# Case 2：跨 owner（楷甯稿填 fake_realtor_01_a01）→ WARN 跨業主
# fake_realtor_01 不是 kaining → 跨業主 anchor 污染
# ────────────────────────────────────────────
print("\nCase 2: 跨 owner（楷甯稿填 fake_realtor_01_a01）→ WARN 跨業主")
data_c2 = {
    "proof_mode": "anchor_first",
    "anchor_ref": "fake_realtor_01_a01",
    "anchor_cost": "某段低潮",
    "because_bridge": "因為那次所以懂了",
}
s2, m2 = chk_anchor_registry_ref(data_c2, "case2.yaml", "楷甯")
_assert("跨業主 fake_realtor_01_a01 → WARN 含 '跨業主'", s2, m2, "WARN", "跨業主 anchor 污染")


# ────────────────────────────────────────────
# Case 3：owner_unresolved（owner 解析不到）→ WARN owner_unresolved（fail-closed）
# 傳入不存在的業主名「不存在業主XYZ」→ _find_owner_id_by_display 回 None → fail-closed
# ────────────────────────────────────────────
print("\nCase 3: owner_unresolved（owner 解析不到）→ WARN owner_unresolved")
data_c3 = {
    "proof_mode": "anchor_first",
    "anchor_ref": "kaining_a01",   # registry-id 格式，觸發 owner 解析路徑
    "anchor_cost": "某段低潮",
    "because_bridge": "因為那次所以懂了",
}
s3, m3 = chk_anchor_registry_ref(data_c3, "case3.yaml", "不存在業主XYZ")
_assert("不存在業主 → WARN 含 'owner_unresolved'", s3, m3, "WARN", "owner_unresolved")


# ────────────────────────────────────────────
# Case 4：usable_for 不含 anchor_first（kaining_a08 僅 voice_lock）→ WARN
# kaining_a08 usable_for=[voice_lock]
# ────────────────────────────────────────────
print("\nCase 4: usable_for 不含 anchor_first（kaining_a08）→ WARN")
data_c4 = {
    "proof_mode": "anchor_first",
    "anchor_ref": "kaining_a08",
    "anchor_cost": "持續追蹤近一年",
    "because_bridge": "因為那次所以懂了",
}
s4, m4 = chk_anchor_registry_ref(data_c4, "case4.yaml", "楷甯")
_assert("kaining_a08 usable_for=[voice_lock] → WARN 含 'usable_for'", s4, m4, "WARN", "usable_for")


# ────────────────────────────────────────────
# 總結
# ────────────────────────────────────────────
print("\n" + "=" * 60)
total = PASS_COUNT + FAIL_COUNT
print(f"結果：{PASS_COUNT}/{total} PASS")
if FAIL_COUNT > 0:
    print("FAIL — 修復後重跑")
    sys.exit(1)
else:
    print("全 PASS")
    sys.exit(0)
