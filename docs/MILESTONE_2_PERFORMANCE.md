# Milestone 2 Performance

## Method

Measured on 2026-08-01 with the project Python 3.12 virtual environment. Timing used `time.perf_counter_ns()` around only pure `decide_status` calls. No database, filesystem, network, GUI, or notification operation occurred inside the measured engine.

- One-decision result is derived from the median of 11 batches of 10,000 identical deterministic decisions.
- Current-record result is the median of 101 passes over 69 rows adapted from the verified read-only backup.
- Synthetic result is the median of 31 passes over 1,000 inputs.

## Results

| Workload | Median | Observed range |
|---|---:|---:|
| One status decision | 3.8936 microseconds | Batch range 38.6080-41.5736 ms per 10,000 |
| All 69 current records | 0.2323 ms | 0.2300-0.2877 ms |
| 1,000 synthetic records | 3.8425 ms | 3.8224-3.9137 ms |

The pure engine is well below a visible UI delay for the current collection. These figures are a local engineering baseline, not a cross-machine guarantee.
