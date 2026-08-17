# -*- coding: utf-8 -*-
"""
tests/test_build_receipt_gate.py — build 收據守門三態測試
（G4，2026-08-14 cxp-enforce-t3-gitgate）

在受控暫存 repo 內測 verify_build_receipt.py 的行為，不碰現役 repo、不做真 commit：
  T1 有新鮮 PASS 收據          → exit 0（過）
  T2 無收據                    → exit 1（拒）
  T3 收據過期（逾時上限）      → exit 1（拒）
  T4 來源稿改過（hash 不符）   → exit 1（拒）
  T5 收據內 validator=FAIL     → exit 1（拒）
  T6 產物被手改（hash 不符）   → exit 1（拒）
  T7 批次多了收據沒驗過的來源檔 → exit 1（拒）
  T8 不在管制名單的產物        → exit 0（跳過，不誤傷）

跑法：python tests/test_build_receipt_gate.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
VERIFIER = os.path.join(LIB, 'verify_build_receipt.py')

results = []


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def make_case(tmp, *, receipt=True, age_hours=1.0, validator_result='PASS',
              mutate_source=False, mutate_output=False, extra_source=False,
              enforced=True, output_name='wendi.html'):
    """在 tmp 下造一組 (產物 + 來源批次 + 收據目錄)，回傳 receipt_dir。"""
    src_dir = os.path.join(tmp, 'batch')
    os.makedirs(src_dir, exist_ok=True)
    src_file = os.path.join(src_dir, 'script_測試_01_01.yaml')
    with open(src_file, 'w', encoding='utf-8') as f:
        f.write('owner: 測試\ntitle: 原始稿\n')
    src_sha = sha256_bytes(open(src_file, 'rb').read())

    out_path = os.path.join(LIB, output_name)  # verifier 以 LIB 為產物根
    receipt_dir = os.path.join(tmp, 'receipts')
    os.makedirs(receipt_dir, exist_ok=True)
    with open(os.path.join(receipt_dir, 'enforced_outputs.txt'), 'w', encoding='utf-8') as f:
        if enforced:
            f.write(output_name + '\n')
        else:
            f.write('# 空名單\n')

    out_sha = sha256_bytes(open(out_path, 'rb').read())
    if mutate_output:
        out_sha = sha256_bytes(b'not the real output')

    if receipt:
        gen = datetime.now() - timedelta(hours=age_hours)
        r = {
            'schema': 'build_receipt/v1',
            'generated_at': gen.isoformat(timespec='seconds'),
            'generated_at_epoch': gen.timestamp(),
            'builder': 'test',
            'owner': '測試',
            'python': sys.executable,
            'output': {'name': output_name, 'path': out_path,
                       'sha256': out_sha, 'size': os.path.getsize(out_path)},
            'source_dirs': [src_dir],
            'sources': [{'path': src_file, 'sha256': src_sha,
                         'size': os.path.getsize(src_file)}],
            'validator': {
                'tool': 'validate_script_batch.py',
                'result': validator_result,
                'runs': [{'batch_dir': src_dir, 'returncode': 0 if validator_result == 'PASS' else 1,
                          'summary': 'test', 'result': validator_result}],
                'ran_at': gen.isoformat(timespec='seconds'),
            },
        }
        with open(os.path.join(receipt_dir, output_name + '.receipt.json'), 'w', encoding='utf-8') as f:
            json.dump(r, f, ensure_ascii=False, indent=2)

    if mutate_source:
        with open(src_file, 'w', encoding='utf-8') as f:
            f.write('owner: 測試\ntitle: 偷改過的稿\n')
    if extra_source:
        with open(os.path.join(src_dir, 'script_測試_01_02.yaml'), 'w', encoding='utf-8') as f:
            f.write('owner: 測試\ntitle: 沒驗過的新稿\n')

    return receipt_dir


def run_verifier(receipt_dir, output_name='wendi.html'):
    env = dict(os.environ)
    env['GITGATE_RECEIPT_DIR'] = receipt_dir
    proc = subprocess.run(
        [sys.executable, '-X', 'utf8', VERIFIER, '--output', output_name],
        cwd=LIB, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env,
    )
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def case(name, expect_rc, **kw):
    tmp = tempfile.mkdtemp(prefix='gitgate_test_')
    try:
        rd = make_case(tmp, **kw)
        rc, out = run_verifier(rd, kw.get('output_name', 'wendi.html'))
        ok = (rc == expect_rc)
        results.append((ok, name, f'expect rc={expect_rc} got rc={rc}'))
        print(f'{"✅" if ok else "❌"} {name}: expect rc={expect_rc} got rc={rc}')
        for line in out.strip().splitlines()[:4]:
            print(f'     {line}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if not os.path.isfile(os.path.join(LIB, 'wendi.html')):
        print('❌ 前置：找不到 wendi.html，無法測試')
        return 1
    print('=== build 收據守門三態測試（受控暫存收據目錄，不動現役）===\n')
    case('T1 有新鮮 PASS 收據 → 過', 0)
    case('T2 無收據 → 拒', 1, receipt=False)
    case('T3 收據過期（100h > 72h 上限）→ 拒', 1, age_hours=100)
    case('T4 來源稿改過 → 拒', 1, mutate_source=True)
    case('T5 收據 validator=FAIL → 拒', 1, validator_result='FAIL')
    case('T6 產物 hash 不符 → 拒', 1, mutate_output=True)
    case('T7 批次多了沒驗過的來源檔 → 拒', 1, extra_source=True)
    case('T8 不在管制名單 → 跳過(過)', 0, enforced=False)

    print('')
    passed = sum(1 for ok, _, _ in results if ok)
    print(f'=== 結果：{passed}/{len(results)} PASS ===')
    for ok, name, detail in results:
        if not ok:
            print(f'  ❌ {name} — {detail}')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
