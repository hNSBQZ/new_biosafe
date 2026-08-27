"""TTS text normalization."""

from __future__ import annotations

import re

_CHINESE_DIGITS = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}

_BSL_PATTERN = re.compile(
    r"(?<![A-Za-z])(A?BSL|BL|ABSL|P)[-‐]([1-4])(?:级别|级)?(?=\s|$|[^\w]|[\u4e00-\u9fff])",
    re.IGNORECASE,
)
_ALPHA_HYPHEN_NUM_PATTERN = re.compile(
    r"(?<![A-Za-z])([A-Za-z]{1,8})-(\d+)(?=\s|$|[^\w]|[\u4e00-\u9fff])"
)
_DECIMAL_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)(?!\d)")


def normalize_for_tts(text: str) -> str:
    text = _BSL_PATTERN.sub(lambda m: f"{m.group(1).upper()}{_CHINESE_DIGITS[m.group(2)]}级", text)
    text = _DECIMAL_PATTERN.sub(
        lambda m: f"{_digits_to_cn(m.group(1))}点{_digits_to_cn(m.group(2))}",
        text,
    )
    return _ALPHA_HYPHEN_NUM_PATTERN.sub(
        lambda m: f"{m.group(1)}{_digits_to_cn(m.group(2))}",
        text,
    )


def _digits_to_cn(value: str) -> str:
    return "".join(_CHINESE_DIGITS.get(char, char) for char in value)
