"""Field validators, model rules, and geography checks (synthetic data only)."""

from __future__ import annotations

import pytest

from mining_accidents import geography, validators
from mining_accidents.models import Claim, ClaimDecision, IncidentClassification


def test_excerpt_word_cap_accepts_short() -> None:
    assert validators.validate_excerpt_word_cap("TEST short excerpt") == "TEST short excerpt"
    assert validators.validate_excerpt_word_cap(None) is None


def test_excerpt_word_cap_rejects_overlong() -> None:
    long_excerpt = " ".join(["kelime"] * 41)
    with pytest.raises(validators.ValidationError, match="cap is 40"):
        validators.validate_excerpt_word_cap(long_excerpt)


def test_province_code_validation() -> None:
    assert validators.validate_province_code("34") == "34"
    assert validators.validate_province_code(None) is None
    with pytest.raises(validators.ValidationError, match="Unknown province"):
        validators.validate_province_code("99")


def test_classification_code_validation() -> None:
    assert validators.validate_classification_code("project_hazard", "methane") == "methane"
    with pytest.raises(validators.ValidationError):
        validators.validate_classification_code("project_hazard", "not_a_code")
    # External systems are not validated against project vocabularies.
    assert validators.validate_classification_code("ESAW", "TEST-EXTERNAL") == "TEST-EXTERNAL"


def test_iso_datetime_validation() -> None:
    assert (
        validators.validate_iso_datetime("2099-01-01T03:15:00+03:00") == "2099-01-01T03:15:00+03:00"
    )
    with pytest.raises(validators.ValidationError):
        validators.validate_iso_datetime("13/01/2099")


def test_ai_assisted_claim_model_forces_needs_review() -> None:
    claim = Claim(
        source_document_id=1,
        field_name="fatalities_current",
        extraction_method="ai_assisted",
        review_status="pending",
    )
    assert claim.review_status == "needs_review"


def test_manual_claim_keeps_given_status() -> None:
    claim = Claim(
        source_document_id=1,
        field_name="fatalities_current",
        extraction_method="manual",
        review_status="pending",
    )
    assert claim.review_status == "pending"


def test_manual_override_requires_supporting_claims() -> None:
    with pytest.raises(ValueError, match="rationale_claim_ids"):
        ClaimDecision(
            incident_id=1,
            field_name="province_code",
            decision="manual_override",
            manual_value="35",
            rationale="TEST harmonized spelling",
            reviewer="TEST-reviewer",
        )


def test_accept_claim_requires_selected_claim() -> None:
    with pytest.raises(ValueError, match="selected_claim_id"):
        ClaimDecision(
            incident_id=1,
            field_name="province_code",
            decision="accept_claim",
            rationale="TEST",
            reviewer="TEST-reviewer",
        )


def test_project_classification_reviewed_needs_source_claim() -> None:
    with pytest.raises(ValueError, match="source_claim_id"):
        IncidentClassification(
            incident_id=1,
            classification_system="project_hazard",
            classification_code="methane",
            review_status="reviewed",
        )


def test_bbox_flags_are_heuristic_not_rejection() -> None:
    flags = geography.check_coordinates(48.85, 2.35, "settlement")  # outside Türkiye
    assert any("heuristic" in f for f in flags)
    assert geography.check_coordinates(39.0, 32.8, "settlement") == []


def test_coordinates_without_precision_flagged() -> None:
    flags = geography.check_coordinates(39.0, 32.8, None)
    assert any("precision missing" in f for f in flags)


def test_exact_pin_contract() -> None:
    assert geography.may_render_exact_pin("exact_verified")
    assert geography.may_render_exact_pin("facility_approximate")
    for precision in ("settlement", "district_centroid", "province_centroid", "unknown", None):
        assert not geography.may_render_exact_pin(precision)
