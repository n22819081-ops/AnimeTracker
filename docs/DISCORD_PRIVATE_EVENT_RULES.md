# Discord Private Event Rules

Private messages explain what changed, title/season/movie identity, episode or airing time when relevant, current provider status, server coverage, missing aired episodes, tracker state, and required action. Absolute local paths are prohibited.

Enabled by default: started airing, new episode aired, series finished, coverage complete, missing aired episodes, confirmed path missing, review required, partial provider refresh failure, and weekly airing summary. Other typed events remain available for explicit filters but are not sent by default.

Examples:

- `New Episode Aired`: `Example Anime Season 2, Episode 4 has aired.` Coverage and missing episode fields may follow.
- `Series Finished Airing`: includes aired total, server coverage, missing episodes, and tracker state.
- `Found on Jellyfin`: `Example Anime Season 2 is now fully available on the server.` Mapping is shown as `Season 02`, never a path.

Windows notifications may mirror selected private events. Their failure is isolated and does not alter Discord delivery truth.
