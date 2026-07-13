"""Turkish-aware text normalization.

Role in the evidence flow: canonical text preserves Turkish characters
exactly; the ``*_normalized`` search/matching columns are produced here and
only here, so entity resolution and search behave consistently. Never use
Python's default ``str.lower()`` for Turkish input — it maps ``I`` to ``i``,
but Turkish dotless-I rules require ``I -> ı`` and ``İ -> i``.
"""

from __future__ import annotations

import re

#: Turkish-specific uppercase -> lowercase pairs that str.lower() gets wrong.
_TR_CASEFOLD = str.maketrans({"I": "ı", "İ": "i"})

#: Diacritic folding for the *_normalized columns (applied after casefolding,
#: so only lowercase forms are needed).
_ASCII_FOLD = str.maketrans(
    {
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ç": "c",
        "ö": "o",
        "ü": "u",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def turkish_casefold(text: str) -> str:
    """Lowercase with Turkish dotted/dotless-I rules (I -> ı, İ -> i)."""
    return text.translate(_TR_CASEFOLD).lower()


def normalize_tr(text: str) -> str:
    """Normalize Turkish text for ``*_normalized`` columns.

    Steps: Turkish-aware casefold, ASCII-fold diacritics (ş->s, ğ->g, ç->c,
    ö->o, ü->u, ı->i), replace punctuation with spaces, collapse whitespace.
    The canonical (display) columns keep the original text untouched.
    """
    folded = turkish_casefold(text).translate(_ASCII_FOLD)
    return _NON_ALNUM.sub(" ", folded).strip()
