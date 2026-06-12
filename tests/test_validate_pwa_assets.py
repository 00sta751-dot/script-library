#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WP-D fixtures：validate_pwa_assets 好案例 + 5 失敗模式（Codex D5 紅線）"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from validate_pwa_assets import run_pwa_checks  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


def make_good(td: Path):
    (td / "icon-192.png").write_bytes(b"x")
    (td / "icon-512.png").write_bytes(b"x")
    (td / "sw.js").write_text("// sw", encoding="utf-8")
    (td / "index.html").write_text(
        '<link rel="manifest" href="manifest.json"><script>navigator.serviceWorker.register("sw.js")</script>',
        encoding="utf-8",
    )
    (td / "manifest.json").write_text(json.dumps({
        "name": "測試庫", "short_name": "庫", "description": "多業主腳本隨時查閱",
        "start_url": "./index.html", "display": "standalone",
        "icons": [{"src": "icon-192.png", "sizes": "192x192"}, {"src": "icon-512.png", "sizes": "512x512"}],
    }, ensure_ascii=False), encoding="utf-8")


with tempfile.TemporaryDirectory() as _td:
    td = Path(_td)

    # 0. good 全過
    make_good(td)
    fails = run_pwa_checks(td)
    check("good_passes", fails == [], str(fails))

    # 1. manifest icons 缺項（空 list）
    make_good(td)
    m = json.loads((td / "manifest.json").read_text(encoding="utf-8"))
    m["icons"] = []
    (td / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    fails = run_pwa_checks(td)
    check("manifest_no_icons_fails", any("icons" in f for f in fails), str(fails))

    # 2. icon 檔缺失
    make_good(td)
    (td / "icon-512.png").unlink()
    fails = run_pwa_checks(td)
    check("icon_file_missing_fails", any("icon-512.png" in f for f in fails), str(fails))

    # 3. sw.js 缺失
    make_good(td)
    (td / "sw.js").unlink()
    fails = run_pwa_checks(td)
    check("sw_missing_fails", any("sw.js" in f for f in fails), str(fails))

    # 4. index 引用缺失
    make_good(td)
    (td / "index.html").write_text("<html>no refs</html>", encoding="utf-8")
    fails = run_pwa_checks(td)
    check("index_refs_missing_fails",
          any("manifest" in f and "index" in f for f in fails) and any("serviceWorker" in f or "sw.js" in f for f in fails),
          str(fails))

    # 5. description 硬編計數過期文案
    make_good(td)
    m = json.loads((td / "manifest.json").read_text(encoding="utf-8"))
    m["description"] = "16支腳本隨時查閱"
    (td / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    fails = run_pwa_checks(td)
    check("desc_hardcoded_count_fails", any("硬編計數" in f for f in fails), str(fails))

    # 6. manifest JSON 壞檔
    make_good(td)
    (td / "manifest.json").write_text("{not json", encoding="utf-8")
    fails = run_pwa_checks(td)
    check("manifest_bad_json_fails", any("解析失敗" in f for f in fails), str(fails))

failed = [n for n, c in results if not c]
print(f"=== {len(results) - len(failed)}/{len(results)} PASS ===")
sys.exit(1 if failed else 0)
