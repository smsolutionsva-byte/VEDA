# Case Matrix

Total cases: **382**

| Category | Count |
|---|---:|
| ambiguity | 36 |
| asset_tags | 52 |
| graph | 44 |
| location | 44 |
| metadata | 40 |
| safety_reporting | 54 |
| temporal | 40 |
| terminology | 42 |
| wbs | 30 |

## Expected outcomes
- `match`: a single correct activity should be retrieved and safely linked.
- `review`: the system should abstain / request planner review.
- `duplicate`: duplicate evidence should not advance progress again.
- `historical`: old evidence should remain historical rather than current progress.