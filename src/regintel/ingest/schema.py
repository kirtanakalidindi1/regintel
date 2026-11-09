"""The common shape every source (FDA, MHRA, ...) is normalized into before storage."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class NormalizedUpdate:
    source: str  # "FDA" or "MHRA"
    source_type: str  # e.g. "drug_enforcement"
    source_id: str  # the source's own identifier, e.g. a recall number
    title: str
    url: str  # link back to the official record
    published_date: date | None
    body_text: str  # labelled text the LLM will summarize and cite from
    raw: dict  # the original record, kept for traceability

    @property
    def content_hash(self) -> str:
        """Fingerprint of the raw record, used to detect when a source edits a record."""
        payload = json.dumps(self.raw, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
