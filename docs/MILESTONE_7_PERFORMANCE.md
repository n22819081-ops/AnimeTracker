# Milestone 7 Performance

Measured on 2026-08-02 with Python 3, PySide6 6.11.1, Qt offscreen mode, the schema-v5 prototype, and median timings from `tests/benchmark_gui_qt_v7.py`.

| Operation | Median |
|---|---:|
| Main-window construction | 465.4148 ms |
| Dashboard population | 4.6719 ms |
| Populate 69-row table | 2.5145 ms |
| Search/filter update | 1.4053 ms |
| Franchise page construction | 4.3740 ms |
| Review page construction | 1.1875 ms |
| Switch across all pages | 0.2004 ms |
| Update one row | 0.0156 ms |
| Create 69 cover placeholders | 1.0330 ms |

Cached interaction is comfortably below visible-freeze thresholds at the current scale. Refresh and scan simulations run through cancellable background workers so painting and input remain available. Network, full inventory, and production delivery performance are intentionally outside Milestone 7.
