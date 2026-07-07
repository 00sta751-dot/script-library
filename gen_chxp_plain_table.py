#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_chxp_plain_table.py — 陳修平公式（chxp_v1）白話對照表產生器

2026-07-07 W2 品管工單 D 項。給澤君「免懂工程代號驗貨」用。

輸入：某批次 yaml 夾（讀每支 script_*.yaml 的 script_method.chxp_v1 欄）。
輸出：一份 md 對照表 —— 每支一小節，列（工程代號欄 | 白話說明 | 原值）。
唯讀輸入；只寫自己的輸出 md（不動任何 yaml / 公版）。

跑法：
  python gen_chxp_plain_table.py --batch-dir <批次夾> [--out <輸出.md>]
不給 --out → 預設寫 <批次夾>/_陳修平公式白話對照表_auto.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_frontmatter(path: Path) -> dict:
    """讀 markdown/yaml frontmatter（--- ... --- 首段）。"""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^---\s*\n", "", text, count=1)
    front = re.split(r"\n---\s*\n", text, maxsplit=1)[0]
    front = re.sub(r"\n---\s*$", "", front)
    data = yaml.safe_load(front) or {}
    return data if isinstance(data, dict) else {}


def list_script_yamls(batch_dir: Path) -> list[Path]:
    return sorted(
        p for p in batch_dir.glob("script_*.yaml")
        if ".bak" not in p.name and ".tmp" not in p.name
    )


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


MISSING = "（缺）"


def _fmt_scalar(v: Any) -> str:
    if v is None:
        return MISSING
    s = str(v).strip()
    return s if s else MISSING


def _fmt_signals(v: Any) -> str:
    """optimization.concrete_signals: list[{quote,type}] → 'n 個：q1 / q2 / …'。"""
    if not isinstance(v, list) or not v:
        return MISSING
    quotes = []
    for item in v:
        if isinstance(item, dict):
            q = item.get("quote")
            t = item.get("type")
            if q is not None:
                quotes.append(f"{q}" + (f"（{t}）" if t else ""))
        elif item is not None:
            quotes.append(str(item))
    if not quotes:
        return f"{len(v)} 個（無 quote 內容）"
    return f"{len(v)} 個：" + " / ".join(quotes)


# 工程代號欄 → 白話說明 → 取值函式（順序 = 陳修平六步）
FIELD_MAP = [
    ("chxp_v1.four_materials.problem_scene", "①問題場景（觀眾卡在哪）",
     lambda c: _fmt_scalar(_dig(c, "four_materials", "problem_scene"))),
    ("chxp_v1.four_materials.old_answer.quote", "②舊答案（大家原本以為的）",
     lambda c: _fmt_scalar(_dig(c, "four_materials", "old_answer", "quote"))),
    ("chxp_v1.four_materials.new_answer.quote", "③新答案（翻過來的觀點）",
     lambda c: _fmt_scalar(_dig(c, "four_materials", "new_answer", "quote"))),
    ("chxp_v1.four_materials.answer_expansion", "④答案展開（怎麼落地）",
     lambda c: _fmt_scalar(_dig(c, "four_materials", "answer_expansion"))),
    ("chxp_v1.assembly.story_vehicle", "⑤故事載體（用什麼包裝）",
     lambda c: _fmt_scalar(_dig(c, "assembly", "story_vehicle"))),
    ("chxp_v1.optimization.concrete_signals", "⑥具體訊號（實例/數字）",
     lambda c: _fmt_signals(_dig(c, "optimization", "concrete_signals"))),
]


def _md_cell(s: str) -> str:
    """md 表格 cell 逃逸：換行→空白、| → 全形，避免破表。"""
    return str(s).replace("\n", " ").replace("|", "｜").strip()


def build_table(batch_dir: Path) -> tuple[str, int, int]:
    """回傳 (md_text, script_count, with_chxp_count)。"""
    yamls = list_script_yamls(batch_dir)
    lines: list[str] = []
    lines.append(f"# 陳修平公式（chxp_v1）白話對照表 — {batch_dir.name}")
    lines.append("")
    lines.append("> 機械抽取自各 `script_*.yaml` 的 `script_method.chxp_v1` 欄（工程代號 chxp＝陳修平公式）。")
    lines.append("> 用途：給免懂工程代號驗貨 —— 左邊是機器代號、中間白話說明、右邊是腳本裡的原值。")
    lines.append("")
    with_chxp = 0
    for p in yamls:
        data = load_frontmatter(p)
        sid = str(data.get("script_id") or p.stem)
        title = _md_cell(_fmt_scalar(data.get("title")))
        chxp = _dig(data, "script_method", "chxp_v1")
        lines.append(f"## {sid}　{title}")
        lines.append("")
        if not isinstance(chxp, dict):
            lines.append("> ⚠️ 此支無 `script_method.chxp_v1` 欄（未套陳修平公式，或欄位結構異常）。")
            lines.append("")
            continue
        with_chxp += 1
        lines.append("| 工程代號欄 | 白話說明 | 原值 |")
        lines.append("|---|---|---|")
        for code, plain, getter in FIELD_MAP:
            val = _md_cell(getter(chxp))
            lines.append(f"| `{code}` | {plain} | {val} |")
        lines.append("")
    return "\n".join(lines) + "\n", len(yamls), with_chxp


def main() -> int:
    ap = argparse.ArgumentParser(description="陳修平公式 chxp_v1 白話對照表產生器")
    ap.add_argument("--batch-dir", required=True, help="批次 yaml 夾絕對路徑")
    ap.add_argument("--out", help="輸出 md 路徑（不給 → 批次夾/_陳修平公式白話對照表_auto.md）")
    args = ap.parse_args()

    batch_dir = Path(args.batch_dir)
    if not batch_dir.exists():
        print(f"[ERROR] 批次夾不存在：{batch_dir}", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else (batch_dir / "_陳修平公式白話對照表_auto.md")
    md, n_yaml, n_chxp = build_table(batch_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[OK] {n_yaml} 支 script yaml，{n_chxp} 支有 chxp_v1 欄 → 對照表已寫：{out_path}")
    if n_yaml == 0:
        print("[WARN] 批次夾找不到 script_*.yaml", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
