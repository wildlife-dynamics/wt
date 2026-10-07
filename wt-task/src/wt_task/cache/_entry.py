"""The metadata record stored alongside a cached payload."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CacheEntry(BaseModel):
    """Points a step's key at its payload, and says how to read it back.

    Keys and payloads are stored separately so that two steps computing the same
    value share one payload, and so that an entry still describes what a step
    produced after its payload has been evicted.

    Attributes:
        content_id: Path of the payload under `cas/`, derived from the value's
            content digest and namespaced by codec.
        codec_id: Codec that wrote the payload and must read it back.
        media_type: Media type of the payload.
        type_ref: Optional schema fingerprint, for codecs that have one.
        created_at: When the entry was written. Read by TTL expiry.
    """

    content_id: str
    codec_id: str
    media_type: str
    type_ref: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
