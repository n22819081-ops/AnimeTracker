# Diagnostics And Support Reports

Production diagnostics report version, schema, profile state, integrity, backup/cache/scan health, review and outbox counts, credential presence, scheduled-run state, Storage Checker isolation, and media-safety state.

Privacy-safe support reports replace the production path with `Production Profile`, include credential presence only, and omit webhook URLs, full media paths, user/computer identity, anime filenames, and stack traces. A detailed local health view may show the production profile path but never credential values.
