"""İSİG Meclisi reports (Tier 2) — adapter stub.

Role in the evidence flow: placeholder only. No fetching or parsing may be
implemented until the source assessment required by
docs/source_assessment_protocol.md is completed and recorded in the source
registry. The foundation build performs no network access for data.
"""

from __future__ import annotations

from mining_accidents.adapters.base import (
    STUB_MESSAGE,
    ClaimDraft,
    SourceAdapter,
    SourceAssessment,
)


class ISIGAdapter(SourceAdapter):
    source_key = "isig"
    adapter_version = "0.0.0"

    def assess(self) -> SourceAssessment:
        raise NotImplementedError(STUB_MESSAGE)

    def fetch(self) -> list[int]:
        raise NotImplementedError(STUB_MESSAGE)

    def parse(self, source_document_id: int) -> list[ClaimDraft]:
        raise NotImplementedError(STUB_MESSAGE)
