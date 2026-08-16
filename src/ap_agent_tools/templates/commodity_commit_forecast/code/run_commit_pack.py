#!/usr/bin/env python3
"""Example deterministic entrypoint (stub).

Real implementation would:
 1) load MANIFEST.yaml inputs
 2) run bom_explode -> allocate -> net
 3) apply labels/overrides.jsonl
 4) write outputs/

This stub only documents the contract for the example package.
"""

def main():
    print("ap-example: run_commit_pack stub - see GUIDELINE.md method steps")
    print("Deterministic engines only; overrides applied after engine pass.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
