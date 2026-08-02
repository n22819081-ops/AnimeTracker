# Milestone 4 Legacy Compatibility

The inventory is not wired into the legacy scanner, production GUI, scheduled check, notifications, matching tables, or live database. It therefore cannot overwrite manual mappings, rejections, overrides, archive state, review decisions, or preserved `On Server` confirmations.

The compatibility test copies the verified Milestone 1 backup to a temporary directory, adapts all 69 active rows before and after a temporary filesystem inventory, and compares the immutable typed results. All 69 remain equal and uniquely representable. The temporary copy passes `PRAGMA integrity_check`; the source backup hash is unchanged.

The service supplies season-scoped files to Milestone 2 domain models without evaluating presence. Existing rules remain authoritative: no mapping is normal `NOT_FOUND`; legacy manual confirmation remains preserved with unknown coverage; releasing coverage requires aired episodes only; finished coverage requires all expected episodes; and special scope remains unresolved until an explicit later decision.

The 421 archived/orphan records remain untouched. No mapping or owner is inferred from inventory paths, titles, years, season folders, or relation data.
