# Credential Migration Guide

Credential migration was explicitly approved and completed on 2026-08-02. A verified pre-settings-change backup was created before reading `notification_config.json`.

Private and shared webhooks are encrypted as separate Windows-user DPAPI blobs. SQLite stores only references, provider, presence, and disabled activation state. Migration sends no message, retains the plaintext legacy file, records only a redacted audit, and rolls back newly stored blobs on failure.

Two separate current-user DPAPI references are present and disabled. The legacy JSON remains unchanged and no message was sent. Activation remains staged: preview, optional channel-specific tests, private delivery, shared delivery, then weekly summaries. Each stage requires separate approval.
