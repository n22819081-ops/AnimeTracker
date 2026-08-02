# Milestone 8 Performance

Measured on 2026-08-02 with the 69-title dataset:

| Operation | Time |
|---|---:|
| Production profile object startup | 0.0164 ms |
| Copy-based database migration | 198.2706 ms |
| Legacy-modern comparison | 1.3104 ms |
| Cached 69-row repository load | 1.9951 ms |
| Cached AniList 69-record load | 0.9958 ms |
| Full status projection | 1.7239 ms |
| Candidate-regeneration setup | 2.1100 ms |
| Dashboard population | 3.8128 ms |
| Verified modern backup | 164.0429 ms |
| Restore validation | 11.0233 ms |
| Diagnostics generation | 7.6477 ms |

The controlled live Jellyfin scan took approximately 370 seconds for 12,335 files and remained outside the GUI thread in production integration.
