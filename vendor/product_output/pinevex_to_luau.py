"""Convert PinevexObject JSON to executable Luau code for Roblox Studio's command bar.

PinevexObject is a structured JSON schema for Roblox-style UI trees. This
translator accepts a PinevexObject JSON object and produces Luau code that,
when pasted into Studio's command bar, creates the complete UI hierarchy under
a ScreenGui in game.StarterGui.

Usage:
    # From a file
    python pinevex_to_luau.py input.json

    # From stdin
    echo '{"type":"Frame","name":"Test","size":[1,1],"bg":[255,0,0]}' | python pinevex_to_luau.py

    # As a Python module
    from pinevex_to_luau import pinevex_to_luau
    luau_code = pinevex_to_luau({"type": "Frame", "name": "Test", ...})

Linter rules (auto-corrections applied during translation):
    1. UIStroke thickness < 1 → StrokeSizingMode = ScaledSize (relative to parent),
       otherwise StrokeSizingMode = FixedSize (pixel units).
    2. TextButton with no text → automatically converted to ImageButton.
    3. UIGridLayout with CellSize=(0.5, 0.5) and offset CellPadding is nudged to
       CellSize=(0.45, 0.45) and centered alignment on both axes.
    4. ImageLabel with wrapped icon token (``<|icon:...|>``) defaults to
       ScaleType=Fit unless ``scaleType`` is explicitly provided.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .layout_bounds import BASE_HEIGHT, BASE_WIDTH, Rect, resolve_rect
except ImportError:
    from layout_bounds import BASE_HEIGHT, BASE_WIDTH, Rect, resolve_rect

# ---------------------------------------------------------------------------
# Inlined token extraction helpers.
# ---------------------------------------------------------------------------

_ICON_TOKEN_PREFIX = "<|icon:"
_ICON_TOKEN_SUFFIX = "|>"
_FONT_TOKEN_PREFIX = "<|font:"
_FONT_TOKEN_SUFFIX = "|>"


def extract_icon_key(value: str) -> str:
    """Strip ``<|icon:...|>`` wrapping and return the inner key."""
    text = str(value).strip()
    if text.startswith(_ICON_TOKEN_PREFIX) and text.endswith(_ICON_TOKEN_SUFFIX):
        return text[len(_ICON_TOKEN_PREFIX):-len(_ICON_TOKEN_SUFFIX)]
    return text


def extract_font_key(value: str) -> str:
    """Strip ``<|font:...|>`` wrapping and return the inner key."""
    text = str(value).strip()
    if text.startswith(_FONT_TOKEN_PREFIX) and text.endswith(_FONT_TOKEN_SUFFIX):
        return text[len(_FONT_TOKEN_PREFIX):-len(_FONT_TOKEN_SUFFIX)]
    return text


# ---------------------------------------------------------------------------
# Icon asset lookup
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_VENDOR_DIR = _SCRIPT_DIR.parent
_ICON_MANIFEST_CANDIDATES = (
    _VENDOR_DIR / "icon_library" / "manifest.json",
)

_icon_manifest: dict[str, dict[str, Any]] = {}
for _icon_manifest_path in _ICON_MANIFEST_CANDIDATES:
    if _icon_manifest_path.exists():
        with open(_icon_manifest_path, "r", encoding="utf-8") as _f:
            _icon_manifest = json.load(_f)
        break

# Key aliases only (no hardcoded IDs).
_ICON_KEY_ALIASES: dict[str, str] = {
    "Textures/Studs": "Textures/Studs/StudsTexture",
}

_RBXASSET_ID_RE = re.compile(r"^rbxassetid://\d+$", re.IGNORECASE)
_ROBLOX_ASSET_URL_RE = re.compile(r"^https?://(?:www\.)?roblox\.com/asset/\?id=\d+$", re.IGNORECASE)


def _resolve_icon(key: str) -> str | None:
    """Resolve an icon key to an rbxassetid:// string, or None."""
    key_raw = extract_icon_key(str(key)).strip()
    if not key_raw:
        return None
    candidates = [key_raw]
    key_norm = key_raw.replace("\\", "/")
    if key_norm not in candidates:
        candidates.append(key_norm)
    if key_norm.endswith(".png"):
        base = key_norm[:-4]
        if base and base not in candidates:
            candidates.append(base)
    else:
        with_png = f"{key_norm}.png"
        if with_png not in candidates:
            candidates.append(with_png)

    for cand in candidates:
        key_norm_cand = cand.replace("\\", "/")
        manifest_keys = [key_norm_cand]
        alias = _ICON_KEY_ALIASES.get(key_norm_cand)
        if alias:
            manifest_keys.append(alias)
        for mk in manifest_keys:
            entry = _icon_manifest.get(mk)
            if entry and isinstance(entry, dict):
                image_id = entry.get("imageId")
                if isinstance(image_id, str) and image_id.strip():
                    return image_id.strip()
    return None


def _looks_like_custom_image_id(value: str) -> bool:
    """Return True if value already looks like a Roblox image content id."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if _RBXASSET_ID_RE.match(text):
        return True
    if text.lower().startswith("rbxasset://"):
        return True
    if _ROBLOX_ASSET_URL_RE.match(text):
        return True
    return False


def _is_wrapped_icon_token(value: Any) -> bool:
    """Return True when value is in wrapped token form: <|icon:KEY|>."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith("<|icon:") and text.endswith("|>")


def _resolve_image_source(value: Any) -> tuple[str | None, str | None]:
    """Resolve an image-like field to (asset_id, unresolved_key)."""
    if value is None:
        return None, None

    text = str(value).strip()
    if not text:
        return None, None

    if _looks_like_custom_image_id(text):
        return text, None

    asset_id = _resolve_icon(text)
    if asset_id:
        return asset_id, None

    return None, extract_icon_key(text).strip() or text


# ---------------------------------------------------------------------------
# Font family mapping
# ---------------------------------------------------------------------------

_FONT_FAMILIES: dict[str, str] = {
    "GothamSSm": "rbxasset://fonts/families/Montserrat.json",  # GothamSSm deprecated, map to Montserrat
    "SourceSansPro": "rbxasset://fonts/families/SourceSansPro.json",
    "Roboto": "rbxasset://fonts/families/Roboto.json",
    "Montserrat": "rbxasset://fonts/families/Montserrat.json",
    "Mosserect": "rbxasset://fonts/families/Montserrat.json",  # legacy alias
    "Ubuntu": "rbxasset://fonts/families/Ubuntu.json",
    "FredokaOne": "rbxasset://fonts/families/FredokaOne.json",
    "LuckiestGuy": "rbxasset://fonts/families/LuckiestGuy.json",
    "ComicNeueAngular": "rbxasset://fonts/families/ComicNeueAngular.json",
    "Oswald": "rbxasset://fonts/families/Oswald.json",
    "SpecialElite": "rbxasset://fonts/families/SpecialElite.json",
    "LegacyArial": "rbxasset://fonts/families/LegacyArial.json",
    "Bangers": "rbxasset://fonts/families/Bangers.json",
    "Creepster": "rbxasset://fonts/families/Creepster.json",
    "IndieFlower": "rbxasset://fonts/families/IndieFlower.json",
    "PermanentMarker": "rbxasset://fonts/families/PermanentMarker.json",
    "TitilliumWeb": "rbxasset://fonts/families/TitilliumWeb.json",
    "Sarpanch": "rbxasset://fonts/families/Sarpanch.json",
}

_FONT_WEIGHT_MAP: dict[str, str] = {
    "Thin": "Enum.FontWeight.Thin",
    "ExtraLight": "Enum.FontWeight.ExtraLight",
    "Light": "Enum.FontWeight.Light",
    "Regular": "Enum.FontWeight.Regular",
    "Medium": "Enum.FontWeight.Medium",
    "SemiBold": "Enum.FontWeight.SemiBold",
    "Bold": "Enum.FontWeight.Bold",
    "ExtraBold": "Enum.FontWeight.ExtraBold",
    "Heavy": "Enum.FontWeight.Heavy",
    "Black": "Enum.FontWeight.Heavy",
}

_FONT_STYLE_MAP: dict[str, str] = {
    "Normal": "Enum.FontStyle.Normal",
    "Italic": "Enum.FontStyle.Italic",
}

# Fallback for undecodable/invalid font values.
_FONT_FALLBACK_FAMILY = "Montserrat"
_FONT_FALLBACK_WEIGHT = "Enum.FontWeight.Heavy"  # Montserrat Black

# Font weight overrides for deprecated/remapped fonts
_FONT_WEIGHT_OVERRIDES: dict[str, str] = {
    "GothamSSm": "Enum.FontWeight.Heavy",  # Montserrat Black = Heavy weight
}

_GUIOBJECT_CLASSES: set[str] = {
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

_TEXT_CLASSES: set[str] = {"TextLabel", "TextButton", "TextBox"}
_IMAGE_CLASSES: set[str] = {"ImageLabel", "ImageButton"}

# Luau reserved words cannot be used as local variable identifiers.
_LUAU_RESERVED_WORDS: set[str] = {
    "and",
    "break",
    "continue",
    "do",
    "else",
    "elseif",
    "end",
    "false",
    "for",
    "function",
    "if",
    "in",
    "local",
    "nil",
    "not",
    "or",
    "repeat",
    "return",
    "then",
    "true",
    "until",
    "while",
}


# ---------------------------------------------------------------------------
# Number/string formatting helpers
# ---------------------------------------------------------------------------

def _fmt(value: int | float) -> str:
    """Format a number for Luau output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return "0"
    if abs(value) < 1e-9:
        value = 0.0
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _quote(s: str) -> str:
    """Quote a string for Luau, handling unicode escapes."""
    result = json.dumps(s)
    # Convert JSON \uXXXX escapes to Luau \u{XXXX} format
    result = re.sub(r'\\u([0-9a-fA-F]{4})', r'\\u{\1}', result)
    return result


def _color3(rgb: list) -> str:
    """Convert [R, G, B] (0-255) to Color3.fromRGB(R, G, B)."""
    r = int(round(float(rgb[0])))
    g = int(round(float(rgb[1])))
    b = int(round(float(rgb[2])))
    return f"Color3.fromRGB({r}, {g}, {b})"


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    """Convert '#RRGGBB' or '#RGB' to (R, G, B), or None when invalid."""
    value = str(hex_str).strip()
    if value.startswith("#"):
        value = value[1:]
    if value.startswith(("0x", "0X")):
        value = value[2:]
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6 or re.fullmatch(r"[0-9a-fA-F]{6}", value) is None:
        return None
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return r, g, b


def _safe_float(value: Any) -> float | None:
    """Parse finite float; return None when parsing fails."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _gradient_color_to_rgb(value: Any) -> tuple[int, int, int] | None:
    """Parse gradient color in common formats."""
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r = _safe_float(value[0])
        g = _safe_float(value[1])
        b = _safe_float(value[2])
        if r is None or g is None or b is None:
            return None
        return (
            max(0, min(255, int(round(r)))),
            max(0, min(255, int(round(g)))),
            max(0, min(255, int(round(b)))),
        )
    if isinstance(value, dict):
        r = _safe_float(value.get("r", value.get("R")))
        g = _safe_float(value.get("g", value.get("G")))
        b = _safe_float(value.get("b", value.get("B")))
        if r is not None and g is not None and b is not None:
            # Accept Color3-style 0..1 and RGB-style 0..255.
            if r <= 1.0 and g <= 1.0 and b <= 1.0:
                r *= 255.0
                g *= 255.0
                b *= 255.0
            return (
                max(0, min(255, int(round(r)))),
                max(0, min(255, int(round(g)))),
                max(0, min(255, int(round(b)))),
            )
    return _hex_to_rgb(str(value))


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float parsing with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_udim2_like(value: Any) -> tuple[float, float, float, float] | None:
    """Parse a UDim2-like value into (xScale, xOffset, yScale, yOffset)."""
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


def _precomputed_parent_relative_size(
    obj: dict[str, Any],
    parent_obj: dict[str, Any] | None,
) -> tuple[float, float, float, float] | None:
    if not isinstance(parent_obj, dict):
        return None
    if "autoSize" in parent_obj:
        return None

    parent_size_ref = str(parent_obj.get("sizeRef", "parent")).lower()
    if parent_size_ref != "viewport":
        return None

    viewport = Rect(0.0, 0.0, float(BASE_WIDTH), float(BASE_HEIGHT))
    child_constraint = str(obj.get("sizeConstraint", "RelativeXY"))
    try:
        parent_rect = resolve_rect(parent_obj, viewport, viewport_rect=viewport, default_size_ref="parent")
        child_rect = resolve_rect(obj, parent_rect, viewport_rect=viewport, default_size_ref="parent")
    except Exception:
        return None

    parent_w, parent_h = parent_rect.w, parent_rect.h
    if parent_w <= 0 or parent_h <= 0:
        return None

    ref_w = parent_w
    ref_h = parent_h
    if child_constraint == "RelativeXX":
        ref_h = parent_w
    elif child_constraint == "RelativeYY":
        ref_w = parent_h
        ref_h = parent_h

    child_w, child_h = child_rect.w, child_rect.h
    if ref_w <= 0 or ref_h <= 0:
        return None
    sx = child_w / ref_w
    sy = child_h / ref_h
    if abs(sx - 1.0) < 0.01:
        sx = 1.0
    if abs(sy - 1.0) < 0.01:
        sy = 1.0
    return (sx, 0.0, sy, 0.0)


def _precomputed_viewport_relative_size(
    obj: dict[str, Any],
) -> tuple[float, float, float, float] | None:
    viewport = Rect(0.0, 0.0, float(BASE_WIDTH), float(BASE_HEIGHT))
    try:
        rect = resolve_rect(obj, viewport, viewport_rect=viewport, default_size_ref="parent")
    except Exception:
        return None
    if viewport.w <= 0 or viewport.h <= 0:
        return None
    sx = rect.w / viewport.w
    sy = rect.h / viewport.h
    if abs(sx - 1.0) < 0.01:
        sx = 1.0
    if abs(sy - 1.0) < 0.01:
        sy = 1.0
    return (sx, 0.0, sy, 0.0)


def _is_effectively_half_cell(udim2: tuple[float, float, float, float] | None) -> bool:
    """Return True for CellSize approximately (0.5, 0.5) regardless of offsets."""
    if udim2 is None:
        return False
    return abs(udim2[0] - 0.5) < 0.02 and abs(udim2[2] - 0.5) < 0.02


# ---------------------------------------------------------------------------
# Variable name generation
# ---------------------------------------------------------------------------

class _VarState:
    """Tracks variable name uniqueness during code generation."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next_var(self, name: str, class_name: str) -> str:
        base = self._to_camel(name) or self._to_camel(class_name) or "instance"
        if base in _LUAU_RESERVED_WORDS:
            base = f"{base}Var"
        count = self._counts.get(base, 0) + 1
        self._counts[base] = count
        if count == 1:
            return base
        return f"{base}{count}"

    @staticmethod
    def _to_camel(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        tokens = re.findall(r"[A-Za-z0-9]+", text)
        if not tokens:
            return ""
        first = tokens[0].lower()
        rest = [t[:1].upper() + t[1:].lower() for t in tokens[1:]]
        camel = first + "".join(rest)
        if not camel:
            return ""
        if not re.match(r"^[A-Za-z_]", camel):
            camel = "inst" + camel[:1].upper() + camel[1:]
        return camel


# ---------------------------------------------------------------------------
# Core translator
# ---------------------------------------------------------------------------

class PinevexTranslator:
    """Translates a PinevexObject dict tree into Luau code lines."""

    def __init__(
        self,
        indent: str = "\t",
        parent_var: str = "screenGui",
        preserve_custom_image_ids: bool = False,
        default_size_ref: str = "parent",
    ) -> None:
        self.indent = indent
        self.parent_var = parent_var
        self.preserve_custom_image_ids = preserve_custom_image_ids
        self.default_size_ref = str(default_size_ref or "parent").lower()
        self._var = _VarState()
        self._lines: list[str] = []
        self._unresolved_icons: list[str] = []

    # -- public API --

    def translate(self, obj: dict[str, Any]) -> str:
        """Translate a PinevexObject and return full executable Luau code."""
        self._lines = []
        self._unresolved_icons = []
        root_behavior = str(obj.get("zIndexBehavior", "Sibling"))
        if "Global" in root_behavior:
            screen_gui_behavior = "Global"
        else:
            screen_gui_behavior = "Sibling"

        # Preamble: create ScreenGui
        self._lines.append("-- Auto-generated by pinevex_to_luau.py")
        self._lines.append("-- Paste this entire block into Roblox Studio's command bar")
        self._lines.append("")
        self._lines.append(f'{self.parent_var} = Instance.new("ScreenGui")')
        self._lines.append(f'{self.parent_var}.Name = "PinevexUI"')
        self._lines.append(f"{self.parent_var}.ResetOnSpawn = false")
        self._lines.append(
            f"{self.parent_var}.ZIndexBehavior = Enum.ZIndexBehavior.{screen_gui_behavior}"
        )
        self._lines.append(f"{self.parent_var}.Parent = game:GetService(\"StarterGui\")")
        self._lines.append("")

        # Emit the root element
        self._emit_element(obj, self.parent_var, 0)

        # Unresolved icon warnings
        if self._unresolved_icons:
            self._lines.append("")
            self._lines.append("-- WARNING: The following icon keys could not be resolved to rbxassetid values.")
            self._lines.append("-- You will need to manually set the Image property for these elements:")
            for icon_key in self._unresolved_icons:
                self._lines.append(f"--   {icon_key}")

        return "\n".join(self._lines)

    # -- element emission --

    def _emit_element(self, obj: dict[str, Any], parent_var: str, depth: int, parent_obj: dict[str, Any] | None = None) -> None:
        """Emit Luau code for a single PinevexObject element and its children."""
        class_name = obj.get("type", "Frame")
        # Linter: TextButton with no text → ImageButton
        if class_name == "TextButton" and not obj.get("text"):
            class_name = "ImageButton"
        name = obj.get("name", class_name)
        var = self._var.next_var(name, class_name)
        pad = self.indent * depth
        is_gui_object = class_name in _GUIOBJECT_CLASSES

        self._lines.append(f'{pad}{var} = Instance.new("{class_name}")')
        self._lines.append(f"{pad}{var}.Name = {_quote(name)}")

        if is_gui_object:
            # -- Core properties --
            self._emit_size(obj, var, pad, parent_var, parent_obj)
            self._emit_position(obj, var, pad)
            self._emit_anchor(obj, var, pad)
            self._emit_background(obj, var, pad)
            self._emit_misc_props(obj, var, pad, class_name)

        # -- Text properties (TextLabel, TextButton, TextBox) --
        if class_name in _TEXT_CLASSES:
            self._emit_text_props(obj, var, pad, class_name)

        # -- Image properties (ImageLabel, ImageButton) --
        if class_name in _IMAGE_CLASSES:
            self._emit_image_props(obj, var, pad, class_name)

        # -- Text/Image hybrid: TextButton and TextLabel can also have icon --
        if class_name not in _IMAGE_CLASSES and class_name in _TEXT_CLASSES and "icon" in obj:
            self._emit_image_props(obj, var, pad, class_name)

        # -- ScrollingFrame properties --
        if class_name == "ScrollingFrame":
            self._emit_scrolling_props(obj, var, pad)

        # -- TextBox-specific properties --
        if class_name == "TextBox":
            self._emit_textbox_props(obj, var, pad)

        # Parent to parent
        self._lines.append(f"{pad}{var}.Parent = {parent_var}")

        if is_gui_object:
            # -- UI Constraints and Modifiers (children of this element) --
            self._emit_corner(obj, var, pad, depth)
            self._emit_stroke(obj, var, pad, depth)
            self._emit_gradient(obj, var, pad, depth)
            self._emit_padding(obj, var, pad, depth)
            self._emit_list_layout(obj, var, pad, depth)
            self._emit_grid_layout(obj, var, pad, depth)
            self._emit_aspect_ratio(obj, var, pad, depth)
            self._emit_text_size_constraint(obj, var, pad, depth)
            self._emit_ui_scale(obj, var, pad, depth)

        # -- Recursive children --
        children = obj.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    self._lines.append("")
                    self._emit_element(child, var, depth + 1, obj)

    # -- Property emitters --

    def _emit_size(self, obj: dict, var: str, pad: str, parent_var: str, parent_obj: dict[str, Any] | None) -> None:
        size = obj.get("size")
        if size is None:
            return
        size_ref = str(obj.get("sizeRef", self.default_size_ref)).lower()
        use_viewport = size_ref == "viewport"
        precomputed_parent_size = (
            _precomputed_parent_relative_size(obj, parent_obj)
            if use_viewport and parent_var != self.parent_var
            else None
        )
        precomputed_viewport_size = _precomputed_viewport_relative_size(obj) if use_viewport else None
        if isinstance(size, list) and len(size) >= 4:
            if precomputed_parent_size is not None:
                xs, xo, ys, yo = precomputed_parent_size
                self._lines.append(f"{pad}{var}.Size = UDim2.new({_fmt(xs)}, {_fmt(xo)}, {_fmt(ys)}, {_fmt(yo)})")
                return
            if precomputed_viewport_size is not None:
                xs, xo, ys, yo = precomputed_viewport_size
                self._lines.append(f"{pad}{var}.Size = UDim2.new({_fmt(xs)}, {_fmt(xo)}, {_fmt(ys)}, {_fmt(yo)})")
                return
            xs, xo, ys, yo = float(size[0]), float(size[1]), float(size[2]), float(size[3])
            self._lines.append(f"{pad}{var}.Size = UDim2.new({_fmt(xs)}, {_fmt(xo)}, {_fmt(ys)}, {_fmt(yo)})")
        elif isinstance(size, list) and len(size) >= 2:
            if precomputed_parent_size is not None:
                xs, xo, ys, yo = precomputed_parent_size
                self._lines.append(f"{pad}{var}.Size = UDim2.new({_fmt(xs)}, {_fmt(xo)}, {_fmt(ys)}, {_fmt(yo)})")
                return
            if precomputed_viewport_size is not None:
                xs, xo, ys, yo = precomputed_viewport_size
                self._lines.append(f"{pad}{var}.Size = UDim2.new({_fmt(xs)}, {_fmt(xo)}, {_fmt(ys)}, {_fmt(yo)})")
                return
            xs, ys = float(size[0]), float(size[1])
            self._lines.append(f"{pad}{var}.Size = UDim2.new({_fmt(xs)}, 0, {_fmt(ys)}, 0)")

    def _emit_position(self, obj: dict, var: str, pad: str) -> None:
        pos = obj.get("position")
        if pos is None:
            return
        if isinstance(pos, list) and len(pos) >= 4:
            xp, xo, yp, yo = float(pos[0]), int(pos[1]), float(pos[2]), int(pos[3])
            self._lines.append(f"{pad}{var}.Position = UDim2.new({_fmt(xp)}, {xo}, {_fmt(yp)}, {yo})")
        elif isinstance(pos, list) and len(pos) >= 2:
            xp, yp = float(pos[0]), float(pos[1])
            self._lines.append(f"{pad}{var}.Position = UDim2.new({_fmt(xp)}, 0, {_fmt(yp)}, 0)")

    def _emit_anchor(self, obj: dict, var: str, pad: str) -> None:
        anchor = obj.get("anchor")
        if anchor is None:
            return
        if isinstance(anchor, list) and len(anchor) >= 2:
            ax, ay = float(anchor[0]), float(anchor[1])
            self._lines.append(f"{pad}{var}.AnchorPoint = Vector2.new({_fmt(ax)}, {_fmt(ay)})")

    def _emit_background(self, obj: dict, var: str, pad: str) -> None:
        bg = obj.get("bg")
        if bg is not None and isinstance(bg, list) and len(bg) >= 3:
            self._lines.append(f"{pad}{var}.BackgroundColor3 = {_color3(bg)}")

        bg_trans = obj.get("bgTransparency")
        if bg_trans is not None:
            self._lines.append(f"{pad}{var}.BackgroundTransparency = {_fmt(bg_trans)}")

        # Always suppress the default border
        self._lines.append(f"{pad}{var}.BorderSizePixel = 0")

    def _emit_misc_props(self, obj: dict, var: str, pad: str, class_name: str) -> None:
        """Emit miscellaneous direct properties."""
        if "zIndex" in obj:
            self._lines.append(f"{pad}{var}.ZIndex = {_fmt(obj['zIndex'])}")
        if "layoutOrder" in obj:
            self._lines.append(f"{pad}{var}.LayoutOrder = {_fmt(obj['layoutOrder'])}")
        if "visible" in obj:
            val = "true" if obj["visible"] else "false"
            self._lines.append(f"{pad}{var}.Visible = {val}")
        if "clipsDescendants" in obj:
            val = "true" if obj["clipsDescendants"] else "false"
            self._lines.append(f"{pad}{var}.ClipsDescendants = {val}")
        if "rotation" in obj:
            self._lines.append(f"{pad}{var}.Rotation = {_fmt(obj['rotation'])}")
        if "autoSize" in obj:
            auto = obj["autoSize"]
            if auto == "X":
                self._lines.append(f"{pad}{var}.AutomaticSize = Enum.AutomaticSize.X")
            elif auto == "Y":
                self._lines.append(f"{pad}{var}.AutomaticSize = Enum.AutomaticSize.Y")
            elif auto == "XY":
                self._lines.append(f"{pad}{var}.AutomaticSize = Enum.AutomaticSize.XY")
        if "sizeConstraint" in obj:
            sc = obj["sizeConstraint"]
            self._lines.append(f"{pad}{var}.SizeConstraint = Enum.SizeConstraint.{sc}")

    def _emit_text_props(self, obj: dict, var: str, pad: str, class_name: str) -> None:
        """Emit text-related properties."""
        if "text" in obj:
            self._lines.append(f"{pad}{var}.Text = {_quote(str(obj['text']))}")
        if "textColor" in obj:
            self._lines.append(f"{pad}{var}.TextColor3 = {_color3(obj['textColor'])}")
        if "textSize" in obj:
            self._lines.append(f"{pad}{var}.TextSize = {_fmt(obj['textSize'])}")
        if "textScaled" in obj and obj["textScaled"]:
            self._lines.append(f"{pad}{var}.TextScaled = true")
        if "textWrapped" in obj and obj["textWrapped"]:
            self._lines.append(f"{pad}{var}.TextWrapped = true")
        if "textTransparency" in obj:
            self._lines.append(f"{pad}{var}.TextTransparency = {_fmt(obj['textTransparency'])}")
        if "textXAlignment" in obj:
            self._lines.append(f"{pad}{var}.TextXAlignment = Enum.TextXAlignment.{obj['textXAlignment']}")
        if "textYAlignment" in obj:
            self._lines.append(f"{pad}{var}.TextYAlignment = Enum.TextYAlignment.{obj['textYAlignment']}")
        if "richText" in obj and obj["richText"]:
            self._lines.append(f"{pad}{var}.RichText = true")
        if "lineHeight" in obj:
            self._lines.append(f"{pad}{var}.LineHeight = {_fmt(obj['lineHeight'])}")

        # Font — now a string (possibly token-wrapped), not a dict
        font = obj.get("font")
        if "font" in obj:
            family_name = ""
            if isinstance(font, str):
                family_name = extract_font_key(font).strip()
            elif isinstance(font, dict):
                # Legacy dict format fallback
                family_raw = font.get("family", "")
                if isinstance(family_raw, str):
                    family_name = extract_font_key(family_raw).strip()

            # Accept explicit Roblox family paths directly.
            fallback_font_used = False
            if family_name.startswith("rbxasset://fonts/families/"):
                family_path = family_name
                default_weight = "Enum.FontWeight.Regular"
            else:
                # Known family aliases only; unknown/undecodable values fall back.
                family_path = _FONT_FAMILIES.get(family_name)
                if family_path is None:
                    family_name = _FONT_FALLBACK_FAMILY
                    family_path = _FONT_FAMILIES[_FONT_FALLBACK_FAMILY]
                    default_weight = _FONT_FALLBACK_WEIGHT
                    fallback_font_used = True
                else:
                    default_weight = _FONT_WEIGHT_OVERRIDES.get(family_name, "Enum.FontWeight.Regular")
            font_weight = obj.get("fontWeight")
            if fallback_font_used:
                weight_enum = _FONT_FALLBACK_WEIGHT
            elif isinstance(font_weight, str):
                if font_weight.startswith("Enum.FontWeight."):
                    weight_enum = font_weight
                else:
                    weight_enum = _FONT_WEIGHT_MAP.get(font_weight, default_weight)
            else:
                weight_enum = default_weight

            font_style = obj.get("fontStyle")
            if isinstance(font_style, str):
                if font_style.startswith("Enum.FontStyle."):
                    style_enum = font_style
                else:
                    style_enum = _FONT_STYLE_MAP.get(font_style, "Enum.FontStyle.Normal")
            else:
                style_enum = "Enum.FontStyle.Normal"
            self._lines.append(
                f'{pad}{var}.FontFace = Font.new("{family_path}", {weight_enum}, {style_enum})'
            )

    def _emit_image_props(self, obj: dict, var: str, pad: str, class_name: str | None = None) -> None:
        """Emit image-related properties."""
        icon_value = obj.get("icon")
        image_value = obj.get("image")
        image_source = icon_value if icon_value not in (None, "") else image_value
        icon_is_wrapped_token = _is_wrapped_icon_token(image_source)
        asset_id, unresolved_key = _resolve_image_source(image_source)
        if asset_id:
            self._lines.append(f"{pad}{var}.Image = {_quote(asset_id)}")
        elif unresolved_key:
            self._lines.append(f'{pad}{var}.Image = "" -- TODO: resolve icon "{unresolved_key}"')
            self._unresolved_icons.append(unresolved_key)

        image_rect_size = obj.get("imageRectSize")
        if isinstance(image_rect_size, list) and len(image_rect_size) >= 2:
            self._lines.append(
                f"{pad}{var}.ImageRectSize = Vector2.new({_fmt(image_rect_size[0])}, {_fmt(image_rect_size[1])})"
            )

        image_rect_offset = obj.get("imageRectOffset")
        if isinstance(image_rect_offset, list) and len(image_rect_offset) >= 2:
            self._lines.append(
                f"{pad}{var}.ImageRectOffset = Vector2.new({_fmt(image_rect_offset[0])}, {_fmt(image_rect_offset[1])})"
            )

        # Roblox default for image objects is Stretch.
        # Rule: ImageLabel + wrapped icon token defaults to Fit (unless explicit).
        if "scaleType" in obj:
            st = obj.get("scaleType", "Stretch")
        elif class_name == "ImageLabel" and icon_is_wrapped_token:
            st = "Fit"
        else:
            st = "Stretch"
        self._lines.append(f"{pad}{var}.ScaleType = Enum.ScaleType.{st}")

        if "imageColor" in obj:
            self._lines.append(f"{pad}{var}.ImageColor3 = {_color3(obj['imageColor'])}")

        if "imageTransparency" in obj:
            self._lines.append(f"{pad}{var}.ImageTransparency = {_fmt(obj['imageTransparency'])}")

        if "tileSize" in obj:
            ts = obj["tileSize"]
            if isinstance(ts, list) and len(ts) >= 4:
                # tileSize is [xScale, xOffset, yScale, yOffset]
                self._lines.append(
                    f"{pad}{var}.TileSize = UDim2.new({_fmt(ts[0])}, {_fmt(ts[1])}, {_fmt(ts[2])}, {_fmt(ts[3])})"
                )

        # Support both current key ("sliceCenter") and legacy key ("slice").
        raw_slice = obj.get("sliceCenter")
        if raw_slice is None:
            raw_slice = obj.get("slice")

        sl: list[Any] | None = None
        if isinstance(raw_slice, list) and len(raw_slice) >= 4:
            sl = raw_slice
        elif isinstance(raw_slice, dict):
            s_min = raw_slice.get("min", raw_slice.get("Min", {}))
            s_max = raw_slice.get("max", raw_slice.get("Max", {}))
            if isinstance(s_min, dict) and isinstance(s_max, dict):
                sl = [
                    s_min.get("x", s_min.get("X", 0)),
                    s_min.get("y", s_min.get("Y", 0)),
                    s_max.get("x", s_max.get("X", 0)),
                    s_max.get("y", s_max.get("Y", 0)),
                ]

        if sl is not None:
            self._lines.append(
                f"{pad}{var}.SliceCenter = Rect.new({_fmt(sl[0])}, {_fmt(sl[1])}, {_fmt(sl[2])}, {_fmt(sl[3])})"
            )
            if st != "Slice":
                self._lines.append(f"{pad}{var}.ScaleType = Enum.ScaleType.Slice")

        slice_scale = obj.get("sliceScale")
        if isinstance(slice_scale, (int, float)):
            self._lines.append(f"{pad}{var}.SliceScale = {_fmt(slice_scale)}")

    def _emit_scrolling_props(self, obj: dict, var: str, pad: str) -> None:
        """Emit ScrollingFrame-specific properties."""
        if "scrollDirection" in obj:
            sd = obj["scrollDirection"]
            self._lines.append(f"{pad}{var}.ScrollingDirection = Enum.ScrollingDirection.{sd}")

        if "scrollBarColor" in obj:
            self._lines.append(f"{pad}{var}.ScrollBarImageColor3 = {_color3(obj['scrollBarColor'])}")

        if "scrollBarTransparency" in obj:
            self._lines.append(f"{pad}{var}.ScrollBarImageTransparency = {_fmt(obj['scrollBarTransparency'])}")

        if "scrollBarThickness" in obj:
            self._lines.append(f"{pad}{var}.ScrollBarThickness = {_fmt(obj['scrollBarThickness'])}")

        if "canvasSize" in obj:
            cs = obj["canvasSize"]
            if isinstance(cs, list) and len(cs) >= 2:
                self._lines.append(f"{pad}{var}.CanvasSize = UDim2.new({_fmt(cs[0])}, 0, {_fmt(cs[1])}, 0)")

        if "autoCanvasSize" in obj:
            acs = obj["autoCanvasSize"]
            if acs == "X":
                self._lines.append(f"{pad}{var}.AutomaticCanvasSize = Enum.AutomaticSize.X")
            elif acs == "Y":
                self._lines.append(f"{pad}{var}.AutomaticCanvasSize = Enum.AutomaticSize.Y")
            elif acs == "XY":
                self._lines.append(f"{pad}{var}.AutomaticCanvasSize = Enum.AutomaticSize.XY")

    def _emit_textbox_props(self, obj: dict, var: str, pad: str) -> None:
        """Emit TextBox-specific properties."""
        if "placeholderText" in obj:
            self._lines.append(f"{pad}{var}.PlaceholderText = {_quote(obj['placeholderText'])}")
        if "placeholderColor" in obj:
            self._lines.append(f"{pad}{var}.PlaceholderColor3 = {_color3(obj['placeholderColor'])}")

    # -- UI Constraint emitters --

    def _emit_corner(self, obj: dict, var: str, pad: str, depth: int) -> None:
        corner = obj.get("corner")
        if corner is None:
            return
        cvar = self._var.next_var("UICorner", "UICorner")
        cpad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{cpad}{cvar} = Instance.new("UICorner")')
        if isinstance(corner, dict):
            s = corner.get("scale", 0)
            o = corner.get("offset", 0)
            self._lines.append(f"{cpad}{cvar}.CornerRadius = UDim.new({_fmt(s)}, {_fmt(o)})")
        elif isinstance(corner, (int, float)):
            self._lines.append(f"{cpad}{cvar}.CornerRadius = UDim.new(0, {_fmt(corner)})")
        self._lines.append(f"{cpad}{cvar}.Parent = {var}")

    def _emit_stroke(self, obj: dict, var: str, pad: str, depth: int) -> None:
        strokes = obj.get("strokes", [])
        if not isinstance(strokes, list):
            return
        for stroke in strokes:
            if not isinstance(stroke, dict):
                continue
            svar = self._var.next_var("UIStroke", "UIStroke")
            spad = self.indent * depth
            self._lines.append(f"")
            self._lines.append(f'{spad}{svar} = Instance.new("UIStroke")')

            if "color" in stroke:
                self._lines.append(f"{spad}{svar}.Color = {_color3(stroke['color'])}")
            thickness = stroke.get("thickness")
            if thickness is not None:
                self._lines.append(f"{spad}{svar}.Thickness = {_fmt(thickness)}")
                if stroke.get("thicknessScale"):
                    self._lines.append(f"{spad}{svar}.StrokeSizingMode = Enum.StrokeSizingMode.ScaledSize")
                else:
                    self._lines.append(f"{spad}{svar}.StrokeSizingMode = Enum.StrokeSizingMode.FixedSize")
            if "transparency" in stroke:
                self._lines.append(f"{spad}{svar}.Transparency = {_fmt(stroke['transparency'])}")

            apply_mode = stroke.get("applyMode")
            if isinstance(apply_mode, str):
                if apply_mode.startswith("Enum.ApplyStrokeMode."):
                    self._lines.append(f"{spad}{svar}.ApplyStrokeMode = {apply_mode}")
                elif apply_mode in {"Border", "Contextual"}:
                    self._lines.append(f"{spad}{svar}.ApplyStrokeMode = Enum.ApplyStrokeMode.{apply_mode}")

            border_position = stroke.get("borderPosition")
            if isinstance(border_position, str):
                if border_position.startswith("Enum.BorderStrokePosition."):
                    self._lines.append(f"{spad}{svar}.BorderStrokePosition = {border_position}")
                elif border_position in {"Outer", "Center", "Inner"}:
                    self._lines.append(
                        f"{spad}{svar}.BorderStrokePosition = Enum.BorderStrokePosition.{border_position}"
                    )

            join_mode = stroke.get("lineJoin", stroke.get("joinMode", "Round"))
            if isinstance(join_mode, str) and join_mode.startswith("Enum.LineJoinMode."):
                join_mode_name = join_mode.rsplit(".", 1)[-1]
                join_mode_expr = join_mode
            else:
                join_mode_name = str(join_mode)
                join_mode_expr = f"Enum.LineJoinMode.{join_mode_name}"
            self._lines.append(f"{spad}{svar}.LineJoinMode = {join_mode_expr}")

            # Check if sibling UICorner exists -- if so, force Round join mode
            if obj.get("corner") is not None and join_mode_name != "Round":
                self._lines.append(f"{spad}{svar}.LineJoinMode = Enum.LineJoinMode.Round")

            self._lines.append(f"{spad}{svar}.Parent = {var}")
            self._emit_gradient(stroke, svar, spad, depth)

    def _emit_gradient(self, obj: dict, var: str, pad: str, depth: int) -> None:
        gradient = obj.get("gradient")
        if gradient is None or not isinstance(gradient, dict):
            return
        gvar = self._var.next_var("UIGradient", "UIGradient")
        gpad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{gpad}{gvar} = Instance.new("UIGradient")')

        if "rotation" in gradient:
            self._lines.append(f"{gpad}{gvar}.Rotation = {_fmt(gradient['rotation'])}")

        # Colors: array of [time, "#RRGGBB"] pairs -> ColorSequence
        colors = gradient.get("colors")
        if colors and isinstance(colors, list):
            points: list[tuple[float, int, int, int]] = []
            for entry in colors:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    t = _safe_float(entry[0])
                    rgb = _gradient_color_to_rgb(entry[1])
                    if t is None or rgb is None:
                        continue
                    r, g, b = rgb
                    points.append((t, r, g, b))
            if len(points) == 1:
                # Roblox ColorSequence requires at least two keypoints.
                _, r, g, b = points[0]
                points = [(0.0, r, g, b), (1.0, r, g, b)]
            if points:
                points.sort(key=lambda p: p[0])
                keypoints = [
                    f"ColorSequenceKeypoint.new({_fmt(t)}, Color3.fromRGB({r}, {g}, {b}))"
                    for t, r, g, b in points
                ]
                kp_str = ", ".join(keypoints)
                self._lines.append(f"{gpad}{gvar}.Color = ColorSequence.new({{{kp_str}}})")

        # Transparency: array of [time, value] pairs -> NumberSequence
        transparency = gradient.get("transparency")
        if transparency and isinstance(transparency, list):
            keypoints = []
            for entry in transparency:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    t = _safe_float(entry[0])
                    v = _safe_float(entry[1])
                    if t is None or v is None:
                        continue
                    keypoints.append(
                        f"NumberSequenceKeypoint.new({_fmt(t)}, {_fmt(v)})"
                    )
            if keypoints:
                kp_str = ", ".join(keypoints)
                self._lines.append(f"{gpad}{gvar}.Transparency = NumberSequence.new({{{kp_str}}})")

        # Offset: [X, Y] -> Vector2
        offset = gradient.get("offset")
        if offset and isinstance(offset, list) and len(offset) >= 2:
            self._lines.append(
                f"{gpad}{gvar}.Offset = Vector2.new({_fmt(offset[0])}, {_fmt(offset[1])})"
            )

        self._lines.append(f"{gpad}{gvar}.Parent = {var}")

    def _emit_padding(self, obj: dict, var: str, pad: str, depth: int) -> None:
        padding = obj.get("padding")
        if padding is None or not isinstance(padding, dict):
            return
        pvar = self._var.next_var("UIPadding", "UIPadding")
        ppad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{ppad}{pvar} = Instance.new("UIPadding")')

        for side, prop_name in [
            ("top", "PaddingTop"),
            ("bottom", "PaddingBottom"),
            ("left", "PaddingLeft"),
            ("right", "PaddingRight"),
        ]:
            val = padding.get(side)
            if val is not None:
                if isinstance(val, dict):
                    scale = val.get("scale", 0)
                    offset = val.get("offset", 0)
                    self._lines.append(
                        f"{ppad}{pvar}.{prop_name} = UDim.new({_fmt(scale)}, {_fmt(offset)})"
                    )
                else:
                    self._lines.append(f"{ppad}{pvar}.{prop_name} = UDim.new(0, {_fmt(val)})")

        self._lines.append(f"{ppad}{pvar}.Parent = {var}")

    def _emit_list_layout(self, obj: dict, var: str, pad: str, depth: int) -> None:
        lst = obj.get("list")
        if lst is None:
            return
        if not isinstance(lst, dict):
            lst = {}
        lvar = self._var.next_var("UIListLayout", "UIListLayout")
        lpad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{lpad}{lvar} = Instance.new("UIListLayout")')

        if "direction" in lst:
            d = lst["direction"]
            if d == "X":
                self._lines.append(f"{lpad}{lvar}.FillDirection = Enum.FillDirection.Horizontal")
            else:
                self._lines.append(f"{lpad}{lvar}.FillDirection = Enum.FillDirection.Vertical")

        if "vAlign" in lst:
            self._lines.append(
                f"{lpad}{lvar}.VerticalAlignment = Enum.VerticalAlignment.{lst['vAlign']}"
            )
        if "hAlign" in lst:
            self._lines.append(
                f"{lpad}{lvar}.HorizontalAlignment = Enum.HorizontalAlignment.{lst['hAlign']}"
            )
        if "spacing" in lst:
            sp = lst["spacing"]
            if isinstance(sp, dict):
                self._lines.append(f"{lpad}{lvar}.Padding = UDim.new({_fmt(sp.get('scale', 0))}, {_fmt(sp.get('offset', 0))})")
            else:
                self._lines.append(f"{lpad}{lvar}.Padding = UDim.new(0, {_fmt(sp)})")
        if "wraps" in lst and lst["wraps"]:
            self._lines.append(f"{lpad}{lvar}.Wraps = true")

        self._lines.append(f"{lpad}{lvar}.SortOrder = Enum.SortOrder.LayoutOrder")
        self._lines.append(f"{lpad}{lvar}.Parent = {var}")

    def _emit_grid_layout(self, obj: dict, var: str, pad: str, depth: int) -> None:
        grid = obj.get("grid")
        if grid is None or not isinstance(grid, dict):
            return
        gvar = self._var.next_var("UIGridLayout", "UIGridLayout")
        gpad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{gpad}{gvar} = Instance.new("UIGridLayout")')

        cell_size = _parse_udim2_like(grid.get("cellSize"))
        cell_padding = _parse_udim2_like(grid.get("cellPadding"))
        has_offset_padding = bool(
            cell_padding is not None and (abs(cell_padding[1]) > 1e-6 or abs(cell_padding[3]) > 1e-6)
        )

        # Post-compile nudge: 0.5x0.5 cells with offset padding often clip/overflow.
        # Tighten cells slightly and force centered alignment in this specific case.
        force_center_align = _is_effectively_half_cell(cell_size) and has_offset_padding
        if force_center_align and cell_size is not None:
            cell_size = (0.45, cell_size[1], 0.45, cell_size[3])

        if cell_size is not None:
            self._lines.append(
                f"{gpad}{gvar}.CellSize = UDim2.new({_fmt(cell_size[0])}, {_fmt(cell_size[1])}, {_fmt(cell_size[2])}, {_fmt(cell_size[3])})"
            )

        if cell_padding is not None:
            self._lines.append(
                f"{gpad}{gvar}.CellPadding = UDim2.new({_fmt(cell_padding[0])}, {_fmt(cell_padding[1])}, {_fmt(cell_padding[2])}, {_fmt(cell_padding[3])})"
            )

        direction = grid.get("direction", "X")
        if direction == "Y":
            self._lines.append(f"{gpad}{gvar}.FillDirection = Enum.FillDirection.Vertical")
        else:
            self._lines.append(f"{gpad}{gvar}.FillDirection = Enum.FillDirection.Horizontal")

        v_align = "Center" if force_center_align else grid.get("vAlign")
        h_align = "Center" if force_center_align else grid.get("hAlign")

        if isinstance(v_align, str) and v_align:
            self._lines.append(
                f"{gpad}{gvar}.VerticalAlignment = Enum.VerticalAlignment.{v_align}"
            )
        if isinstance(h_align, str) and h_align:
            self._lines.append(
                f"{gpad}{gvar}.HorizontalAlignment = Enum.HorizontalAlignment.{h_align}"
            )

        self._lines.append(f"{gpad}{gvar}.SortOrder = Enum.SortOrder.LayoutOrder")
        self._lines.append(f"{gpad}{gvar}.Parent = {var}")

    def _emit_aspect_ratio(self, obj: dict, var: str, pad: str, depth: int) -> None:
        ar = obj.get("aspectRatio")
        if ar is None:
            return
        avar = self._var.next_var("UIAspectRatioConstraint", "UIAspectRatioConstraint")
        apad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{apad}{avar} = Instance.new("UIAspectRatioConstraint")')
        self._lines.append(f"{apad}{avar}.AspectRatio = {_fmt(ar)}")
        self._lines.append(f"{apad}{avar}.Parent = {var}")

    def _emit_text_size_constraint(self, obj: dict, var: str, pad: str, depth: int) -> None:
        tsc = obj.get("textSizeConstraint")
        if tsc is None or not isinstance(tsc, dict):
            return
        tvar = self._var.next_var("UITextSizeConstraint", "UITextSizeConstraint")
        tpad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{tpad}{tvar} = Instance.new("UITextSizeConstraint")')

        if "min" in tsc:
            self._lines.append(f"{tpad}{tvar}.MinTextSize = {_fmt(tsc['min'])}")
        if "max" in tsc:
            self._lines.append(f"{tpad}{tvar}.MaxTextSize = {_fmt(tsc['max'])}")

        self._lines.append(f"{tpad}{tvar}.Parent = {var}")

    def _emit_ui_scale(self, obj: dict, var: str, pad: str, depth: int) -> None:
        scale = obj.get("scale")
        if scale is None:
            return
        svar = self._var.next_var("UIScale", "UIScale")
        spad = self.indent * depth
        self._lines.append(f"")
        self._lines.append(f'{spad}{svar} = Instance.new("UIScale")')
        self._lines.append(f"{spad}{svar}.Scale = {_fmt(scale)}")
        self._lines.append(f"{spad}{svar}.Parent = {var}")


# ---------------------------------------------------------------------------
# Public function API
# ---------------------------------------------------------------------------

def pinevex_to_luau(
    obj: dict[str, Any],
    indent: str = "\t",
    parent_var: str = "screenGui",
    preserve_custom_image_ids: bool = False,
    default_size_ref: str = "parent",
) -> str:
    """Convert a PinevexObject dict to executable Luau code.

    Args:
        obj: The PinevexObject dictionary (root element).
        indent: Indentation unit (default: tab).
        parent_var: Variable name for the ScreenGui parent.
        preserve_custom_image_ids: Keep unresolved Roblox image IDs/URLs as-is
            instead of emitting Image = "" placeholders.
        default_size_ref: Fallback size reference when ``sizeRef`` is absent.
            Defaults to "parent" for public renderer inputs.

    Returns:
        A string of Luau code ready to paste into Studio's command bar.
    """
    translator = PinevexTranslator(
        indent=indent,
        parent_var=parent_var,
        preserve_custom_image_ids=preserve_custom_image_ids,
        default_size_ref=default_size_ref,
    )
    return translator.translate(obj)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _decode_clipboard_bytes(raw: bytes) -> str:
    """Decode clipboard bytes robustly across UTF-8/UTF-16/codepage output."""
    if not raw:
        return ""

    # PowerShell frequently emits UTF-16 with NUL bytes when piped.
    likely_utf16 = raw.count(0) > max(1, len(raw) // 8)
    if likely_utf16:
        encodings = ("utf-16-le", "utf-16", "utf-16-be", "utf-8", "cp1252", "latin-1")
    else:
        # Prefer single-byte fallbacks before UTF-16 to avoid mojibake on
        # malformed UTF-8 clipboard payloads with no UTF-16 NUL pattern.
        encodings = ("utf-8", "cp1252", "latin-1", "utf-16-le", "utf-16-be", "utf-16")

    for enc in encodings:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue

    # Last resort: never fail on clipboard decode.
    return raw.decode("utf-8", errors="replace")


def _read_clipboard_text() -> str:
    """Read text clipboard content using common Windows/Unix clipboard tools."""
    commands = [
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        ["pwsh.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        ["wl-paste", "-n"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["pbpaste"],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=False, timeout=5)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
        if result.returncode != 0:
            continue
        stdout = result.stdout if isinstance(result.stdout, (bytes, bytearray)) else b""
        text = _decode_clipboard_bytes(bytes(stdout)).replace("\r\n", "\n")
        if text.strip():
            return text
    return ""


def _extract_json_from_text(text: str) -> str:
    """Extract JSON object/array text from clipboard content if present."""
    if not text:
        return ""

    candidate = text.lstrip("\ufeff").strip()
    if not candidate:
        return ""

    # Common copy format: fenced markdown block.
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()

    # Fast path: already starts with JSON delimiters.
    if candidate and candidate[0] in ("{", "["):
        return candidate

    # Fallback: locate JSON start within surrounding text.
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if not starts:
        return ""
    return candidate[min(starts):].strip()


def _sanitize_json_text(text: str) -> str:
    """Sanitize clipboard JSON text by repairing invalid chars inside strings."""
    if not text:
        return ""

    s = text.lstrip("\ufeff").replace("\x00", "")
    out: list[str] = []
    in_string = False
    escape = False

    for ch in s:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                continue

            if ch == "\\":
                out.append(ch)
                escape = True
                continue

            if ch == '"':
                out.append(ch)
                in_string = False
                continue

            code = ord(ch)

            # JSON strings cannot contain raw control characters.
            if code < 0x20:
                if ch == "\n":
                    out.append("\\n")
                elif ch == "\r":
                    out.append("\\r")
                elif ch == "\t":
                    out.append("\\t")
                else:
                    out.append(f"\\u{code:04x}")
                continue

            # Replace lone surrogate code points with replacement character.
            if 0xD800 <= code <= 0xDFFF:
                out.append("\uFFFD")
                continue

            out.append(ch)
            continue

        out.append(ch)
        if ch == '"':
            in_string = True

    return "".join(out)


def _json_load_with_repair(raw: str) -> tuple[dict[str, Any], bool]:
    """Load JSON with a best-effort repair pass for clipboard corruption."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _sanitize_json_text(raw)
        if repaired != raw:
            obj = json.loads(repaired)
            if isinstance(obj, dict):
                return obj, True
            raise TypeError("PinevexObject must be a JSON object (dict), not a list or scalar.")
        raise

    if not isinstance(obj, dict):
        raise TypeError("PinevexObject must be a JSON object (dict), not a list or scalar.")
    return obj, False


def _read_json_input(args: argparse.Namespace) -> tuple[str, bool]:
    """Read JSON from file/stdin/clipboard."""
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            return f.read(), False

    raw = ""
    if not sys.stdin.isatty():
        # Some runners provide non-tty stdin but no data; handle that by falling back.
        raw = sys.stdin.read()
        if raw.strip():
            return raw, False

    clip_text = _read_clipboard_text()
    clip_json = _extract_json_from_text(clip_text)
    if clip_json:
        return clip_json, True
    return "", False

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert PinevexObject JSON to executable Luau code for Roblox Studio."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Path to a JSON file containing a PinevexObject. Reads from stdin if omitted.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path. Prints to stdout if omitted.",
    )
    parser.add_argument(
        "--indent",
        default="\t",
        help="Indentation unit (default: tab). Use '  ' for 2-space indent.",
    )
    parser.add_argument(
        "--preserve-custom-image-ids",
        action="store_true",
        help="Keep unresolved Roblox image IDs/URLs instead of Image=\"\" placeholders.",
    )
    parser.add_argument(
        "--default-size-ref",
        choices=["parent", "viewport"],
        default="parent",
        help="Fallback sizeRef when omitted in JSON (default: parent).",
    )
    args = parser.parse_args()

    raw, from_clipboard = _read_json_input(args)
    if from_clipboard:
        print("Read JSON from clipboard.", file=sys.stderr)

    raw = raw.strip()
    if not raw:
        print("Error: empty input (no JSON from file/stdin/clipboard)", file=sys.stderr)
        sys.exit(1)

    try:
        obj, repaired = _json_load_with_repair(raw)
        if repaired:
            print("Warning: repaired invalid control/unicode characters in JSON input.", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except TypeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    luau_code = pinevex_to_luau(
        obj,
        indent=args.indent,
        preserve_custom_image_ids=args.preserve_custom_image_ids,
        default_size_ref=args.default_size_ref,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(luau_code)
            f.write("\n")
        print(f"Wrote {len(luau_code)} bytes to {args.output}", file=sys.stderr)
    else:
        print(luau_code)

    # Copy output to clipboard (WSL2)
    try:
        proc = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE)
        proc.communicate(input=luau_code.encode("utf-16-le"), timeout=5)
        print("Copied Luau output to clipboard.", file=sys.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass  # clip.exe not available — silently skip


if __name__ == "__main__":
    main()
