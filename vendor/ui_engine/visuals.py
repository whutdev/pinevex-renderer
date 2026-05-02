import math
import re
import skia


def _num(value, default: float = 0.0) -> float:
    """Convert arbitrary value to float with fallback."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' to (r, g, b) ints with tolerant fallback."""
    h = "" if hex_str is None else str(hex_str).lstrip("#")
    # Keep only valid hex chars so malformed model outputs don't crash render.
    h = re.sub(r"[^0-9a-fA-F]", "", h)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) < 6:
        h = (h + "FFFFFF")[:6]
    else:
        h = h[:6]
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 255, 255, 255


def _alpha_from_transparency(transparency: float) -> int:
    return round((1.0 - transparency) * 255)


def resolve_corner(node: dict, w: float, h: float) -> float:
    """Resolve UICorner radius from scale/offset UDim or bare number."""
    corner = node.get("corner")
    if corner is None:
        return 0.0
    if isinstance(corner, dict):
        # scale applies to min(w, h); result clamped to min(w, h)/2 (pill shape)
        r = _num(corner.get("scale", 0), 0.0) * min(w, h) + _num(corner.get("offset", 0), 0.0)
        return min(r, min(w, h) / 2)
    return max(0.0, _num(corner, 0.0))


def make_gradient_shader(
    gradient: dict, x: float, y: float, w: float, h: float,
    base_color: tuple[int, int, int] = (255, 255, 255),
    base_transparency: float = 0.0,
) -> skia.Shader | None:
    """Build a linear gradient shader pre-multiplied with a base color.

    Returns None if fewer than 2 color stops.
    """
    raw_color_stops = gradient.get("colors", [])
    color_stops = [
        (stop[0], stop[1])
        for stop in raw_color_stops
        if isinstance(stop, (list, tuple)) and len(stop) >= 2
    ]
    if len(color_stops) < 2:
        return None

    rotation_deg = _num(gradient.get("rotation", 0), 0.0)
    raw_transparency_stops = gradient.get("transparency", [])
    transparency_stops = [
        (stop[0], stop[1])
        for stop in raw_transparency_stops
        if isinstance(stop, (list, tuple)) and len(stop) >= 2
    ]
    offset = gradient.get("offset") or [0, 0]

    trans_map = sorted(transparency_stops, key=lambda s: s[0]) if transparency_stops else []
    color_map = sorted(color_stops, key=lambda s: s[0])

    def _sample_transparency(t: float) -> float:
        if not trans_map:
            return 0.0
        if t <= trans_map[0][0]:
            return trans_map[0][1]
        if t >= trans_map[-1][0]:
            return trans_map[-1][1]
        for i in range(len(trans_map) - 1):
            t0, v0 = trans_map[i]
            t1, v1 = trans_map[i + 1]
            if t0 <= t <= t1:
                span = t1 - t0
                if span == 0:
                    return v0
                frac = (t - t0) / span
                return v0 + (v1 - v0) * frac
        return 0.0

    def _sample_color(t: float) -> tuple[int, int, int]:
        if not color_map:
            return (255, 255, 255)
        if t <= color_map[0][0]:
            return _parse_hex_color(color_map[0][1])
        if t >= color_map[-1][0]:
            return _parse_hex_color(color_map[-1][1])
        for i in range(len(color_map) - 1):
            t0, c0 = color_map[i]
            t1, c1 = color_map[i + 1]
            if t0 <= t <= t1:
                r0, g0, b0 = _parse_hex_color(c0)
                r1, g1, b1 = _parse_hex_color(c1)
                span = t1 - t0
                if span == 0:
                    return (r0, g0, b0)
                frac = (t - t0) / span
                return (
                    round(r0 + (r1 - r0) * frac),
                    round(g0 + (g1 - g0) * frac),
                    round(b0 + (b1 - b0) * frac),
                )
        return _parse_hex_color(color_map[-1][1])

    # Merge positions from both color and transparency sequences
    all_times = sorted({t for t, _ in color_stops} | {t for t, _ in transparency_stops})

    br, bg_c, bb = base_color
    positions = []
    colors = []
    for time_val in all_times:
        r, g, b = _sample_color(time_val)
        # Pre-multiply with base color
        r = (r * br) // 255
        g = (g * bg_c) // 255
        b = (b * bb) // 255
        grad_trans = _sample_transparency(time_val)
        alpha = round((1.0 - base_transparency) * (1.0 - grad_trans) * 255)
        alpha = max(0, min(255, alpha))
        colors.append(skia.Color(r, g, b, alpha))
        positions.append(float(time_val))

    cx = x + w / 2.0 + _num(offset[0] if isinstance(offset, (list, tuple)) and len(offset) > 0 else 0.0, 0.0) * w
    cy = y + h / 2.0 + _num(offset[1] if isinstance(offset, (list, tuple)) and len(offset) > 1 else 0.0, 0.0) * h
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)
    # Cover-line model: keep exact angle and ensure the gradient line spans the element.
    half_len = (w * abs(cos_r) + h * abs(sin_r)) / 2.0
    dx = cos_r * half_len
    dy = sin_r * half_len
    start = skia.Point(cx - dx, cy - dy)
    end = skia.Point(cx + dx, cy + dy)

    return skia.GradientShader.MakeLinear([start, end], colors, positions)


def draw_background(
    canvas: skia.Canvas, x: float, y: float, w: float, h: float, node: dict,
    gradient: dict | None = None,
) -> None:
    """Draw background color fill with optional corner radius and bgTransparency."""
    bg = node.get("bg")
    if bg is None:
        return
    if w <= 0 or h <= 0:
        return

    transparency = _num(node.get("bgTransparency", 0), 0.0)
    if transparency >= 1:
        return

    r, g, b = int(bg[0]), int(bg[1]), int(bg[2])

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
            paint.setColor(skia.Color(r, g, b, _alpha_from_transparency(transparency)))
    else:
        paint.setColor(skia.Color(r, g, b, _alpha_from_transparency(transparency)))

    radius = resolve_corner(node, w, h)
    rect = skia.Rect.MakeXYWH(x, y, w, h)

    if radius > 0:
        rrect = skia.RRect.MakeRectXY(rect, radius, radius)
        canvas.drawRRect(rrect, paint)
    else:
        canvas.drawRect(rect, paint)


def draw_stroke(
    canvas: skia.Canvas, x: float, y: float, w: float, h: float, node: dict, stroke: dict
) -> None:
    """Draw UIStroke border around element."""
    if w <= 0 or h <= 0:
        return

    color = stroke.get("color", [0, 0, 0])
    thickness = _num(stroke.get("thickness", 1), 1.0)
    if stroke.get("thicknessScale"):
        thickness = thickness * min(w, h)
    transparency = _num(stroke.get("transparency", 0), 0.0)

    if transparency >= 1 or thickness <= 0:
        return

    r, g, b = int(color[0]), int(color[1]), int(color[2])

    _JOIN_MAP = {
        "round": skia.Paint.Join.kRound_Join,
        "bevel": skia.Paint.Join.kBevel_Join,
        "miter": skia.Paint.Join.kMiter_Join,
    }

    paint = skia.Paint()
    paint.setAntiAlias(True)
    paint.setStyle(skia.Paint.kStroke_Style)
    paint.setStrokeWidth(float(thickness))
    join_key = str(stroke.get("lineJoin", "Round")).strip().lower()
    paint.setStrokeJoin(_JOIN_MAP.get(join_key, skia.Paint.Join.kRound_Join))

    stroke_grad = stroke.get("gradient")
    if stroke_grad:
        shader = make_gradient_shader(
            stroke_grad, x, y, w, h,
            base_color=(r, g, b), base_transparency=transparency,
        )
        if shader:
            paint.setShader(shader)
        else:
            paint.setColor(skia.Color(r, g, b, _alpha_from_transparency(transparency)))
    else:
        paint.setColor(skia.Color(r, g, b, _alpha_from_transparency(transparency)))

    # BorderStrokePosition: skia strokes are centered on the path, so
    # shift the rect inward/outward by half the thickness.
    # Then apply BorderOffset (UDim relative to min(w, h)).
    inset = 0.0
    border_pos = stroke.get("borderPosition", "Outer")
    if border_pos == "Inner":
        inset = thickness / 2
    elif border_pos == "Outer":
        inset = -thickness / 2
    # Center: inset = 0, stroke centered on edge

    border_offset = stroke.get("borderOffset")
    if border_offset:
        # Positive offset = outward, so subtract from inset
        bo = _num(border_offset.get("scale", 0), 0.0) * min(w, h) + _num(border_offset.get("offset", 0), 0.0)
        inset -= bo

    sx = x + inset
    sy = y + inset
    sw = w - inset * 2
    sh = h - inset * 2

    if sw <= 0 or sh <= 0:
        return

    radius = resolve_corner(node, w, h)
    rect = skia.Rect.MakeXYWH(sx, sy, sw, sh)
    path = skia.Path()
    if radius > 0:
        # Roblox Round joins appear slightly softer than Skia's rect-corner stroke joins.
        # Apply the softness boost only when the source actually has corner radius.
        round_join_boost = (thickness * 0.25) if join_key == "round" else 0.0
        adj_radius = max(0.0, radius - inset + round_join_boost)
        adj_radius = min(adj_radius, min(sw, sh) / 2.0)
        rrect = skia.RRect.MakeRectXY(rect, adj_radius, adj_radius)
        path.addRRect(rrect)
    else:
        # Keep truly square widgets square (Round join still controls miter behavior).
        path.addRect(rect)
    canvas.drawPath(path, paint)
