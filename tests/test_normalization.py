"""Turkish normalization — the İ/ı cases are tested explicitly per spec §9."""

from __future__ import annotations

from mining_accidents.normalization import normalize_tr, turkish_casefold


def test_dotless_capital_i_casefolds_to_dotless_lowercase() -> None:
    # Turkish: I -> ı (Python's default .lower() wrongly gives 'i').
    assert turkish_casefold("I") == "ı"
    assert turkish_casefold("ISPARTA") == "ısparta"


def test_dotted_capital_i_casefolds_to_dotted_lowercase() -> None:
    # Turkish: İ -> i.
    assert turkish_casefold("İ") == "i"
    assert turkish_casefold("İSTANBUL") == "istanbul"


def test_mixed_turkish_casefold() -> None:
    assert turkish_casefold("DİYARBAKIR") == "diyarbakır"
    assert turkish_casefold("IĞDIR") == "ığdır"


def test_python_default_lower_would_be_wrong() -> None:
    # Documents why turkish_casefold exists: the default is incorrect for tr.
    assert "ISPARTA".lower() == "isparta"  # wrong for Turkish
    assert turkish_casefold("ISPARTA") == "ısparta"  # correct


def test_normalize_tr_ascii_folds_diacritics() -> None:
    assert normalize_tr("şğıçöü") == "sgicou"
    assert normalize_tr("İSTANBUL") == "istanbul"
    assert normalize_tr("IĞDIR") == "igdir"


def test_normalize_tr_punctuation_and_whitespace() -> None:
    assert normalize_tr("TEST  Madencilik   A.Ş.") == "test madencilik a s"
    assert normalize_tr("  Çayırhan-2 (TEST) ") == "cayirhan 2 test"


def test_normalize_tr_empty_and_symbol_only() -> None:
    assert normalize_tr("") == ""
    assert normalize_tr("...!?") == ""


def test_canonical_text_is_not_touched_by_normalization_helpers() -> None:
    # Canonical columns keep Turkish characters exactly; normalize_tr is only
    # for *_normalized columns. Guard the input is not mutated.
    original = "TEST Kömür İşletmesi"
    normalize_tr(original)
    assert original == "TEST Kömür İşletmesi"
