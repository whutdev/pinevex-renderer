from .text_runs import *

def _has_pua(text: str) -> bool:
    return any(ch in _PUA_CHARS for ch in text)


def _should_prefer_tight_height(text: str) -> bool:
    """Use tight-height TextScaled only for text likely to benefit from it.

    Tight bounds over-scale normal word labels in Studio parity tests.
    Restrict this mode to symbol-only labels.
    """
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return False
    return all(not ch.isalnum() for ch in stripped)


def _is_symbol_only_text(text: str) -> bool:
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return False
    return all(not ch.isalnum() for ch in stripped)


def _wrap_lines(text: str, font: skia.Font, max_width: float,
                emoji_font: skia.Font | None = None,
                fallback_fonts: tuple[skia.Font, ...] | None = None) -> list[str]:
    """Word-wrap text into lines that fit within max_width."""
    if max_width <= 0:
        return [text]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if _measure_mixed(candidate, font, emoji_font, fallback_fonts) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_font_size(text: str, typeface: skia.Typeface, max_w: float, max_h: float,
                   wrapped: bool, emoji_typeface: skia.Typeface | None = None,
                   fallback_typefaces: list[skia.Typeface] | None = None,
                   requested_weight: int = 400,
                   italic: bool = False,
                   prefer_tight_height: bool = False,
                   tight_height_line_floor: float = 0.0,
                   min_size: float = _TEXTSCALED_DEFAULT_MIN,
                   max_size: float = _TEXTSCALED_DEFAULT_MAX) -> float:
    """Binary search for the largest font size where text fits in the rect."""
    lo = max(0.1, float(min_size))
    hi = max(lo, float(max_size))
    best = lo
    for _ in range(30):
        mid = (lo + hi) / 2
        font = skia.Font(typeface, mid)
        _apply_font_draw_style(font, typeface, requested_weight, italic=italic)
        ef = skia.Font(emoji_typeface, mid) if emoji_typeface else None
        if ef:
            _apply_font_draw_style(ef, emoji_typeface, requested_weight)
        fallback_fonts = _build_fallback_fonts(fallback_typefaces or [], mid)
        metrics = font.getMetrics()
        line_h = -metrics.fAscent + metrics.fDescent
        if wrapped:
            lines = _wrap_lines(text, font, max_w, ef, fallback_fonts)
            if prefer_tight_height and len(lines) == 1 and not _has_pua(lines[0]):
                total_h = (
                    _measure_mixed_tight_height(lines[0], font, ef, fallback_fonts)
                    * _GRADIENT_TIGHT_HEIGHT_SCALE
                )
                if tight_height_line_floor > 0:
                    total_h = max(total_h, line_h * tight_height_line_floor)
            else:
                total_h = line_h * len(lines)
            max_line_w = max((_measure_mixed(ln, font, ef, fallback_fonts) for ln in lines), default=0)
            fits = max_line_w <= max_w and total_h <= max_h
        else:
            if not prefer_tight_height or _has_pua(text):
                text_h = line_h
            else:
                text_h = (
                    _measure_mixed_tight_height(text, font, ef, fallback_fonts)
                    * _GRADIENT_TIGHT_HEIGHT_SCALE
                )
                if tight_height_line_floor > 0:
                    text_h = max(text_h, line_h * tight_height_line_floor)
            fits = _measure_mixed(text, font, ef, fallback_fonts) <= max_w and text_h <= max_h
        if fits:
            best = mid
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.5:
            break
    return best


def _measure_mixed_tight_height(
    text: str,
    font: skia.Font,
    emoji_font: skia.Font | None = None,
    fallback_fonts: tuple[skia.Font, ...] | None = None,
) -> float:
    """Measure rendered glyph tight height for mixed runs.

    Falls back to line metrics when path bounds are unavailable.
    """
    if not text:
        return 0.0

    cursor = 0.0
    top = None
    bottom = None
    has_bounds = False
    for run_text, run_font in _split_font_runs(text, font, emoji_font, fallback_fonts):
        if not run_text:
            continue
        glyph_path = _text_path(run_text, run_font, cursor, 0.0)
        if glyph_path is not None:
            b = glyph_path.computeTightBounds()
            bt = float(b.top())
            bb = float(b.bottom())
            top = bt if top is None else min(top, bt)
            bottom = bb if bottom is None else max(bottom, bb)
            has_bounds = True
        cursor += _measure_run_text(run_text, run_font)

    if has_bounds and top is not None and bottom is not None:
        return max(0.0, bottom - top)

    m = font.getMetrics()
    return -m.fAscent + m.fDescent


# ---------------------------------------------------------------------------
# Rich text parsing and layout
# ---------------------------------------------------------------------------


_JOIN_MAP = {
    "round": skia.Paint.Join.kRound_Join,
    "bevel": skia.Paint.Join.kBevel_Join,
    "miter": skia.Paint.Join.kMiter_Join,
}


__all__ = [name for name in globals() if not name.startswith("__")]
