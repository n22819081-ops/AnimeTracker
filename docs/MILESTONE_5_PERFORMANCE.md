# Milestone 5 Performance

## Method

Measured on 2026-08-02 with Python 3.12 using `tests/benchmark_matching_v4.py`. The harness builds typed inventory models entirely in memory. It performs no filesystem scan, database access, network request, GUI action, notification, scheduler operation, or Storage Checker invocation.

- One entry: median of 25 candidate generations against one 12-episode item.
- All 69: median of 5 complete passes over 69 synthetic AniList entries against 69 synthetic inventory items (4,761 title/item comparisons and 828 file observations per pass).
- Large inventory: median of 7 candidate generations against one synthetic item containing 4,800 episode observations.
- Rejection: median of 25 generations with an exact-target rejection.
- Review: median of 100 deterministic review generations.
- Many-to-one coverage: median of 100 evaluations of Season 01, Season 02, and Season 00 mappings sharing one inventory item.

## Results

| Workload | Median |
|---|---:|
| One-entry candidate generation | 0.0865 ms |
| All 69 entries against 69 items | 2,292.1660 ms |
| Candidate generation with 4,800 files | 6.3440 ms |
| Rejection filtering | 0.0845 ms |
| Review-case generation | 0.0026 ms |
| Three-scope many-to-one coverage | 0.0225 ms |

The 69-entry test intentionally exercises a broad cross-product and repeatedly fingerprints the complete snapshot for each entry. A future batch coordinator can calculate the snapshot fingerprint once and reuse it, but that optimization is outside Milestone 5. These figures are local engineering baselines, not hardware-independent guarantees.
