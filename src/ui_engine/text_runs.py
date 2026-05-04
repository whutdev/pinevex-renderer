from .text_fonts import *

def _build_fallback_fonts(typefaces: list[skia.Typeface], size: float) -> tuple[skia.Font, ...]:
    fonts: list[skia.Font] = []
    for tf in typefaces:
        f = skia.Font(tf, size)
        f.setEdging(skia.Font.Edging.kAntiAlias)
        fonts.append(f)
    return tuple(fonts)


def _font_has_glyph(font: skia.Font, ch: str) -> bool:
    tf = font.getTypeface()
    if not tf:
        return False
    key = (tf.uniqueID(), ch)
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached
    glyphs = font.textToGlyphs(ch)
    has = bool(glyphs and glyphs[0] != 0)
    _glyph_cache[key] = has
    return has


def _typeface_family_name(font: skia.Font | None) -> str:
    if font is None:
        return ""
    tf = font.getTypeface()
    if tf is None:
        return ""
    try:
        return (tf.getFamilyName() or "").strip().lower()
    except Exception:
        return ""


def _pick_font_for_char(ch: str, main_font: skia.Font, emoji_font: skia.Font | None,
                        fallback_fonts: tuple[skia.Font, ...]) -> skia.Font:
    if ch in _PUA_CHARS:
        # Roblox-specific PUA glyphs should come from RobloxEmoji first.
        # Twemoji and other fallback fonts can report a nonzero .notdef glyph and
        # render tofu, so prefer an explicit RobloxEmoji face when available.
        pua_candidates: list[skia.Font] = []
        if emoji_font is not None:
            pua_candidates.append(emoji_font)
        pua_candidates.extend(fallback_fonts)
        pua_candidates.append(main_font)

        for candidate in pua_candidates:
            family_name = _typeface_family_name(candidate)
            if "robloxemoji" in family_name or "roblox emoji" in family_name:
                if _font_has_glyph(candidate, ch):
                    return candidate

        if emoji_font and _font_has_glyph(emoji_font, ch):
            return emoji_font
        for ff in fallback_fonts:
            if _font_has_glyph(ff, ch):
                return ff
        if _font_has_glyph(main_font, ch):
            return main_font
        return main_font

    if _font_has_glyph(main_font, ch):
        return main_font
    if emoji_font and _font_has_glyph(emoji_font, ch):
        return emoji_font
    for ff in fallback_fonts:
        if _font_has_glyph(ff, ch):
            return ff
    return main_font


def _split_font_runs(text: str, main_font: skia.Font, emoji_font: skia.Font | None,
                     fallback_fonts: tuple[skia.Font, ...] | None = None) -> list[tuple[str, skia.Font]]:
    if not text:
        return []
    runs: list[tuple[str, skia.Font]] = []
    buf: list[str] = []
    ff = fallback_fonts or ()
    current_font: skia.Font | None = None
    for ch in text:
        chosen_font = _pick_font_for_char(ch, main_font, emoji_font, ff)
        if current_font is not None and chosen_font is not current_font and buf:
            runs.append(("".join(buf), current_font))
            buf = []
        buf.append(ch)
        current_font = chosen_font
    if buf and current_font is not None:
        runs.append(("".join(buf), current_font))
    return runs


def _is_robux_run(text: str) -> bool:
    return bool(text) and all(ch == _ROBUX_CHAR for ch in text)


def _hex_path(cx: float, cy: float, r: float) -> skia.Path:
    p = skia.Path()
    for i in range(6):
        ang = math.radians(60.0 * i)
        px = cx + r * math.cos(ang)
        py = cy + r * math.sin(ang)
        if i == 0:
            p.moveTo(px, py)
        else:
            p.lineTo(px, py)
    p.close()
    return p


def _robux_advance(font: skia.Font) -> float:
    return float(font.measureText(_ROBUX_CHAR))


def _stroke_width_from_thickness(thickness: float) -> float:
    """Map Roblox stroke thickness to Skia stroke width in pixels."""
    # Text stroke paths are drawn centered and then interior-cleared for outline parity,
    # so we need a 2x expansion to preserve intended visible stroke thickness.
    return max(0.0, float(thickness) * 2.0 + 0.5)


def _draw_robux_symbol(canvas: skia.Canvas, x: float, baseline_y: float,
                       font: skia.Font, paint: skia.Paint) -> float:
    advance = _robux_advance(font)
    if advance <= 0:
        return 0.0

    m = font.getMetrics()
    glyph_h = float(-m.fAscent + m.fDescent)
    if glyph_h <= 0:
        return advance

    cx = x + advance * 0.5
    cy = baseline_y + (m.fAscent + m.fDescent) * 0.5

    # Slightly larger than font box to match Studio's robux glyph presence.
    size = min(advance * 1.08, glyph_h * 1.03)
    outer_r = size * 0.5
    inner_r = size * 0.31
    square_half = size * 0.102

    outer_hex = _hex_path(cx, cy, outer_r)
    inner_hex = _hex_path(cx, cy, inner_r)
    square = skia.Rect.MakeLTRB(cx - square_half, cy - square_half, cx + square_half, cy + square_half)

    style = paint.getStyle()
    if style == skia.Paint.kStroke_Style:
        outer_p = skia.Paint(paint)
        canvas.drawPath(outer_hex, outer_p)

        # Inner contours intentionally a bit stronger than outer contour.
        inner_p = skia.Paint(paint)
        inner_p.setStrokeWidth(float(paint.getStrokeWidth()) * 1.35)
        canvas.drawPath(inner_hex, inner_p)
        canvas.drawRect(square, inner_p)
        return advance

    # Fill path: outer hex minus center square hole.
    fill_path = skia.Path()
    fill_path.setFillType(skia.PathFillType.kEvenOdd)
    fill_path.addPath(outer_hex)
    fill_path.addRect(square)
    canvas.drawPath(fill_path, paint)
    return advance


def _measure_run_text(run_text: str, font: skia.Font) -> float:
    if not run_text:
        return 0.0
    if _is_robux_run(run_text):
        if _font_has_glyph(font, _ROBUX_CHAR):
            return float(font.measureText(run_text)) * _ROBUX_GLYPH_X_SCALE
        return _robux_advance(font) * len(run_text)
    return float(font.measureText(run_text))


def _text_path(run_text: str, font: skia.Font, x: float, baseline_y: float) -> skia.Path | None:
    glyphs = font.textToGlyphs(run_text)
    if not glyphs:
        return None
    glyph_paths = font.getPaths(glyphs)
    if not glyph_paths:
        return None
    positions = font.getPos(glyphs, skia.Point(float(x), float(baseline_y)))
    if not positions:
        return None

    out = skia.Path()
    has_path = False
    for gp, pos in zip(glyph_paths, positions):
        if gp is None:
            continue
        out.addPath(gp, float(pos.fX), float(pos.fY))
        has_path = True
    return out if has_path else None


def _robux_draw_font(font: skia.Font) -> skia.Font:
    """Use a non-faux-emboldened font for Robux glyph contour fidelity."""
    if not font.isEmbolden():
        return font
    out = font.makeWithSize(float(font.getSize()))
    if out is None:
        return font
    out.setEmbolden(False)
    return out


def _path_bounds_area(path: skia.Path) -> float:
    b = path.computeTightBounds()
    return max(0.0, float(b.width())) * max(0.0, float(b.height()))


def _path_contours(path: skia.Path) -> list[skia.Path]:
    contours: list[skia.Path] = []
    measure = skia.PathMeasure(path, False, 1.0)
    while True:
        seg_len = float(measure.getLength())
        if seg_len > 0.0:
            contour = skia.Path()
            if measure.getSegment(0.0, seg_len, contour, True) and contour.countVerbs() > 0:
                contours.append(contour)
        if not measure.nextContour():
            break
    return contours


def _draw_robux_inner_reinforce(canvas: skia.Canvas, glyph_path: skia.Path,
                                base_paint: skia.Paint) -> None:
    contours = _path_contours(glyph_path)
    if len(contours) <= 1:
        # Fallback path when contour extraction fails.
        reinforce = skia.Paint(base_paint)
        inner_sw = min(
            float(base_paint.getStrokeWidth()) * _ROBUX_INNER_REINFORCE_WIDTH,
            float(base_paint.getStrokeWidth()) + _ROBUX_INNER_REINFORCE_MAX_ADD,
        )
        reinforce.setStrokeWidth(inner_sw)
        reinforce.setAlpha(max(1, int(base_paint.getAlpha() * _ROBUX_INNER_REINFORCE_ALPHA)))
        canvas.save()
        canvas.clipPath(glyph_path, True)
        inner_clip = _robux_inner_clip_rect(glyph_path, _ROBUX_INNER_REINFORCE_CLIP_INSET_FRAC)
        if inner_clip is not None:
            canvas.clipRect(inner_clip)
        canvas.drawPath(glyph_path, reinforce)
        canvas.restore()
        return

    contours_with_area = [(c, _path_bounds_area(c)) for c in contours]
    outer_idx = max(range(len(contours_with_area)), key=lambda i: contours_with_area[i][1])
    inner = [(c, a) for i, (c, a) in enumerate(contours_with_area) if i != outer_idx]
    if not inner:
        return

    min_inner_area = min(a for _, a in inner)
    base_sw = float(base_paint.getStrokeWidth())
    for contour, area in inner:
        reinforce = skia.Paint(base_paint)
        width_scale = _ROBUX_INNER_REINFORCE_WIDTH
        alpha_scale = _ROBUX_INNER_REINFORCE_ALPHA
        # Smallest inner contour is the center square; keep it slightly lighter.
        if area <= min_inner_area * 1.02:
            width_scale *= _ROBUX_INNER_CENTER_REINFORCE_WIDTH
            alpha_scale *= _ROBUX_INNER_CENTER_REINFORCE_ALPHA
        inner_sw = min(
            base_sw * width_scale,
            base_sw + _ROBUX_INNER_REINFORCE_MAX_ADD,
        )
        reinforce.setStrokeWidth(inner_sw)
        reinforce.setAlpha(max(1, int(base_paint.getAlpha() * alpha_scale)))
        canvas.drawPath(contour, reinforce)


def _robux_inner_clip_rect(glyph_path: skia.Path, inset_frac: float) -> skia.Rect | None:
    gb = glyph_path.computeTightBounds()
    inset = min(float(gb.width()), float(gb.height())) * max(0.0, inset_frac)
    if inset <= 0.0:
        return None
    il = float(gb.left()) + inset
    it = float(gb.top()) + inset
    ir = float(gb.right()) - inset
    ib = float(gb.bottom()) - inset
    if ir <= il or ib <= it:
        return None
    return skia.Rect.MakeLTRB(il, it, ir, ib)


def _draw_robux_fill_inner_detail(canvas: skia.Canvas, glyph_path: skia.Path,
                                  font: skia.Font, fill_paint: skia.Paint) -> None:
    alpha = int(fill_paint.getAlpha() * _ROBUX_FILL_INNER_REINFORCE_ALPHA)
    if alpha <= 0:
        return
    detail = skia.Paint()
    detail.setAntiAlias(True)
    detail.setStyle(skia.Paint.kStroke_Style)
    detail.setStrokeJoin(skia.Paint.Join.kRound_Join)
    detail.setStrokeWidth(max(
        _ROBUX_FILL_INNER_REINFORCE_MIN_WIDTH,
        float(font.getSize()) * _ROBUX_FILL_INNER_REINFORCE_WIDTH_SCALE,
    ))
    detail.setColor(skia.Color(0, 0, 0, alpha))
    canvas.save()
    canvas.clipPath(glyph_path, True)
    inner_clip = _robux_inner_clip_rect(glyph_path, _ROBUX_FILL_INNER_REINFORCE_CLIP_INSET_FRAC)
    if inner_clip is not None:
        canvas.clipRect(inner_clip)
    canvas.drawPath(glyph_path, detail)
    canvas.restore()


def _draw_run_text(canvas: skia.Canvas, run_text: str, x: float, baseline_y: float,
                   font: skia.Font, paint: skia.Paint) -> float:
    if not run_text:
        return 0.0
    if not _is_robux_run(run_text):
        canvas.drawString(run_text, x, baseline_y, font, paint)
        return float(font.measureText(run_text))
    if _font_has_glyph(font, _ROBUX_CHAR):
        draw_font = _robux_draw_font(font)
        robux_adv = float(font.measureText(run_text))
        apply_geom = (
            abs(_ROBUX_GLYPH_X_SCALE - 1.0) > 1e-6
            or abs(_ROBUX_GLYPH_Y_SCALE - 1.0) > 1e-6
        )
        if apply_geom:
            m = font.getMetrics()
            anchor_x = x + robux_adv * 0.5
            anchor_y = baseline_y + (m.fAscent + m.fDescent) * 0.5
            canvas.save()
            canvas.translate(anchor_x, anchor_y)
            canvas.scale(_ROBUX_GLYPH_X_SCALE, _ROBUX_GLYPH_Y_SCALE)
            canvas.translate(-anchor_x, -anchor_y)
        robux_paint = paint
        if paint.getStyle() == skia.Paint.kStroke_Style:
            robux_paint = skia.Paint(paint)
            base_sw = float(paint.getStrokeWidth())
            # Robux glyphs need a touch more weight than generic glyph paths, but
            # cap the growth so thick source strokes do not balloon.
            boosted_sw = min(base_sw * _ROBUX_STROKE_BOOST, base_sw + 1.25)
            robux_paint.setStrokeWidth(boosted_sw)

        glyph_path = None
        if paint.getStyle() == skia.Paint.kStroke_Style:
            glyph_path = _text_path(run_text, draw_font, x, baseline_y)
        if glyph_path is not None:
            canvas.drawPath(glyph_path, robux_paint)
            _draw_robux_inner_reinforce(canvas, glyph_path, robux_paint)
        else:
            canvas.drawString(run_text, x, baseline_y, draw_font, robux_paint)
            if paint.getStyle() == skia.Paint.kStroke_Style:
                reinforce = skia.Paint(robux_paint)
                inner_sw = min(
                    float(robux_paint.getStrokeWidth()) * _ROBUX_INNER_REINFORCE_WIDTH,
                    float(robux_paint.getStrokeWidth()) + _ROBUX_INNER_REINFORCE_MAX_ADD,
                )
                reinforce.setStrokeWidth(inner_sw)
                reinforce.setAlpha(max(1, int(robux_paint.getAlpha() * _ROBUX_INNER_REINFORCE_ALPHA)))
                canvas.drawString(run_text, x, baseline_y, draw_font, reinforce)
            elif paint.getStyle() == skia.Paint.kFill_Style:
                glyph_path = _text_path(run_text, draw_font, x, baseline_y)
                if glyph_path is not None:
                    _draw_robux_fill_inner_detail(canvas, glyph_path, draw_font, robux_paint)
        if apply_geom:
            canvas.restore()
        return robux_adv * _ROBUX_GLYPH_X_SCALE

    cursor = x
    for _ in run_text:
        cursor += _draw_robux_symbol(canvas, cursor, baseline_y, font, paint)
    return cursor - x


def _measure_mixed(text: str, main_font: skia.Font, emoji_font: skia.Font | None,
                   fallback_fonts: tuple[skia.Font, ...] | None = None) -> float:
    is_pua_digit_mix = any(ch in _PUA_CHARS for ch in text) and any(ch.isdigit() for ch in text)
    total = 0.0
    prev_run_text = ""
    for run_text, run_font in _split_font_runs(text, main_font, emoji_font, fallback_fonts):
        eff_font = _effective_run_font(run_text, run_font, is_pua_digit_mix)
        if is_pua_digit_mix and prev_run_text:
            total -= _pua_digit_tighten(prev_run_text, run_text, eff_font)
        total += _measure_run_text(run_text, eff_font)
        prev_run_text = run_text
    return total


def _draw_mixed(canvas: skia.Canvas, text: str, x: float, y: float,
                main_font: skia.Font, emoji_font: skia.Font | None, paint: skia.Paint,
                fallback_fonts: tuple[skia.Font, ...] | None = None) -> None:
    is_pua_digit_mix = any(ch in _PUA_CHARS for ch in text) and any(ch.isdigit() for ch in text)
    mix_dx = float(main_font.getSize()) * _ROBUX_MIX_X_OFFSET_EM if is_pua_digit_mix else 0.0
    mix_dy = float(main_font.getSize()) * _ROBUX_MIX_Y_OFFSET_EM if is_pua_digit_mix else 0.0
    cursor = x + mix_dx
    prev_run_text = ""
    for run_text, run_font in _split_font_runs(text, main_font, emoji_font, fallback_fonts):
        eff_font = _effective_run_font(run_text, run_font, is_pua_digit_mix)
        if is_pua_digit_mix and prev_run_text:
            cursor -= _pua_digit_tighten(prev_run_text, run_text, eff_font)

        run_y = y + mix_dy + _run_baseline_shift(run_text, eff_font, is_pua_digit_mix)
        run_paint = paint
        _draw_run_text(canvas, run_text, cursor, run_y, eff_font, run_paint)
        if _should_reinforce_faux_fill(eff_font, run_paint):
            if is_pua_digit_mix:
                _draw_run_text(canvas, run_text, cursor + _faux_reinforce_dx(eff_font), run_y, eff_font, run_paint)
            else:
                _draw_run_text(canvas, run_text, cursor, run_y, eff_font, run_paint)

        cursor += _measure_run_text(run_text, eff_font)
        prev_run_text = run_text


def _pua_digit_tighten(prev_run_text: str, run_text: str, run_font: skia.Font) -> float:
    if not prev_run_text or not run_text:
        return 0.0
    if prev_run_text[-1] not in _PUA_CHARS:
        return 0.0
    if not run_text[0].isdigit():
        return 0.0
    tighten = max(0.8, float(run_font.getSize()) * 0.038)
    if prev_run_text[-1] == _ROBUX_CHAR:
        # Add a touch of breathing room between Robux symbol and following digit.
        return tighten * (1.0 - _ROBUX_NEXT_CHAR_SPACING_RELAX)
    return tighten


def _run_size_scale(run_text: str, is_pua_digit_mix: bool) -> float:
    if not is_pua_digit_mix or not run_text:
        return 1.0
    if all(ch in _PUA_CHARS for ch in run_text):
        return _ROBUX_PUA_RUN_SCALE
    if run_text[0].isdigit():
        return _ROBUX_DIGIT_RUN_SCALE
    return 1.0


def _effective_run_font(run_text: str, run_font: skia.Font, is_pua_digit_mix: bool) -> skia.Font:
    scale = _run_size_scale(run_text, is_pua_digit_mix)
    if abs(scale - 1.0) < 1e-6:
        return run_font

    out = run_font.makeWithSize(float(run_font.getSize()) * scale)
    if out is None:
        return run_font

    return out


def _run_baseline_shift(run_text: str, run_font: skia.Font, is_pua_digit_mix: bool) -> float:
    if not is_pua_digit_mix or not run_text:
        return 0.0
    sz = float(run_font.getSize())
    if all(ch in _PUA_CHARS for ch in run_text):
        return _ROBUX_PUA_BASELINE_SHIFT * sz
    if run_text[0].isdigit():
        return _ROBUX_DIGIT_BASELINE_SHIFT * sz
    return 0.0


__all__ = [name for name in globals() if not name.startswith("__")]
