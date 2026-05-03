"""Main orchestrator: recursively render a PinevexObject tree to a PNG via skia."""
from dataclasses import dataclass, field
from pathlib import Path

import skia

from .layout import Rect, resolve_rect, BASE_WIDTH, BASE_HEIGHT
from .visuals import draw_background, draw_stroke, make_gradient_shader, resolve_corner
from .text import draw_text
from .assets import load_icon, draw_image

_debug_paint: skia.Paint | None = None


def _pil_image_from_skia_image(image: skia.Image):
    """Convert a Skia image directly to PIL without PNG encode/decode."""
    from PIL import Image

    arr = image.toarray(
        colorType=skia.ColorType.kRGBA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
    )
    return Image.fromarray(arr, "RGBA")

_STROKE_POSITION_ORDER = {"Inner": 0, "Center": 1, "Outer": 2}


def _normalize_z_index_behavior(value) -> str | None:
    """Normalize z-index behavior values to `Global`/`Sibling`."""
    if value is None:
        return None
    text = str(value)
    if "Global" in text:
        return "Global"
    if "Sibling" in text:
        return "Sibling"
    return None


def _annotate(canvas, text):
    """Set annotation on StepCanvas; no-op on regular skia.Canvas."""
    if hasattr(canvas, 'annotate'):
        canvas.annotate(text)


def _num(value, default: float = 0.0) -> float:
    """Convert arbitrary value to float with a safe default."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _seq_num(value, idx: int, default: float = 0.0) -> float:
    """Safely read a numeric sequence slot."""
    if isinstance(value, (list, tuple)) and len(value) > idx:
        return _num(value[idx], default)
    return float(default)


def _sort_strokes(strokes: list[dict]) -> list[dict]:
    """Sort strokes by BorderStrokePosition: Inner first, then Center, then Outer.

    Roblox renders strokes in this order so that outer strokes visually cover inner ones
    where they overlap.
    """
    return sorted(strokes, key=lambda s: _STROKE_POSITION_ORDER.get(
        s.get("borderPosition", "Outer"), 1))


def _draw_node_strokes(canvas: skia.Canvas, node: dict, rect: Rect) -> None:
    """Draw only the strokes for a node (deferred pass), respecting rotation."""
    if node.get("visible") is False:
        return
    strokes = node.get("strokes", [])
    if not strokes:
        return
    canvas.save()
    rotation = node.get("rotation")
    if rotation:
        cx, cy = rect.x + rect.w / 2.0, rect.y + rect.h / 2.0
        canvas.rotate(float(rotation), cx, cy)
    is_text = node.get("type", "") in ("TextLabel", "TextButton", "TextBox")
    for s in _sort_strokes(strokes):
        if not is_text or s.get("applyMode") == "Border":
            draw_stroke(canvas, rect.x, rect.y, rect.w, rect.h, node, s)
    canvas.restore()


def _draw_debug_outline(canvas: skia.Canvas, x: float, y: float, w: float, h: float) -> None:
    """Draw a thin black outline for debug mode."""
    global _debug_paint
    if _debug_paint is None:
        _debug_paint = skia.Paint(
            Color=skia.Color(128, 0, 128, 255),
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1,
            AntiAlias=True,
        )
    canvas.drawRect(skia.Rect.MakeXYWH(x, y, w, h), _debug_paint)


def _draw_canvas_group_gradient(canvas: skia.Canvas, rect: Rect, gradient: dict) -> None:
    """Apply a CanvasGroup UIGradient over already-rendered group contents."""
    shader = make_gradient_shader(
        gradient, rect.x, rect.y, rect.w, rect.h,
        base_color=(255, 255, 255), base_transparency=0.0,
    )
    if not shader:
        return
    paint = skia.Paint()
    paint.setAntiAlias(True)
    paint.setBlendMode(skia.BlendMode.kModulate)
    paint.setShader(shader)
    canvas.drawRect(skia.Rect.MakeXYWH(rect.x, rect.y, rect.w, rect.h), paint)


def _merge_rect(a: Rect, b: Rect) -> Rect:
    """Return the union of two rects."""
    x1 = min(a.x, b.x)
    y1 = min(a.y, b.y)
    x2 = max(a.x + a.w, b.x + b.w)
    y2 = max(a.y + a.h, b.y + b.h)
    return Rect(x1, y1, x2 - x1, y2 - y1)


def _intersect_rect(a: Rect, b: Rect) -> Rect | None:
    """Return intersection of two rects, or None when disjoint."""
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x1, y1, x2 - x1, y2 - y1)


def _push_crop_clip(ctx: dict, clip_rect: Rect) -> None:
    """Push a descendant crop clip rect (intersected with current clip stack)."""
    stack = ctx.setdefault("_crop_clip_stack", [])
    current = stack[-1] if stack else None
    clipped = _intersect_rect(current, clip_rect) if current is not None else clip_rect
    stack.append(clipped)


def _pop_crop_clip(ctx: dict) -> None:
    """Pop a descendant crop clip rect."""
    stack = ctx.get("_crop_clip_stack")
    if not stack:
        return
    stack.pop()
    if not stack:
        ctx.pop("_crop_clip_stack", None)


def _crop_track_rect(ctx: dict, rect: Rect) -> None:
    """Expand crop bounds with rect, constrained by active descendant clip if any."""
    stack = ctx.get("_crop_clip_stack") or []
    if stack:
        clip_rect = stack[-1]
        if clip_rect is None:
            return
        bounded = _intersect_rect(rect, clip_rect)
        if bounded is None:
            return
    else:
        bounded = rect

    existing = ctx.get("_crop_rect")
    if existing is None:
        ctx["_crop_rect"] = Rect(bounded.x, bounded.y, bounded.w, bounded.h)
    else:
        ctx["_crop_rect"] = _merge_rect(existing, bounded)


def _crop_stroke_bleed(node: dict, rect: Rect) -> float:
    """Return max outward border-stroke bleed in pixels for crop bounds."""
    strokes = node.get("strokes", [])
    if not strokes:
        return 0.0

    node_type = node.get("type", "")
    is_text = node_type in ("TextLabel", "TextButton", "TextBox")
    max_bleed = 0.0

    for stroke in strokes:
        # Mirror render path: text nodes only draw Border-mode UIStroke here.
        if is_text and stroke.get("applyMode") != "Border":
            continue

        thickness = _num(stroke.get("thickness", 1), 1.0)
        if stroke.get("thicknessScale"):
            thickness *= min(rect.w, rect.h)
        if thickness <= 0:
            continue

        inset = 0.0
        border_pos = stroke.get("borderPosition", "Outer")
        if border_pos == "Inner":
            inset = thickness / 2.0
        elif border_pos == "Outer":
            inset = -thickness / 2.0

        border_offset = stroke.get("borderOffset")
        if isinstance(border_offset, dict):
            bo = _num(border_offset.get("scale", 0), 0.0) * min(rect.w, rect.h) + _num(
                border_offset.get("offset", 0), 0.0
            )
            inset -= bo

        # Path is stroked centered on edge, so outward bleed is:
        #   max(0, stroke_half - inset)
        bleed = max(0.0, thickness / 2.0 - inset)
        if bleed > max_bleed:
            max_bleed = bleed

    return max_bleed


def _begin_crop_tracking(ctx: dict, node: dict, rect: Rect) -> bool:
    """Enable descendant crop tracking and expand crop bounds with this rect."""
    prev_active = bool(ctx.get("_crop_track_active", False))
    active = prev_active or bool(node.get("_crop"))
    ctx["_crop_track_active"] = active
    if active:
        bleed = _crop_stroke_bleed(node, rect)
        track_rect = rect if bleed <= 0 else Rect(
            rect.x - bleed, rect.y - bleed, rect.w + bleed * 2.0, rect.h + bleed * 2.0
        )
        _crop_track_rect(ctx, track_rect)
    return prev_active


def _end_crop_tracking(ctx: dict, prev_active: bool) -> None:
    """Restore previous crop tracking state."""
    ctx["_crop_track_active"] = prev_active


def _resolve_udim(val, parent_dim: float) -> float:
    """Resolve a UDim value (dict with scale/offset, or bare number) to pixels."""
    if isinstance(val, dict):
        return _num(val.get("scale", 0), 0.0) * parent_dim + _num(val.get("offset", 0), 0.0)
    if val is None:
        return 0.0
    return _num(val, 0.0)


def _resolve_node_rect(node: dict, parent_rect: Rect, ctx: dict) -> Rect:
    """Resolve a node rect honoring sizeRef + renderer defaults."""
    return resolve_rect(
        node,
        parent_rect,
        viewport_rect=ctx.get("_viewport_rect"),
        default_size_ref=ctx.get("_default_size_ref", "parent"),
    )


def _scrolling_frame_rects(node: dict, rect: Rect,
                           parent_rect: Rect | None = None) -> tuple[Rect, bool]:
    """Return (canvas_rect, force_clip) for a ScrollingFrame, or (rect, False) otherwise.

    The canvas rect is the virtual space children are positioned in.
    force_clip signals the caller to clip to *rect* even if clipsDescendants is unset.

    CanvasSize scale references the ScrollingFrame's parent rect size.
    Roblox default CanvasSize is UDim2.new(0, 0, 2, 0) when not explicitly set.

    Pinevex canvasPosition is normalized scroll progress [x%, y%] over the
    scrollable range, not a raw pixel offset from Roblox snapshots.
    """
    if node.get("type") != "ScrollingFrame":
        return rect, False
    canvas_size = node.get("canvasSize")
    if canvas_size is None:
        # Roblox default for ScrollingFrame.CanvasSize
        canvas_size = [0, 0, 2, 0]
    canvas_pos = node.get("canvasPosition", [0, 0])
    auto = node.get("autoCanvasSize", "")
    # CanvasSize scale is resolved relative to ScrollingFrame parent space.
    ref_base = parent_rect if parent_rect is not None else rect
    ref_w = ref_base.w
    ref_h = ref_base.h
    # canvasSize is a UDim2: [xScale, yScale] or [xScale, xOffset, yScale, yOffset]
    if canvas_size and len(canvas_size) == 4:
        cw = _num(canvas_size[0], 0.0) * ref_w + _num(canvas_size[1], 0.0)
        ch = _num(canvas_size[2], 0.0) * ref_h + _num(canvas_size[3], 0.0)
    elif canvas_size and len(canvas_size) == 2:
        csx = _num(canvas_size[0], 0.0)
        csy = _num(canvas_size[1], 0.0)
        cw = csx * ref_w if csx > 0 else 0
        ch = csy * ref_h if csy > 0 else 0
    else:
        cw = 0
        ch = 0
    # Canvas is at least the visible frame area
    cw = max(cw, rect.w)
    ch = max(ch, rect.h)
    if auto in ("X", "Y", "XY"):
        extent_w, extent_h = _scrolling_content_extent(node, rect, cw, ch, {
            "_viewport_rect": Rect(0, 0, BASE_WIDTH, BASE_HEIGHT),
            "_default_size_ref": "parent",
        })
        if auto in ("X", "XY"):
            cw = max(cw, extent_w, rect.w)
        if auto in ("Y", "XY"):
            ch = max(ch, extent_h, rect.h)
    # canvasPosition is normalized [0..1] progress over the scrollable range.
    scroll_x = max(0.0, cw - rect.w)
    scroll_y = max(0.0, ch - rect.h)
    canvas_px_x = max(0.0, min(1.0, _seq_num(canvas_pos, 0, 0.0))) * scroll_x
    canvas_px_y = max(0.0, min(1.0, _seq_num(canvas_pos, 1, 0.0))) * scroll_y
    canvas_rect = Rect(rect.x - canvas_px_x, rect.y - canvas_px_y, cw, ch)
    return canvas_rect, True


def _resolve_padding(padding: dict, rect_w: float, rect_h: float) -> tuple[float, float, float, float]:
    """Resolve UIPadding dict to (top, bottom, left, right) in pixels."""
    top = _resolve_udim(padding.get("top"), rect_h)
    bottom = _resolve_udim(padding.get("bottom"), rect_h)
    left = _resolve_udim(padding.get("left"), rect_w)
    right = _resolve_udim(padding.get("right"), rect_w)
    return top, bottom, left, right


def _measure_list_main_axis(children: list[dict], size_ref_rect: Rect,
                            direction: str, spacing: float, ctx: dict) -> float:
    """Measure total main-axis extent of visible children (width for X, height for Y)."""
    total = 0.0
    count = 0
    for child in children:
        if child.get("visible") is False:
            continue
        child_rect = _resolve_node_rect(child, size_ref_rect, ctx)
        total += child_rect.w if direction == "X" else child_rect.h
        count += 1
    if count > 1:
        total += spacing * (count - 1)
    return total


def _measure_list_cross_axis(children: list[dict], size_ref_rect: Rect,
                             direction: str, ctx: dict) -> float:
    """Measure max cross-axis extent of visible list children."""
    max_cross = 0.0
    for child in children:
        if child.get("visible") is False:
            continue
        child_rect = _resolve_node_rect(child, size_ref_rect, ctx)
        cross = child_rect.h if direction == "X" else child_rect.w
        if cross > max_cross:
            max_cross = cross
    return max_cross


def _scrolling_content_extent(node: dict, rect: Rect, base_canvas_w: float,
                              base_canvas_h: float, ctx: dict) -> tuple[float, float]:
    """Estimate direct child content extent for ScrollingFrame auto sizing."""
    children = [child for child in (node.get("children") or []) if child.get("visible") is not False]
    if not children:
        return 0.0, 0.0

    child_parent = Rect(rect.x, rect.y, base_canvas_w, base_canvas_h)
    pad_top, pad_bottom, pad_left, pad_right = _resolve_padding(
        node.get("padding", {}), child_parent.w, child_parent.h
    )
    content_rect = Rect(
        child_parent.x + pad_left,
        child_parent.y + pad_top,
        max(0.0, child_parent.w - pad_left - pad_right),
        max(0.0, child_parent.h - pad_top - pad_bottom),
    )
    size_ref = content_rect if node.get("padding") else child_parent
    list_layout = node.get("list")
    grid_layout = node.get("grid")

    if list_layout and not list_layout.get("wraps", False):
        direction = list_layout.get("direction", "Y")
        spacing_raw = list_layout.get("spacing", 0)
        axis_dim = size_ref.h if direction == "Y" else size_ref.w
        spacing = _resolve_udim(spacing_raw, axis_dim)
        main = _measure_list_main_axis(children, size_ref, direction, spacing, ctx)
        cross = _measure_list_cross_axis(children, size_ref, direction, ctx)
        if direction == "X":
            return pad_left + main + pad_right, pad_top + cross + pad_bottom
        return pad_left + cross + pad_right, pad_top + main + pad_bottom

    if grid_layout:
        cell_size = grid_layout.get("cellSize", [0.1, 0.1])
        cell_padding = grid_layout.get("cellPadding", [0, 0])
        direction = grid_layout.get("direction", "X")
        cell_w = _seq_num(cell_size, 0, 0.1) * size_ref.w
        cell_h = _seq_num(cell_size, 1, 0.1) * size_ref.h
        pad_x = _seq_num(cell_padding, 0, 0.0) * size_ref.w
        pad_y = _seq_num(cell_padding, 1, 0.0) * size_ref.h
        if cell_w > 0 and cell_h > 0:
            count = len(children)
            cols = max(1, int((content_rect.w + pad_x) / (cell_w + pad_x)))
            rows = max(1, int((content_rect.h + pad_y) / (cell_h + pad_y)))
            if direction == "Y":
                used_rows = min(rows, count) if count > 0 else 0
                used_cols = ((count + rows - 1) // rows) if rows > 0 else 0
            else:
                used_cols = min(cols, count) if count > 0 else 0
                used_rows = ((count + cols - 1) // cols) if cols > 0 else 0
            extent_w = used_cols * cell_w + max(0, used_cols - 1) * pad_x
            extent_h = used_rows * cell_h + max(0, used_rows - 1) * pad_y
            return pad_left + extent_w + pad_right, pad_top + extent_h + pad_bottom

    max_right = 0.0
    max_bottom = 0.0
    for child in children:
        child_rect = _resolve_node_rect(child, content_rect, ctx)
        max_right = max(max_right, (child_rect.x + child_rect.w) - child_parent.x)
        max_bottom = max(max_bottom, (child_rect.y + child_rect.h) - child_parent.y)
    return max_right, max_bottom


def _main_axis_offset(align: str, container_dim: float, total_dim: float) -> float:
    """Return the starting offset to align total_dim within container_dim."""
    if align == "Center":
        return (container_dim - total_dim) / 2
    if align in ("Right", "Bottom"):
        return container_dim - total_dim
    return 0.0


def _render_list_children(canvas: skia.Canvas, children: list[dict], content_rect: Rect,
                          layout: dict, ctx: dict, size_ref_rect: Rect | None = None) -> None:
    """Render children in a UIListLayout arrangement."""
    direction = layout.get("direction", "Y")
    spacing_raw = layout.get("spacing", 0)
    wraps = layout.get("wraps", False)
    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    axis_dim = size_ref.h if direction == "Y" else size_ref.w
    spacing = _resolve_udim(spacing_raw, axis_dim)
    visible_children = [child for child in children if child.get("visible") is not False]

    # Wrapped horizontal lists form rows. Align each row by hAlign.
    if direction == "X" and wraps:
        if not visible_children:
            return

        main_spacing = spacing
        # For wrapped horizontal lists, inter-row spacing follows the cross axis.
        row_spacing = _resolve_udim(spacing_raw, content_rect.h)

        rows: list[tuple[list[tuple[dict, Rect]], float, float]] = []
        row_items: list[tuple[dict, Rect]] = []
        row_w = 0.0
        row_h = 0.0

        for child in visible_children:
            child_rect = _resolve_node_rect(child, size_ref, ctx)
            next_w = child_rect.w if not row_items else row_w + main_spacing + child_rect.w
            if row_items and next_w > content_rect.w:
                rows.append((row_items, row_w, row_h))
                row_items = [(child, child_rect)]
                row_w = child_rect.w
                row_h = child_rect.h
            else:
                if row_items:
                    row_w += main_spacing + child_rect.w
                else:
                    row_w = child_rect.w
                row_h = max(row_h, child_rect.h)
                row_items.append((child, child_rect))

        if row_items:
            rows.append((row_items, row_w, row_h))

        total_h = sum(h for _, _, h in rows)
        if len(rows) > 1:
            total_h += row_spacing * (len(rows) - 1)

        h_align = layout.get("hAlign", "Left")
        v_align = layout.get("vAlign", "Top")
        y_cursor = content_rect.y + _main_axis_offset(v_align, content_rect.h, total_h)

        for items, width, height in rows:
            x_cursor = content_rect.x + _main_axis_offset(h_align, content_rect.w, width)
            for child, child_rect in items:
                py = y_cursor
                if v_align == "Center":
                    py += (height - child_rect.h) / 2
                elif v_align == "Bottom":
                    py += height - child_rect.h
                placed = Rect(x_cursor, py, child_rect.w, child_rect.h)
                _render_node_at(canvas, child, placed, ctx, parent_rect=content_rect)
                x_cursor += child_rect.w + main_spacing
            y_cursor += height + row_spacing
        return

    # Wrapped vertical lists form columns. Align columns as a group, then align
    # children within each column.
    if direction == "Y" and wraps:
        if not visible_children:
            return

        main_spacing = spacing
        # For wrapped vertical lists, inter-column spacing follows the cross axis.
        column_spacing = _resolve_udim(spacing_raw, content_rect.w)

        columns: list[tuple[list[tuple[dict, Rect]], float, float]] = []
        col_items: list[tuple[dict, Rect]] = []
        col_h = 0.0
        col_w = 0.0

        for child in visible_children:
            child_rect = _resolve_node_rect(child, size_ref, ctx)
            next_h = child_rect.h if not col_items else col_h + main_spacing + child_rect.h
            if col_items and next_h > content_rect.h:
                columns.append((col_items, col_w, col_h))
                col_items = [(child, child_rect)]
                col_h = child_rect.h
                col_w = child_rect.w
            else:
                if col_items:
                    col_h += main_spacing + child_rect.h
                else:
                    col_h = child_rect.h
                col_w = max(col_w, child_rect.w)
                col_items.append((child, child_rect))

        if col_items:
            columns.append((col_items, col_w, col_h))

        total_w = sum(w for _, w, _ in columns)
        if len(columns) > 1:
            total_w += column_spacing * (len(columns) - 1)

        h_align = layout.get("hAlign", "Left")
        v_align = layout.get("vAlign", "Top")
        x_cursor = content_rect.x + _main_axis_offset(h_align, content_rect.w, total_w)

        for items, width, height in columns:
            y_cursor = content_rect.y + _main_axis_offset(v_align, content_rect.h, height)
            for child, child_rect in items:
                px = x_cursor
                if h_align == "Center":
                    px += (width - child_rect.w) / 2
                elif h_align == "Right":
                    px += width - child_rect.w
                placed = Rect(px, y_cursor, child_rect.w, child_rect.h)
                _render_node_at(canvas, child, placed, ctx, parent_rect=content_rect)
                y_cursor += child_rect.h + main_spacing
            x_cursor += width + column_spacing
        return

    # Main-axis alignment (hAlign for X, vAlign for Y) offsets the starting cursor
    if direction == "X":
        main_align = layout.get("hAlign", "Left")
    else:
        main_align = layout.get("vAlign", "Top")
    if not wraps and main_align not in ("Left", "Top"):
        total = _measure_list_main_axis(visible_children, size_ref, direction, spacing, ctx)
        cursor = _main_axis_offset(main_align, axis_dim, total)
    else:
        cursor = 0.0

    cross_cursor = 0.0
    line_max_cross = 0.0
    for child in visible_children:

        child_rect = _resolve_node_rect(child, size_ref, ctx)

        if direction == "X":
            # Wrap to next row if child exceeds container width
            if wraps and cursor > 0 and cursor + child_rect.w > content_rect.w:
                cross_cursor += line_max_cross + spacing
                cursor = 0.0
                line_max_cross = 0.0
            # Horizontal: stack left-to-right
            placed = Rect(content_rect.x + cursor, content_rect.y + cross_cursor,
                          child_rect.w, child_rect.h)
            v_align = layout.get("vAlign", "Top")
            if v_align == "Center":
                placed.y = content_rect.y + cross_cursor + (content_rect.h - child_rect.h) / 2
            elif v_align == "Bottom":
                placed.y = content_rect.y + cross_cursor + content_rect.h - child_rect.h
            cursor += child_rect.w + spacing
            line_max_cross = max(line_max_cross, child_rect.h)
        else:
            # Wrap to next column if child exceeds container height
            if wraps and cursor > 0 and cursor + child_rect.h > content_rect.h:
                cross_cursor += line_max_cross + spacing
                cursor = 0.0
                line_max_cross = 0.0
            # Vertical: stack top-to-bottom
            placed = Rect(content_rect.x + cross_cursor, content_rect.y + cursor,
                          child_rect.w, child_rect.h)
            h_align = layout.get("hAlign", "Left")
            if h_align == "Center":
                placed.x = content_rect.x + cross_cursor + (content_rect.w - child_rect.w) / 2
            elif h_align == "Right":
                placed.x = content_rect.x + cross_cursor + content_rect.w - child_rect.w
            cursor += child_rect.h + spacing
            line_max_cross = max(line_max_cross, child_rect.w)

        _render_node_at(canvas, child, placed, ctx, parent_rect=content_rect)


def _render_grid_children(canvas: skia.Canvas, children: list[dict], content_rect: Rect,
                          layout: dict, ctx: dict, size_ref_rect: Rect | None = None) -> None:
    """Render children in a UIGridLayout arrangement."""
    cell_size = layout.get("cellSize", [0.1, 0.1])
    cell_padding = layout.get("cellPadding", [0, 0])
    direction = layout.get("direction", "X")

    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    cell_w = _seq_num(cell_size, 0, 0.1) * size_ref.w
    cell_h = _seq_num(cell_size, 1, 0.1) * size_ref.h
    pad_x = _seq_num(cell_padding, 0, 0.0) * size_ref.w
    pad_y = _seq_num(cell_padding, 1, 0.0) * size_ref.h

    if cell_w <= 0 or cell_h <= 0:
        return

    cols = max(1, int((content_rect.w + pad_x) / (cell_w + pad_x)))
    rows = max(1, int((content_rect.h + pad_y) / (cell_h + pad_y)))

    def _fit_grid_child(child: dict, cell: Rect) -> Rect:
        # UIGridLayout overrides child size to the cell, then constraints (e.g. UIAspectRatioConstraint)
        # can shrink it to fit.
        w = cell.w
        h = cell.h

        aspect = child.get("aspectRatio")
        if aspect is not None and aspect > 0 and h > 0:
            current = w / h
            if current > aspect:
                w = h * aspect
            else:
                h = w / aspect

        scale = child.get("scale")
        if scale is not None:
            s = _num(scale, 1.0)
            w *= s
            h *= s

        return Rect(
            x=cell.x + (cell.w - w) / 2,
            y=cell.y + (cell.h - h) / 2,
            w=w,
            h=h,
        )

    # Match Roblox layout behavior: hidden children do not consume grid slots.
    visible_children = [child for child in children if child.get("visible") is not False]

    for i, child in enumerate(visible_children):
        if direction == "Y":
            row = i % rows
            col = i // rows
        else:
            col = i % cols
            row = i // cols
        cx = content_rect.x + col * (cell_w + pad_x)
        cy = content_rect.y + row * (cell_h + pad_y)
        cell = Rect(cx, cy, cell_w, cell_h)
        placed = _fit_grid_child(child, cell)
        _render_node_at(canvas, child, placed, ctx, parent_rect=content_rect)


def _render_node_at(canvas: skia.Canvas, node: dict, rect: Rect, ctx: dict,
                    parent_rect: Rect | None = None) -> None:
    """Render a node at an explicit rect (used by layout systems that override positioning)."""
    if node.get("visible") is False:
        return
    if rect.w <= 0 or rect.h <= 0:
        return

    if "_rect_map" in ctx and "_path" in node:
        ctx["_rect_map"][node["_path"]] = rect

    prev_crop_active = _begin_crop_tracking(ctx, node, rect)

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    canvas.save()

    rotation = node.get("rotation")
    if rotation:
        cx = rect.x + rect.w / 2.0
        cy = rect.y + rect.h / 2.0
        canvas.rotate(float(rotation), cx, cy)

    # Compute ScrollingFrame canvas rect (clip deferred until after strokes)
    canvas_rect, force_clip = _scrolling_frame_rects(node, rect, parent_rect)

    gradient = node.get("gradient")
    node_type = node.get("type", "")
    is_text = node_type in ("TextLabel", "TextButton", "TextBox")
    is_image = node_type in ("ImageLabel", "ImageButton")
    has_canvas_group_gradient = node_type == "CanvasGroup" and gradient is not None
    if has_canvas_group_gradient:
        _annotate(canvas, f"CanvasGroup layer: {name}")
        canvas.saveLayer(skia.Rect.MakeXYWH(rect.x, rect.y, rect.w, rect.h))
    node_gradient = None if has_canvas_group_gradient else gradient
    _annotate(canvas, f"BG: {name}")
    draw_background(canvas, rect.x, rect.y, rect.w, rect.h, node, gradient=node_gradient)

    # Border strokes
    for s in _sort_strokes(node.get("strokes", [])):
        if not is_text or s.get("applyMode") == "Border":
            _annotate(canvas, f"Stroke: {name} — thick={s.get('thickness', 1)}, pos={s.get('borderPosition', 'Outer')}")
            draw_stroke(canvas, rect.x, rect.y, rect.w, rect.h, node, s)

    # Clip AFTER strokes so Outer strokes aren't clipped by own clipsDescendants
    pushed_crop_clip = False
    if force_clip or node.get("clipsDescendants"):
        corner_r = resolve_corner(node, rect.w, rect.h)
        sk_rect = skia.Rect.MakeXYWH(rect.x, rect.y, rect.w, rect.h)
        if corner_r > 0:
            canvas.clipRRect(skia.RRect.MakeRectXY(sk_rect, corner_r, corner_r))
        else:
            canvas.clipRect(sk_rect)
        _push_crop_clip(ctx, rect)
        pushed_crop_clip = True

    if is_text and node.get("text"):
        _annotate(canvas, f"Text: {name} — '{node.get('text', '')[:30]}'")
        draw_text(canvas, rect.x, rect.y, rect.w, rect.h, node, ctx.get("fonts_dir"),
                  gradient=node_gradient if is_text else None)

    if is_image or node.get("icon"):
        img = None
        icon_key = node.get("icon", "")
        icons_dir = ctx.get("icons_dir")
        if icon_key and icons_dir:
            img = load_icon(icon_key, icons_dir)
        _annotate(canvas, f"Image: {name} — {icon_key}")
        draw_image(canvas, rect.x, rect.y, rect.w, rect.h, node, img,
                   gradient=node_gradient if is_image else None)

    # Recurse into children of this layout-placed node
    children = node.get("children", [])
    if children:
        # ScrollingFrame: children are positioned within the canvas rect
        child_parent = canvas_rect if force_clip else rect
        visible_child_parent = rect
        pad_top, pad_bottom, pad_left, pad_right = _resolve_padding(
            node.get("padding", {}), child_parent.w, child_parent.h)
        inner = Rect(
            child_parent.x + pad_left,
            child_parent.y + pad_top,
            child_parent.w - pad_left - pad_right,
            child_parent.h - pad_top - pad_bottom,
        )
        visible_inner = Rect(
            visible_child_parent.x + pad_left,
            visible_child_parent.y + pad_top,
            visible_child_parent.w - pad_left - pad_right,
            visible_child_parent.h - pad_top - pad_bottom,
        )
        list_layout = node.get("list")
        grid_layout = node.get("grid")
        children_ordered = sorted(children, key=lambda c: c.get("layoutOrder", 0))
        if node.get("type") == "ScrollingFrame":
            auto_canvas = node.get("autoCanvasSize")
            if auto_canvas:
                size_ref_for_layout = visible_inner if node.get("padding") else visible_child_parent
            else:
                size_ref_for_layout = inner if node.get("padding") else child_parent
        else:
            size_ref_for_layout = inner if node.get("padding") else child_parent
        if list_layout:
            _render_list_children(canvas, children_ordered, inner, list_layout, ctx,
                                  size_ref_rect=size_ref_for_layout)
        elif grid_layout:
            _render_grid_children(canvas, children_ordered, inner, grid_layout, ctx,
                                  size_ref_rect=size_ref_for_layout)
        else:
            children_draw = sorted(children, key=lambda c: c.get("zIndex", 1))
            for child in children_draw:
                render_node(canvas, child, inner, ctx)

    if pushed_crop_clip:
        _pop_crop_clip(ctx)

    if has_canvas_group_gradient:
        _annotate(canvas, f"CanvasGroup gradient: {name}")
        _draw_canvas_group_gradient(canvas, rect, gradient)
        canvas.restore()

    if ctx.get("debug"):
        _annotate(canvas, f"Debug outline: {name}")
        _draw_debug_outline(canvas, rect.x, rect.y, rect.w, rect.h)

    canvas.restore()
    _end_crop_tracking(ctx, prev_crop_active)


def render_node(canvas: skia.Canvas, node: dict, parent_rect: Rect, ctx: dict) -> None:
    """Recursively render a PinevexObject node and all its children.

    ctx dict contains: icons_dir (Path|None), fonts_dir (Path|None)
    """
    # 1. Check visibility
    if node.get("visible") is False:
        return

    # 2. Resolve absolute pixel rect
    rect = _resolve_node_rect(node, parent_rect, ctx)

    # 3. Skip zero-area nodes
    if rect.w <= 0 or rect.h <= 0:
        return

    if "_rect_map" in ctx and "_path" in node:
        ctx["_rect_map"][node["_path"]] = rect

    prev_crop_active = _begin_crop_tracking(ctx, node, rect)

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    # 4. Save canvas state
    canvas.save()

    # 5. Apply rotation around rect center
    rotation = node.get("rotation")
    if rotation:
        cx = rect.x + rect.w / 2.0
        cy = rect.y + rect.h / 2.0
        canvas.rotate(float(rotation), cx, cy)

    # 6. Compute ScrollingFrame canvas rect (clip deferred until after strokes)
    canvas_rect, force_clip = _scrolling_frame_rects(node, rect, parent_rect)

    # 7. Route gradient to correct draw function
    gradient = node.get("gradient")
    node_type = node.get("type", "")
    is_text = node_type in ("TextLabel", "TextButton", "TextBox")
    is_image = node_type in ("ImageLabel", "ImageButton")
    has_canvas_group_gradient = node_type == "CanvasGroup" and gradient is not None
    if has_canvas_group_gradient:
        _annotate(canvas, f"CanvasGroup layer: {name}")
        canvas.saveLayer(skia.Rect.MakeXYWH(rect.x, rect.y, rect.w, rect.h))
    node_gradient = None if has_canvas_group_gradient else gradient
    _annotate(canvas, f"BG: {name}")
    draw_background(canvas, rect.x, rect.y, rect.w, rect.h, node, gradient=node_gradient)

    # 8. Border strokes (skipped during pass-1 of two-pass deferred rendering)
    if not ctx.get("_skip_strokes"):
        for s in _sort_strokes(node.get("strokes", [])):
            if not is_text or s.get("applyMode") == "Border":
                _annotate(canvas, f"Stroke: {name} — thick={s.get('thickness', 1)}, pos={s.get('borderPosition', 'Outer')}")
                draw_stroke(canvas, rect.x, rect.y, rect.w, rect.h, node, s)

    # 8b. Clip AFTER strokes so Outer strokes aren't clipped by own clipsDescendants
    pushed_crop_clip = False
    if force_clip or node.get("clipsDescendants"):
        corner_r = resolve_corner(node, rect.w, rect.h)
        sk_rect = skia.Rect.MakeXYWH(rect.x, rect.y, rect.w, rect.h)
        if corner_r > 0:
            canvas.clipRRect(skia.RRect.MakeRectXY(sk_rect, corner_r, corner_r))
        else:
            canvas.clipRect(sk_rect)
        _push_crop_clip(ctx, rect)
        pushed_crop_clip = True

    # 9. Text rendering for text-based types
    if is_text and node.get("text"):
        _annotate(canvas, f"Text: {name} — '{node.get('text', '')[:30]}'")
        draw_text(canvas, rect.x, rect.y, rect.w, rect.h, node, ctx.get("fonts_dir"),
                  gradient=node_gradient if is_text else None)

    # 10. Image rendering for image types or nodes with an icon
    if is_image or node.get("icon"):
        img = None
        icon_key = node.get("icon", "")
        icons_dir = ctx.get("icons_dir")
        if icon_key and icons_dir:
            img = load_icon(icon_key, icons_dir)
        _annotate(canvas, f"Image: {name} — {icon_key}")
        draw_image(canvas, rect.x, rect.y, rect.w, rect.h, node, img,
                   gradient=node_gradient if is_image else None)

    # 11-13. Render children with layout support
    children = node.get("children", [])
    if children:
        # ScrollingFrame: children are positioned within the canvas rect
        child_parent = canvas_rect if force_clip else rect
        visible_child_parent = rect
        # Apply padding to content area
        pad_top, pad_bottom, pad_left, pad_right = _resolve_padding(
            node.get("padding", {}), child_parent.w, child_parent.h)
        content_rect = Rect(
            child_parent.x + pad_left,
            child_parent.y + pad_top,
            child_parent.w - pad_left - pad_right,
            child_parent.h - pad_top - pad_bottom,
        )
        visible_content_rect = Rect(
            visible_child_parent.x + pad_left,
            visible_child_parent.y + pad_top,
            visible_child_parent.w - pad_left - pad_right,
            visible_child_parent.h - pad_top - pad_bottom,
        )

        # Sort by layoutOrder (for list/grid), then zIndex for draw order
        children_ordered = sorted(children, key=lambda c: c.get("layoutOrder", 0))

        list_layout = node.get("list")
        grid_layout = node.get("grid")
        if node.get("type") == "ScrollingFrame":
            auto_canvas = node.get("autoCanvasSize")
            if auto_canvas:
                size_ref_for_layout = visible_content_rect if node.get("padding") else visible_child_parent
            else:
                size_ref_for_layout = content_rect if node.get("padding") else child_parent
        else:
            size_ref_for_layout = content_rect if node.get("padding") else child_parent

        if list_layout:
            _render_list_children(canvas, children_ordered, content_rect, list_layout, ctx,
                                  size_ref_rect=size_ref_for_layout)
        elif grid_layout:
            _render_grid_children(canvas, children_ordered, content_rect, grid_layout, ctx,
                                  size_ref_rect=size_ref_for_layout)
        else:
            # Default: each child positioned independently
            children_draw = sorted(children, key=lambda c: c.get("zIndex", 1))
            for child in children_draw:
                render_node(canvas, child, content_rect, ctx)

    if pushed_crop_clip:
        _pop_crop_clip(ctx)

    if has_canvas_group_gradient:
        _annotate(canvas, f"CanvasGroup gradient: {name}")
        _draw_canvas_group_gradient(canvas, rect, gradient)
        canvas.restore()

    # 14. Debug outline
    if ctx.get("debug"):
        _annotate(canvas, f"Debug outline: {name}")
        _draw_debug_outline(canvas, rect.x, rect.y, rect.w, rect.h)

    # 15. Restore canvas state
    canvas.restore()
    _end_crop_tracking(ctx, prev_crop_active)


## ---------------------------------------------------------------------------
#  Global ZIndexBehavior — two-pass rendering
# ---------------------------------------------------------------------------

@dataclass
class _DrawEntry:
    z_index: int           # node's zIndex (default 0)
    dfs_order: int         # DFS insertion order (tiebreaker)
    node: dict
    rect: Rect
    canvas_ops: list = field(default_factory=list)  # ordered rotation/clip ops from ancestors + self


def _collect_entries(node: dict, parent_rect: Rect, parent_ops: list,
                     entries: list, ctx: dict, override_rect: Rect | None = None) -> None:
    """DFS walk collecting _DrawEntry items for Global z-index mode."""
    if node.get("visible") is False:
        return

    rect = override_rect if override_rect is not None else _resolve_node_rect(node, parent_rect, ctx)

    if rect.w <= 0 or rect.h <= 0:
        return

    if "_rect_map" in ctx and "_path" in node:
        ctx["_rect_map"][node["_path"]] = rect

    prev_crop_active = _begin_crop_tracking(ctx, node, rect)
    pushed_crop_clip = False
    try:
        # Build canvas ops: copy parent chain, then add this node's rotation + clip
        ops = list(parent_ops)

        rotation = node.get("rotation")
        if rotation:
            cx = rect.x + rect.w / 2.0
            cy = rect.y + rect.h / 2.0
            ops.append(("rotate", float(rotation), cx, cy))

        ignore_scroll_clipping = bool(ctx.get("_ignore_scroll_clipping", False))

        # Compute ScrollingFrame canvas rect (self-clip deferred so own strokes aren't clipped)
        canvas_rect, force_clip = _scrolling_frame_rects(node, rect, parent_rect)

        # Node entry WITHOUT self-clip — own Outer strokes must not be clipped
        entries.append(_DrawEntry(
            z_index=node.get("zIndex", 1),
            dfs_order=len(entries),
            node=node,
            rect=rect,
            canvas_ops=list(ops),
        ))

        # Add self-clip AFTER entry so only children inherit it
        should_clip_children = force_clip or node.get("clipsDescendants")
        if ignore_scroll_clipping and node.get("type") == "ScrollingFrame":
            should_clip_children = False
        if should_clip_children:
            corner_r = resolve_corner(node, rect.w, rect.h)
            if corner_r > 0:
                ops.append(("clip_rrect", rect.x, rect.y, rect.w, rect.h, corner_r))
            else:
                ops.append(("clip_rect", rect.x, rect.y, rect.w, rect.h))
            _push_crop_clip(ctx, rect)
            pushed_crop_clip = True

        # Recurse children
        children = node.get("children", [])
        if not children:
            return

        # ScrollingFrame: children are positioned within the canvas rect
        child_parent = canvas_rect if force_clip else rect
        visible_child_parent = rect
        pad_top, pad_bottom, pad_left, pad_right = _resolve_padding(
            node.get("padding", {}), child_parent.w, child_parent.h)
        content_rect = Rect(
            child_parent.x + pad_left,
            child_parent.y + pad_top,
            child_parent.w - pad_left - pad_right,
            child_parent.h - pad_top - pad_bottom,
        )
        visible_content_rect = Rect(
            visible_child_parent.x + pad_left,
            visible_child_parent.y + pad_top,
            visible_child_parent.w - pad_left - pad_right,
            visible_child_parent.h - pad_top - pad_bottom,
        )

        list_layout = node.get("list")
        grid_layout = node.get("grid")
        children_ordered = sorted(children, key=lambda c: c.get("layoutOrder", 0))
        if node.get("type") == "ScrollingFrame":
            auto_canvas = node.get("autoCanvasSize")
            if auto_canvas:
                size_ref_for_layout = visible_content_rect if node.get("padding") else visible_child_parent
            else:
                size_ref_for_layout = content_rect if node.get("padding") else child_parent
        else:
            size_ref_for_layout = content_rect if node.get("padding") else child_parent

        if list_layout:
            _collect_list_children(children_ordered, content_rect, list_layout, ops, entries, ctx,
                                   size_ref_rect=size_ref_for_layout)
        elif grid_layout:
            _collect_grid_children(children_ordered, content_rect, grid_layout, ops, entries, ctx,
                                   size_ref_rect=size_ref_for_layout)
        else:
            for child in children:
                _collect_entries(child, content_rect, ops, entries, ctx)
    finally:
        if pushed_crop_clip:
            _pop_crop_clip(ctx)
        _end_crop_tracking(ctx, prev_crop_active)


def _collect_list_children(children: list[dict], content_rect: Rect,
                           layout: dict, parent_ops: list, entries: list, ctx: dict,
                           size_ref_rect: Rect | None = None) -> None:
    """Collect entries for UIListLayout children (mirrors _render_list_children)."""
    direction = layout.get("direction", "Y")
    spacing_raw = layout.get("spacing", 0)
    wraps = layout.get("wraps", False)
    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    axis_dim = size_ref.h if direction == "Y" else size_ref.w
    spacing = _resolve_udim(spacing_raw, axis_dim)
    visible_children = [child for child in children if child.get("visible") is not False]

    # Wrapped horizontal lists form rows. Align each row by hAlign.
    if direction == "X" and wraps:
        if not visible_children:
            return

        main_spacing = spacing
        # For wrapped horizontal lists, inter-row spacing follows the cross axis.
        row_spacing = _resolve_udim(spacing_raw, content_rect.h)

        rows: list[tuple[list[tuple[dict, Rect]], float, float]] = []
        row_items: list[tuple[dict, Rect]] = []
        row_w = 0.0
        row_h = 0.0

        for child in visible_children:
            child_rect = _resolve_node_rect(child, size_ref, ctx)
            next_w = child_rect.w if not row_items else row_w + main_spacing + child_rect.w
            if row_items and next_w > content_rect.w:
                rows.append((row_items, row_w, row_h))
                row_items = [(child, child_rect)]
                row_w = child_rect.w
                row_h = child_rect.h
            else:
                if row_items:
                    row_w += main_spacing + child_rect.w
                else:
                    row_w = child_rect.w
                row_h = max(row_h, child_rect.h)
                row_items.append((child, child_rect))

        if row_items:
            rows.append((row_items, row_w, row_h))

        total_h = sum(h for _, _, h in rows)
        if len(rows) > 1:
            total_h += row_spacing * (len(rows) - 1)

        h_align = layout.get("hAlign", "Left")
        v_align = layout.get("vAlign", "Top")
        y_cursor = content_rect.y + _main_axis_offset(v_align, content_rect.h, total_h)

        for items, width, height in rows:
            x_cursor = content_rect.x + _main_axis_offset(h_align, content_rect.w, width)
            for child, child_rect in items:
                py = y_cursor
                if v_align == "Center":
                    py += (height - child_rect.h) / 2
                elif v_align == "Bottom":
                    py += height - child_rect.h
                placed = Rect(x_cursor, py, child_rect.w, child_rect.h)
                _collect_entries(child, content_rect, parent_ops, entries, ctx, override_rect=placed)
                x_cursor += child_rect.w + main_spacing
            y_cursor += height + row_spacing
        return

    # Wrapped vertical lists form columns. Align columns as a group, then align
    # children within each column.
    if direction == "Y" and wraps:
        if not visible_children:
            return

        main_spacing = spacing
        # For wrapped vertical lists, inter-column spacing follows the cross axis.
        column_spacing = _resolve_udim(spacing_raw, content_rect.w)

        columns: list[tuple[list[tuple[dict, Rect]], float, float]] = []
        col_items: list[tuple[dict, Rect]] = []
        col_h = 0.0
        col_w = 0.0

        for child in visible_children:
            child_rect = _resolve_node_rect(child, size_ref, ctx)
            next_h = child_rect.h if not col_items else col_h + main_spacing + child_rect.h
            if col_items and next_h > content_rect.h:
                columns.append((col_items, col_w, col_h))
                col_items = [(child, child_rect)]
                col_h = child_rect.h
                col_w = child_rect.w
            else:
                if col_items:
                    col_h += main_spacing + child_rect.h
                else:
                    col_h = child_rect.h
                col_w = max(col_w, child_rect.w)
                col_items.append((child, child_rect))

        if col_items:
            columns.append((col_items, col_w, col_h))

        total_w = sum(w for _, w, _ in columns)
        if len(columns) > 1:
            total_w += column_spacing * (len(columns) - 1)

        h_align = layout.get("hAlign", "Left")
        v_align = layout.get("vAlign", "Top")
        x_cursor = content_rect.x + _main_axis_offset(h_align, content_rect.w, total_w)

        for items, width, height in columns:
            y_cursor = content_rect.y + _main_axis_offset(v_align, content_rect.h, height)
            for child, child_rect in items:
                px = x_cursor
                if h_align == "Center":
                    px += (width - child_rect.w) / 2
                elif h_align == "Right":
                    px += width - child_rect.w
                placed = Rect(px, y_cursor, child_rect.w, child_rect.h)
                _collect_entries(child, content_rect, parent_ops, entries, ctx, override_rect=placed)
                y_cursor += child_rect.h + main_spacing
            x_cursor += width + column_spacing
        return

    # Main-axis alignment offset
    if direction == "X":
        main_align = layout.get("hAlign", "Left")
    else:
        main_align = layout.get("vAlign", "Top")
    if not wraps and main_align not in ("Left", "Top"):
        total = _measure_list_main_axis(visible_children, size_ref, direction, spacing, ctx)
        cursor = _main_axis_offset(main_align, axis_dim, total)
    else:
        cursor = 0.0

    cross_cursor = 0.0
    line_max_cross = 0.0

    for child in visible_children:

        child_rect = _resolve_node_rect(child, size_ref, ctx)

        if direction == "X":
            if wraps and cursor > 0 and cursor + child_rect.w > content_rect.w:
                cross_cursor += line_max_cross + spacing
                cursor = 0.0
                line_max_cross = 0.0
            placed = Rect(content_rect.x + cursor, content_rect.y + cross_cursor,
                          child_rect.w, child_rect.h)
            v_align = layout.get("vAlign", "Top")
            if v_align == "Center":
                placed.y = content_rect.y + cross_cursor + (content_rect.h - child_rect.h) / 2
            elif v_align == "Bottom":
                placed.y = content_rect.y + cross_cursor + content_rect.h - child_rect.h
            cursor += child_rect.w + spacing
            line_max_cross = max(line_max_cross, child_rect.h)
        else:
            if wraps and cursor > 0 and cursor + child_rect.h > content_rect.h:
                cross_cursor += line_max_cross + spacing
                cursor = 0.0
                line_max_cross = 0.0
            placed = Rect(content_rect.x + cross_cursor, content_rect.y + cursor,
                          child_rect.w, child_rect.h)
            h_align = layout.get("hAlign", "Left")
            if h_align == "Center":
                placed.x = content_rect.x + cross_cursor + (content_rect.w - child_rect.w) / 2
            elif h_align == "Right":
                placed.x = content_rect.x + cross_cursor + content_rect.w - child_rect.w
            cursor += child_rect.h + spacing
            line_max_cross = max(line_max_cross, child_rect.w)

        _collect_entries(child, content_rect, parent_ops, entries, ctx, override_rect=placed)


def _collect_grid_children(children: list[dict], content_rect: Rect,
                           layout: dict, parent_ops: list, entries: list, ctx: dict,
                           size_ref_rect: Rect | None = None) -> None:
    """Collect entries for UIGridLayout children (mirrors _render_grid_children)."""
    cell_size = layout.get("cellSize", [0.1, 0.1])
    cell_padding = layout.get("cellPadding", [0, 0])
    direction = layout.get("direction", "X")

    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    cell_w = _seq_num(cell_size, 0, 0.1) * size_ref.w
    cell_h = _seq_num(cell_size, 1, 0.1) * size_ref.h
    pad_x = _seq_num(cell_padding, 0, 0.0) * size_ref.w
    pad_y = _seq_num(cell_padding, 1, 0.0) * size_ref.h

    if cell_w <= 0 or cell_h <= 0:
        return

    cols = max(1, int((content_rect.w + pad_x) / (cell_w + pad_x)))
    rows = max(1, int((content_rect.h + pad_y) / (cell_h + pad_y)))

    def _fit_grid_child(child: dict, cell: Rect) -> Rect:
        w = cell.w
        h = cell.h

        aspect = child.get("aspectRatio")
        if aspect is not None and aspect > 0 and h > 0:
            current = w / h
            if current > aspect:
                w = h * aspect
            else:
                h = w / aspect

        scale = child.get("scale")
        if scale is not None:
            s = _num(scale, 1.0)
            w *= s
            h *= s

        return Rect(
            x=cell.x + (cell.w - w) / 2,
            y=cell.y + (cell.h - h) / 2,
            w=w,
            h=h,
        )

    # Match Roblox layout behavior: hidden children do not consume grid slots.
    visible_children = [child for child in children if child.get("visible") is not False]

    for i, child in enumerate(visible_children):
        if direction == "Y":
            row = i % rows
            col = i // rows
        else:
            col = i % cols
            row = i // cols
        cx = content_rect.x + col * (cell_w + pad_x)
        cy = content_rect.y + row * (cell_h + pad_y)
        cell = Rect(cx, cy, cell_w, cell_h)
        placed = _fit_grid_child(child, cell)
        _collect_entries(child, content_rect, parent_ops, entries, ctx, override_rect=placed)


def _draw_single_node(canvas: skia.Canvas, node: dict, rect: Rect, ctx: dict) -> None:
    """Draw a single node's visuals (background, stroke, text, image) without recursion."""
    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")
    gradient = node.get("gradient")
    node_type = node.get("type", "")
    is_text = node_type in ("TextLabel", "TextButton", "TextBox")
    is_image = node_type in ("ImageLabel", "ImageButton")
    _annotate(canvas, f"BG: {name}")
    draw_background(canvas, rect.x, rect.y, rect.w, rect.h, node, gradient=gradient)

    # Border strokes — after background, before content
    for s in _sort_strokes(node.get("strokes", [])):
        if not is_text or s.get("applyMode") == "Border":
            _annotate(canvas, f"Stroke: {name} — thick={s.get('thickness', 1)}, pos={s.get('borderPosition', 'Outer')}")
            draw_stroke(canvas, rect.x, rect.y, rect.w, rect.h, node, s)

    if is_text and node.get("text"):
        _annotate(canvas, f"Text: {name} — '{node.get('text', '')[:30]}'")
        draw_text(canvas, rect.x, rect.y, rect.w, rect.h, node, ctx.get("fonts_dir"),
                  gradient=gradient if is_text else None)

    if is_image or node.get("icon"):
        img = None
        icon_key = node.get("icon", "")
        icons_dir = ctx.get("icons_dir")
        if icon_key and icons_dir:
            img = load_icon(icon_key, icons_dir)
        _annotate(canvas, f"Image: {name} — {icon_key}")
        draw_image(canvas, rect.x, rect.y, rect.w, rect.h, node, img,
                   gradient=gradient if is_image else None)

    if ctx.get("debug"):
        _annotate(canvas, f"Debug outline: {name}")
        _draw_debug_outline(canvas, rect.x, rect.y, rect.w, rect.h)


def _render_global(canvas: skia.Canvas, obj: dict, root_rect: Rect, ctx: dict) -> None:
    """Render using Global ZIndexBehavior: flat sort by zIndex across entire tree."""
    entries: list[_DrawEntry] = []
    _collect_entries(obj, root_rect, [], entries, ctx)

    entries.sort(key=lambda e: (e.z_index, e.dfs_order))

    for entry in entries:
        canvas.save()
        for op in entry.canvas_ops:
            if op[0] == "rotate":
                canvas.rotate(op[1], op[2], op[3])
            elif op[0] == "clip_rrect":
                sk_rect = skia.Rect.MakeXYWH(op[1], op[2], op[3], op[4])
                canvas.clipRRect(skia.RRect.MakeRectXY(sk_rect, op[5], op[5]))
            elif op[0] == "clip_rect":
                canvas.clipRect(skia.Rect.MakeXYWH(op[1], op[2], op[3], op[4]))
        _draw_single_node(canvas, entry.node, entry.rect, ctx)
        canvas.restore()


def render_json(
    obj: dict,
    output_path: str | Path | None = None,
    width: int = BASE_WIDTH,
    height: int = BASE_HEIGHT,
    icons_dir: Path | None = None,
    fonts_dir: Path | None = None,
    bg_color: tuple = (255, 255, 255),
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "parent",
    debug: bool = False,
    out: dict | None = None,
    rect_map: dict | None = None,
):
    """Render a complete PinevexObject to a PNG file.

    If *output_path* is ``None``, returns a ``PIL.Image`` instead of writing
    to disk.

    If *out* is provided, any node with ``_crop: True`` will have its resolved
    rect stored in ``out["crop_rect"]`` as a ``Rect``.

    If *rect_map* is provided, every node that has a ``_path`` key will have
    its resolved ``Rect`` stored in ``rect_map[node["_path"]]``.
    """
    surface = skia.Surface(width, height)
    canvas = surface.getCanvas()

    # Fill with background color (RGB or RGBA)
    _annotate(canvas, "Clear canvas")
    if len(bg_color) == 4:
        canvas.clear(skia.Color(*bg_color))
    else:
        canvas.clear(skia.Color(*bg_color, 255))

    root_rect = Rect(0, 0, width, height)
    ctx = {
        "icons_dir": icons_dir,
        "fonts_dir": fonts_dir,
        "debug": debug,
        "_viewport_rect": root_rect,
        "_default_size_ref": str(default_size_ref or "parent").lower(),
    }
    if rect_map is not None:
        ctx["_rect_map"] = rect_map

    requested_behavior = _normalize_z_index_behavior(z_index_behavior) or "Sibling"
    root_behavior = _normalize_z_index_behavior(obj.get("zIndexBehavior")) or requested_behavior

    if root_behavior == "Global":
        _render_global(canvas, obj, root_rect, ctx)
    else:
        render_node(canvas, obj, root_rect, ctx)

    image = surface.makeImageSnapshot()

    if out is not None and "_crop_rect" in ctx:
        out["crop_rect"] = ctx["_crop_rect"]

    if output_path is None:
        return _pil_image_from_skia_image(image)
    else:
        image.save(str(output_path), skia.kPNG)


def collect_layout_info(
    obj: dict,
    *,
    width: int = BASE_WIDTH,
    height: int = BASE_HEIGHT,
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "parent",
    out: dict | None = None,
    rect_map: dict | None = None,
    ignore_scroll_clipping: bool = False,
) -> dict:
    """Resolve layout/crop geometry without rasterizing any pixels.

    This runs the same placement traversal used by the renderer, including
    list/grid layout, scrolling-frame canvas handling, padding, clipping, and
    crop tracking, but it does not draw.
    """
    root_rect = Rect(0, 0, width, height)
    ctx = {
        "_viewport_rect": root_rect,
        "_default_size_ref": str(default_size_ref or "parent").lower(),
        "_ignore_scroll_clipping": bool(ignore_scroll_clipping),
    }
    if rect_map is not None:
        ctx["_rect_map"] = rect_map

    # Geometry/crop tracking is independent of z-order draw submission, so a
    # single collection traversal is sufficient here.
    _collect_entries(obj, root_rect, [], [], ctx)

    result: dict = {}
    if out is not None:
        result = out
    if "_crop_rect" in ctx:
        result["crop_rect"] = ctx["_crop_rect"]
    return result
