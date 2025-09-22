"""Utility functions for multilingual text normalization."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Dict, Tuple

# Precompiled regex patterns for efficiency
ARABIC_DIACRITICS = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭ]')
ARABIC_TATWEEL = 'ـ'
ARABIC_INDIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
EASTERN_ARABIC_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')

# Normalise Arabic characters that commonly appear as stylistic variants
ARABIC_GLYPH_MAP = str.maketrans({
    'آ': 'ا',  # ALEF WITH MADDA ABOVE -> ALEF
    'أ': 'ا',  # ALEF WITH HAMZA ABOVE -> ALEF
    'إ': 'ا',  # ALEF WITH HAMZA BELOW -> ALEF
    'ة': 'ه',  # TEH MARBUTA -> HEH
    'ى': 'ي',  # ALEF MAKSURA -> YEH
    'ٱ': 'ا',  # ALEF WASLA -> ALEF
    'ڣ': 'ث',  # DOTLESS THEH -> THEH
    'ڤ': 'ف',  # DOTLESS FEH -> FEH
    'ک': 'ك',  # KEHEH -> KAF
    'گ': 'ك',  # GAF -> KAF
})

# Map common confusables used in homograph attacks to their ASCII equivalents
HOMOGLYPH_MAP = str.maketrans({
    'ß': 'ss',
    'Ø': 'o',
    '٠': '0',
    '١': '1',
    '٢': '2',
    '٣': '3',
    '٤': '4',
    '٥': '5',
    '٦': '6',
    '٧': '7',
    '٨': '8',
    '٩': '9',
    '۰': '0',
    '۱': '1',
    '۲': '2',
    '۳': '3',
    '۴': '4',
    '۵': '5',
    '۶': '6',
    '۷': '7',
    '۸': '8',
    '۹': '9',
    'Α': 'A',
    'Β': 'B',
    'Ε': 'E',
    'Η': 'H',
    'Ι': 'I',
    'Κ': 'K',
    'Μ': 'M',
    'Ν': 'N',
    'Ο': 'O',
    'Ρ': 'P',
    'Τ': 'T',
    'Υ': 'Y',
    'Χ': 'X',
    'а': 'a',
    'е': 'e',
    'о': 'o',
    'р': 'p',
    'с': 'c',
    'х': 'x',
    'і': 'i',
    'ї': 'i',
})


def normalize_arabic_text(text: str) -> str:
    """Apply Arabic-specific normalisation steps."""
    if not text:
        return text
    normalized = ARABIC_DIACRITICS.sub('', text)
    normalized = normalized.replace(ARABIC_TATWEEL, '')
    normalized = normalized.translate(ARABIC_GLYPH_MAP)
    normalized = normalized.translate(ARABIC_INDIC_DIGITS)
    normalized = normalized.translate(EASTERN_ARABIC_DIGITS)
    return normalized


def fold_confusables(text: str) -> str:
    """Replace homoglyph characters with ASCII equivalents for comparison."""
    if not text:
        return text
    return text.translate(HOMOGLYPH_MAP)


def analyze_script_mix(text: str) -> Dict[str, float]:
    """Return relative frequency of Unicode script classes present in the text."""
    if not text:
        return {}
    counter: Counter[str] = Counter()
    total = 0
    for ch in text:
        script = _script_name(ch)
        if script:
            counter[script] += 1
            total += 1
    if total == 0:
        return {}
    return {key: value / total for key, value in counter.items()}


def normalize_and_summarize(text: str) -> Tuple[str, Dict[str, float]]:
    """Return a folded version of text plus script mix metadata."""
    normalized = fold_confusables(normalize_arabic_text(text))
    return normalized, analyze_script_mix(text)


def _script_name(ch: str) -> str:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return 'other'
    if 'ARABIC' in name:
        return 'arabic'
    if 'LATIN' in name:
        return 'latin'
    if 'CYRILLIC' in name:
        return 'cyrillic'
    if 'GREEK' in name:
        return 'greek'
    if ch.isdigit():
        return 'digit'
    if 'HEBREW' in name:
        return 'hebrew'
    if 'DEVANAGARI' in name:
        return 'devanagari'
    return 'other'
