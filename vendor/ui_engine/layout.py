from dataclasses import dataclass

BASE_WIDTH = 1920
BASE_HEIGHT = 1080

_FULL_PARENT_DEFAULT_SIZE_TYPES = {"ScreenGui"}
_GUI_OBJECT_DEFAULT_SIZE_TYPES = {
    "Frame",
    "CanvasGroup",
    "ScrollingFrame",
    "TextLabel",
    "TextButton",
    "TextBox",
    "ImageLabel",
    "ImageButton",
    "ViewportFrame",
    "VideoFrame",
}


def _estimate_text_auto_width(node: dict, height_px: float) -> float:
    """Heuristic width estimate for zero-width text nodes with AutomaticSize.X."""
    text = str(node.get("text", ""))
    if not text:
        return 1.0

    text_size = float(node.get("textSize", 14.0))
    if node.get("textScaled", False) and height_px > 0:
        # TextScaled labels typically leave small vertical padding.
        text_size = max(1.0, height_px * 0.72)

    units = 0.0
    for ch in text:
        if ch.isspace():
            units += 0.35
        elif ch in "ilI|.,'`!":
            units += 0.38
        elif ch in "mwMW@#%&":
            units += 0.95
        else:
            units += 0.62

    width = max(1.0, units * text_size)
    for stroke in node.get("strokes", []) or []:
        if isinstance(stroke, dict):
            t = stroke.get("thickness")
            if isinstance(t, (int, float)):
                width += float(t) * 2.0
    return max(1.0, width)


def _estimate_text_auto_height(node: dict, width_px: float) -> float:
    """Heuristic height estimate for zero-height text nodes with AutomaticSize.Y."""
    text = str(node.get("text", ""))
    if not text:
        return 1.0

    text_size = float(node.get("textSize", 14.0))
    if node.get("textScaled", False) and width_px > 0:
        # Conservative fallback when only width is known.
        text_size = max(1.0, min(text_size, width_px * 0.5))

    lines = text.count("\n") + 1
    return max(1.0, text_size * 1.2 * lines)


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float


def _default_size_value(node: dict):
    """Return fallback size terms for nodes with no explicit size.

    Raw snapshot capture strips default GuiObject.Size values, so missing size
    on snapshot-derived GuiObjects should resolve like Roblox's default
    ``UDim2.new(0, 100, 0, 100)`` rather than filling the parent.
    """
    node_type = str(node.get("type") or "")
    if node_type in _FULL_PARENT_DEFAULT_SIZE_TYPES:
        return [1, 1]
    if node_type in _GUI_OBJECT_DEFAULT_SIZE_TYPES:
        return [0, 100, 0, 100]
    return [1, 1]


def resolve_rect(
    node: dict,
    parent_rect: Rect,
    *,
    viewport_rect: Rect | None = None,
    default_size_ref: str = "parent",
) -> Rect:
    """Compute absolute pixel rect for a PinevexObject node.

    Position remains parent-relative (Roblox semantics). Size reference is:
      - ``node.sizeRef`` when provided ("viewport" or "parent")
      - otherwise ``default_size_ref``.
    """
    size = node.get("size", _default_size_value(node))
    position = node.get("position", [0, 0])
    anchor = node.get("anchor", [0, 0])
    constraint = node.get("sizeConstraint", "RelativeXY")
    size_ref = str(node.get("sizeRef", default_size_ref)).lower()
    size_parent = viewport_rect if size_ref == "viewport" and viewport_rect is not None else parent_rect

    def _num(value, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    # Determine reference dimensions based on sizeConstraint
    if constraint == "RelativeXX":
        ref_w = size_parent.w
        ref_h = size_parent.w
    elif constraint == "RelativeYY":
        ref_w = size_parent.h
        ref_h = size_parent.h
    else:  # RelativeXY
        ref_w = size_parent.w
        ref_h = size_parent.h

    # Size: [xScale, yScale] or [xScale, xOffset, yScale, yOffset]
    if isinstance(size, (list, tuple)) and len(size) == 4:
        w = _num(size[0], 0.0) * ref_w + _num(size[1], 0.0)
        h = _num(size[2], 0.0) * ref_h + _num(size[3], 0.0)
    else:
        sx = _num(size[0], 1.0) if isinstance(size, (list, tuple)) and len(size) > 0 else 1.0
        sy = _num(size[1], 1.0) if isinstance(size, (list, tuple)) and len(size) > 1 else 1.0
        w = sx * ref_w
        h = sy * ref_h

    auto_size = node.get("autoSize")
    if auto_size in ("X", "XY") and w <= 1e-3:
        w = _estimate_text_auto_width(node, h)
    if auto_size in ("Y", "XY") and h <= 1e-3:
        h = _estimate_text_auto_height(node, w)

    # Apply aspect ratio constraint (shrink to fit)
    aspect = node.get("aspectRatio")
    if aspect is not None and aspect > 0 and h > 0:
        current = w / h
        if current > aspect:
            # too wide, shrink width
            w = h * aspect
        else:
            # too tall, shrink height
            h = w / aspect

    # Apply UIScale (scale around center)
    scale = node.get("scale")
    if scale is not None:
        s = _num(scale, 1.0)
        w *= s
        h *= s

    # Position: [xScale, yScale] or [xScale, xOffset, yScale, yOffset]
    if isinstance(position, (list, tuple)) and len(position) == 4:
        px = _num(position[0], 0.0) * parent_rect.w + _num(position[1], 0.0)
        py = _num(position[2], 0.0) * parent_rect.h + _num(position[3], 0.0)
    else:
        pxs = _num(position[0], 0.0) if isinstance(position, (list, tuple)) and len(position) > 0 else 0.0
        pys = _num(position[1], 0.0) if isinstance(position, (list, tuple)) and len(position) > 1 else 0.0
        px = pxs * parent_rect.w
        py = pys * parent_rect.h

    ax = _num(anchor[0], 0.0) if isinstance(anchor, (list, tuple)) and len(anchor) > 0 else 0.0
    ay = _num(anchor[1], 0.0) if isinstance(anchor, (list, tuple)) and len(anchor) > 1 else 0.0
    x = parent_rect.x + px - ax * w
    y = parent_rect.y + py - ay * h

    return Rect(x=x, y=y, w=w, h=h)
