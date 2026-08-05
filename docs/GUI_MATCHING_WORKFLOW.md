# GUI Matching Workflow

The Needs Review page is sourced from genuine open or acknowledged review cases. Ordinary Not on Server entries are not promoted to review. The review dialog presents the tracked identity, evidence, candidates, confidence, and additive match points.

Suggestions require a user decision. Stale candidates disable confirmation until regenerated. The visible actions cover confirming, choosing another target, rejection, Not on Server, and automatic-match suppression; production persistence remains disabled in the Milestone 7 development profile.

Franchise grouping and Jellyfin mapping stay separate. The franchise tree shows each AniList identity with relation context, format/year, tracker status, mapping scope, and coverage. Season numbering is displayed only from stored mapping scope, never inferred solely from graph order.

Add Anime accepts title, ID, or URL input, optional year/format filters, paging, exact-result selection, and opt-in related entries. It never selects every relation or maps to Jellyfin automatically. Live AniList insertion is not enabled in this milestone; the dialog boundary is ready for the later operations integration.

Review records are joined to canonical metadata before presentation. Each item shows title, AniList ID, format, season/year, review type, severity, explanation, current mapping, and attached candidate evidence. Relation targets in the franchise tree use the centralized title resolver and retain provider direction; season scope comes only from stored mapping data.

Candidate rows are prepared once before the dialog is displayed. Normal table cells contain concise prose such as exact-title match, explicit season scope, detected episode range, expected episode count, year conflict, movie evidence, prior rejection, and confirmed-parent evidence. False booleans that add no useful context are omitted. Raw structured JSON is available only through **Show technical evidence**.

The target and details panel make scope explicit: parent folder, `Season 02` (when supported), confidence, match points, conflict state, and evidence lines are shown before confirmation. A parent Season 1 folder cannot satisfy Season 2 without explicit Season 2 inventory evidence.

The table uses interactive widths, single-line elided summaries, and a separate details panel. It does not auto-fit columns, query SQLite, regenerate evidence, or rebuild the model during resize. Match points include a tooltip stating that they rank candidates and are not percentages.
