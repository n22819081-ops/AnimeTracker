# Franchise Graph Rules

Franchise graphs use explicit AniList source/target IDs and relation types. Direction, target format/status/title, provider, and retrieval time are preserved. Similar titles without an edge remain disconnected.

Supported relation vocabulary includes prequel, sequel, side story, parent, spin-off, alternative, summary, character, other, movie, OVA, ONA, and special. Main-series suggestions use only prequel/sequel/parent evidence. Movie, OVA, ONA, special, side-story, and spin-off edges form branches. Alternative, character, and other edges produce ambiguity warnings.

Connected components may suggest franchise groups, but suggestions remain separate from Jellyfin mappings. Group IDs are deterministic from member AniList IDs; suggestions retain relation evidence, a conservative main title, confidence, confirmation state, and warnings. No title is merged by name alone, no chronology is converted into a Jellyfin season, and no graph operation creates a folder or server mapping.
