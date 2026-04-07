"""Generate beautiful code snippet images for social media posts.

Extracts code blocks from LinkedIn post text and renders them as styled PNG
images using Pygments for syntax highlighting and Pillow for rendering.
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from pygments import lex
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
from pygments.styles import get_style_by_name
from pygments.token import Token

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Code block extraction
# ---------------------------------------------------------------------------

@dataclass
class CodeBlock:
    """A code block extracted from post text."""
    code: str
    start_line: int


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """Extract 4-space indented code blocks from post text.

    Matches the convention used by the post generator prompt which requires
    code snippets indented with 4 spaces.
    """
    lines = text.splitlines()
    blocks: list[CodeBlock] = []
    current_lines: list[str] = []
    block_start = 0
    blank_run = 0

    for i, line in enumerate(lines):
        if line.startswith("    ") and line.strip():
            if blank_run > 1 and current_lines:
                # Large gap — flush current block, start new one
                _flush_block(blocks, current_lines, block_start)
                current_lines = []
            if not current_lines:
                block_start = i
            current_lines.append(line[4:])  # strip 4-space indent
            blank_run = 0
        elif not line.strip() and current_lines:
            # Blank line inside a code block — preserve it
            blank_run += 1
            current_lines.append("")
        else:
            if current_lines:
                _flush_block(blocks, current_lines, block_start)
                current_lines = []
            blank_run = 0

    # Flush last block
    if current_lines:
        _flush_block(blocks, current_lines, block_start)

    return blocks


def _flush_block(blocks: list[CodeBlock], lines: list[str], start: int) -> None:
    # Trim trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        blocks.append(CodeBlock(code="\n".join(lines), start_line=start))


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_KEYWORD_HINTS = [
    (r"\bdef\b.*:\s*$|\bimport\b|\bprint\s*\(", "python"),
    (r"\bfunc\b|\bpackage\b|\bgo\b.*\{|\bfmt\.", "go"),
    (r"\bconst\b|\blet\b|\bvar\b.*=|=>\s*\{|\bconsole\.", "javascript"),
    (r"\bfn\b|\blet\s+mut\b|\bimpl\b|\buse\s+\w+::", "rust"),
    (r"^\s*\w+:\s*\n|^\s*-\s+\w+:", "yaml"),
    (r"^\s*FROM\b|^\s*RUN\b|^\s*CMD\b", "docker"),
    (r"<\w+>.*</\w+>|<\w+\s*/?>", "html"),
]


def detect_language(code: str) -> str:
    """Detect programming language from code content.

    Uses keyword heuristics first (more reliable for short snippets),
    then falls back to Pygments guess_lexer.
    Returns a Pygments lexer alias (e.g. 'python', 'go', 'yaml').
    """
    import re as _re  # noqa: PLC0415

    # Keyword-based heuristics for common languages
    for pattern, lang in _KEYWORD_HINTS:
        if _re.search(pattern, code, _re.MULTILINE):
            return lang

    try:
        lexer = guess_lexer(code)
        return lexer.aliases[0] if lexer.aliases else "text"
    except Exception:  # noqa: BLE001
        return "text"


# ---------------------------------------------------------------------------
# Image rendering
# ---------------------------------------------------------------------------

# Layout constants
_FONT_SIZE = 16
_LINE_HEIGHT = 24
_PADDING_X = 32
_PADDING_Y = 40
_CORNER_RADIUS = 12
_MAX_LINES = 30
_TITLE_BAR_HEIGHT = 36
_DOT_RADIUS = 6
_DOT_Y = _TITLE_BAR_HEIGHT // 2
_DOT_COLORS = ("#ff5f56", "#ffbd2e", "#27c93f")  # close, minimize, maximize
_DOT_SPACING = 22

# Monokai-ish background
_BG_COLOR = "#272822"
_TITLE_BAR_COLOR = "#1e1e1e"

# Monospace font candidates (in order of preference)
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Linux (GH Actions)
    "/System/Library/Fonts/Menlo.ttc",  # macOS
    "/System/Library/Fonts/SFMono-Regular.otf",  # macOS alternative
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",  # Linux alt
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load the best available monospace font."""
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    # Fallback — Pillow default (not monospace, but functional)
    return ImageFont.load_default(size)


def render_code_image(
    code: str,
    language: str = "text",
    theme: str = "monokai",
) -> bytes:
    """Render a code snippet as a styled PNG image.

    Returns raw PNG bytes.
    """
    # Truncate long snippets
    lines = code.splitlines()
    truncated = False
    if len(lines) > _MAX_LINES:
        lines = lines[:_MAX_LINES]
        truncated = True
        lines.append("...")
    code_text = "\n".join(lines)

    # Tokenize
    try:
        lexer = get_lexer_by_name(language)
    except Exception:  # noqa: BLE001
        lexer = TextLexer()

    style = get_style_by_name(theme)
    tokens = list(lex(code_text, lexer))

    # Load font and measure
    font = _load_font(_FONT_SIZE)
    # Measure character width (monospace — all chars same width)
    char_bbox = font.getbbox("M")
    char_width = char_bbox[2] - char_bbox[0]

    # Calculate dimensions
    max_line_len = max((len(line) for line in lines), default=0)
    content_width = max_line_len * char_width
    content_height = len(lines) * _LINE_HEIGHT

    img_width = content_width + 2 * _PADDING_X
    img_height = content_height + _TITLE_BAR_HEIGHT + _PADDING_Y + _PADDING_Y // 2

    # Minimum width for the title bar dots
    img_width = max(img_width, 200)

    # Create image
    img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw rounded rectangle background
    draw.rounded_rectangle(
        [(0, 0), (img_width - 1, img_height - 1)],
        radius=_CORNER_RADIUS,
        fill=_BG_COLOR,
    )

    # Draw title bar
    draw.rounded_rectangle(
        [(0, 0), (img_width - 1, _TITLE_BAR_HEIGHT)],
        radius=_CORNER_RADIUS,
        fill=_TITLE_BAR_COLOR,
    )
    # Fill the bottom corners of the title bar (they should be square)
    draw.rectangle(
        [(0, _CORNER_RADIUS), (img_width - 1, _TITLE_BAR_HEIGHT)],
        fill=_TITLE_BAR_COLOR,
    )

    # Draw window chrome dots
    dot_x_start = _PADDING_X // 2 + _DOT_RADIUS
    for i, color in enumerate(_DOT_COLORS):
        cx = dot_x_start + i * _DOT_SPACING
        cy = _DOT_Y
        draw.ellipse(
            [(cx - _DOT_RADIUS, cy - _DOT_RADIUS), (cx + _DOT_RADIUS, cy + _DOT_RADIUS)],
            fill=color,
        )

    # Render syntax-highlighted tokens
    x = _PADDING_X
    y = _TITLE_BAR_HEIGHT + _PADDING_Y // 2

    for ttype, value in tokens:
        # Get color for this token type
        color = _token_color(style, ttype)

        for char in value:
            if char == "\n":
                x = _PADDING_X
                y += _LINE_HEIGHT
                continue
            draw.text((x, y), char, fill=color, font=font)
            x += char_width

    # Export as PNG
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _token_color(style, ttype) -> str:
    """Resolve a Pygments token type to a hex color string."""
    while ttype:
        style_entry = style.style_for_token(ttype)
        if style_entry and style_entry["color"]:
            return f"#{style_entry['color']}"
        ttype = ttype.parent
    # Default to light gray
    return "#f8f8f2"


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def generate_code_snippet_image(post_text: str) -> Optional[bytes]:
    """Extract the first code block from a post and render it as a PNG.

    Returns PNG bytes, or None if no code block is found.
    """
    blocks = extract_code_blocks(post_text)
    if not blocks:
        return None

    # Use the first (usually the main) code block
    block = blocks[0]
    language = detect_language(block.code)
    logger.info("Generating code image: language=%s, lines=%d", language, block.code.count("\n") + 1)

    try:
        return render_code_image(block.code, language=language)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to render code image", exc_info=True)
        return None
