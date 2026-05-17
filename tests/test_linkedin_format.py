"""Tests for src/linkedin_format.py."""

from __future__ import annotations

from src.linkedin_format import to_linkedin_format


def test_bold_to_unicode_bold():
    assert to_linkedin_format("**Hello**") == "𝐇𝐞𝐥𝐥𝐨"


def test_bold_with_digits():
    assert to_linkedin_format("**2026**") == "𝟐𝟎𝟐𝟔"


def test_italic_star_to_unicode_italic():
    assert to_linkedin_format("*hello*") == "ℎ𝑒𝑙𝑙𝑜"


def test_italic_underscore_to_unicode_italic():
    assert to_linkedin_format("_hello_") == "ℎ𝑒𝑙𝑙𝑜"


def test_italic_h_uses_planck_constant():
    assert to_linkedin_format("*h*") == "ℎ"


def test_does_not_apply_italic_inside_word():
    # snake_case should NOT be italicized
    assert "𝑠" not in to_linkedin_format("function snake_case_name(x)")


def test_does_not_apply_star_italic_to_bold():
    # ** stays bold, not italic
    result = to_linkedin_format("**bold**")
    assert "𝐛" in result
    assert "𝑏" not in result


def test_dash_bullet_to_unicode_bullet():
    assert to_linkedin_format("- one\n- two") == "• one\n• two"


def test_asterisk_bullet_to_unicode_bullet():
    assert to_linkedin_format("* item\n* item2") == "• item\n• item2"


def test_indented_bullet_normalized():
    assert to_linkedin_format("  - nested item") == "• nested item"


def test_inline_dash_not_treated_as_bullet():
    # "well-known" must not become "• known"
    assert "•" not in to_linkedin_format("This is a well-known fact.")


def test_strip_backticks():
    assert to_linkedin_format("Use `Temporal` here") == "Use Temporal here"


def test_strip_heading_marker():
    assert to_linkedin_format("# Heading\nbody") == "Heading\nbody"


def test_full_post_round_trip():
    src = (
        "Most engineers retry API calls with exponential backoff.\n\n"
        "They miss the real problem.\n\n"
        "**Idempotency** is what matters.\n\n"
        "- key one\n"
        "- key two\n"
        "- key three\n\n"
        "What's your biggest *retry* mistake?"
    )
    out = to_linkedin_format(src)
    assert "**" not in out
    assert "𝐈𝐝𝐞𝐦𝐩𝐨𝐭𝐞𝐧𝐜𝐲" in out
    assert out.count("• ") == 3
    assert "-" not in out.split("\n\n")[3]  # bullets section has no dashes
    # italic *retry*: the 'r' should not be a regular 'r'
    assert "𝑟𝑒𝑡𝑟𝑦" in out


def test_idempotent_when_already_formatted():
    text = "𝐇𝐞𝐥𝐥𝐨 world\n• one\n• two"
    assert to_linkedin_format(text) == text


def test_empty_string_returns_empty():
    assert to_linkedin_format("") == ""


def test_none_safe():
    assert to_linkedin_format(None) is None
