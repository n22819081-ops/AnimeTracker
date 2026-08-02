# Server Inventory Naming Rules

## Supported Patterns

- Season directories: `Season 2`, `Season 02`, `S2`, and `S02`.
- Special directories: `Special`, `Specials`, `Season 0`, `Season 00`, and `S00`.
- Explicit special groups: `OVA`, `OVAs`, `ONA`, and `ONAs`.
- Episode filenames: `S02E03`, `2x03`, `S01E03-E05`, and `S01E03E04`.
- A leading episode number such as `03 - Title` only when an explicit season/special directory provides scope.
- Movie media in a Movies root, whether in a movie folder or directly under the root.
- Media extensions: AVI, M2TS, M4V, MKV, MOV, MP4, MPEG, MPG, TS, WEBM, and WMV.

Season numbers with and without leading zeroes normalize to the same integer. Season 00 never supplies Season 1, and Season 1 never supplies Season 2. Filename suffixes such as `v2` or `v3` do not create replacement semantics.

## Ignored Sidecars And Extras

Artwork, subtitle, and metadata extensions are not media observations. Media beneath explicit Samples, Extras, Trailers, Featurettes, Interviews, Deleted Scenes, Behind the Scenes, or Shorts directories is classified as extra and excluded from episode/movie facts.

## Conservative Behavior

Punctuation, apostrophes, brackets, dots, dashes, Unicode text, and original path spelling are preserved. A standalone year from 1900 through 2199 is recorded as folder evidence only. It does not establish title identity.

Media without reliable season/episode syntax is retained as unrecognized. Explicit OVA/ONA/Specials folders retain numberless media as special evidence but do not invent an episode number. Absolute anime numbering, disc-order numbering, ranges larger than 100 episodes, edition semantics, split cour identity, and Jellyfin metadata IDs are unsupported without stronger evidence.

The parser never infers AniList IDs, title mappings, franchise relationships, season mappings, digital/Blu-ray availability, or workflow state.
