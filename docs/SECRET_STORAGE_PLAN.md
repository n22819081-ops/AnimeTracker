# Secret Storage Plan

## Current State

Two Discord webhook URLs are stored in plaintext `data/notification_config.json`. The file is hidden by the GUI and ignored by Git, but Windows ACL behavior means `chmod(0600)` is not sufficient protection. No webhook values were copied into reports, Git, logs, the prototype database, or ordinary modern settings.

## Target Design

Windows Credential Manager is preferred. Windows DPAPI scoped to the current user is the fallback.

The modern database stores only:

- A non-secret credential identifier.
- Channel purpose: `PRIVATE_TRACKER` or `SHARED_ANNOUNCEMENT`.
- Enabled state and non-secret preferences.
- Credential provider name.

Private and shared credentials remain separate and cannot share templates, event rules, baselines, or delivery history.

## Future Reversible Migration

1. Create a verified encrypted backup of the existing JSON beside the immutable modernization baseline.
2. Read one webhook into memory without logging or displaying it.
3. Write it to Credential Manager under a purpose-specific identifier.
4. Read back the credential and compare an in-memory SHA-256 digest; do not send a Discord test.
5. Store only the credential identifier in `credential_references`.
6. Repeat independently for the shared webhook.
7. Keep the plaintext file unchanged until both credentials are verified and rollback is tested.
8. Rename or remove plaintext storage only during a separately approved cutover operation.

## Logging Rules

- Apply webhook URL redaction before any exception or diagnostic reaches logs.
- Log only credential identifiers, channel purpose, HTTP status, and exception type.
- Never include webhook URLs in subprocess arguments, migration reports, exports, crash reports, or notification payload diagnostics.
- Secret migration failures must leave the original JSON intact and report only a non-secret error type.
