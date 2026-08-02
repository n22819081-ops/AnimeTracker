# AniList Legacy Comparison Report

The modern adapter was evaluated against all 69 active rows from the verified read-only backup using locally constructed typed metadata and sanitized provider fixtures. It can represent and compare English, romaji, native and synonym titles, provider status, season/year, episode count, format, dates, URLs, and relation values without writing the source database.

The legacy client remains unchanged. Differences in provider values are returned field-by-field rather than written automatically. Generic legacy relation labels are retained as unresolved edges with no invented target AniList ID and `provider_confirmed=false`; a future provider refresh can supply confirmed edges while the legacy label remains auditable.

Failure behavior differs intentionally: the modern service returns typed safe errors, preserves stale valid data, and reports partial batches. No live 69-title refresh was performed. All 421 ownerless archived prototype records remain preserved and were not reassigned.
