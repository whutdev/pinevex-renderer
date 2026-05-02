from __future__ import annotations

import json
import re
from typing import Any

try:
    from .layout_bounds import BASE_HEIGHT, BASE_WIDTH
except ImportError:
    from layout_bounds import BASE_HEIGHT, BASE_WIDTH

_SUNBURST_ICON_KEY = "Custom/Sunburst"
_SUNBURST_NAME_HINTS = ("sunbursteffect", "sunburst", "sunrays", "rays")
_VIEWPORT_ABS_SIZE = (float(BASE_WIDTH), float(BASE_HEIGHT))
_HARD_CODED_STUD_TEXTURE_KEYS = {
    "Textures/Hardcoded/GoldenStudsShelfButtonTexture.png",
    "Textures/Hardcoded/GreenButtonPlasmaStuds.png",
    "Textures/Hardcoded/GreenStudShelfButtonTexture.png",
}
_STUD_TILE_TEXTURE_KEYS = {
    "Textures/Studs/StudSingleWhiteBackground",
    "Textures/Studs/StudsInletTexture",
    "Textures/Studs/StudsTexture",
}
_CANONICAL_STUD_TILE_KEY = "Textures/Studs/StudsTexture"
_FONT_TOKEN_PREFIX = "<|font:"
_FONT_TOKEN_SUFFIX = "|>"
_ALLOWED_POSTPROCESS_FONTS = {
    "montserrat": "Montserrat",
    "fredokaone": "FredokaOne",
    "gothamssm": "GothamSSm",
}
_DEFAULT_POSTPROCESS_FONT = "GothamSSm"
_FONT_ASSET_RE = re.compile(r"rbxasset://fonts/families/([^/]+)\.json$", re.IGNORECASE)
_STUD_TILE_PIXEL_TARGETS = {
    # Calibrated from the known-good SingleWhiteBackground case
    # `tileSize = [0.078, 0, 0.325, 0]` on a `size = [0.131, 0, 0.057, 0]` element.
    "Textures/Studs/StudSingleWhiteBackground": (19.6, 20.0),
    # Plain StudsTexture reads better with a distinctly taller repeat.
    "Textures/Studs/StudsTexture": (36.0, 54.0),
    "Textures/Studs/StudsInletTexture": (36.0, 35.7),
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_udim2_like(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)):
        if len(value) >= 4:
            return (
                _to_float(value[0], 0.0),
                _to_float(value[1], 0.0),
                _to_float(value[2], 0.0),
                _to_float(value[3], 0.0),
            )
        if len(value) >= 2:
            return (
                _to_float(value[0], 0.0),
                0.0,
                _to_float(value[1], 0.0),
                0.0,
            )
        return None

    if isinstance(value, dict):
        x = value.get("x", value.get("X"))
        y = value.get("y", value.get("Y"))
        if isinstance(x, dict) and isinstance(y, dict):
            return (
                _to_float(x.get("scale", x.get("Scale", 0)), 0.0),
                _to_float(x.get("offset", x.get("Offset", 0)), 0.0),
                _to_float(y.get("scale", y.get("Scale", 0)), 0.0),
                _to_float(y.get("offset", y.get("Offset", 0)), 0.0),
            )
    return None


def _replace_udim2_like(original: Any, values: tuple[float, float, float, float]) -> Any:
    x_scale, x_offset, y_scale, y_offset = values
    if isinstance(original, (list, tuple)):
        if len(original) >= 4:
            return [x_scale, x_offset, y_scale, y_offset]
        if len(original) >= 2:
            return [x_scale, y_scale]
    if isinstance(original, dict):
        out = dict(original)
        x = out.get("x", out.get("X"))
        y = out.get("y", out.get("Y"))
        if isinstance(x, dict) and isinstance(y, dict):
            x_out = dict(x)
            y_out = dict(y)
            if "scale" in x_out or "offset" in x_out:
                x_out["scale"] = x_scale
                x_out["offset"] = x_offset
            else:
                x_out["Scale"] = x_scale
                x_out["Offset"] = x_offset
            if "scale" in y_out or "offset" in y_out:
                y_out["scale"] = y_scale
                y_out["offset"] = y_offset
            else:
                y_out["Scale"] = y_scale
                y_out["Offset"] = y_offset
            if "x" in out or "y" in out:
                out["x"] = x_out
                out["y"] = y_out
            else:
                out["X"] = x_out
                out["Y"] = y_out
            return out
    return [x_scale, x_offset, y_scale, y_offset]


def _is_effectively_half_cell(value: Any) -> bool:
    udim2 = _parse_udim2_like(value)
    if udim2 is None:
        return False
    return abs(udim2[0] - 0.5) < 0.02 and abs(udim2[2] - 0.5) < 0.02


def _is_effectively_half_scale(value: float | None) -> bool:
    if value is None:
        return False
    return abs(float(value) - 0.5) < 0.02


def _canonical_half_scale_minus_padding(padding_x_scale: float) -> float:
    return max(0.0, 0.5 - (padding_x_scale / 2.0))


def _is_wrapped_icon_token(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith("<|icon:") and text.endswith("|>")


def _wrapped_icon_key(value: Any) -> str | None:
    if not _is_wrapped_icon_token(value):
        return None
    text = str(value).strip()
    return text[len("<|icon:"):-len("|>")].strip() or None


def _wrapped_icon_token(icon_key: str) -> str:
    return f"<|icon:{icon_key}|>"


def _normalized_image_key(node: dict[str, Any]) -> str | None:
    for field in ("icon", "image"):
        raw = node.get(field)
        if raw in (None, ""):
            continue
        wrapped = _wrapped_icon_key(raw)
        key = wrapped if wrapped is not None else str(raw).strip()
        if key:
            return key.replace("\\", "/")
    return None


def _set_image_key(node: dict[str, Any], icon_key: str) -> None:
    icon_value = node.get("icon")
    if icon_value not in (None, ""):
        if _is_wrapped_icon_token(icon_value):
            node["icon"] = _wrapped_icon_token(icon_key)
        else:
            node["icon"] = icon_key
        return
    image_value = node.get("image")
    if image_value not in (None, ""):
        node["image"] = icon_key
        return
    node["icon"] = icon_key


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lower()


def _unwrap_font_token(value: str) -> tuple[str, bool]:
    text = str(value or "").strip()
    if text.startswith(_FONT_TOKEN_PREFIX) and text.endswith(_FONT_TOKEN_SUFFIX):
        return text[len(_FONT_TOKEN_PREFIX):-len(_FONT_TOKEN_SUFFIX)].strip(), True
    return text, False


def _canonical_font_family(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("family", "")
    raw, _was_wrapped = _unwrap_font_token(str(value or ""))
    raw = raw.strip()
    if not raw:
        return _DEFAULT_POSTPROCESS_FONT
    asset_match = _FONT_ASSET_RE.fullmatch(raw)
    if asset_match:
        raw = asset_match.group(1).strip()
    canonical = _ALLOWED_POSTPROCESS_FONTS.get(raw.lower())
    if canonical:
        return canonical
    return _DEFAULT_POSTPROCESS_FONT


def _coerce_allowed_font(value: Any) -> str:
    raw_text = ""
    if isinstance(value, dict):
        raw_text = str(value.get("family", "") or "")
    else:
        raw_text = str(value or "")
    _raw, was_wrapped = _unwrap_font_token(raw_text)
    canonical = _canonical_font_family(value)
    if was_wrapped:
        return f"{_FONT_TOKEN_PREFIX}{canonical}{_FONT_TOKEN_SUFFIX}"
    return canonical


def _has_sunburst_name_hint(value: Any) -> bool:
    normalized = _normalized_text(value)
    if not normalized:
        return False
    return any(hint in normalized for hint in _SUNBURST_NAME_HINTS)


def _should_remap_to_sunburst(node: dict[str, Any]) -> bool:
    class_name = str(node.get("type") or "")
    if class_name != "ImageLabel":
        return False
    return _has_sunburst_name_hint(node.get("name"))


def _rgb_triplet(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        r = int(round(float(value[0])))
        g = int(round(float(value[1])))
        b = int(round(float(value[2])))
    except (TypeError, ValueError):
        return None
    return r, g, b


def _is_near_white_rgb(value: Any) -> bool:
    rgb = _rgb_triplet(value)
    if rgb is None:
        return False
    r, g, b = rgb
    return r > 225 and g > 225 and b > 225


def _is_greenish_stroke_rgb(value: Any) -> bool:
    rgb = _rgb_triplet(value)
    if rgb is None:
        return False
    r, g, b = rgb
    max_rb = max(r, b)
    return g >= 55 and g >= r + 20 and g >= b + 20 and max_rb <= 90


def _estimate_node_absolute_size(
    node: dict[str, Any],
    parent_abs_size: tuple[float, float] | None,
) -> tuple[float, float]:
    size = _parse_udim2_like(node.get("size"))
    if size is None:
        return parent_abs_size or _VIEWPORT_ABS_SIZE

    if str(node.get("sizeRef") or "").strip().lower() == "viewport":
        ref_w, ref_h = _VIEWPORT_ABS_SIZE
    else:
        ref_w, ref_h = parent_abs_size or _VIEWPORT_ABS_SIZE

    abs_w = max(0.0, size[0] * ref_w + size[1])
    abs_h = max(0.0, size[2] * ref_h + size[3])
    return abs_w, abs_h


def _stud_tile_size_for(icon_key: str, node_abs_size: tuple[float, float]) -> list[float] | None:
    abs_w, abs_h = node_abs_size
    if abs_w <= 1e-6 or abs_h <= 1e-6:
        return None
    target = _STUD_TILE_PIXEL_TARGETS.get(icon_key)
    if target is None:
        return None
    tile_w_px, tile_h_px = target
    x_scale = max(0.0, tile_w_px / abs_w)
    y_scale = max(0.0, tile_h_px / abs_h)
    if icon_key == "Textures/Studs/StudsTexture":
        return [
            round(min(1.25, x_scale), 4),
            0.0,
            round(min(1.5, y_scale), 4),
            0.0,
        ]
    return [
        round(min(1.0, x_scale), 4),
        0.0,
        round(min(1.0, y_scale), 4),
        0.0,
    ]


def _is_tiled_image_node(node: dict[str, Any]) -> bool:
    class_name = str(node.get("type") or "")
    if class_name not in {"ImageLabel", "ImageButton"}:
        return False
    return str(node.get("scaleType") or "").strip().lower() == "tile"


def _postprocess_tiled_texture_node(
    node: dict[str, Any],
    parent_abs_size: tuple[float, float] | None,
) -> tuple[dict[str, Any], tuple[float, float]]:
    node_abs_size = _estimate_node_absolute_size(node, parent_abs_size)
    if not _is_tiled_image_node(node):
        return node, node_abs_size

    icon_key = _normalized_image_key(node)
    if icon_key in _HARD_CODED_STUD_TEXTURE_KEYS:
        _set_image_key(node, _CANONICAL_STUD_TILE_KEY)
        icon_key = _CANONICAL_STUD_TILE_KEY

    if icon_key in _STUD_TILE_TEXTURE_KEYS:
        tile_size = _stud_tile_size_for(icon_key, node_abs_size)
        if tile_size is not None and tile_size[0] >= 0.999 and tile_size[2] >= 0.999:
            # Partial streamed trees can carry incomplete parent sizing, which
            # collapses nested stud tiles to a bogus 1x1 repeat. Fall back to
            # viewport-relative sizing in that case so partial JSON stays sane.
            fallback_abs_size = _estimate_node_absolute_size(node, None)
            fallback_tile_size = _stud_tile_size_for(icon_key, fallback_abs_size)
            if fallback_tile_size is not None:
                tile_size = fallback_tile_size
        if tile_size is not None:
            node["tileSize"] = tile_size

    return node, node_abs_size


def _postprocess_node(node: dict[str, Any]) -> dict[str, Any]:
    class_name = str(node.get("type") or "")
    strokes = node.get("strokes")

    if isinstance(strokes, list):
        for stroke in strokes:
            if isinstance(stroke, dict) and _rgb_triplet(stroke.get("color")) is None:
                stroke["color"] = [0, 0, 0]

    if class_name == "TextButton" and not node.get("text"):
        node["type"] = "ImageButton"

    if class_name == "ImageLabel" and "scaleType" not in node and _is_wrapped_icon_token(node.get("icon")):
        node["scaleType"] = "Fit"

    if _should_remap_to_sunburst(node):
        node["icon"] = _wrapped_icon_token(_SUNBURST_ICON_KEY)
        if "scaleType" not in node:
            node["scaleType"] = "Fit"

    grid = node.get("grid")
    if isinstance(grid, dict):
        cell_padding = _parse_udim2_like(grid.get("cellPadding"))
        has_offset_padding = bool(
            cell_padding is not None and (abs(cell_padding[1]) > 1e-6 or abs(cell_padding[3]) > 1e-6)
        )
        if _is_effectively_half_cell(grid.get("cellSize")) and has_offset_padding:
            parsed_cell_size = _parse_udim2_like(grid.get("cellSize")) or (0.5, 0.0, 0.5, 0.0)
            grid["cellSize"] = _replace_udim2_like(
                grid.get("cellSize"),
                (0.45, parsed_cell_size[1], 0.45, parsed_cell_size[3]),
            )
            grid["vAlign"] = "Center"
            grid["hAlign"] = "Center"

    if class_name == "TextLabel" and _is_near_white_rgb(node.get("textColor")) and isinstance(strokes, list):
        for stroke in strokes:
            if isinstance(stroke, dict) and _is_greenish_stroke_rgb(stroke.get("color")):
                stroke["color"] = [0, 0, 0]

    if class_name == "TextLabel":
        node["textScaled"] = True

    if class_name in {"TextLabel", "TextButton", "TextBox"}:
        node["font"] = _coerce_allowed_font(node.get("font"))

    return node


def _postprocess_texture_tree(
    obj: Any,
    parent_abs_size: tuple[float, float] | None = None,
) -> Any:
    if isinstance(obj, dict):
        out = dict(obj)
        out, node_abs_size = _postprocess_tiled_texture_node(out, parent_abs_size)
        children = out.get("children")
        if isinstance(children, list):
            out["children"] = [_postprocess_texture_tree(child, node_abs_size) for child in children]
        return out
    if isinstance(obj, list):
        return [_postprocess_texture_tree(item, parent_abs_size) for item in obj]
    return obj


def _postprocess_list_tightness_tree(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = dict(obj)
        children = out.get("children")
        list_cfg = out.get("list")
        if isinstance(children, list):
            processed_children = [_postprocess_list_tightness_tree(child) for child in children]
            if isinstance(list_cfg, dict):
                padding = _parse_udim2_like(list_cfg.get("padding", list_cfg.get("Padding")))
                padding_x_scale = padding[0] if padding is not None else 0.0
                if abs(padding_x_scale) > 1e-6:
                    tightened_children: list[Any] = []
                    for child in processed_children:
                        if isinstance(child, dict):
                            child_size = _parse_udim2_like(child.get("size"))
                            if child_size is not None and _is_effectively_half_scale(child_size[0]):
                                child = dict(child)
                                tightened_x_scale = _canonical_half_scale_minus_padding(padding_x_scale)
                                child["size"] = _replace_udim2_like(
                                    child.get("size"),
                                    (tightened_x_scale, child_size[1], child_size[2], child_size[3]),
                                )
                        tightened_children.append(child)
                    processed_children = tightened_children
            out["children"] = processed_children
        return out
    if isinstance(obj, list):
        return [_postprocess_list_tightness_tree(item) for item in obj]
    return obj


def _postprocess_basic_object(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {key: _postprocess_basic_object(value) for key, value in obj.items()}
        return _postprocess_node(out)
    if isinstance(obj, list):
        return [_postprocess_basic_object(item) for item in obj]
    return obj


def postprocess_pinevex_object(obj: Any) -> Any:
    processed = _postprocess_basic_object(obj)
    processed = _postprocess_list_tightness_tree(processed)
    return _postprocess_texture_tree(processed)


def postprocess_pinevex_json_text(text: str, *, indent: int | None = None) -> str:
    parsed = json.loads(text)
    processed = postprocess_pinevex_object(parsed)
    return json.dumps(processed, ensure_ascii=False, indent=indent)
