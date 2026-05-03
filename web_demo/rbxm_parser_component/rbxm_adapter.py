"""Convert rbxm_parser VirtualInstance trees to raw node dicts for flatten_node()."""

import re

import requests

from .rbxm_parser.parser import parse_rbxm_bytes as _parse_rbxm_bytes

# ---------------------------------------------------------------------------
# Font asset ID → family name resolution
# ---------------------------------------------------------------------------

_RBXASSETID_RE = re.compile(r"rbxassetid://(\d+)")
_ROBLOX_ASSET_URL_RE = re.compile(r"https?://(?:www\.)?roblox\.com/asset/\?id=(\d+)", re.IGNORECASE)

# Well-known Roblox built-in font families (avoids API calls for common fonts)
_FONT_ASSET_CACHE: dict[str, str] = {
    "11702779409": "Poppins",
    "11702779514": "Oswald",
    "11702779517": "Montserrat",
    "11702779556": "Lato",
    "12187370747": "Noto Sans",
    "12187371840": "Silkscreen",
    "12187374537": "Sono",
    "12187374954": "Fira Sans",
    "12187375181": "Merriweather",
    "12187375399": "Roboto",
    "12187375716": "Finger Paint",
    "12187375893": "Nunito",
    "16658221428": "Builder Sans",
    "16658233911": "Builder Sans Semi",
    "16658236243": "Builder Serif",
    "16658237174": "Builder Extended",
    "16658246179": "Builder Mono",
}


def _resolve_font_family(family_url: str) -> str:
    """Resolve an rbxassetid:// font URL to a family name.

    Uses a local cache, then falls back to the Roblox API for unknown IDs.
    Returns the original URL unchanged if resolution fails.
    """
    m = _RBXASSETID_RE.search(family_url)
    if not m:
        return family_url
    aid = m.group(1)
    if aid in _FONT_ASSET_CACHE:
        return _FONT_ASSET_CACHE[aid]
    # API fallback
    try:
        resp = requests.get(
            "https://apis.roblox.com/toolbox-service/v1/items/details",
            params={"assetIds": aid},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            name = item.get("asset", {}).get("name", "")
            if name:
                _FONT_ASSET_CACHE[aid] = name
                return name
    except Exception:
        pass
    return family_url


def _normalize_asset_ref(prop_name: str, value: str) -> str:
    """Normalize supported Roblox web asset URLs to rbxassetid:// for asset fields."""
    if prop_name != "Image":
        return value
    m = _ROBLOX_ASSET_URL_RE.search(value)
    if m:
        return f"rbxassetid://{m.group(1)}"
    return value


# ---------------------------------------------------------------------------
# Roblox enum value mappings used by the binary RBXM parser.
# ---------------------------------------------------------------------------

ENUM_VALUES = {
    "SizeConstraint": {"RelativeXY": 0, "RelativeXX": 1, "RelativeYY": 2},
    "BorderMode": {"Outline": 0, "Middle": 1, "Inset": 2},
    "AutomaticSize": {"None": 0, "X": 1, "Y": 2, "XY": 3},
    "TextXAlignment": {"Left": 0, "Right": 1, "Center": 2},
    "TextYAlignment": {"Top": 0, "Center": 1, "Bottom": 2},
    "TextTruncate": {"None": 0, "AtEnd": 1, "SplitWord": 2},
    "ScaleType": {"Stretch": 0, "Slice": 1, "Tile": 2, "Fit": 3, "Crop": 4},
    "ResamplerMode": {"Default": 0, "Pixelated": 1},
    "ResampleMode": {"Default": 0, "Pixelated": 1},
    "ScrollingDirection": {"X": 1, "Y": 2, "XY": 4},
    "ElasticBehavior": {"WhenScrollable": 0, "Always": 1, "Never": 2},
    "ZIndexBehavior": {"Global": 0, "Sibling": 1},
    "ScreenInsets": {"None": 0, "DeviceSafeInsets": 1, "CoreUISafeInsets": 2, "TopbarSafeInsets": 3},
    "SafeAreaCompatibility": {"None": 0, "FullscreenExtension": 1},
    "NormalId": {"Right": 0, "Top": 1, "Back": 2, "Left": 3, "Bottom": 4, "Front": 5},
    "SurfaceGuiSizingMode": {"FixedSize": 0, "PixelsPerStud": 1},
    "FillDirection": {"Horizontal": 0, "Vertical": 1},
    "HorizontalAlignment": {"Center": 0, "Left": 1, "Right": 2},
    "VerticalAlignment": {"Center": 0, "Top": 1, "Bottom": 2},
    "SortOrder": {"Name": 0, "Custom": 1, "LayoutOrder": 2},
    "StartCorner": {"TopLeft": 0, "TopRight": 1, "BottomLeft": 2, "BottomRight": 3},
    "UIFlexAlignment": {"None": 0, "Fill": 1, "SpaceAround": 2, "SpaceBetween": 3, "SpaceEvenly": 4},
    "ItemLineAlignment": {"Automatic": 0, "Start": 1, "Center": 2, "End": 3, "Stretch": 4},
    "EasingDirection": {"In": 0, "Out": 1, "InOut": 2},
    "EasingStyle": {"Linear": 0, "Sine": 1, "Back": 2, "Quad": 3, "Quart": 4, "Quint": 5, "Bounce": 6, "Elastic": 7, "Exponential": 8, "Circular": 9, "Cubic": 10},
    "ApplyStrokeMode": {"Contextual": 0, "Border": 1},
    "LineJoinMode": {"Round": 0, "Bevel": 1, "Miter": 2},
    "AspectType": {"FitWithinMaxSize": 0, "ScaleWithParentSize": 1},
    "DominantAxis": {"Width": 0, "Height": 1},
    "UIFlexMode": {"None": 0, "Grow": 1, "Shrink": 2, "Fill": 3, "Custom": 4},
    "FontStyle": {"Normal": 0, "Italic": 1},
    "FontWeight": {
        "Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400,
        "Medium": 500, "SemiBold": 600, "Bold": 700, "ExtraBold": 800, "Heavy": 900,
    },
    "TableMajorAxis": {"RowMajor": 0, "ColumnMajor": 1},
    "StrokeSizingMode": {"FixedSize": 0, "ScaledSize": 1},
    "BorderStrokePosition": {"Outer": 0, "Center": 1, "Inner": 2},
}

TOKEN_PROPERTIES = {
    "SizeConstraint", "BorderMode", "AutomaticSize", "TextXAlignment",
    "TextYAlignment", "TextTruncate", "Font", "ScaleType", "ResamplerMode",
    "ScrollingDirection", "ElasticBehavior", "ZIndexBehavior", "ScreenInsets",
    "SafeAreaCompatibility", "Face", "SizingMode", "FillDirection",
    "HorizontalAlignment", "VerticalAlignment", "SortOrder", "StartCorner",
    "HorizontalFlex", "VerticalFlex", "ItemLineAlignment", "EasingDirection",
    "EasingStyle", "ApplyStrokeMode", "LineJoinMode", "AspectType",
    "DominantAxis", "FlexMode", "MajorAxis", "StrokeSizingMode",
    "BorderStrokePosition",
}

# Build reverse lookup: enum_type -> {int_value -> "Enum.type.item"}
REVERSE_ENUM_VALUES: dict[str, dict[int, str]] = {}
for _enum_type, _items in ENUM_VALUES.items():
    REVERSE_ENUM_VALUES[_enum_type] = {v: f"Enum.{_enum_type}.{k}" for k, v in _items.items()}

# Map property name -> enum type name for TOKEN_PROPERTIES
PROPERTY_TO_ENUM: dict[str, str] = {}
for _prop in TOKEN_PROPERTIES:
    # Most properties map directly to an enum of the same name
    if _prop in ENUM_VALUES:
        PROPERTY_TO_ENUM[_prop] = _prop
    # Handle special cases where property name differs from enum type
    elif _prop == "Face":
        PROPERTY_TO_ENUM[_prop] = "NormalId"
    elif _prop == "SizingMode":
        PROPERTY_TO_ENUM[_prop] = "SurfaceGuiSizingMode"
    elif _prop == "HorizontalFlex":
        PROPERTY_TO_ENUM[_prop] = "UIFlexAlignment"
    elif _prop == "VerticalFlex":
        PROPERTY_TO_ENUM[_prop] = "UIFlexAlignment"
    elif _prop == "FlexMode":
        PROPERTY_TO_ENUM[_prop] = "UIFlexMode"
    elif _prop == "MajorAxis":
        PROPERTY_TO_ENUM[_prop] = "TableMajorAxis"


def _convert_value(prop_name: str, v):
    """Convert a single rbxm_parser property value to the dict format flatten_node() expects."""
    if v is None:
        return None

    # Primitives
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        # Enum properties stored as raw ints — resolve to "Enum.Type.Item" strings
        if prop_name in PROPERTY_TO_ENUM:
            enum_type = PROPERTY_TO_ENUM[prop_name]
            reverse = REVERSE_ENUM_VALUES.get(enum_type, {})
            if v in reverse:
                return reverse[v]
            # Unknown enum value — drop property so flatten_node uses Roblox defaults
            return None
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        return _normalize_asset_ref(prop_name, v)

    # Color3: has .r, .g, .b (floats 0-1)
    if hasattr(v, "r") and hasattr(v, "g") and hasattr(v, "b"):
        return {"r": float(v.r), "g": float(v.g), "b": float(v.b)}

    # UDim2: has .x and .y where each is a UDim (has .scale, .offset)
    if hasattr(v, "x") and hasattr(v, "y"):
        x, y = v.x, v.y
        if hasattr(x, "scale") and hasattr(x, "offset"):
            # UDim2
            return {
                "x": {"scale": float(x.scale), "offset": int(x.offset)},
                "y": {"scale": float(y.scale), "offset": int(y.offset)},
            }
        # Vector2 (x and y are plain numbers)
        if not hasattr(v, "z"):
            return {"x": float(x), "y": float(y)}
        # Vector3
        return {"x": float(x), "y": float(y), "z": float(v.z)}

    # UDim (standalone): has .scale, .offset but no .x/.y
    if hasattr(v, "scale") and hasattr(v, "offset"):
        return {"scale": float(v.scale), "offset": int(v.offset)}

    # Font: has .family, .weight, .style
    if hasattr(v, "family") and hasattr(v, "weight") and hasattr(v, "style"):
        style_val = v.style
        # Font.style may be int (0=Normal, 1=Italic) — map to string
        if isinstance(style_val, int):
            reverse_style = REVERSE_ENUM_VALUES.get("FontStyle", {})
            style_val = reverse_style.get(style_val, "Enum.FontStyle.Normal")
        # Font.weight is int (e.g. 400) — convert to enum string for _extract_font_weight()
        weight_val = v.weight
        if isinstance(weight_val, int):
            reverse_weight = REVERSE_ENUM_VALUES.get("FontWeight", {})
            weight_val = reverse_weight.get(weight_val, f"Enum.FontWeight.Regular")
        family = str(v.family)
        # Resolve rbxassetid:// font URLs to family names
        if "rbxassetid://" in family:
            family = _resolve_font_family(family)
        return {
            "family": family,
            "weight": str(weight_val),
            "style": str(style_val),
        }

    # NumberRange: has .min, .max (plain numbers)
    if hasattr(v, "min") and hasattr(v, "max"):
        min_val, max_val = v.min, v.max
        # Rect: .min and .max are Vector2s
        if hasattr(min_val, "x"):
            return {
                "min": {"x": float(min_val.x), "y": float(min_val.y)},
                "max": {"x": float(max_val.x), "y": float(max_val.y)},
            }
        return {"min": float(min_val), "max": float(max_val)}

    # ColorSequence: object with .keypoints list of ColorSequenceKeypoint(.time, .value=Color3)
    if hasattr(v, "keypoints") and v.keypoints and hasattr(v.keypoints[0], "value") and hasattr(v.keypoints[0].value, "r"):
        return [
            {
                "time": float(kp.time),
                "color": {"r": float(kp.value.r), "g": float(kp.value.g), "b": float(kp.value.b)},
            }
            for kp in v.keypoints
        ]

    # NumberSequence: object with .keypoints list of NumberSequenceKeypoint(.time, .value, .envelope)
    if hasattr(v, "keypoints") and v.keypoints and hasattr(v.keypoints[0], "value"):
        return [
            {
                "time": float(kp.time),
                "value": float(kp.value),
                "envelope": float(getattr(kp, "envelope", 0)),
            }
            for kp in v.keypoints
        ]

    # Fallback: try str()
    return str(v)


def _instance_to_node(inst) -> dict:
    """Convert a single VirtualInstance to a raw node dict."""
    props = {}
    for prop_name, prop_value in inst.properties.items():
        if prop_name == "Name":
            continue
        converted = _convert_value(prop_name, prop_value)
        if converted is not None:
            props[prop_name] = converted

    node = {
        "className": inst.class_name,
        "name": inst.properties.get("Name", inst.class_name),
        "properties": props,
        "children": [_instance_to_node(child) for child in inst.children],
    }
    return node


def parse_rbxm_to_tree(data: bytes) -> list[dict]:
    """Parse rbxm bytes into list of raw Roblox JSON tree nodes.

    Returns nodes in the format flatten_node() expects:
    {className, name, properties: {...}, children: [...]}
    """
    model = _parse_rbxm_bytes(data)
    return [_instance_to_node(inst) for inst in model.tree]
