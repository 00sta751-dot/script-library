#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_pwa_assets.py — PWA 三件（manifest / sw / icons）部署驗證（2026-06-12 零留尾戰役 WP-D）

背景（6/11 夜 ledger P3-17 後半）：PWA 三件此前無任何驗證閘覆蓋 — manifest 壞了 / icon 缺檔 /
index.html 引用斷線都不會被部署鏈攔下。本驗證器以 check_15 掛進 validate_deploy.py main。

檢查 6 件：
1. manifest.json 存在且 JSON 可解析
2. manifest 必要欄位齊（name / start_url / display / icons 非空 list）
3. icons 內每個 src 檔案實際存在
4. sw.js 存在
5. index.html 雙引用在位（rel="manifest" + serviceWorker 註冊/sw.js）
6. manifest description 禁硬編「N支」型過期計數文案（P3-17 前半根治：不准再寫死數字）

CLI：python validate_pwa_assets.py [repo_root]   # 預設=本檔所在目錄；exit 0 全過 / exit 2 有 FAIL
"""

import json
import re
import sys
from pathlib import Path


def run_pwa_checks(root: Path) -> list:
    """回 list[FAIL 訊息]，空 list = 全過。"""
    fails = []
    manifest_path = root / "manifest.json"
    sw_path = root / "sw.js"
    index_path = root / "index.html"

    # 1. manifest 存在 + 可解析
    if not manifest_path.exists():
        fails.append("PWA: manifest.json 不存在")
        return fails  # 後續檢查無意義
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        fails.append(f"PWA: manifest.json JSON 解析失敗：{e}")
        return fails

    # 2. 必要欄位
    for key in ("name", "start_url", "display"):
        if not manifest.get(key):
            fails.append(f"PWA: manifest.json 缺必要欄位 {key!r}")
    icons = manifest.get("icons")
    if not isinstance(icons, list) or not icons:
        fails.append("PWA: manifest.json icons 必須是非空 list")
        icons = []

    # 3. icon 檔案存在
    for ic in icons:
        src = (ic or {}).get("src", "")
        if not src:
            fails.append("PWA: manifest icons 有項目缺 src")
            continue
        if not (root / src).exists():
            fails.append(f"PWA: icon 檔不存在：{src}")

    # 4. sw.js
    if not sw_path.exists():
        fails.append("PWA: sw.js 不存在")

    # 5. index.html 雙引用
    if not index_path.exists():
        fails.append("PWA: index.html 不存在")
    else:
        idx = index_path.read_text(encoding="utf-8", errors="replace")
        if 'rel="manifest"' not in idx and "rel='manifest'" not in idx:
            fails.append('PWA: index.html 缺 <link rel="manifest"> 引用')
        if "serviceWorker" not in idx and "sw.js" not in idx:
            fails.append("PWA: index.html 缺 serviceWorker / sw.js 註冊")

    # 6. description 禁硬編計數（「16支腳本」型過期文案）
    desc = str(manifest.get("description", ""))
    if re.search(r"\d+\s*支", desc):
        fails.append(
            f"PWA: manifest description 含硬編計數「{desc}」— 會隨批次成長過期，禁寫死數字"
        )

    return fails


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    fails = run_pwa_checks(root)
    if fails:
        for f in fails:
            print(f"  ❌ {f}")
        print(f"== validate_pwa_assets: {len(fails)} FAIL ==")
        return 2
    print("== validate_pwa_assets: 6/6 PASS ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
