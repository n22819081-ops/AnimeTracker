# Rejection And Suppression Rules

A rejection says a particular candidate or target is wrong. Suppression says automatic suggestions for one tracked AniList entry should stop. They are deliberately separate records.

Rejection scopes are candidate/exact target, exact path, folder, stable inventory item, and explicitly selected franchise. An exact Season 01 rejection does not reject Season 02. Folder scope is broader only when the user chooses it. Stable-item rejection survives path case changes and item ordering; if the same path reappears under a materially different stable identity, it creates `UNSTABLE_REJECTED_TARGET` review instead of silently broadening the decision.

Rejections persist until explicitly cleared or an optional expiration passes. Candidate regeneration applies a deterministic penalty and keeps rejected candidates visible as diagnostics, never as the leading automatic suggestion.

`Suppress automatic matching` returns no candidates but leaves confirmed mappings untouched. `Not on Server`, `No valid candidate`, `Skip for now`, and `Clear confirmed mapping` are distinct manual decisions. Not on Server clears the current mapping and blocks weak preselection; it is a normal state, not a rejection, review, archive, or permanent ban. A later explicit manual mapping remains possible.
