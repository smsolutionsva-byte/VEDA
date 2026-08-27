#!/usr/bin/env bash
set -euo pipefail
python VEDA_HARD_BENCHMARK/integration_audit.py
python VEDA_HARD_BENCHMARK/run_hard_benchmark.py --mode full --backend bge-m3
