#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_trend_report.py — 潮汐週報品管員（9 欄自動擋）

⚠️ DEPRECATED（2026-06-12 零留尾戰役 WP-D — F-16 死閘門根治）：
  本驗證器驗的 report_v2.md / report.md 格式自 2026-05-23 Cyborg 化後不再產出，
  對現行資料 0 標的、批次模式空集合恆 PASS = 守門功能已死（6/11 夜 + 6/12 雙掃描證實）。
  現役守門已遷移：trend-daily\\validate_cyborg_yaml.py（dispatch_to_shortform_system.py
  落地前 fail-closed 驗 cyborg_*.yaml，fail 不落地；fixtures 13/13）。
  pre-commit Part 4 觸發段已同日摘除。本檔保留供歷史 report_v2.md 重驗用，勿掛新流程。

對齊 _知識管理SOP.md §12.2 潮汐 → 編劇銜接 SOP（6 步流程從 Step 1 frontmatter 開始）
參考架構：validate_script_batch.py（15 件自動擋）

9 必驗欄位（frontmatter）：
  finding_id         / suggested_layer     / layer_reason
  has_industry_specific / has_owner_specific / impact_if_misplaced
  evidence_videos    / confidence          / report_type

用法：
  python validate_trend_report.py <report.md>
  python validate_trend_report.py --batch-dir <資料夾>   # 掃資料夾下所有 report_v2.md

PASS → exit 0 / FAIL → exit 1

建檔：2026-05-22 / 對齊 SOP §12.2 Step 1 frontmatter 9 欄
"""

import sys
import os
import re
import argparse
from pathlib import Path
from typing import Optional

# UTF-8 輸出防亂碼（Windows cp950）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ── §12.2 Step 1 — 9 必驗欄位 ──────────────────────────────
# 來源：_知識管理SOP.md §12.2 潮汐 → 編劇銜接 SOP frontmatter schema
REQUIRED_FRONTMATTER_FIELDS = [
    'finding_id',           # 唯一識別碼（例：2026-W21-IG-001）
    'suggested_layer',      # 建議層：L0 / L1 / L2 / L1_房仲 / L1_美容
    'layer_reason',         # 為何建議此層（≥ 1 句具體說明）
    'has_industry_specific',  # true/false — 是否含行業特定資訊
    'has_owner_specific',   # true/false — 是否含業主特定資訊
    'impact_if_misplaced',  # 放錯層的影響（簡述）
    'evidence_videos',      # 證據影片清單（≥ 1 個 URL 或 [unverified: 來源說明]）
    'confidence',           # 信心 %（0-100 整數）
    'report_type',          # weekly_trend / ad_hoc_research / platform_algorithm
]

# ── 報告格式驗證 ─────────────────────────────────────────────
REQUIRED_SECTIONS = [
    '一句話總結',
    'Top 趨勢',
    '跨平台共識',
    '優化建議',
]

# ── 平台清單（2026-05-22 澤君拍板：4 平台）──────────────────
VALID_PLATFORMS = {'IG_Reels', 'FB_Reels', 'TikTok_Global', 'Threads'}
REMOVED_PLATFORMS = {'Douyin_CN', 'Xiaohongshu', '小紅書', '抖音中國'}


# ────────────────────────────────────────────────────────────
# frontmatter 解析
# ────────────────────────────────────────────────────────────
def extract_frontmatter(text: str) -> Optional[dict]:
    """從 markdown 文字抽出 YAML frontmatter（--- ... --- 區間）。"""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            k, _, v = line.partition(':')
            result[k.strip()] = v.strip()
    return result


# ────────────────────────────────────────────────────────────
# 單份報告驗
# ────────────────────────────────────────────────────────────
def validate_one(report_path: Path) -> list[str]:
    """驗單份潮汐週報。回傳問題清單（空 = PASS）。"""
    issues = []

    if not report_path.exists():
        return [f'[FATAL] 找不到報告檔案：{report_path}']

    try:
        text = report_path.read_text(encoding='utf-8')
    except Exception as e:
        return [f'[FATAL] 讀檔失敗：{e}']

    # ── Check 1：frontmatter 存在 ────────────────────────────
    fm = extract_frontmatter(text)
    if fm is None:
        issues.append('[C-001] 缺 YAML frontmatter（--- ... --- 區塊）— §12.2 Step 1 斷點')
        # 沒有 frontmatter 後續欄位驗不下去
        return issues

    # ── Check 2-10：9 必驗欄位齊 ────────────────────────────
    for field in REQUIRED_FRONTMATTER_FIELDS:
        if field not in fm:
            issues.append(f'[C-{2 + REQUIRED_FRONTMATTER_FIELDS.index(field):03d}] '
                          f'缺 frontmatter 欄位：{field}')
        elif not fm[field] or fm[field] in ('', '""', "''", 'null', 'None'):
            issues.append(f'[C-{2 + REQUIRED_FRONTMATTER_FIELDS.index(field):03d}] '
                          f'frontmatter 欄位為空：{field}')

    # ── Check 11：confidence 是 0-100 整數 ──────────────────
    if 'confidence' in fm:
        try:
            conf = int(fm['confidence'].replace('%', '').strip())
            if not 0 <= conf <= 100:
                issues.append(f'[C-011] confidence 值超出範圍（0-100）：{fm["confidence"]}')
        except ValueError:
            issues.append(f'[C-011] confidence 非整數：{fm["confidence"]}')

    # ── Check 12：report_type 合法值 ─────────────────────────
    valid_report_types = {'weekly_trend', 'ad_hoc_research', 'platform_algorithm'}
    if 'report_type' in fm and fm['report_type'] not in valid_report_types:
        issues.append(f'[C-012] report_type 非合法值（應為 {valid_report_types}）：{fm["report_type"]}')

    # ── Check 13：已移除平台不應出現在內文 ──────────────────
    for removed_plat in REMOVED_PLATFORMS:
        if removed_plat in text:
            issues.append(f'[C-013] 報告內文含已移除平台「{removed_plat}」— 2026-05-22 澤君拍板砍除')

    # ── Check 14：evidence_videos 非空 + 至少 1 個 URL 或 [unverified] ─
    if 'evidence_videos' in fm:
        ev = fm['evidence_videos']
        if ev and ev not in ('[]', '""', "''"):
            # 接受 URL（http）或 [unverified: 來源說明]
            has_url = 'http' in ev
            has_unverified = 'unverified' in ev.lower()
            if not (has_url or has_unverified):
                issues.append(
                    f'[C-014] evidence_videos 格式無效 — 需含 URL 或 [unverified: 來源說明]：{ev[:80]}'
                )

    # ── Check 15：報告包含必要段落 ───────────────────────────
    for section in REQUIRED_SECTIONS:
        if section not in text:
            issues.append(f'[C-015] 報告缺必要段落：「{section}」')

    return issues


# ────────────────────────────────────────────────────────────
# 批次驗
# ────────────────────────────────────────────────────────────
def validate_batch(batch_dir: Path) -> bool:
    """掃批次資料夾下所有 report_v2.md / report.md，全 PASS 回 True。"""
    report_files = list(batch_dir.rglob('report_v2.md')) + list(batch_dir.rglob('report.md'))
    if not report_files:
        import sys
        print(
            f'⚠️  validate_trend_report: 0 個 report_v2.md/report.md 標的'
            f' — 此格式 Cyborg 流程後已退役（現產 cyborg_*.yaml），本驗證器目前空轉、非真 PASS',
            file=sys.stderr
        )
        return True  # 空目錄不算失敗（pre-commit exit 語意不變）

    all_pass = True
    for f in sorted(set(report_files)):
        issues = validate_one(f)
        rel = f.relative_to(batch_dir) if f.is_relative_to(batch_dir) else f
        if issues:
            print(f'\n❌ {rel} — {len(issues)} 件問題：')
            for issue in issues:
                print(f'   {issue}')
            all_pass = False
        else:
            print(f'✅ {rel} — PASS')
    return all_pass


# ────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='潮汐週報品管員（9 欄自動擋）— 對齊 §12.2 Step 1 frontmatter'
    )
    parser.add_argument('report', nargs='?', help='單份報告路徑（report_v2.md）')
    parser.add_argument('--batch-dir', help='批次驗：掃資料夾下所有 report_v2.md')
    parser.add_argument('--strict', action='store_true', help='strict 模式（任一 FAIL 即 exit 1）')
    args = parser.parse_args()

    if args.batch_dir:
        batch_dir = Path(args.batch_dir)
        print(f'=== validate_trend_report.py 批次模式：{batch_dir} ===')
        ok = validate_batch(batch_dir)
        if not ok:
            print('\n❌ 批次驗證失敗 — 修正後再 commit')
            print('嚴禁用 git commit --no-verify 繞過')
            sys.exit(1)
        print('\n✅ 批次驗證全 PASS')
        sys.exit(0)

    elif args.report:
        report_path = Path(args.report)
        print(f'=== validate_trend_report.py 單份驗：{report_path} ===')
        issues = validate_one(report_path)
        if issues:
            print(f'\n❌ {len(issues)} 件問題：')
            for issue in issues:
                print(f'   {issue}')
            print('\n嚴禁用 git commit --no-verify 繞過')
            sys.exit(1)
        print('✅ PASS')
        sys.exit(0)

    else:
        # 沒指定報告 → 掃當下趨勢研究資料夾
        default_dir = Path(r'C:\Users\00sta\Documents\Claude\Projects\腳本\短影音趨勢研究')
        print(f'=== validate_trend_report.py 預設掃：{default_dir} ===')
        ok = validate_batch(default_dir)
        sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
