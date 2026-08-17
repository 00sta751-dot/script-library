# -*- coding: utf-8 -*-
"""
verify_build_receipt.py — build 收據驗證器（G2/G3 共用，2026-08-14 cxp-enforce-t3-gitgate）

驗一張 _build_receipts/<output>.receipt.json 是否「存在＋新鮮＋PASS」：
  R1 收據存在、可解析、schema 對
  R2 validator 實跑結果 = PASS（FAIL/ERROR 一律擋）
  R3 來源稿新鮮：收據內每個來源檔的 sha256 對得上當前磁碟內容；
     來源檔消失、或批次資料夾冒出收據沒收錄的新來源檔 → 視為過期
  R4 產物新鮮：收據內 output.sha256 對得上「要進 commit 的那份內容」
     （--staged：有 staged 就比 staged blob，否則比工作區檔案）
  R5 時效：收據 age <= 上限（預設 72 小時，env GITGATE_RECEIPT_MAX_AGE_HOURS 可調）

用法：
  python verify_build_receipt.py --output wendi.html            # 比工作區
  python verify_build_receipt.py --output wendi.html --staged   # pre-commit 用
  python verify_build_receipt.py --all-enforced --staged
  python verify_build_receipt.py --list-enforced

exit：0 = 全過；1 = 有 FAIL。

管制名單：_build_receipts/enforced_outputs.txt（一行一個輸出檔名，# 為註解）。
名單檔不存在時 fallback 到 DEFAULT_ENFORCED（最小可行：wendi.html）。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

LIB = os.path.dirname(os.path.abspath(__file__))
# 收據目錄：預設 <repo>/_build_receipts；測試用 GITGATE_RECEIPT_DIR 覆蓋（fixtures 隔離用，正式流程不設）
RECEIPT_DIR = os.environ.get('GITGATE_RECEIPT_DIR') or os.path.join(LIB, '_build_receipts')
ENFORCED_LIST = os.path.join(RECEIPT_DIR, 'enforced_outputs.txt')
GRANDFATHER_FILE = os.path.join(RECEIPT_DIR, 'grandfathered.json')
SCHEMA = 'build_receipt/v1'
DEFAULT_ENFORCED = ['wendi.html']
DEFAULT_MAX_AGE_HOURS = 72.0
SOURCE_EXTS = ('.yaml', '.yml', '.md')


def max_age_hours():
    raw = os.environ.get('GITGATE_RECEIPT_MAX_AGE_HOURS', '').strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_MAX_AGE_HOURS


def enforced_outputs():
    if os.path.isfile(ENFORCED_LIST):
        names = []
        with open(ENFORCED_LIST, encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if line:
                    names.append(line)
        return names
    return list(DEFAULT_ENFORCED)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _git(args, binary=False):
    proc = subprocess.run(['git'] + args, cwd=LIB, capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout if binary else proc.stdout.decode('utf-8', 'replace')


def staged_paths():
    out = _git(['diff', '--cached', '--name-only'])
    if not out:
        return []
    return [p.strip() for p in out.splitlines() if p.strip()]


def receipt_path_for(name):
    return os.path.join(RECEIPT_DIR, os.path.basename(name) + '.receipt.json')


def load_grandfather():
    """裝閘當下既存產物的豁免名冊（只認固定 sha256；產物內容一改就失效）。"""
    if not os.path.isfile(GRANDFATHER_FILE):
        return {}
    try:
        with open(GRANDFATHER_FILE, encoding='utf-8') as f:
            return json.load(f).get('entries', {})
    except Exception:
        return {}


def verify_output(name, use_staged=False, allow_grandfather=False):
    """回傳 (ok: bool, msgs: list[str])。msgs 全是人話，直接給人看。"""
    msgs = []
    rp = receipt_path_for(name)

    # ── R1 收據存在 / 可解析 ──
    if not os.path.isfile(rp):
        # 裝閘當下的既存產物：只在 deploy 端（allow_grandfather）且內容完全沒動過時放行，
        # 大聲留痕。內容一改 → hash 不合 → 立刻回到硬擋。pre-commit 端不吃這條。
        if allow_grandfather:
            gf = load_grandfather().get(name)
            cur = os.path.join(LIB, name)
            if gf and os.path.isfile(cur) and sha256_file(cur) == gf.get('sha256'):
                msgs.append(f'⚠ {name}: 無 build 收據，但內容與裝閘當下完全相同 '
                            f'（grandfathered @ {gf.get("recorded_at")}）→ 本次放行、已留痕')
                msgs.append(f'   原因：{gf.get("reason", "")}')
                msgs.append(f'   一旦重跑 build 或手改此檔，hash 即不符 → 立刻恢復硬擋，必須附收據')
                return True, msgs
        msgs.append(f'❌ {name}: 找不到 build 收據 {os.path.relpath(rp, LIB)}'
                    f' — 這份產物沒有「跑過 validator」的證明，拒絕 commit')
        msgs.append(f'   修法：重跑對應 build 腳本（會自動實跑 validate_script_batch.py 並寫收據）')
        return False, msgs
    try:
        with open(rp, encoding='utf-8') as f:
            r = json.load(f)
    except Exception as e:
        msgs.append(f'❌ {name}: 收據解析失敗（{type(e).__name__}: {e}）→ 視同無收據')
        return False, msgs
    if r.get('schema') != SCHEMA:
        msgs.append(f'❌ {name}: 收據 schema 不是 {SCHEMA}（拿到 {r.get("schema")!r}）→ 視同無收據')
        return False, msgs

    ok = True

    # ── R2 validator 結果 ──
    v = r.get('validator') or {}
    vres = v.get('result')
    if vres != 'PASS':
        ok = False
        msgs.append(f'❌ {name}: 收據內 validator 結果 = {vres!r}（非 PASS）— 稿件品管沒過，拒絕 commit')
        for run in (v.get('runs') or []):
            if run.get('result') != 'PASS':
                msgs.append(f'   ↳ {os.path.basename(run.get("batch_dir", "?"))}: '
                            f'rc={run.get("returncode")} {run.get("summary") or run.get("error", "")}')

    # ── R5 時效 ──
    epoch = r.get('generated_at_epoch')
    if not isinstance(epoch, (int, float)):
        ok = False
        msgs.append(f'❌ {name}: 收據缺 generated_at_epoch，無法判新鮮度 → 視同過期')
    else:
        age_h = (datetime.now().timestamp() - float(epoch)) / 3600.0
        limit = max_age_hours()
        if age_h > limit:
            ok = False
            msgs.append(f'❌ {name}: 收據已過期（{age_h:.1f} 小時 > 上限 {limit:.0f} 小時，'
                        f'產生於 {r.get("generated_at")}）— 重跑 build 再 commit')
        elif age_h < -0.2:
            ok = False
            msgs.append(f'❌ {name}: 收據時間在未來（{r.get("generated_at")}）— 時鐘或收據被動過手腳，拒收')

    # ── R3 來源稿新鮮 ──
    recorded = {}
    for s in (r.get('sources') or []):
        recorded[os.path.abspath(s.get('path', ''))] = s.get('sha256')
    if not recorded:
        ok = False
        msgs.append(f'❌ {name}: 收據沒記錄任何來源稿 — 無法證明驗的是這批稿，拒收')
    for path, want in recorded.items():
        if not os.path.isfile(path):
            ok = False
            msgs.append(f'❌ {name}: 來源稿已不存在：{path} — 收據過期')
            continue
        got = sha256_file(path)
        if got != want:
            ok = False
            msgs.append(f'❌ {name}: 來源稿改過但沒重跑 build：{os.path.basename(path)}'
                        f'（收據 {str(want)[:12]}… / 現在 {got[:12]}…）')
    # 新增來源檔（收據沒收錄）也算過期
    for d in (r.get('source_dirs') or []):
        if not os.path.isdir(d):
            ok = False
            msgs.append(f'❌ {name}: 收據記錄的批次資料夾不存在：{d} — 收據過期')
            continue
        for fn in sorted(os.listdir(d)):
            if fn.startswith('.') or fn.startswith('_'):
                continue
            fp = os.path.join(d, fn)
            if not os.path.isfile(fp) or not fn.lower().endswith(SOURCE_EXTS):
                continue
            if os.path.abspath(fp) not in recorded:
                ok = False
                msgs.append(f'❌ {name}: 批次多了收據沒驗過的來源檔：{fn} — 重跑 build 再 commit')

    # ── R4 產物新鮮 ──
    out_want = (r.get('output') or {}).get('sha256')
    rel = os.path.relpath(os.path.join(LIB, name), LIB)
    got_out = None
    src_desc = '工作區'
    if use_staged and rel in staged_paths():
        blob = _git(['show', f':{rel}'], binary=True)
        if blob is None:
            ok = False
            msgs.append(f'❌ {name}: 讀不到 staged 內容（git show :{rel} 失敗）')
        else:
            got_out = sha256_bytes(blob)
            src_desc = 'staged'
    if got_out is None and os.path.isfile(os.path.join(LIB, name)):
        got_out = sha256_file(os.path.join(LIB, name))
    if got_out is None:
        ok = False
        msgs.append(f'❌ {name}: 產物檔不存在，無法比對收據')
    elif got_out != out_want:
        ok = False
        msgs.append(f'❌ {name}: 要 commit 的 HTML（{src_desc}）與收據記錄的產物不一致'
                    f'（收據 {str(out_want)[:12]}… / {src_desc} {got_out[:12]}…）'
                    f' — 產物被手改或非本次 build 產出，拒絕 commit')

    if ok:
        msgs.append(f'✅ {name}: 收據新鮮且 validator=PASS'
                    f'（{r.get("generated_at")}，來源 {len(recorded)} 檔，比對來源={src_desc}）')
    return ok, msgs


def main():
    ap = argparse.ArgumentParser(description='驗 build 收據（存在＋新鮮＋PASS）')
    ap.add_argument('--output', action='append', default=[],
                    help='要驗的產物檔名（可重複），如 wendi.html')
    ap.add_argument('--all-enforced', action='store_true', help='驗管制名單全部')
    ap.add_argument('--staged', action='store_true', help='產物比對 staged blob（pre-commit 用）')
    ap.add_argument('--list-enforced', action='store_true', help='印出管制名單後結束')
    ap.add_argument('--quiet-pass', action='store_true', help='全過時不印細節')
    ap.add_argument('--allow-grandfather', action='store_true',
                    help='允許裝閘當下既存產物（內容 hash 未變者）在無收據時放行並留痕（deploy 端用）')
    a = ap.parse_args()

    if a.list_enforced:
        for n in enforced_outputs():
            print(n)
        return 0

    targets = list(a.output)
    if a.all_enforced or not targets:
        targets = enforced_outputs()
    # 只驗管制名單內的（名單外的產物尚未接線，驗了必然無收據）
    allow = set(enforced_outputs())
    skipped = [t for t in targets if t not in allow]
    targets = [t for t in targets if t in allow]
    for s in skipped:
        print(f'⏭️ {s}: 不在收據管制名單（{os.path.relpath(ENFORCED_LIST, LIB)}），跳過')

    if not targets:
        print('⏭️ 沒有需要驗收據的產物')
        return 0

    all_ok = True
    for t in targets:
        ok, msgs = verify_output(t, use_staged=a.staged,
                                 allow_grandfather=a.allow_grandfather)
        all_ok = all_ok and ok
        if not ok or not a.quiet_pass:
            for m in msgs:
                print(m)
    if not all_ok:
        print('')
        print('❌ build 收據守門擋住 — 交稿必附「跑過 validator」的新鮮證明')
        print('   修法：重跑該業主的 build 腳本（會實跑 validate_script_batch.py 並更新收據），'
              '確認 validator PASS 後再 commit')
        print('   嚴禁用 git commit --no-verify 繞過（--no-verify 跳得過本機 hook，'
              '但 validate_deploy.py check 19 上站前會再擋一次）')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
