# Many-To-One Mapping Rules

Multiple AniList identities may use one server folder because uniqueness is defined by AniList ID plus precise target scope, not folder path.

Example:

| AniList identity | Inventory item | Target |
|---|---|---|
| Season 1 | `Example Anime (2024)` | `SERIES_SEASON`, Season 01 |
| Season 2 | `Example Anime (2024)` | `SERIES_SEASON`, Season 02 |
| OVA | `Example Anime (2024)` | `SERIES_SPECIALS`, Season 00 |

Coverage for each row is independent. Season 01 files cannot satisfy Season 02 or Season 00. The parent folder only supplies shared inventory identity and relation evidence; it never proves franchise-wide presence.

Two AniList IDs claiming the same exact season target produce `DUPLICATE_SEASON_CLAIM`. Multiple distinct seasons on one item are valid. A legacy folder mapping with no season remains `UNKNOWN_TARGET` until manually refined. Movies use `MOVIE_ITEM`; an OVA or ONA may instead be manually confirmed as a separate series or movie when server organization supports it.
