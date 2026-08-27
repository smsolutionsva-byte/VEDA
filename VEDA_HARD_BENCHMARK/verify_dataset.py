#!/usr/bin/env python3
# The benchmark dataset is intentionally shipped pre-generated and deterministic.
# Do not regenerate or edit expected outputs while tuning VEDA.
from pathlib import Path
import hashlib
p=Path(__file__).parent/'cases'/'oil_hard_cases.jsonl'
print('cases_sha256=',hashlib.sha256(p.read_bytes()).hexdigest())
print('cases=',sum(1 for _ in p.open(encoding='utf-8')))
