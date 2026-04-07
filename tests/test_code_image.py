"""Tests for code_image module — extraction, detection, and rendering."""

from __future__ import annotations

from src.code_image import (
    CodeBlock,
    detect_language,
    extract_code_blocks,
    generate_code_snippet_image,
    render_code_image,
)


# ---------------------------------------------------------------------------
# extract_code_blocks
# ---------------------------------------------------------------------------

def test_extract_single_block():
    text = (
        "Here's a tip:\n"
        "\n"
        "    def hello():\n"
        "        print('world')\n"
        "\n"
        "Try it out!"
    )
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].code == "def hello():\n    print('world')"


def test_extract_multiple_blocks():
    text = (
        "First snippet:\n"
        "\n"
        "    x = 1\n"
        "    y = 2\n"
        "\n"
        "And another:\n"
        "\n"
        "    print(x + y)\n"
    )
    blocks = extract_code_blocks(text)
    assert len(blocks) == 2
    assert blocks[0].code == "x = 1\ny = 2"
    assert blocks[1].code == "print(x + y)"


def test_extract_no_code():
    text = "This post has no code at all.\n\nJust regular text."
    blocks = extract_code_blocks(text)
    assert blocks == []


def test_extract_strips_indent():
    text = "Look:\n\n    const x = 42;\n"
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].code == "const x = 42;"
    # No leading spaces — the 4-space indent was stripped
    assert not blocks[0].code.startswith(" ")


def test_extract_preserves_internal_indent():
    text = (
        "Example:\n"
        "\n"
        "    if True:\n"
        "        nested()\n"
        "            deep()\n"
    )
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert "    nested()" in blocks[0].code
    assert "        deep()" in blocks[0].code


def test_extract_blank_line_inside_block():
    text = (
        "Code:\n"
        "\n"
        "    line1\n"
        "\n"
        "    line2\n"
    )
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].code == "line1\n\nline2"


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------

def test_detect_python():
    code = "def hello():\n    print('world')\n    return True"
    lang = detect_language(code)
    assert lang == "python" or lang == "python3"


def test_detect_fallback():
    # Very short ambiguous snippet
    lang = detect_language("x")
    assert isinstance(lang, str)  # Should return something, not crash


# ---------------------------------------------------------------------------
# render_code_image
# ---------------------------------------------------------------------------

def test_render_returns_valid_png():
    png = render_code_image("print('hello')", language="python")
    assert isinstance(png, bytes)
    assert png[:4] == b"\x89PNG"


def test_render_reasonable_size():
    png = render_code_image("x = 1\ny = 2\nz = 3", language="python")
    # Should be at least a few KB, not empty
    assert len(png) > 500
    # Should not be absurdly large for 3 lines
    assert len(png) < 500_000


def test_render_long_code_truncated():
    long_code = "\n".join(f"line_{i} = {i}" for i in range(100))
    png = render_code_image(long_code, language="python")
    assert isinstance(png, bytes)
    assert png[:4] == b"\x89PNG"


def test_render_empty_code():
    png = render_code_image("", language="text")
    assert isinstance(png, bytes)
    assert png[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# generate_code_snippet_image (end-to-end)
# ---------------------------------------------------------------------------

def test_generate_no_code_returns_none():
    result = generate_code_snippet_image("Just a regular post with no code.")
    assert result is None


def test_generate_with_code_returns_png():
    post = (
        "Here's how to set up a workflow:\n"
        "\n"
        "    from temporal import workflow\n"
        "\n"
        "    @workflow.defn\n"
        "    class MyWorkflow:\n"
        "        @workflow.run\n"
        "        async def run(self):\n"
        "            return await workflow.execute_activity(do_work)\n"
        "\n"
        "This saves hours of debugging."
    )
    result = generate_code_snippet_image(post)
    assert result is not None
    assert result[:4] == b"\x89PNG"
    assert len(result) > 1000  # non-trivial image
