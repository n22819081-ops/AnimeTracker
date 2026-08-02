# Notification Privacy Rules

Privacy filtering runs before enqueue and before delivery. It rejects or redacts full Windows paths, Discord webhook URLs, token/API-key/password forms, stack traces, raw headers, and explicit secret-bearing fields.

Allowed labels include `Example Anime (2024), Season 02`, `Season 00`, and `Movies library`. Shared templates expose no internal review, provider, database, username, computer, or filesystem details.

Errors are reduced to a redacted type and first-line summary of at most 300 characters. Credential values use a redacted wrapper whose string and representation never reveal the value. Modern SQLite stores only credential provider and identifier references.
