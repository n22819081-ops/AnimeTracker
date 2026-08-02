# Discord Shared Announcement Rules

Shared messages are friend-facing and include only availability facts:

- New episodes available, batched into ranges such as `Episodes 4-6`.
- Season complete.
- New series available.
- New anime movie available.
- Optional weekly server summary.

Shared messages never include review details, provider errors, missing paths, rejections, internal mappings, database identifiers, usernames, filesystem data, or scheduled-task health. A movie and series use distinct templates.

Silent delivery sets integer `flags: 4096` in every Discord JSON request body, including every compacted/split part. Disabling silent delivery omits `flags`. Silent Discord messages still appear normally in the channel and may create an unread badge; the flag suppresses push/banner notifications.

The first complete inventory establishes a baseline without announcements. Only later additions or availability changes enqueue messages. Partial scans and temporary outages cannot produce removals. A failed delivery never advances the baseline; explicit acceptance or successful delivery is required.
