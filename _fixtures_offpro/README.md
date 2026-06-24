Round 2 deterministic hybrid fixtures.

The executable coverage for these cases lives in:

  python validate_script_batch.py --fixtures --expect-enforce

The self-test builds the pass/fail cases in memory to avoid coupling these
fixtures to legacy batch-level checks that are unrelated to the hybrid gates.
This directory is a stable manifest of the required case set for later expansion
into full end-to-end batch directories.

