# Artifact byte savings — all 18 P2-T prune maps (op<0.01 removal → serialized-bytes reduction)

> 2026-08-08. PLY is uniform-per-row ⇒ bytes ≈ removal fraction. Values = 3-seed mean over the
> 18 P2-T prune `final_after_opt` maps. Storage/transfer framing (NOT runtime/refine advance).

| seq | op<0.01 rm% (3-seed mean, range) | serialized-bytes saved |
|---|---|---|
| balloon | 16.2% (12.8–18.4) | ≈11–16% |
| balloon2 | 10.5% (8.8–11.4) | ≈8–11% |
| mv_no_box | 9.4% (8.4–10.0) | ≈8–9% |
| mv_no_box2 | 11.7% (9.6–13.0) | ≈9–11% |
| pt1 | 10.1% (9.9–10.3) | ≈9–10% |
| pt2 | 13.3% (10.5–18.4) | ≈10–16% |

Aggregate: mean removal ≈ 11.9%, bytes saved ≈ 9–16% across sequences.
(Framing: STORAGE/TRANSFER reduction, not refinement/runtime acceleration — per AUTO_REVIEW Round1.)
