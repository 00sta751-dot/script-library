# -*- coding: utf-8 -*-
"""
_build_receipt.py — build 收據共用層（G1，2026-08-14 cxp-enforce-t3-gitgate）

用途：build_*.py 產出 HTML 後，實跑 validate_script_batch.py 並把
「來源稿 hash + validator 實跑結果 + 時間戳 + 產物 hash」寫成收據 JSON。
pre-commit（Part 7）與 validate_deploy（check 19）再驗這張收據，
關掉「不跑 validator 直接交稿」的旁路。

收據落點：<repo>/_build_receipts/<輸出檔名>.receipt.json
  例：wendi.html → _build_receipts/wendi.html.receipt.json
  （原提案叫 _build_receipt.json 單檔；本 repo 有 8+ 業主共用同一目錄，
    單檔會互相覆蓋，故改為 per-output 收據檔＋專用目錄。）

本檔只負責「寫」，驗證邏輯全在 verify_build_receipt.py（single source of truth）。
回退：刪本檔 + build_wendi.py 內 write_build_receipt 呼叫段即可。
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

LIB = os.path.dirname(os.path.abspath(__file__))
# 收據目錄：預設 <repo>/_build_receipts；測試用 GITGATE_RECEIPT_DIR 覆蓋（fixtures 隔離用，正式流程不設）
RECEIPT_DIR = os.environ.get('GITGATE_RECEIPT_DIR') or os.path.join(LIB, '_build_receipts')
SCHEMA = 'build_receipt/v1'

# 收據要納入 hash 的來源副檔名（腳本 yaml + 脆文 md）
SOURCE_EXTS = ('.yaml', '.yml', '.md')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def collect_sources(source_dirs):
    """收集各批次資料夾第一層的來源檔（不遞迴，避開 _superseded_* / _archive）。"""
    out = []
    for d in source_dirs:
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith('.') or name.startswith('_'):
                continue
            fp = os.path.join(d, name)
            if not os.path.isfile(fp):
                continue
            if not name.lower().endswith(SOURCE_EXTS):
                continue
            out.append({
                'path': fp,
                'sha256': sha256_file(fp),
                'size': os.path.getsize(fp),
            })
    return out


def run_validator(py, owner, source_dirs, timeout=600):
    """實跑 validate_script_batch.py --strict（每個批次資料夾各跑一次）。
    回傳 dict：result=PASS/FAIL/ERROR、各批次 returncode 與彙總行。"""
    validator = os.path.join(LIB, 'validate_script_batch.py')
    runs = []
    overall = 'PASS'
    if not os.path.isfile(validator):
        return {
            'tool': 'validate_script_batch.py',
            'result': 'ERROR',
            'error': f'validator 不存在：{validator}',
            'runs': runs,
            'ran_at': datetime.now().isoformat(timespec='seconds'),
        }
    for d in source_dirs:
        d = os.path.abspath(d)
        args = [py, '-X', 'utf8', validator, '--batch-dir', d, '--strict']
        if owner:
            args[4:4] = ['--owner', owner]
        try:
            proc = subprocess.run(
                args, cwd=LIB, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout,
            )
            rc = proc.returncode
            summary = ''
            for line in (proc.stdout or '').splitlines():
                if '品管彙總' in line:
                    summary = line.strip()
            runs.append({
                'batch_dir': d,
                'argv': args[1:],
                'returncode': rc,
                'summary': summary,
                'result': 'PASS' if rc == 0 else 'FAIL',
            })
            if rc != 0:
                overall = 'FAIL'
        except Exception as e:  # timeout / 直譯器炸掉 → ERROR（等同不可信，驗證端當 FAIL）
            runs.append({
                'batch_dir': d,
                'argv': args[1:],
                'returncode': None,
                'summary': '',
                'result': 'ERROR',
                'error': f'{type(e).__name__}: {e}',
            })
            overall = 'ERROR'
    return {
        'tool': 'validate_script_batch.py',
        'result': overall,
        'runs': runs,
        'ran_at': datetime.now().isoformat(timespec='seconds'),
    }


def receipt_path_for(output_path):
    return os.path.join(RECEIPT_DIR, os.path.basename(output_path) + '.receipt.json')


def write_build_receipt(output_path, owner, source_dirs, builder,
                        py=None, extra=None):
    """產出收據並落地。回傳 (receipt_path, receipt_dict)。
    呼叫端請包 try/except：收據寫不出來 = 沒收據 = commit 會被擋（fail-closed，安全側）。"""
    py = py or sys.executable
    source_dirs = [os.path.abspath(d) for d in source_dirs if d]
    output_path = os.path.abspath(output_path)

    sources = collect_sources(source_dirs)
    validator = run_validator(py, owner, source_dirs)

    receipt = {
        'schema': SCHEMA,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'generated_at_epoch': datetime.now().timestamp(),
        'builder': builder,
        'owner': owner or '',
        'python': py,
        'output': {
            'name': os.path.basename(output_path),
            'path': output_path,
            'sha256': sha256_file(output_path),
            'size': os.path.getsize(output_path),
        },
        'source_dirs': source_dirs,
        'sources': sources,
        'validator': validator,
    }
    if extra:
        receipt['extra'] = extra

    os.makedirs(RECEIPT_DIR, exist_ok=True)
    rp = receipt_path_for(output_path)
    with open(rp, 'w', encoding='utf-8') as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return rp, receipt
