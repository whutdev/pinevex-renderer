"""Convert raw Roblox UI trees to PinevexObject flat schema."""

import re

# UI modifier classNames that become parent properties rather than children
_UI_CLASSES = {
    "UICorner",
    "UIStroke",
    "UIGradient",
    "UIPadding",
    "UIListLayout",
    "UIGridLayout",
    "UITableLayout",
    "UIPageLayout",
    "UIScale",
    "UIAspectRatioConstraint",
    "UISizeConstraint",
    "UITextSizeConstraint",
    "UIFlexItem",
}

# Visual GUI classNames that should be kept as children
_GUI_CLASSES = {
    "Frame", "CanvasGroup", "ScrollingFrame",
    "TextLabel", "TextButton", "TextBox",
    "ImageLabel", "ImageButton",
    "ViewportFrame", "VideoFrame",
}

# Script classes are never visual, and their descendants represent runtime/script
# scaffolding that should not leak into render trees.
_SCRIPT_CLASSES = {
    "Script",
    "LocalScript",
    "ModuleScript",
}

# Classes that can paint a background fill.
_BG_CLASSES = set(_GUI_CLASSES)

_FONT_FAMILY_RE = re.compile(r"rbxasset://fonts/families/(\w+)\.json")


def _num(value, default: float = 0.0) -> float:
    """Convert arbitrary value to float with fallback."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _color3_to_rgb(c: dict | None) -> list[int] | None:
    """Convert Roblox Color3 dict {r, g, b} (0-1 floats) to [R, G, B] (0-255 ints)."""
    if c is None:
        return None
    return [round(c.get("r", 0) * 255), round(c.get("g", 0) * 255), round(c.get("b", 0) * 255)]


def _udim2_to_scale(u: dict | None) -> list[float] | None:
    """Extract [x.scale, y.scale] from a UDim2 dict (offsets ignored)."""
    if u is None:
        return None
    x = u.get("x", u.get("X", {}))
    y = u.get("y", u.get("Y", {}))
    if isinstance(x, dict) and isinstance(y, dict):
        return [
            _num(x.get("scale", x.get("Scale", 0)), 0.0),
            _num(y.get("scale", y.get("Scale", 0)), 0.0),
        ]
    return None


def _udim2_to_full(u: dict | None) -> list[float] | None:
    """Extract UDim2 as [xScale, yScale] or [xScale, xOffset, yScale, yOffset] when offsets are non-zero."""
    if u is None:
        return None
    x = u.get("x", u.get("X", {}))
    y = u.get("y", u.get("Y", {}))
    if isinstance(x, dict) and isinstance(y, dict):
        xs = _num(x.get("scale", x.get("Scale", 0)), 0.0)
        xo = _num(x.get("offset", x.get("Offset", 0)), 0.0)
        ys = _num(y.get("scale", y.get("Scale", 0)), 0.0)
        yo = _num(y.get("offset", y.get("Offset", 0)), 0.0)
        if xo != 0 or yo != 0:
            return [xs, xo, ys, yo]
        return [xs, ys]
    return None


def _vector2_to_list(v: dict | None) -> list[float] | None:
    """Extract [x, y] from a Vector2 dict."""
    if v is None:
        return None
    return [
        _num(v.get("x", v.get("X", 0)), 0.0),
        _num(v.get("y", v.get("Y", 0)), 0.0),
    ]


def _extract_font_family(font_face: dict | None) -> str | None:
    """Extract family name from FontFace.family path or plain name."""
    if font_face is None:
        return None
    family = font_face.get("family", font_face.get("Family", ""))
    if not isinstance(family, str):
        return None
    # Standard rbxasset:// path
    m = _FONT_FAMILY_RE.search(family)
    if m:
        return m.group(1)
    # Already a plain family name (e.g. resolved from rbxassetid://)
    if family and not family.startswith("rbx"):
        return family
    return None


def _extract_font_weight(font_face: dict | None) -> str | None:
    """Extract weight name from FontFace.weight (e.g. 'Regular', 'Bold', 'Heavy')."""
    if font_face is None:
        return None
    weight = font_face.get("weight", font_face.get("Weight"))
    if weight and isinstance(weight, str):
        # Handle enum format: "Enum.FontWeight.Bold" → "Bold"
        if weight.startswith("Enum."):
            parts = weight.split(".")
            return parts[-1] if len(parts) >= 3 else None
        return weight
    return None


def _extract_font_style(font_face: dict | None) -> str | None:
    """Extract style name from FontFace.style (e.g. 'Normal', 'Italic')."""
    if font_face is None:
        return None
    style = font_face.get("style", font_face.get("Style"))
    if style and isinstance(style, str):
        # Handle enum format: "Enum.FontStyle.Italic" -> "Italic"
        if style.startswith("Enum."):
            parts = style.split(".")
            return parts[-1] if len(parts) >= 3 else None
        return style
    return None


def _extract_enum_value(val) -> str | None:
    """Extract the value portion from an Enum string like 'Enum.ScaleType.Fit' -> 'Fit',
    or from a dict like {'EnumType': 'ScaleType', 'Value': 'Fit'} -> 'Fit'."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get("Value")
    if isinstance(val, str) and val.startswith("Enum."):
        parts = val.split(".")
        return parts[-1] if len(parts) >= 3 else None
    return str(val)


def _collect_renderable_children(raw_children: list[dict]) -> list[dict]:
    """Collect renderable GUI children, traversing non-UI wrapper instances.

    Roblox trees sometimes include organizational/script wrappers (e.g. Folder)
    between GUI nodes. These wrappers should not block discovery of renderable
    descendants.
    """
    out: list[dict] = []
    for child in raw_children:
        cls = child.get("className", "")
        if cls in _GUI_CLASSES:
            out.append(child)
            continue
        if cls in _SCRIPT_CLASSES:
            continue
        if cls in _UI_CLASSES:
            continue
        nested = child.get("children", [])
        if isinstance(nested, list) and nested:
            out.extend(_collect_renderable_children(nested))
    return out


def _extract_gradient_props(props: dict) -> dict | None:
    """Extract UIGradient properties into a gradient dict, or None if disabled/empty."""
    if props.get("Enabled") is False:
        return None
    gradient = {}
    rotation = props.get("Rotation")
    if rotation is not None:
        gradient["rotation"] = rotation
    offset = props.get("Offset")
    if offset is not None:
        gradient["offset"] = _vector2_to_list(offset)
    color_seq = props.get("Color")
    if color_seq and isinstance(color_seq, list):
        stops = []
        for stop in color_seq:
            t = stop.get("time", 0)
            c = stop.get("color")
            if c is not None:
                r, g, b = round(c.get("r", 0) * 255), round(c.get("g", 0) * 255), round(c.get("b", 0) * 255)
                stops.append((t, f"#{r:02x}{g:02x}{b:02x}"))
        gradient["colors"] = stops
    trans_seq = props.get("Transparency")
    if trans_seq and isinstance(trans_seq, list):
        trans_stops = []
        for stop in trans_seq:
            trans_stops.append((stop.get("time", 0), stop.get("value", 0)))
        gradient["transparency"] = trans_stops
    return gradient if gradient else None


def _extract_ui_modifiers(children: list[dict]) -> dict:
    """Extract UI modifier children (UICorner, UIStroke, UIGradient, UIScale,
    UIAspectRatioConstraint, UISizeConstraint) into a dict of PinevexObject properties."""
    mods = {}
    for child in children:
        cls = child.get("className", "")
        props = child.get("properties", {})

        if cls == "UICorner":
            cr = props.get("CornerRadius")
            if cr is None:
                # Roblox applies a non-zero default CornerRadius when UICorner exists
                # but CornerRadius is not explicitly set.
                mods["corner"] = {"scale": 0, "offset": 8}
            elif isinstance(cr, dict):
                mods["corner"] = {
                    "scale": cr.get("scale", cr.get("Scale", 0)),
                    "offset": cr.get("offset", cr.get("Offset", 0)),
                }
            else:
                mods["corner"] = {"scale": 0, "offset": cr}

        elif cls == "UIStroke":
            if props.get("Enabled") is False:
                continue
            stroke = {}
            thickness = props.get("Thickness")
            if thickness is not None:
                stroke["thickness"] = thickness
            color = props.get("Color")
            if color is not None:
                stroke["color"] = _color3_to_rgb(color)
            transparency = props.get("Transparency")
            if transparency is not None:
                stroke["transparency"] = transparency
            sizing_mode = _extract_enum_value(props.get("StrokeSizingMode"))
            if sizing_mode == "ScaledSize":
                stroke["thicknessScale"] = True
            apply_mode = _extract_enum_value(props.get("ApplyStrokeMode"))
            if apply_mode == "Border":
                stroke["applyMode"] = "Border"
            border_pos = _extract_enum_value(props.get("BorderStrokePosition"))
            if border_pos and border_pos != "Outer":
                stroke["borderPosition"] = border_pos
            border_offset = props.get("BorderOffset")
            if border_offset is not None:
                if isinstance(border_offset, dict):
                    bo_scale = border_offset.get("scale", border_offset.get("Scale", 0))
                    bo_offset = border_offset.get("offset", border_offset.get("Offset", 0))
                    if bo_scale != 0 or bo_offset != 0:
                        stroke["borderOffset"] = {"scale": bo_scale, "offset": bo_offset}
                elif isinstance(border_offset, (int, float)) and border_offset != 0:
                    stroke["borderOffset"] = {"scale": 0, "offset": border_offset}
            line_join = _extract_enum_value(props.get("LineJoinMode"))
            if line_join and line_join != "Round":
                stroke["lineJoin"] = line_join
            # Extract UIGradient from UIStroke's children (skip disabled ones)
            for sc in child.get("children", []):
                if sc.get("className") == "UIGradient":
                    sg = _extract_gradient_props(sc.get("properties", {}))
                    if sg:
                        stroke["gradient"] = sg
                        break
            if stroke:
                mods.setdefault("strokes", []).append(stroke)

        elif cls == "UIGradient":
            gradient = _extract_gradient_props(props)
            if gradient:
                mods["gradient"] = gradient

        elif cls == "UIScale":
            scale = props.get("Scale")
            if scale is not None:
                mods["scale"] = scale

        elif cls == "UIAspectRatioConstraint":
            mods["aspectRatio"] = props.get("AspectRatio", 1.0)

        elif cls == "UISizeConstraint":
            pass

        elif cls == "UIListLayout":
            lst = {}
            fill_dir = _extract_enum_value(props.get("FillDirection"))
            if fill_dir == "Horizontal":
                lst["direction"] = "X"
            else:
                lst["direction"] = "Y"
            v_align = _extract_enum_value(props.get("VerticalAlignment"))
            if v_align and v_align != "Top":
                lst["vAlign"] = v_align
            h_align = _extract_enum_value(props.get("HorizontalAlignment"))
            if h_align and h_align != "Left":
                lst["hAlign"] = h_align
            padding = props.get("Padding")
            if padding is not None:
                if isinstance(padding, dict):
                    lst["spacing"] = {
                        "scale": padding.get("scale", padding.get("Scale", 0)),
                        "offset": padding.get("offset", padding.get("Offset", 0)),
                    }
                elif isinstance(padding, (int, float)):
                    lst["spacing"] = {"scale": 0, "offset": padding}
            wraps = props.get("Wraps")
            if wraps:
                lst["wraps"] = True
            mods["list"] = lst

        elif cls == "UIGridLayout":
            grid = {}
            fill_dir = _extract_enum_value(props.get("FillDirection"))
            if fill_dir == "Vertical":
                grid["direction"] = "Y"
            else:
                grid["direction"] = "X"
            cell_size = _udim2_to_scale(props.get("CellSize"))
            if cell_size is not None:
                grid["cellSize"] = cell_size
            cell_pad = _udim2_to_scale(props.get("CellPadding"))
            if cell_pad is not None:
                grid["cellPadding"] = cell_pad
            v_align = _extract_enum_value(props.get("VerticalAlignment"))
            if v_align and v_align != "Top":
                grid["vAlign"] = v_align
            h_align = _extract_enum_value(props.get("HorizontalAlignment"))
            if h_align and h_align != "Left":
                grid["hAlign"] = h_align
            mods["grid"] = grid

        elif cls == "UIPadding":
            padding = {}
            for side, prop_name in [("top", "PaddingTop"), ("bottom", "PaddingBottom"),
                                     ("left", "PaddingLeft"), ("right", "PaddingRight")]:
                val = props.get(prop_name)
                if val is not None:
                    if isinstance(val, dict):
                        padding[side] = {
                            "scale": val.get("scale", val.get("Scale", 0)),
                            "offset": val.get("offset", val.get("Offset", 0)),
                        }
                    elif isinstance(val, (int, float)):
                        padding[side] = {"scale": 0, "offset": val}
            if padding:
                mods["padding"] = padding

        elif cls == "UITextSizeConstraint":
            tsc = {}
            min_size = props.get("MinTextSize")
            if min_size is not None:
                tsc["min"] = min_size
            max_size = props.get("MaxTextSize")
            if max_size is not None:
                tsc["max"] = max_size
            if tsc:
                mods["textSizeConstraint"] = tsc

    return mods


def flatten_node(raw: dict) -> dict:
    """Convert a raw Roblox node to PinevexObject format."""
    props = raw.get("properties", {})
    result = {}

    # Type and name
    result["type"] = raw.get("className", "Frame")
    name = raw.get("name")
    if name:
        result["name"] = name

    # Size
    size = _udim2_to_full(props.get("Size"))
    if size is not None:
        result["size"] = size
        # Raw Roblox UDim2 sizes are parent-relative; mark this explicitly.
        result["sizeRef"] = "parent"

    # Position
    position = _udim2_to_full(props.get("Position"))
    if position is not None:
        result["position"] = position

    # Anchor
    anchor = _vector2_to_list(props.get("AnchorPoint"))
    if anchor is not None and anchor != [0, 0]:
        result["anchor"] = anchor

    # Background color/transparency.
    # Non-visual container classes (e.g. Folder/UI* wrappers) should not emit an implicit
    # white background; only visual GUI classes can paint fills.
    if result["type"] in _BG_CLASSES:
        bg = _color3_to_rgb(props.get("BackgroundColor3"))
        result["bg"] = bg if bg is not None else [255, 255, 255]

        bg_trans = props.get("BackgroundTransparency")
        if bg_trans is not None and bg_trans != 0:
            result["bgTransparency"] = bg_trans

    # Rotation
    rotation = props.get("Rotation")
    if rotation is not None and rotation != 0:
        result["rotation"] = rotation

    # Visible
    visible = props.get("Visible")
    if visible is not None and visible is False:
        result["visible"] = False

    # ClipsDescendants
    clips = props.get("ClipsDescendants")
    if clips:
        result["clipsDescendants"] = True

    # ZIndex
    zindex = props.get("ZIndex")
    # Keep explicit zIndex, including Roblox's default value of 1.
    if zindex is not None:
        result["zIndex"] = zindex

    # LayoutOrder
    layout_order = props.get("LayoutOrder")
    if layout_order is not None and layout_order != 0:
        result["layoutOrder"] = layout_order

    # SizeConstraint
    size_constraint = _extract_enum_value(props.get("SizeConstraint"))
    if size_constraint and size_constraint != "RelativeXY":
        result["sizeConstraint"] = size_constraint

    # AutomaticSize
    auto_size = _extract_enum_value(props.get("AutomaticSize"))
    if auto_size and auto_size != "None":
        result["autoSize"] = auto_size

    # Text properties
    text = props.get("Text")
    if text:
        result["text"] = text

    text_color = _color3_to_rgb(props.get("TextColor3"))
    if text_color is not None:
        result["textColor"] = text_color

    text_size = props.get("TextSize")
    if text_size is not None:
        result["textSize"] = text_size

    text_scaled = props.get("TextScaled")
    if text_scaled:
        result["textScaled"] = True

    text_wrapped = props.get("TextWrapped")
    if text_wrapped:
        result["textWrapped"] = True

    rich_text = props.get("RichText")
    if rich_text:
        result["richText"] = True

    text_x = _extract_enum_value(props.get("TextXAlignment"))
    if text_x and text_x != "Center":
        result["textXAlignment"] = text_x

    text_y = _extract_enum_value(props.get("TextYAlignment"))
    if text_y and text_y != "Center":
        result["textYAlignment"] = text_y

    text_trans = props.get("TextTransparency")
    if text_trans is not None and text_trans != 0:
        result["textTransparency"] = text_trans

    text_stroke_color = _color3_to_rgb(props.get("TextStrokeColor3"))
    if text_stroke_color is not None and text_stroke_color != [0, 0, 0]:
        result["textStrokeColor"] = text_stroke_color

    text_stroke_trans = props.get("TextStrokeTransparency")
    if text_stroke_trans is not None and text_stroke_trans != 1:
        result["textStrokeTransparency"] = text_stroke_trans

    # Font
    font_face = props.get("FontFace") or props.get("fontFace")
    font_family = _extract_font_family(font_face)
    if font_family:
        result["font"] = font_family
    font_weight = _extract_font_weight(font_face)
    if font_weight and font_weight != "Regular":
        result["fontWeight"] = font_weight
    font_style = _extract_font_style(font_face)
    if font_style and font_style != "Normal":
        result["fontStyle"] = font_style

    # Image / icon
    image = props.get("Image")
    if image:
        result["icon"] = image

    # ImageRect atlas cropping
    raw_image_rect_size = props.get("ImageRectSize")
    if isinstance(raw_image_rect_size, dict):
        image_rect_size = [
            _num(raw_image_rect_size.get("x", raw_image_rect_size.get("X", 0)), 0.0),
            _num(raw_image_rect_size.get("y", raw_image_rect_size.get("Y", 0)), 0.0),
        ]
        if image_rect_size[0] > 0 and image_rect_size[1] > 0:
            result["imageRectSize"] = image_rect_size
            # Snapshot compatibility metadata:
            # Some captures provide SpriteSheet grid metadata in attributes while
            # ImageRect* values stay in authored source-pixel space.
            # Renderer can use this to map ImageRect cropping onto downscaled
            # cached thumbnails without changing logical Pinevex fields.
            attrs = raw.get("attributes")
            if isinstance(attrs, dict):
                sprite_sheet = attrs.get("SpriteSheet")
                if isinstance(sprite_sheet, dict):
                    ssx = sprite_sheet.get("x", sprite_sheet.get("X"))
                    ssy = sprite_sheet.get("y", sprite_sheet.get("Y"))
                    if isinstance(ssx, (int, float)) and isinstance(ssy, (int, float)):
                        if ssx > 1 and ssy > 1:
                            result["imageRectSheet"] = [ssx, ssy]

    raw_image_rect_offset = props.get("ImageRectOffset")
    if isinstance(raw_image_rect_offset, dict):
        image_rect_offset = [
            _num(raw_image_rect_offset.get("x", raw_image_rect_offset.get("X", 0)), 0.0),
            _num(raw_image_rect_offset.get("y", raw_image_rect_offset.get("Y", 0)), 0.0),
        ]
        if image_rect_offset[0] != 0 or image_rect_offset[1] != 0:
            result["imageRectOffset"] = image_rect_offset

    # ScaleType
    scale_type = _extract_enum_value(props.get("ScaleType"))
    if scale_type and scale_type != "Stretch":
        result["scaleType"] = scale_type

    # SliceCenter (for ScaleType == "Slice") — Rect2D {min:{x,y}, max:{x,y}}
    raw_slice = props.get("SliceCenter")
    if raw_slice is not None:
        s_min = raw_slice.get("min", raw_slice.get("Min", {}))
        s_max = raw_slice.get("max", raw_slice.get("Max", {}))
        if isinstance(s_min, dict) and isinstance(s_max, dict):
            sc = [
                _num(s_min.get("x", s_min.get("X", 0)), 0.0),
                _num(s_min.get("y", s_min.get("Y", 0)), 0.0),
                _num(s_max.get("x", s_max.get("X", 0)), 0.0),
                _num(s_max.get("y", s_max.get("Y", 0)), 0.0),
            ]
            if sc != [0, 0, 0, 0]:
                result["sliceCenter"] = sc

    # SliceScale
    slice_scale = props.get("SliceScale")
    if slice_scale is not None and slice_scale != 1.0:
        result["sliceScale"] = slice_scale

    # TileSize (for ScaleType == "Tile") — full UDim2 [xScale, xOffset, yScale, yOffset]
    raw_tile = props.get("TileSize")
    if raw_tile is not None:
        tx = raw_tile.get("x", raw_tile.get("X", {}))
        ty = raw_tile.get("y", raw_tile.get("Y", {}))
        if isinstance(tx, dict) and isinstance(ty, dict):
            tile = [
                _num(tx.get("scale", tx.get("Scale", 0)), 0.0),
                _num(tx.get("offset", tx.get("Offset", 0)), 0.0),
                _num(ty.get("scale", ty.get("Scale", 0)), 0.0),
                _num(ty.get("offset", ty.get("Offset", 0)), 0.0),
            ]
            if tile != [1, 0, 1, 0]:  # skip default
                result["tileSize"] = tile

    # ImageColor3 (tint)
    image_color = _color3_to_rgb(props.get("ImageColor3"))
    if image_color is not None and image_color != [255, 255, 255]:
        result["imageColor"] = image_color

    # ImageTransparency
    image_trans = props.get("ImageTransparency")
    if image_trans is not None and image_trans != 0:
        result["imageTransparency"] = image_trans

    # ScrollingFrame properties
    if result["type"] == "ScrollingFrame":
        canvas_size = _udim2_to_full(props.get("CanvasSize"))
        if canvas_size is not None:
            result["canvasSize"] = canvas_size
        canvas_pos = _vector2_to_list(props.get("CanvasPosition"))
        if canvas_pos is not None and canvas_pos != [0, 0]:
            result["canvasPosition"] = canvas_pos
        scroll_bar = props.get("ScrollBarThickness")
        if scroll_bar is not None and scroll_bar != 0:
            result["scrollBarThickness"] = scroll_bar
        scroll_dir = _extract_enum_value(props.get("ScrollingDirection"))
        if scroll_dir and scroll_dir != "XY":
            result["scrollDirection"] = scroll_dir
        auto_canvas = _extract_enum_value(props.get("AutomaticCanvasSize"))
        if auto_canvas and auto_canvas != "None":
            result["autoCanvasSize"] = auto_canvas

    # Process children: separate UI modifiers from real children
    raw_children = raw.get("children", [])
    ui_children = [c for c in raw_children if c.get("className", "") in _UI_CLASSES]
    real_children = _collect_renderable_children(raw_children)

    # Extract UI modifier properties
    mods = _extract_ui_modifiers(ui_children)
    result.update(mods)

    # Recursively flatten real children
    if real_children:
        result["children"] = [flatten_node(c) for c in real_children]

    return result


def strip_visible(obj):
    """Remove ``visible`` from the root element only."""
    if isinstance(obj, dict):
        obj.pop("visible", None)
