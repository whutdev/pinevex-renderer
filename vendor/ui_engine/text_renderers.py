from .text_rich import *


def _text_stroke_thickness_scale(font_family: str | None) -> float:
    """Calibrate text-outline heft for pixel-like faces."""
    family = (font_family or "").strip().lower()
    if family in {"pressstart2p", "pressstart"}:
        return 0.8
    return 1.0


def _max_text_outline_thickness(
    node: dict,
    text_size: float,
    gradient: dict | None = None,
    *,
    thickness_scale: float = 1.0,
    gradient_scaled: bool = False,
) -> float:
    """Return max visible text-outline thickness in px for fit calculations."""
    max_thickness = 0.0

    legacy = _build_legacy_text_stroke(node)
    if legacy is not None:
        max_thickness = max(max_thickness, float(legacy[0]) * thickness_scale)

    for s in node.get("strokes", []):
        if s.get("applyMode") == "Border":
            continue
        thickness = float(s.get("thickness", 1))
        if s.get("thicknessScale"):
            thickness *= float(text_size)
        thickness *= thickness_scale
        if gradient_scaled and gradient:
            thickness *= _GRADIENT_TEXT_STROKE_SCALE
        transparency = float(s.get("transparency", 0))
        if thickness <= 0 or transparency >= 1:
            continue
        max_thickness = max(max_thickness, thickness)

    return max_thickness


def _draw_text_plain_rtl(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
                         node: dict, fonts_dir: Path | None = None,
                         gradient: dict | None = None) -> bool:
    text = node.get("text", "")
    if not text or not _TEXTLAYOUT_AVAILABLE:
        return False

    transparency = node.get("textTransparency", 0.0)
    if transparency >= 1.0:
        return True

    family, weight = _resolve_font(node.get("font"), node.get("fontWeight"))
    stroke_thickness_scale = _text_stroke_thickness_scale(family)
    italic = _is_italic_style(node.get("fontStyle"))
    typeface = _load_typeface(family, weight, fonts_dir, italic=italic)
    _get_emoji_typeface(fonts_dir)
    fallback_typefaces = _with_emoji_fallback_typefaces(
        _get_fallback_typefaces(fonts_dir), fonts_dir
    )
    slant = skia.FontStyle.Slant.kItalic_Slant if italic else skia.FontStyle.Slant.kUpright_Slant
    font_style = skia.FontStyle(weight, 5, slant)
    text_size = float(node.get("textSize", 14.0))

    main_family = typeface.getFamilyName() or family
    font_families, font_typefaces = _font_aliases_for_run(
        skia.Font(typeface, max(1.0, text_size)),
        tuple(skia.Font(tf, max(1.0, text_size)) for tf in fallback_typefaces),
    )
    if not font_families and main_family:
        font_families = [main_family]
        font_typefaces = []
    if not font_families:
        return False

    content_x, content_y, content_w, content_h = _resolve_text_content_rect(node, x, y, w, h)
    if content_w <= 0 or content_h <= 0:
        return True

    wrapped = bool(node.get("textWrapped", False))
    wrapped_effective = wrapped and _has_break_opportunities(text)
    if node.get("textScaled", False):
        min_size, max_size = _textscaled_size_limits(node)
        text_size = max(min_size, min(text_size, max_size))
        for _ in range(4):
            stroke_pad = _max_text_outline_thickness(
                node,
                text_size,
                gradient,
                thickness_scale=stroke_thickness_scale,
                gradient_scaled=True,
            )
            fit_w = max(1.0, content_w - stroke_pad * 2.0)
            fit_h = max(1.0, content_h - stroke_pad * 2.0)
            next_size = _fit_paragraph_font_size(
                text=text,
                font_families=font_families,
                font_typefaces=font_typefaces,
                font_style=font_style,
                max_w=fit_w,
                max_h=fit_h,
                wrapped=wrapped_effective,
                min_size=min_size,
                max_size=max_size,
            )
            if abs(next_size - text_size) < 0.1:
                text_size = next_size
                break
            text_size = next_size

    color = node.get("textColor", [0, 0, 0])
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    alpha = int((1.0 - transparency) * 255)
    fill_paint = skia.Paint()
    fill_paint.setAntiAlias(True)
    if gradient:
        shader = make_gradient_shader(
            gradient, x, y, w, h,
            base_color=(r, g, b), base_transparency=transparency,
        )
        if shader:
            fill_paint.setShader(shader)
        else:
            fill_paint.setColor(skia.Color(r, g, b, alpha))
    else:
        fill_paint.setColor(skia.Color(r, g, b, alpha))

    x_align = node.get("textXAlignment", "Center")
    draw_align = _map_text_align(x_align) if wrapped_effective else skia.textlayout.TextAlign.kLeft

    measure_para = _build_paragraph(
        text=text,
        font_families=font_families,
        font_typefaces=font_typefaces,
        font_style=font_style,
        text_size=text_size,
        paint=fill_paint,
        text_align=draw_align,
        max_width=content_w,
        wrapped=wrapped_effective,
    )
    if measure_para is None:
        return False

    total_text_h = measure_para.Height
    y_align = node.get("textYAlignment", "Center")
    if y_align == "Top":
        start_y = content_y
    elif y_align == "Bottom":
        start_y = content_y + content_h - total_text_h
    else:
        start_y = content_y + (content_h - total_text_h) / 2

    if wrapped_effective:
        draw_x = content_x
    else:
        line_w = measure_para.LongestLine
        if x_align == "Left":
            draw_x = content_x
        elif x_align == "Right":
            draw_x = content_x + content_w - line_w
        else:
            draw_x = content_x + (content_w - line_w) / 2

    stroke_paints: list[tuple[float, skia.Paint]] = []
    legacy_text_stroke = _build_legacy_text_stroke(node)
    if legacy_text_stroke is not None:
        stroke_paints.append(legacy_text_stroke)

    for s in node.get("strokes", []):
        if s.get("applyMode") == "Border":
            continue
        s_thickness = s.get("thickness", 1)
        if s.get("thicknessScale"):
            s_thickness = s_thickness * text_size
        s_thickness = s_thickness * stroke_thickness_scale
        if gradient:
            s_thickness = s_thickness * _GRADIENT_TEXT_STROKE_SCALE
        s_color = s.get("color", [0, 0, 0])
        s_trans = s.get("transparency", 0)
        if s_thickness <= 0 or s_trans >= 1:
            continue
        sp = skia.Paint()
        sp.setAntiAlias(True)
        sp.setStyle(skia.Paint.kStroke_Style)
        sp.setStrokeWidth(_stroke_width_from_thickness(float(s_thickness)))
        join = str(s.get("lineJoin", "Round")).lower()
        sp.setStrokeJoin(_JOIN_MAP.get(join, skia.Paint.Join.kRound_Join))
        sr, sg, sb = int(s_color[0]), int(s_color[1]), int(s_color[2])
        s_alpha = round((1.0 - s_trans) * 255)
        s_grad = s.get("gradient") or gradient
        if s_grad:
            s_shader = make_gradient_shader(
                s_grad, x, y, w, h,
                base_color=(sr, sg, sb), base_transparency=s_trans,
            )
            if s_shader:
                sp.setShader(s_shader)
            else:
                sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        else:
            sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        stroke_paints.append((s_thickness, sp))

    stroke_paints.sort(key=lambda t: t[0], reverse=True)
    max_stroke = max((t for t, _ in stroke_paints), default=0.0)
    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(
        content_x - max_stroke, content_y - max_stroke,
        content_w + max_stroke * 2, content_h + max_stroke * 2,
    ))

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    if stroke_paints:
        stroke_bounds = skia.Rect.MakeXYWH(
            content_x - max_stroke * 2, content_y - max_stroke * 2,
            content_w + max_stroke * 4, content_h + max_stroke * 4,
        )
        _annotate(canvas, f"Text stroke layer: {name}")
        canvas.saveLayer(stroke_bounds)
        for _, sp in stroke_paints:
            stroke_para = _build_paragraph(
                text=text,
                font_families=font_families,
                font_typefaces=font_typefaces,
                font_style=font_style,
                text_size=text_size,
                paint=sp,
                text_align=draw_align,
                max_width=content_w,
                wrapped=wrapped_effective,
            )
            if stroke_para is not None:
                _annotate(canvas, f"Text stroke: {name}")
                stroke_para.paint(canvas, draw_x, start_y)

        # Roblox icon PUA glyphs keep clearer inner contour lines without knockout clear.
        if not _has_pua(text):
            clear_paint = skia.Paint()
            clear_paint.setAntiAlias(True)
            clear_paint.setBlendMode(skia.BlendMode.kDstOut)
            clear_para = _build_paragraph(
                text=text,
                font_families=font_families,
                font_typefaces=font_typefaces,
                font_style=font_style,
                text_size=text_size,
                paint=clear_paint,
                text_align=draw_align,
                max_width=content_w,
                wrapped=wrapped_effective,
            )
            if clear_para is not None:
                clear_para.paint(canvas, draw_x, start_y)
        canvas.restore()

    fill_para = _build_paragraph(
        text=text,
        font_families=font_families,
        font_typefaces=font_typefaces,
        font_style=font_style,
        text_size=text_size,
        paint=fill_paint,
        text_align=draw_align,
        max_width=content_w,
        wrapped=wrapped_effective,
    )
    if fill_para is not None:
        _annotate(canvas, f"Text fill: {name}")
        fill_para.paint(canvas, draw_x, start_y)

    canvas.restore()
    return True


def _draw_text_plain(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
                     node: dict, fonts_dir: Path | None = None,
                     gradient: dict | None = None) -> None:
    text = node.get("text", "")
    if not text:
        return

    transparency = node.get("textTransparency", 0.0)
    if transparency >= 1.0:
        return

    if _contains_rtl(text):
        if _draw_text_plain_rtl(canvas, x, y, w, h, node, fonts_dir, gradient):
            return

    content_x, content_y, content_w, content_h = _resolve_text_content_rect(node, x, y, w, h)
    if content_w <= 0 or content_h <= 0:
        return

    # Font setup
    family, weight = _resolve_font(node.get("font"), node.get("fontWeight"))
    stroke_thickness_scale = _text_stroke_thickness_scale(family)
    italic = _is_italic_style(node.get("fontStyle"))
    typeface = _load_typeface(family, weight, fonts_dir, italic=italic)
    emoji_typeface = _get_emoji_typeface(fonts_dir)
    fallback_typefaces = _with_emoji_fallback_typefaces(
        _get_fallback_typefaces(fonts_dir), fonts_dir
    )
    text_size = node.get("textSize", 14.0)
    wrapped = node.get("textWrapped", False)
    use_tight_height = bool(gradient) and _should_prefer_tight_height(text)
    symbol_floor = 0.0
    if bool(gradient) and _is_symbol_only_text(text):
        use_tight_height = True
        symbol_floor = _SYMBOL_TIGHT_HEIGHT_LINE_FLOOR

    if node.get("textScaled", False):
        min_size, max_size = _textscaled_size_limits(node)
        text_size = max(float(min_size), min(float(text_size), float(max_size)))
        for _ in range(4):
            stroke_pad = _max_text_outline_thickness(
                node,
                text_size,
                gradient,
                thickness_scale=stroke_thickness_scale,
            )
            fit_w = max(1.0, content_w - stroke_pad * 2.0)
            fit_h = max(1.0, content_h - stroke_pad * 2.0)
            next_size = _fit_font_size(
                text,
                typeface,
                fit_w,
                fit_h,
                wrapped,
                emoji_typeface,
                fallback_typefaces,
                requested_weight=weight,
                italic=italic,
                prefer_tight_height=use_tight_height,
                tight_height_line_floor=symbol_floor,
                min_size=min_size,
                max_size=max_size,
            )
            if abs(next_size - text_size) < 0.1:
                text_size = next_size
                break
            text_size = next_size

    font = skia.Font(typeface, text_size)
    _apply_font_draw_style(font, typeface, weight, italic=italic)
    emoji_font = skia.Font(emoji_typeface, text_size) if emoji_typeface else None
    if emoji_font:
        _apply_font_draw_style(emoji_font, emoji_typeface, weight)
    fallback_fonts = _build_fallback_fonts(fallback_typefaces, text_size)

    # Paint
    color = node.get("textColor", [0, 0, 0])
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    alpha = int((1.0 - transparency) * 255)
    paint = skia.Paint()
    paint.setAntiAlias(True)
    if gradient:
        shader = make_gradient_shader(
            gradient, x, y, w, h,
            base_color=(r, g, b), base_transparency=transparency,
        )
        if shader:
            paint.setShader(shader)
        else:
            paint.setColor(skia.Color(r, g, b, alpha))
    else:
        paint.setColor(skia.Color(r, g, b, alpha))

    # Build lines
    if wrapped:
        lines = _wrap_lines(text, font, content_w, emoji_font, fallback_fonts)
    else:
        lines = [text]

    # Metrics
    metrics = font.getMetrics()
    ascent = -metrics.fAscent
    descent = metrics.fDescent
    leading = metrics.fLeading if metrics.fLeading > 0 else 0
    line_height_mult = node.get("lineHeight", 1.0)
    single_line_h = ascent + descent
    line_step = single_line_h * line_height_mult + leading
    total_text_h = single_line_h + line_step * (len(lines) - 1) if lines else 0

    # Vertical alignment
    y_align = node.get("textYAlignment", "Center")
    if y_align == "Top":
        start_y = content_y + ascent
    elif y_align == "Bottom":
        start_y = content_y + content_h - total_text_h + ascent
    else:  # Center
        start_y = content_y + (content_h - total_text_h) / 2 + ascent

    # Horizontal alignment
    x_align = node.get("textXAlignment", "Center")

    # Text strokes (contextual UIStrokes — outlines behind the fill)
    stroke_paints: list[tuple[float, skia.Paint]] = []
    legacy_text_stroke = _build_legacy_text_stroke(node)
    if legacy_text_stroke is not None:
        stroke_paints.append(legacy_text_stroke)

    for s in node.get("strokes", []):
        if s.get("applyMode") == "Border":
            continue
        s_thickness = s.get("thickness", 1)
        if s.get("thicknessScale"):
            s_thickness = s_thickness * text_size
        s_thickness = s_thickness * stroke_thickness_scale
        s_color = s.get("color", [0, 0, 0])
        s_trans = s.get("transparency", 0)
        if s_thickness <= 0 or s_trans >= 1:
            continue
        sp = skia.Paint()
        sp.setAntiAlias(True)
        sp.setStyle(skia.Paint.kStroke_Style)
        sp.setStrokeWidth(_stroke_width_from_thickness(float(s_thickness)))
        join = str(s.get("lineJoin", "Round")).lower()
        sp.setStrokeJoin(_JOIN_MAP.get(join, skia.Paint.Join.kRound_Join))
        sr, sg, sb = int(s_color[0]), int(s_color[1]), int(s_color[2])
        s_alpha = round((1.0 - s_trans) * 255)
        s_grad = s.get("gradient") or gradient
        if s_grad:
            s_shader = make_gradient_shader(
                s_grad, x, y, w, h,
                base_color=(sr, sg, sb), base_transparency=s_trans,
            )
            if s_shader:
                sp.setShader(s_shader)
            else:
                sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        else:
            sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        stroke_paints.append((s_thickness, sp))

    stroke_paints.sort(key=lambda t: t[0], reverse=True)

    max_stroke = max((t for t, _ in stroke_paints), default=0)
    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(
        content_x - max_stroke, content_y - max_stroke,
        content_w + max_stroke * 2, content_h + max_stroke * 2,
    ))

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    for i, line in enumerate(lines):
        baseline_y = start_y + i * line_step
        line_w = _measure_mixed(line, font, emoji_font, fallback_fonts)
        if x_align == "Left":
            line_x = content_x
        elif x_align == "Right":
            line_x = content_x + content_w - line_w
        else:  # Center
            line_x = content_x + (content_w - line_w) / 2

        if stroke_paints:
            stroke_bounds = skia.Rect.MakeXYWH(
                content_x - max_stroke * 2, content_y - max_stroke * 2,
                content_w + max_stroke * 4, content_h + max_stroke * 4,
            )
            _annotate(canvas, f"Text stroke layer: {name}")
            canvas.saveLayer(stroke_bounds)
            for _, sp in stroke_paints:
                _annotate(canvas, f"Text stroke: {name}")
                _draw_mixed(canvas, line, line_x, baseline_y, font, emoji_font, sp, fallback_fonts)
            # Roblox icon PUA glyphs keep clearer inner contour lines without knockout clear.
            if not _has_pua(line):
                clear_paint = skia.Paint()
                clear_paint.setAntiAlias(True)
                clear_paint.setBlendMode(skia.BlendMode.kDstOut)
                _draw_mixed(canvas, line, line_x, baseline_y, font, emoji_font, clear_paint, fallback_fonts)
            canvas.restore()

        _annotate(canvas, f"Text fill: {name}")
        _draw_mixed(canvas, line, line_x, baseline_y, font, emoji_font, paint, fallback_fonts)

    canvas.restore()


def draw_text(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
              node: dict, fonts_dir: Path | None = None,
              gradient: dict | None = None) -> None:
    """Render text within the given rect based on node properties."""
    if w <= 0 or h <= 0:
        return

    text = node.get("text", "")
    if not text:
        return

    text_gradient = gradient
    if gradient is not None:
        text_gradient = dict(gradient)
        text_gradient["rotation"] = (
            float(gradient.get("rotation", 0.0)) + _TEXT_GRADIENT_ROTATION_OFFSET_DEG
        )

    if node.get("richText"):
        _draw_text_rich(canvas, x, y, w, h, node, fonts_dir, text_gradient)
    else:
        _draw_text_plain(canvas, x, y, w, h, node, fonts_dir, text_gradient)


__all__ = [name for name in globals() if not name.startswith("__")]
