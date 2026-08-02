from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .models import ArchiveBundle, ArchivedTrackedMedia


def archive_tracked_media(bundle: ArchiveBundle, archived_at: datetime, reason: str = "") -> ArchivedTrackedMedia:
    archived_media = replace(bundle.tracked_media, archived_at=archived_at)
    return ArchivedTrackedMedia(replace(bundle, tracked_media=archived_media), archived_at, reason)


def restore_tracked_media(archived: ArchivedTrackedMedia) -> ArchiveBundle:
    return replace(archived.bundle, tracked_media=replace(archived.bundle.tracked_media, archived_at=None))


def active_only(bundles: tuple[ArchiveBundle, ...]) -> tuple[ArchiveBundle, ...]:
    return tuple(bundle for bundle in bundles if not bundle.tracked_media.is_archived)
