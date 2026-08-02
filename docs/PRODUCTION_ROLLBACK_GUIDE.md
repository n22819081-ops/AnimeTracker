# Production Rollback Guide

Rollback requires explicit approval. It disables modern scheduled and notification activation in bootstrap, can disable the modern task and re-enable the legacy task through injected verified task operations, and leaves the modern database intact for diagnosis.

The legacy database, application, launchers, logs, backups, and plaintext config remain available. No media restore is required because Anime Tracker never modifies media. Secure credential blobs remain unless a later explicit cleanup is approved. Do not run both legacy and modern scheduled delivery simultaneously.
