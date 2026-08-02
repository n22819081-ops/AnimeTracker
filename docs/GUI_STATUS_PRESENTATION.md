# GUI Status Presentation

AniList, tracker workflow, server presence, episode coverage, and review state remain independent dimensions. A releasing title may have complete server coverage; a finished title is omitted from Ready to Add only when current coverage is complete.

Tables use text labels as well as accessible colors. Dashboard Needs Review counts active `review_cases`, not ordinary Not on Server rows. On Server uses complete coverage. Movies show unknown availability honestly when no supported source or manual decision exists.

The detail dialog displays all status dimensions separately and keeps full local paths hidden by default. Season scopes are explicit mapping labels such as Season 00, Season 01, and Season 02; multiple AniList entries can point to one franchise folder without collapsing their identities.

Display titles follow one policy: English, Romaji, native, stored legacy title, then AniList ID only as an emergency fallback. AniList ID remains secondary technical context. Mapping presentation distinguishes `Not mapped`, `Suggestion available`, `Confirmed`, and `Broken`. Coverage distinguishes `Not evaluated`, `Unknown`, `Partial`, and `Complete`. `No confirmed server mapping` means there is no active mapping; `Unknown coverage` is reserved for mapped records without sufficient episode evidence.

Candidate-free review dialogs show an explicit no-candidate explanation and hide target, confidence, path, and evidence fields. Mark Not on Server remains available without a candidate or mapping. Successful actions close the dialog and refresh every page; failures remain visible and keep the dialog open.

Notification event generation and delivery activation are separate states. Private, shared, and Windows checkboxes persist independently. Stage 1 visibly reports Preview Only and keeps delivery activation disabled without making an apparently interactive control silently ignore input.
