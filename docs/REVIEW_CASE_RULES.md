# Review Case Rules

Review cases are typed, stable records with `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`, and `SUPERSEDED` lifecycle states. Evidence, candidate IDs, mapping IDs, timestamps, resolution, and user note are retained.

Cases are created for close strong candidates, conflicting active mappings, duplicate exact-season claims, missing confirmed paths or seasons, movie/series conflict, unresolved special parent, absolute numbering, legacy unknown season scope, changed inventory identity, and rejected targets reappearing through unstable identity.

Cases are not created for zero candidates, normal Not on Server state, upcoming anime, transient provider/server outages, partial/canceled inventory alone, or archived entries.

Review IDs derive from profile, AniList ID, review type, and stable target/mapping identities. Regenerating a session updates the existing case instead of duplicating it. Confirmation resolves only review types addressed by that target; unrelated cases remain open. Missing confirmed content marks the mapping broken and preserves it. Repeated missing scans do not duplicate broken-history events, and no alternative mapping silently replaces it.
