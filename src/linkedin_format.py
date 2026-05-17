"""Convert post text to LinkedIn-ready format.

LinkedIn's composer doesn't render markdown — `**bold**` shows as literal
asterisks, `- bullets` shows as `-`, `` `code` `` shows backticks. This
module rewrites text so it copies cleanly into LinkedIn:

  • Markdown bold (``**X**``) → Unicode Mathematical Bold characters (𝐗)
  • Markdown italic (``*X*`` or ``_X_``) → Unicode Mathematical Italic (𝑋)
  • Leading list markers (``- ``, ``* ``) at line start → ``• ``
  • Backticks stripped (LinkedIn renders them as `)
  • Heading markers (``#`` lines) stripped — LinkedIn has no headings

The Unicode characters used are real characters that survive copy-paste
into any LinkedIn surface (composer, comment, mobile). They are the same
approach used by tools like typegrow.com.

Accessibility note: Unicode-bold characters aren't always read by screen
readers as "bold" — they're read as their Mathematical Alphanumeric
counterparts. For mission-critical accessibility, prefer no emphasis at
all. We err on the side of LinkedIn-native style for posts intended to
perform on the feed.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Unicode character translation
# ---------------------------------------------------------------------------


_BOLD_UPPER_OFFSET = 0x1D400 - ord("A")
_BOLD_LOWER_OFFSET = 0x1D41A - ord("a")
_BOLD_DIGIT_OFFSET = 0x1D7CE - ord("0")

_ITALIC_UPPER_OFFSET = 0x1D434 - ord("A")
_ITALIC_LOWER_OFFSET = 0x1D44E - ord("a")
# Mathematical italic 'h' is unified at U+210E (PLANCK CONSTANT) — special-cased.
_ITALIC_H = "ℎ"


def _bold_char(ch: str) -> str:
    code = ord(ch)
    if 0x41 <= code <= 0x5A:  # A-Z
        return chr(code + _BOLD_UPPER_OFFSET)
    if 0x61 <= code <= 0x7A:  # a-z
        return chr(code + _BOLD_LOWER_OFFSET)
    if 0x30 <= code <= 0x39:  # 0-9
        return chr(code + _BOLD_DIGIT_OFFSET)
    return ch


def _italic_char(ch: str) -> str:
    if ch == "h":
        return _ITALIC_H
    code = ord(ch)
    if 0x41 <= code <= 0x5A:
        return chr(code + _ITALIC_UPPER_OFFSET)
    if 0x61 <= code <= 0x7A:
        return chr(code + _ITALIC_LOWER_OFFSET)
    return ch


def _translate(text: str, translator) -> str:
    return "".join(translator(c) for c in text)


# ---------------------------------------------------------------------------
# Markdown → Unicode replacements
# ---------------------------------------------------------------------------


_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
# *italic* — avoid matching ** by requiring no leading/trailing *
_ITALIC_STAR_RE = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?![\*\w])")
# _italic_ — avoid matching __ and word_word internals
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w_])_([^_\n]+?)_(?![\w_])")


def _replace_bold(match: re.Match) -> str:
    return _translate(match.group(1), _bold_char)


def _replace_italic(match: re.Match) -> str:
    return _translate(match.group(1), _italic_char)


# ---------------------------------------------------------------------------
# Bullet + heading + backtick cleanup
# ---------------------------------------------------------------------------


_BULLET_RE = re.compile(r"^[ \t]*([-*])\s+", re.MULTILINE)
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}\s+", re.MULTILINE)
_BACKTICK_RE = re.compile(r"`+")


def _convert_bullets(text: str) -> str:
    return _BULLET_RE.sub("• ", text)


def _strip_headings(text: str) -> str:
    return _HEADING_RE.sub("", text)


def _strip_backticks(text: str) -> str:
    return _BACKTICK_RE.sub("", text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_linkedin_format(text: str) -> str:
    """Rewrite text so it copies cleanly into LinkedIn's composer.

    Idempotent — running twice on the same text produces the same output.
    """
    if not text:
        return text
    out = _BOLD_RE.sub(_replace_bold, text)
    out = _ITALIC_STAR_RE.sub(_replace_italic, out)
    out = _ITALIC_UNDERSCORE_RE.sub(_replace_italic, out)
    out = _convert_bullets(out)
    out = _strip_headings(out)
    out = _strip_backticks(out)
    return out
