"""The metadata record stored alongside a cached payload."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Now, in UTC. One place, so the freshness check can be driven in tests."""
    return datetime.now(timezone.utc)


class CacheEntry(BaseModel):
    """Points a step's key at its payload, and says how to read it back.

    Keys and payloads are stored separately so that two steps computing the same
    value share one payload, and so that an entry still describes what a step
    produced after its payload has been evicted.

    Attributes:
        content_id: `<codec>/<hex>`: the step's root codec and the value's
            content digest, which together locate the payload under `content/`.
        codec_id: Codec that wrote the payload and must read it back.
        media_type: Media type of the payload.
        type_ref: Optional schema fingerprint, for codecs that have one.
        created_at: When the entry was written. Read by the freshness
            check that `WT_CACHE__IO_TTL` puts on io-tagged steps.
    """

    content_id: str
    codec_id: str
    media_type: str
    type_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
