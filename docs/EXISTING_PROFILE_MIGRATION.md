# Existing Profile Adoption

The one-time workflow detects the project-local modern profile and requires explicit confirmation. It creates a verified online pre-adoption backup, copies through a staging directory, verifies database/file hashes, schema, counts, `integrity_check`, `foreign_key_check`, mappings, rejections, candidates, outbox, and redacted DPAPI retrieval, then atomically adopts the target.

The source remains intact as rollback. Nothing is moved or deleted. If a DPAPI blob cannot be decrypted under the current Windows user, it is preserved, delivery stays disabled, and the credential is marked for re-entry. No test Discord message is sent.
