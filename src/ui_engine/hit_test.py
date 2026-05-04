"""Hit-test / GetGuiObjectsAtPosition for PinevexObject trees.

Mirrors the renderer's traversal logic (layout, clipping, z-order) but collects
overlapping nodes instead of drawing.  Returns results topmost-first so the
caller can identify occluders and hide them by mutating the original dicts.
"""

from .layout import Rect, resolve_rect, BASE_WIDTH, BASE_HEIGHT


# ---------------------------------------------------------------------------
#  Helpers (mirrored from renderer.py, skia-free)
# ---------------------------------------------------------------------------

def _num(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _seq_num(value, idx: int, default: float = 0.0) -> float:
    if isinstance(value, (list, tuple)) and len(value) > idx:
        return _num(value[idx], default)
    return float(default)


def _resolve_udim(val, parent_dim: float) -> float:
    if isinstance(val, dict):
        return _num(val.get("scale", 0), 0.0) * parent_dim + _num(val.get("offset", 0), 0.0)
    if val is None:
        return 0.0
    return _num(val, 0.0)


def _resolve_padding(padding: dict, rect_w: float, rect_h: float) -> tuple[float, float, float, float]:
    top = _resolve_udim(padding.get("top"), rect_h)
    bottom = _resolve_udim(padding.get("bottom"), rect_h)
    left = _resolve_udim(padding.get("left"), rect_w)
    right = _resolve_udim(padding.get("right"), rect_w)
    return top, bottom, left, right


def _resolve_node_rect(node: dict, parent_rect: Rect, ctx: dict) -> Rect:
    return resolve_rect(
        node,
        parent_rect,
        viewport_rect=ctx.get("_viewport_rect"),
        default_size_ref=ctx.get("_default_size_ref", "parent"),
    )


def _scrolling_frame_rects(node: dict, rect: Rect,
                           parent_rect: Rect | None = None) -> tuple[Rect, bool]:
    if node.get("type") != "ScrollingFrame":
        return rect, False
    canvas_size = node.get("canvasSize")
    if canvas_size is None:
        canvas_size = [0, 0, 2, 0]
    # Pinevex canvasPosition is normalized scroll progress [x%, y%] over the
    # scrollable range, not a raw pixel offset from Roblox snapshots.
    canvas_pos = node.get("canvasPosition", [0, 0])
    auto = node.get("autoCanvasSize", "")
    ref_base = parent_rect if parent_rect is not None else rect
    ref_w = ref_base.w
    ref_h = ref_base.h
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
    scroll_x = max(0.0, cw - rect.w)
    scroll_y = max(0.0, ch - rect.h)
    canvas_px_x = max(0.0, min(1.0, _seq_num(canvas_pos, 0, 0.0))) * scroll_x
    canvas_px_y = max(0.0, min(1.0, _seq_num(canvas_pos, 1, 0.0))) * scroll_y
    canvas_rect = Rect(
        rect.x - canvas_px_x,
        rect.y - canvas_px_y,
        cw,
        ch,
    )
    return canvas_rect, True


def _intersect_rect(a: Rect, b: Rect) -> Rect | None:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x1, y1, x2 - x1, y2 - y1)


def _measure_list_main_axis(children: list[dict], size_ref_rect: Rect,
                            direction: str, spacing: float, ctx: dict) -> float:
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
    if align == "Center":
        return (container_dim - total_dim) / 2
    if align in ("Right", "Bottom"):
        return container_dim - total_dim
    return 0.0


# ---------------------------------------------------------------------------
#  Hit-test core
# ---------------------------------------------------------------------------

def _rects_overlap(a: Rect, b: Rect) -> bool:
    """Check if two rects overlap (non-zero intersection)."""
    return (a.x < b.x + b.w and a.x + a.w > b.x and
            a.y < b.y + b.h and a.y + a.h > b.y)


def _hit_node(node: dict, rect: Rect, query: Rect, clip_stack: list[Rect],
              hits: list[dict], ctx: dict, parent_rect: Rect | None = None,
              rect_index: dict[int, Rect] | None = None) -> None:
    """Traverse a single node, collecting hits in draw order (bottom-up)."""
    if node.get("visible") is False:
        return
    if rect.w <= 0 or rect.h <= 0:
        return

    # Effective clip = intersection of all ancestor clips
    effective_rect = rect
    for clip in clip_stack:
        clipped = _intersect_rect(effective_rect, clip)
        if clipped is None:
            return  # fully clipped out
        effective_rect = clipped

    if rect_index is not None:
        rect_index[id(node)] = effective_rect

    # Check overlap with query region
    overlaps = _rects_overlap(effective_rect, query)

    # ScrollingFrame canvas rect
    canvas_rect, force_clip = _scrolling_frame_rects(node, rect, parent_rect)

    # If this node overlaps, record it
    if overlaps:
        hits.append(node)

    # Push clip for children if clipsDescendants or ScrollingFrame
    pushed_clip = False
    if force_clip or node.get("clipsDescendants"):
        clip_stack.append(rect)
        pushed_clip = True

    # Recurse children
    children = node.get("children", [])
    if children:
        child_parent = canvas_rect if force_clip else rect
        pad_top, pad_bottom, pad_left, pad_right = _resolve_padding(
            node.get("padding", {}), child_parent.w, child_parent.h)
        content_rect = Rect(
            child_parent.x + pad_left,
            child_parent.y + pad_top,
            child_parent.w - pad_left - pad_right,
            child_parent.h - pad_top - pad_bottom,
        )

        list_layout = node.get("list")
        grid_layout = node.get("grid")
        children_ordered = sorted(children, key=lambda c: c.get("layoutOrder", 0))
        size_ref_for_layout = content_rect if node.get("padding") else child_parent

        if list_layout:
            _hit_list_children(children_ordered, content_rect, list_layout,
                               query, clip_stack, hits, ctx,
                               size_ref_rect=size_ref_for_layout,
                               rect_index=rect_index)
        elif grid_layout:
            _hit_grid_children(children_ordered, content_rect, grid_layout,
                               query, clip_stack, hits, ctx,
                               size_ref_rect=size_ref_for_layout,
                               rect_index=rect_index)
        else:
            children_draw = sorted(children, key=lambda c: c.get("zIndex", 1))
            for child in children_draw:
                child_rect = _resolve_node_rect(child, content_rect, ctx)
                _hit_node(child, child_rect, query, clip_stack, hits, ctx,
                          parent_rect=content_rect, rect_index=rect_index)

    if pushed_clip:
        clip_stack.pop()


def _hit_node_at(node: dict, rect: Rect, query: Rect, clip_stack: list[Rect],
                 hits: list[dict], ctx: dict, parent_rect: Rect | None = None,
                 rect_index: dict[int, Rect] | None = None) -> None:
    """Hit-test a node at an explicit rect (used by layout systems)."""
    _hit_node(
        node, rect, query, clip_stack, hits, ctx,
        parent_rect=parent_rect, rect_index=rect_index
    )


# ---------------------------------------------------------------------------
#  Layout children (mirrors renderer's list/grid logic)
# ---------------------------------------------------------------------------

def _hit_list_children(children: list[dict], content_rect: Rect,
                       layout: dict, query: Rect, clip_stack: list[Rect],
                       hits: list[dict], ctx: dict,
                       size_ref_rect: Rect | None = None,
                       rect_index: dict[int, Rect] | None = None) -> None:
    direction = layout.get("direction", "Y")
    spacing_raw = layout.get("spacing", 0)
    wraps = layout.get("wraps", False)
    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    axis_dim = size_ref.h if direction == "Y" else size_ref.w
    spacing = _resolve_udim(spacing_raw, axis_dim)
    visible_children = [c for c in children if c.get("visible") is not False]

    # --- Wrapped horizontal ---
    if direction == "X" and wraps:
        if not visible_children:
            return
        main_spacing = spacing
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
                row_w = row_w + main_spacing + child_rect.w if row_items else child_rect.w
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
                _hit_node_at(child, placed, query, clip_stack, hits, ctx,
                             parent_rect=content_rect, rect_index=rect_index)
                x_cursor += child_rect.w + main_spacing
            y_cursor += height + row_spacing
        return

    # --- Wrapped vertical ---
    if direction == "Y" and wraps:
        if not visible_children:
            return
        main_spacing = spacing
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
                col_h = col_h + main_spacing + child_rect.h if col_items else child_rect.h
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
                _hit_node_at(child, placed, query, clip_stack, hits, ctx,
                             parent_rect=content_rect, rect_index=rect_index)
                y_cursor += child_rect.h + main_spacing
            x_cursor += width + column_spacing
        return

    # --- Non-wrapped ---
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

        _hit_node_at(child, placed, query, clip_stack, hits, ctx,
                     parent_rect=content_rect, rect_index=rect_index)


def _hit_grid_children(children: list[dict], content_rect: Rect,
                       layout: dict, query: Rect, clip_stack: list[Rect],
                       hits: list[dict], ctx: dict,
                       size_ref_rect: Rect | None = None,
                       rect_index: dict[int, Rect] | None = None) -> None:
    cell_size = layout.get("cellSize", [0.1, 0.1])
    cell_padding = layout.get("cellPadding", [0, 0])

    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    cell_w = _seq_num(cell_size, 0, 0.1) * size_ref.w
    cell_h = _seq_num(cell_size, 1, 0.1) * size_ref.h
    pad_x = _seq_num(cell_padding, 0, 0.0) * size_ref.w
    pad_y = _seq_num(cell_padding, 1, 0.0) * size_ref.h

    if cell_w <= 0 or cell_h <= 0:
        return

    cols = max(1, int((content_rect.w + pad_x) / (cell_w + pad_x)))

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
            w=w, h=h,
        )

    visible_children = [c for c in children if c.get("visible") is not False]

    for i, child in enumerate(visible_children):
        col = i % cols
        row = i // cols
        cx = content_rect.x + col * (cell_w + pad_x)
        cy = content_rect.y + row * (cell_h + pad_y)
        cell = Rect(cx, cy, cell_w, cell_h)
        placed = _fit_grid_child(child, cell)
        _hit_node_at(child, placed, query, clip_stack, hits, ctx,
                     parent_rect=content_rect, rect_index=rect_index)


# ---------------------------------------------------------------------------
#  Global ZIndexBehavior collection (flat sort)
# ---------------------------------------------------------------------------

def _collect_global_entries(node: dict, rect: Rect, clip_stack: list[Rect],
                            entries: list[tuple[int, int, dict, Rect]],
                            ctx: dict, parent_rect: Rect | None = None) -> None:
    """DFS walk collecting (z_index, dfs_order, node, effective_rect) for Global mode."""
    if node.get("visible") is False:
        return
    if rect.w <= 0 or rect.h <= 0:
        return

    # Compute effective (clipped) rect
    effective_rect = rect
    for clip in clip_stack:
        clipped = _intersect_rect(effective_rect, clip)
        if clipped is None:
            return
        effective_rect = clipped

    canvas_rect, force_clip = _scrolling_frame_rects(node, rect, parent_rect)

    entries.append((
        node.get("zIndex", 1),
        len(entries),  # dfs_order
        node,
        effective_rect,
    ))

    # Push clip for children
    pushed_clip = False
    if force_clip or node.get("clipsDescendants"):
        clip_stack.append(rect)
        pushed_clip = True

    children = node.get("children", [])
    if children:
        child_parent = canvas_rect if force_clip else rect
        pad_top, pad_bottom, pad_left, pad_right = _resolve_padding(
            node.get("padding", {}), child_parent.w, child_parent.h)
        content_rect = Rect(
            child_parent.x + pad_left,
            child_parent.y + pad_top,
            child_parent.w - pad_left - pad_right,
            child_parent.h - pad_top - pad_bottom,
        )

        list_layout = node.get("list")
        grid_layout = node.get("grid")
        children_ordered = sorted(children, key=lambda c: c.get("layoutOrder", 0))
        size_ref_for_layout = content_rect if node.get("padding") else child_parent

        if list_layout:
            _collect_global_list(children_ordered, content_rect, list_layout,
                                clip_stack, entries, ctx,
                                size_ref_rect=size_ref_for_layout)
        elif grid_layout:
            _collect_global_grid(children_ordered, content_rect, grid_layout,
                                clip_stack, entries, ctx,
                                size_ref_rect=size_ref_for_layout)
        else:
            for child in children:
                child_rect = _resolve_node_rect(child, content_rect, ctx)
                _collect_global_entries(child, child_rect, clip_stack, entries, ctx,
                                       parent_rect=content_rect)

    if pushed_clip:
        clip_stack.pop()


def _collect_global_list(children: list[dict], content_rect: Rect,
                         layout: dict, clip_stack: list[Rect],
                         entries: list, ctx: dict,
                         size_ref_rect: Rect | None = None) -> None:
    """Collect Global-mode entries for list layout children."""
    direction = layout.get("direction", "Y")
    spacing_raw = layout.get("spacing", 0)
    wraps = layout.get("wraps", False)
    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    axis_dim = size_ref.h if direction == "Y" else size_ref.w
    spacing = _resolve_udim(spacing_raw, axis_dim)
    visible_children = [c for c in children if c.get("visible") is not False]

    # --- Wrapped horizontal ---
    if direction == "X" and wraps:
        if not visible_children:
            return
        main_spacing = spacing
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
                row_w = row_w + main_spacing + child_rect.w if row_items else child_rect.w
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
                _collect_global_entries(child, placed, clip_stack, entries, ctx,
                                       parent_rect=content_rect)
                x_cursor += child_rect.w + main_spacing
            y_cursor += height + row_spacing
        return

    # --- Wrapped vertical ---
    if direction == "Y" and wraps:
        if not visible_children:
            return
        main_spacing = spacing
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
                col_h = col_h + main_spacing + child_rect.h if col_items else child_rect.h
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
                _collect_global_entries(child, placed, clip_stack, entries, ctx,
                                       parent_rect=content_rect)
                y_cursor += child_rect.h + main_spacing
            x_cursor += width + column_spacing
        return

    # --- Non-wrapped ---
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

        _collect_global_entries(child, placed, clip_stack, entries, ctx,
                               parent_rect=content_rect)


def _collect_global_grid(children: list[dict], content_rect: Rect,
                         layout: dict, clip_stack: list[Rect],
                         entries: list, ctx: dict,
                         size_ref_rect: Rect | None = None) -> None:
    """Collect Global-mode entries for grid layout children."""
    cell_size = layout.get("cellSize", [0.1, 0.1])
    cell_padding = layout.get("cellPadding", [0, 0])
    size_ref = size_ref_rect if size_ref_rect is not None else content_rect
    cell_w = _seq_num(cell_size, 0, 0.1) * size_ref.w
    cell_h = _seq_num(cell_size, 1, 0.1) * size_ref.h
    pad_x = _seq_num(cell_padding, 0, 0.0) * size_ref.w
    pad_y = _seq_num(cell_padding, 1, 0.0) * size_ref.h
    if cell_w <= 0 or cell_h <= 0:
        return
    cols = max(1, int((content_rect.w + pad_x) / (cell_w + pad_x)))

    def _fit(child: dict, cell: Rect) -> Rect:
        w, h = cell.w, cell.h
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
        return Rect(cell.x + (cell.w - w) / 2, cell.y + (cell.h - h) / 2, w, h)

    visible_children = [c for c in children if c.get("visible") is not False]
    for i, child in enumerate(visible_children):
        col = i % cols
        row = i // cols
        cx = content_rect.x + col * (cell_w + pad_x)
        cy = content_rect.y + row * (cell_h + pad_y)
        placed = _fit(child, Rect(cx, cy, cell_w, cell_h))
        _collect_global_entries(child, placed, clip_stack, entries, ctx,
                               parent_rect=content_rect)


# ---------------------------------------------------------------------------
#  Instance resolution helpers
# ---------------------------------------------------------------------------

def _normalize_instance_segments(instance_path: str) -> list[str]:
    path = str(instance_path or "").strip()
    if not path:
        return []
    if "/" in path:
        segments = [seg for seg in path.split("/") if seg]
    else:
        segments = [seg for seg in path.split(".") if seg]
    return segments


def _match_path_from(node: dict, segments: list[str], idx: int = 0) -> dict | None:
    if not isinstance(node, dict):
        return None
    if idx >= len(segments):
        return None
    if str(node.get("name", "")) != segments[idx]:
        return None
    if idx == len(segments) - 1:
        return node
    for child in node.get("children", []) or []:
        hit = _match_path_from(child, segments, idx + 1)
        if hit is not None:
            return hit
    return None


def _find_instance_by_segments(root: dict, segments: list[str]) -> dict | None:
    if not isinstance(root, dict):
        return None
    if not segments:
        return None
    # Allow anchored path ("Root.Frame.Button") or subtree-only path ("Frame.Button").
    anchored = _match_path_from(root, segments, 0)
    if anchored is not None:
        return anchored

    for child in root.get("children", []) or []:
        hit = _find_instance_by_segments(child, segments)
        if hit is not None:
            return hit
    return None


def _resolve_target_instance(root: dict, instance: dict | str | list[str] | tuple[str, ...]) -> dict | None:
    if isinstance(instance, dict):
        return instance
    if isinstance(instance, (list, tuple)):
        segments = [str(seg).strip() for seg in instance if str(seg).strip()]
        return _find_instance_by_segments(root, segments)
    if isinstance(instance, str):
        segments = _normalize_instance_segments(instance)
        return _find_instance_by_segments(root, segments)
    return None


def get_instance_rect(
    obj: dict,
    instance: dict | str | list[str] | tuple[str, ...],
    width: int = 1920,
    height: int = 1080,
    *,
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "viewport",
) -> Rect | None:
    """Resolve an instance's effective on-screen rect using hit-test traversal."""
    target = _resolve_target_instance(obj, instance)
    if target is None:
        return None

    viewport = Rect(0, 0, float(width), float(height))
    ctx: dict = {
        "_viewport_rect": viewport,
        "_default_size_ref": default_size_ref,
    }

    if z_index_behavior == "Global":
        entries: list[tuple[int, int, dict, Rect]] = []
        root_rect = _resolve_node_rect(obj, viewport, ctx)
        _collect_global_entries(obj, root_rect, [], entries, ctx)
        for _, _, node, eff_rect in entries:
            if node is target:
                return eff_rect
        return None

    root_rect = _resolve_node_rect(obj, viewport, ctx)
    rect_index: dict[int, Rect] = {}
    # Large query so traversal visits all visible nodes for indexing.
    q = Rect(-1.0e9, -1.0e9, 2.0e9, 2.0e9)
    _hit_node(obj, root_rect, q, [], [], ctx, rect_index=rect_index)
    return rect_index.get(id(target))


def get_instance_region(
    obj: dict,
    instance: dict | str | list[str] | tuple[str, ...],
    width: int = 1920,
    height: int = 1080,
    *,
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "viewport",
) -> tuple[float, float, float, float] | None:
    """Resolve an instance to a normalized region (x, y, w, h) in [0,1] space."""
    rect = get_instance_rect(
        obj,
        instance,
        width=width,
        height=height,
        z_index_behavior=z_index_behavior,
        default_size_ref=default_size_ref,
    )
    if rect is None or rect.w <= 0 or rect.h <= 0:
        return None

    x1 = max(0.0, min(float(width), float(rect.x)))
    y1 = max(0.0, min(float(height), float(rect.y)))
    x2 = max(0.0, min(float(width), float(rect.x + rect.w)))
    y2 = max(0.0, min(float(height), float(rect.y + rect.h)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height)


def get_objects_at_instance(
    obj: dict,
    instance: dict | str | list[str] | tuple[str, ...],
    width: int = 1920,
    height: int = 1080,
    *,
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "viewport",
) -> list[dict]:
    """Return topmost-first hits over an instance's automatically resolved region."""
    region = get_instance_region(
        obj,
        instance,
        width=width,
        height=height,
        z_index_behavior=z_index_behavior,
        default_size_ref=default_size_ref,
    )
    if region is None:
        return []
    x, y, w, h = region
    return get_objects_at_region(
        obj,
        x,
        y,
        w,
        h,
        width=width,
        height=height,
        z_index_behavior=z_index_behavior,
        default_size_ref=default_size_ref,
    )


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def get_objects_at_region(
    obj: dict,
    x: float, y: float, w: float, h: float,
    width: int = 1920, height: int = 1080,
    *,
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "viewport",
) -> list[dict]:
    """Return all visible PinevexObject dicts overlapping the query region, topmost first.

    Parameters
    ----------
    obj : dict
        Root PinevexObject tree.
    x, y, w, h : float
        Query region in scale coordinates (0-1).
    width, height : int
        Viewport size in pixels.
    z_index_behavior : str
        "Sibling" (default) or "Global".
    default_size_ref : str
        Default size reference for nodes without explicit sizeRef.

    Returns
    -------
    list[dict]
        Original node dicts from the tree (same references), topmost first.
    """
    viewport = Rect(0, 0, float(width), float(height))
    query = Rect(x * width, y * height, w * width, h * height)

    ctx: dict = {
        "_viewport_rect": viewport,
        "_default_size_ref": default_size_ref,
    }

    if z_index_behavior == "Global":
        entries: list[tuple[int, int, dict, Rect]] = []
        root_rect = _resolve_node_rect(obj, viewport, ctx)
        _collect_global_entries(obj, root_rect, [], entries, ctx)
        # Sort by (zIndex, dfs_order) — draw order is bottom-up
        entries.sort(key=lambda e: (e[0], e[1]))
        # Filter to those overlapping the query
        hits = [node for _, _, node, eff_rect in entries
                if _rects_overlap(eff_rect, query)]
        # Reverse for topmost-first
        hits.reverse()
        return hits
    else:
        # Sibling mode: DFS in draw order, collecting hits bottom-up
        hits: list[dict] = []
        root_rect = _resolve_node_rect(obj, viewport, ctx)
        _hit_node(obj, root_rect, query, [], hits, ctx)
        # Reverse for topmost-first
        hits.reverse()
        return hits
