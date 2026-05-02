import html
import math
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

import skia

from .visuals import make_gradient_shader

_TOKEN_RE = re.compile(r"<\|font:(.+?)\|>")
_FONT_FAMILY_PATH_RE = re.compile(r"rbxasset://fonts/families/(\w+)\.json", re.IGNORECASE)
_ATTR_RE = re.compile(r"([A-Za-z]+)\s*=\s*(\"([^\"]*)\"|'([^']*)')")
_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)


def _annotate(canvas, text):
    """Set annotation on StepCanvas; no-op on regular skia.Canvas."""
    if hasattr(canvas, 'annotate'):
        canvas.annotate(text)


# Roblox PUA codepoints that live in RobloxEmoji.ttf
_PUA_CHARS = frozenset("\ue000\ue001\ue002")
_ROBUX_CHAR = "\ue002"
_ROBUX_STROKE_BOOST = 1.16
_ROBUX_INNER_REINFORCE_WIDTH = 1.36
_ROBUX_INNER_REINFORCE_ALPHA = 0.62
_ROBUX_INNER_REINFORCE_MAX_ADD = 2.10
_ROBUX_INNER_REINFORCE_CLIP_INSET_FRAC = 0.0
_ROBUX_INNER_CENTER_REINFORCE_WIDTH = 1.00
_ROBUX_INNER_CENTER_REINFORCE_ALPHA = 0.00
_ROBUX_FILL_INNER_REINFORCE_WIDTH_SCALE = 0.012
_ROBUX_FILL_INNER_REINFORCE_MIN_WIDTH = 0.45
_ROBUX_FILL_INNER_REINFORCE_ALPHA = 0.0
_ROBUX_FILL_INNER_REINFORCE_CLIP_INSET_FRAC = 0.0
_ROBUX_GLYPH_X_SCALE = 0.99
_ROBUX_GLYPH_Y_SCALE = 0.97
_ROBUX_NEXT_CHAR_SPACING_RELAX = 0.40
_ROBUX_PUA_RUN_SCALE = 1.24
_ROBUX_DIGIT_RUN_SCALE = 1.03
_ROBUX_PUA_BASELINE_SHIFT = -0.035
_ROBUX_DIGIT_BASELINE_SHIFT = -0.02
# Small Studio-parity nudge for mixed robux runs ("99"): move slightly right/down.
_ROBUX_MIX_X_OFFSET_EM = 0.0020
_ROBUX_MIX_Y_OFFSET_EM = 0.0100
# Slightly conservative scale for tight-height TextScaled on gradient labels.
_GRADIENT_TIGHT_HEIGHT_SCALE = 1.09
_GRADIENT_TEXT_STROKE_SCALE = 1.05
_TEXT_GRADIENT_ROTATION_OFFSET_DEG = -10.0
_SYMBOL_TIGHT_HEIGHT_LINE_FLOOR = 0.82
_TEXTSCALED_DEFAULT_MIN = 1.0
_TEXTSCALED_DEFAULT_MAX = 100.0
_emoji_typeface: skia.Typeface | None = None
_emoji_fallback_typeface: skia.Typeface | None = None
_emoji_load_attempted = False
_fallback_typefaces: list[skia.Typeface] = []
_fallback_load_attempted = False
_glyph_cache: dict[tuple[int, str], bool] = {}
_ARABIC_TEST_CHAR = "ش"
_FALLBACK_FONT_FILES = (
    "NotoNaskhArabicUI-Regular.ttf",
    "NotoSansArabicUI-Regular.ttf",
    "NotoNaskhArabic-Regular.ttf",
    "NotoSansArabic-Regular.ttf",
)
_FALLBACK_FONT_NAMES = (
    "Noto Naskh Arabic UI",
    "Noto Naskh Arabic",
    "Noto Sans Arabic",
    "Segoe UI",
)
_RTL_BIDI_CLASSES = frozenset({"R", "AL", "RLE", "RLO", "RLI"})
_LTR_BIDI_CLASSES = frozenset({"L", "LRE", "LRO", "LRI"})
_TEXTLAYOUT_AVAILABLE = hasattr(skia, "textlayout")
_unicode_engine: skia.Unicode | None = None
_unicode_load_attempted = False
_roblox_fonts_by_name: dict[str, Path] = {}
_roblox_fonts_load_attempted = False


__all__ = [name for name in globals() if not name.startswith("__")]

