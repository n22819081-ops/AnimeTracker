# Matching Score Rules

The scorer is deterministic and independent from SQLite and GUI state. Components are retained with every candidate so the total is explainable.

| Evidence | Effect |
|---|---:|
| Exact provider title variant | +70 |
| Fuzzy title similarity | scaled positive evidence |
| Matching year | +15 |
| Conflicting folder year | -12 |
| Library/media kind agreement | positive evidence |
| Explicit requested season exists | +50 |
| Season conflict | blocking penalty |
| Episode count/range plausible | positive evidence |
| Season 00 evidence for special content | positive evidence, never automatic confirmation |
| Exact movie evidence in Movies | strong positive evidence |
| Confirmed related parent mapping | positive franchise evidence |
| Existing exact confirmed mapping | +1000 |
| Applicable rejection | -1000 and `REJECTED` confidence |

Explicit season evidence intentionally outweighs a parent folder year mismatch. Season 1 can never satisfy Season 2 because target generation requires the requested season to exist. Movies are generated from Movies inventory only. Similar unrelated names below the evidence threshold are omitted.

The total is an unbounded additive ranking value, not a percentage. The GUI therefore labels it **Match points**. Confidence is classified as follows:

| Confidence | Rule |
|---|---|
| `VERY_STRONG` | 150 points or more, with no blocking conflict |
| `STRONG` | 110-149 points, with no blocking conflict |
| `POSSIBLE` | 75-109 points, with no blocking conflict |
| `WEAK` | 45-74 points, with no blocking conflict |
| `INSUFFICIENT_EVIDENCE` | Fewer than 45 points |
| `CONFLICTING` | Explicit season conflict or media-kind conflict, regardless of points |
| `REJECTED` | An active rejection applies, regardless of points |

Confidence never confirms a mapping. Close candidates, unresolved season scope, movie/TV conflict, mixed folders, special-parent ambiguity, absolute numbering, and active mappings block preselection. Existing confirmed mappings can carry a large historical ranking bonus, which is another reason match points must never be presented as a percentage.
