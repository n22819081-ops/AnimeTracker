# Backup And Restore Guide

Modern backups use SQLite's online backup API and include database hash, integrity result, schema/version metadata, manifest, non-secret settings/bootstrap, and credential-reference metadata. Raw credential values are excluded.

Version 1.0.0 creates backups in the selected per-user profile, never the installation directory. Scheduled checks create a backup before enabled operations. Restore is restricted to the modern profile and should always be validated on disposable data first.

Retention is dry-run only: newest 10, daily representatives for 14 days, and weekly representatives for 12 weeks are retained. Pre-migration and pre-production-cutover checkpoints are always protected; legacy backups are outside retention.

Restore verifies manifest, database hash, integrity, and metadata, creates a pre-restore backup, acquires an exclusive restore lock, and atomically replaces only the modern production database. Controlled restore validation targeted an ignored disposable profile, passed integrity, and preserved all 69 active records. The legacy database is never a restore target.
