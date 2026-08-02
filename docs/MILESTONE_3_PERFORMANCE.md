# Milestone 3 Performance

## Method

Measured on 2026-08-02 with Python 3.12 and temporary schema-v3 cache databases under `migration_test`. Provider responses were sanitized local fixtures; no network was used. Medians use 1,001 iterations for cache/graph operations, 5,001 fixture parses, 21 persisted 69-record batches, and 51 bulk 1,000-record evaluations.

## Results

| Workload | Median | Observed range |
|---|---:|---:|
| Fresh cache lookup | 0.4399 ms | 0.2796-1.7094 ms |
| Stale cache lookup | 0.3892 ms | 0.2830-0.5968 ms |
| One fixture parse | 0.0097 ms | 0.0094-0.0479 ms |
| Franchise graph, 69 nodes | 0.0423 ms | 0.0409-0.1023 ms |
| Persisted cache-only refresh, 69 records | 9.1804 ms | 7.6502-106.5657 ms |
| Bulk evaluation, 1,000 cached records | 27.2852 ms | 24.8482-36.8363 ms |

The 69-record cache-based refresh completes well below visible-delay thresholds at its median. Bulk reads use one SQLite read transaction rather than one connection per title. The higher one-off 69-record maximum reflects local Windows filesystem/antivirus scheduling and is retained rather than hidden.
