# Release Security Audit 1.0.0

Static and source-runtime controls passed: no `shell=True`, `eval`, arbitrary template execution, external/bare Python task action, unverified executable PATH lookup, webhook logging, raw SQLite secrets, automatic notification activation, automatic scheduled-task installation, legacy-task disable, broad profile deletion, media write path, Jellyfin mutation, Storage Checker invocation, source-tree runtime dependency, or administrator requirement for normal use.

The UAC helper uses an argument array, an absolute system PowerShell path, a separately named validation task, `RunLevel Limited`, and the packaged EXE as its action. Installer privileges are per-user. Restore/adoption writes are contained to validated application profiles.

**Result: PASS with packaged execution validation blocked.** The controlled environment denied process creation for newly generated unsigned executables before application code ran. Therefore launch, installer lifecycle, and packaged relocation are not claimed as passed. Defender found no threats in all three release targets. This single local scan is not universal antivirus certification.
