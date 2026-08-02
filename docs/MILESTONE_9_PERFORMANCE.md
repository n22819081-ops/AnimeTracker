# Milestone 9 Performance

Measured on the development Windows 11 machine with a disposable copy of the 69-title modern profile, Python 3.12.10, PySide6 6.11.1, and offscreen Qt. Values are single-run observations, not clean-machine certification.

| Operation | Milliseconds |
|---|---:|
| Existing-profile repository | 0.017 |
| Load 69 rows | 6.742 |
| Dashboard population | 8.558 |
| Construct main window and 12 pages | 130.624 |
| Navigate all pages | 11.863 |
| Search/filter sequence | 0.079 |
| Diagnostics | 11.836 |
| Verified backup | 99.549 |
| Clean profile creation | 171.126 |
| Disabled scheduled check | 28.152 |
| Profile adoption verification | 121.979 |
