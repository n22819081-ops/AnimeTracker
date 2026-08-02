# Code Signing

`Anime Tracker.exe` and `Anime-Tracker-Setup-1.0.0.exe` are unsigned. Windows SmartScreen may warn because the publisher has no reputation-backed certificate. Verify the SHA-256 values in `SHA256SUMS.txt` using `Get-FileHash`.

A future release should use a trusted Authenticode certificate and timestamp both launcher and installer. A self-signed certificate was not used to imply public trust, and no security control was bypassed during this build.
