import base64
import ctypes
import io
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from json_repair import repair_json
from PIL import Image as PILImage
from pydantic import BaseModel


def _preload_native_libs() -> None:
    if not sys.platform.startswith("linux"):
        return

    native_root = Path(__file__).resolve().parents[1] / "vendor" / "native"
    if not native_root.is_dir():
        return

    load_order = [
        "libexpat.so.1",
        "libXau.so.6",
        "libXdmcp.so.6",
        "libxcb.so.1",
        "libX11.so.6",
        "libXext.so.6",
        "libGLdispatch.so.0",
        "libGLX.so.0",
        "libGL.so.1",
        "libEGL.so.1",
    ]

    for name in load_order:
        path = native_root / name
        if path.is_file():
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)


_preload_native_libs()


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_ENGINE_ROOT = PROJECT_ROOT / "src" / "ui_engine"
ICON_LIBRARY_ROOT = PROJECT_ROOT / "vendor" / "icon_library"
PRODUCT_OUTPUT_ROOT = PROJECT_ROOT / "vendor" / "product_output"

for required_path in (UI_ENGINE_ROOT, ICON_LIBRARY_ROOT, PRODUCT_OUTPUT_ROOT):
    if not required_path.exists():
        raise RuntimeError(f"Missing required runtime path: {required_path.relative_to(PROJECT_ROOT)}")

sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PRODUCT_OUTPUT_ROOT.parent))

from ui_engine.renderer import render_json  # noqa: E402
from ui_engine.assets import _load_image_cached  # noqa: E402
from ui_engine.text_fonts import audit_required_font_variants, _try_load_exact_typeface  # noqa: E402
from ui_engine.asset_fetcher import collect_asset_ids, fetch_icons  # noqa: E402
from product_output.pinevex_postprocess import postprocess_pinevex_object  # noqa: E402
from product_output.pinevex_to_luau import pinevex_to_luau  # noqa: E402


FONTS_DIR = UI_ENGINE_ROOT / "fonts"
ICONS_DIR = ICON_LIBRARY_ROOT
ICON_CACHE_DIR = Path(
    os.getenv("ICON_CACHE_DIR", "/tmp/pinevex-renderer/cache/icons")
).resolve()
os.environ.setdefault("ICON_CACHE_DIR", str(ICON_CACHE_DIR))

app = FastAPI(title="Pinevex Renderer")


class RenderRequest(BaseModel):
    pinevex_object: str | dict
    allow_partial: bool = True
    include_preview: bool = True
    include_luau: bool = True
    viewport_size: list[int] | tuple[int, int] | dict[str, int] | str | None = None
    transparent_background: bool = False


def _extract_json_candidate(text: str) -> str:
    raw = text.strip()
    if not raw:
        return ""

    think_close = raw.rfind("</think>")
    if think_close != -1:
        raw = raw[think_close + len("</think>"):]

    if "```json" in raw:
        raw = raw.split("```json", 1)[1]
    else:
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            raw = stripped[3:]

    starts = [idx for idx in (raw.find("{"), raw.find("[")) if idx != -1]
    if not starts:
        return ""

    raw = raw[min(starts):]
    if "```" in raw:
        raw = raw.split("```", 1)[0]

    return raw.strip()


def _looks_complete_json(text: str) -> bool:
    in_string = False
    escape_next = False
    stack = []
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if not stack or stack[-1] != ch:
                return False
            stack.pop()
    return bool(text.strip()) and not in_string and not stack


def _stabilize_partial_json(text: str) -> str:
    in_string = False
    escape_next = False
    stack = []
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()
    if in_string:
        if text.endswith("\\"):
            text = text[:-1]
        text += '"'
    text = text.rstrip().rstrip(",")
    for closer in reversed(stack):
        text += closer
    return text


def _parse_partial_json(text: str):
    raw = _extract_json_candidate(text)
    if not raw:
        return None, False

    is_complete = _looks_complete_json(raw)
    candidates = [raw]
    if not is_complete:
        stabilized = _stabilize_partial_json(raw)
        if stabilized and stabilized != raw:
            candidates.append(stabilized)

    for candidate in candidates:
        try:
            repaired = repair_json(
                candidate,
                return_objects=True,
                stream_stable=True,
            )
        except Exception:
            continue

        if isinstance(repaired, (dict, list)):
            return repaired, is_complete

    return None, False


def _fetch_icons_sync(obj):
    asset_ids = collect_asset_ids(obj)
    if not asset_ids:
        return
    ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for _ in fetch_icons(asset_ids, ICON_CACHE_DIR):
        pass
    _load_image_cached.cache_clear()


def _crop_preview_image(img: PILImage.Image, crop_rect: Any, padding: float = 0.12) -> PILImage.Image:
    if crop_rect is None:
        return img
    width, height = img.size
    try:
        pad_x = float(crop_rect.w) * max(0.0, padding)
        pad_y = float(crop_rect.h) * max(0.0, padding)
        x1 = max(0, int(float(crop_rect.x) - pad_x))
        y1 = max(0, int(float(crop_rect.y) - pad_y))
        x2 = min(width, int(float(crop_rect.x) + float(crop_rect.w) + pad_x))
        y2 = min(height, int(float(crop_rect.y) + float(crop_rect.h) + pad_y))
    except Exception:
        return img
    if x2 <= x1 or y2 <= y1:
        return img
    return img.crop((x1, y1, x2, y2))


def _prepare_preview_object(obj: dict) -> dict:
    render_obj = deepcopy(obj)
    render_obj["position"] = [0.5, 0, 0.5, 0]
    render_obj["anchor"] = [0.5, 0.5]
    render_obj["_crop"] = True
    return render_obj


def _parse_viewport_size(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (max(1, int(value[0])), max(1, int(value[1])))
        except Exception:
            return None
    if isinstance(value, dict):
        try:
            return (
                max(1, int(value.get("width"))),
                max(1, int(value.get("height"))),
            )
        except Exception:
            return None
    if isinstance(value, str):
        raw = value.strip().lower().replace(" ", "")
        sep = "x" if "x" in raw else "," if "," in raw else None
        if not sep:
            return None
        try:
            left, right = raw.split(sep, 1)
            return (max(1, int(left)), max(1, int(right)))
        except Exception:
            return None
    return None


def _render_preview_bytes(
    obj: dict,
    viewport_size: Any = None,
    transparent_background: bool = False,
) -> bytes:
    render_obj = _prepare_preview_object(obj)
    width, height = _parse_viewport_size(viewport_size) or (1920, 1080)
    render_out: dict[str, Any] = {}
    bg_color = (255, 255, 255, 0) if transparent_background else (255, 255, 255)
    img = render_json(
        render_obj,
        output_path=None,
        fonts_dir=FONTS_DIR,
        icons_dir=ICONS_DIR,
        width=width,
        height=height,
        bg_color=bg_color,
        default_size_ref="parent",
        out=render_out,
    )
    img = _crop_preview_image(img, render_out.get("crop_rect"), padding=0.12)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _resolve_request_object(req: RenderRequest) -> tuple[dict, bool]:
    if isinstance(req.pinevex_object, dict):
        obj = req.pinevex_object
        is_complete = True
    else:
        obj, is_complete = _parse_partial_json(req.pinevex_object)

    if not obj or not isinstance(obj, dict):
        raise HTTPException(status_code=422, detail="Unable to parse Pinevex object")

    obj = postprocess_pinevex_object(obj)
    _fetch_icons_sync(obj)
    return obj, is_complete


def _check_auth(authorization: str | None) -> None:
    expected = os.getenv("RENDERER_API_KEY")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _inspect_font_variant(family: str, weight: int, italic: bool = False) -> dict[str, Any]:
    tf = _try_load_exact_typeface(family, weight, FONTS_DIR, italic=italic)
    if tf is None:
        return {
            "requested_family": family,
            "requested_weight": weight,
            "italic": italic,
            "loaded": False,
        }

    style = tf.fontStyle()
    return {
        "requested_family": family,
        "requested_weight": weight,
        "italic": italic,
        "loaded": True,
        "family_name": tf.getFamilyName(),
        "unique_id": tf.uniqueID(),
        "style_weight": int(style.weight()),
        "style_width": int(style.width()),
        "style_slant": int(style.slant()),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ui_engine": UI_ENGINE_ROOT.exists(),
        "icon_library": ICON_LIBRARY_ROOT.exists(),
        "product_output": PRODUCT_OUTPUT_ROOT.exists(),
    }


@app.get("/font-health")
def font_health(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    bundled_files = sorted(path.name for path in FONTS_DIR.glob("*") if path.is_file())
    return {
        "status": "ok",
        "bundled_files": bundled_files,
        "missing_required_variants": audit_required_font_variants(FONTS_DIR),
        "checks": [
            _inspect_font_variant("FredokaOne", 400),
            _inspect_font_variant("Montserrat", 400),
            _inspect_font_variant("Montserrat", 500),
            _inspect_font_variant("Montserrat", 700),
            _inspect_font_variant("Montserrat", 900),
            _inspect_font_variant("SourceSansPro", 400),
        ],
    }


@app.post("/render")
def render(req: RenderRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    obj, is_complete = _resolve_request_object(req)

    response = {
        "ok": True,
        "complete": is_complete,
        "repaired": not is_complete,
        "pinevex_object": json.dumps(obj, ensure_ascii=False),
    }

    if req.include_preview:
        try:
            preview_bytes = _render_preview_bytes(
                obj,
                req.viewport_size,
                req.transparent_background,
            )
            response["preview"] = (
                f"data:image/png;base64,{base64.b64encode(preview_bytes).decode('ascii')}"
            )
            response["image"] = response["preview"]
        except Exception:
            response["preview"] = None
    if req.include_luau:
        response["luau"] = pinevex_to_luau(obj, default_size_ref="parent")

    return response


@app.post("/preview.png")
def render_preview(req: RenderRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    obj, _ = _resolve_request_object(req)
    try:
        preview_bytes = _render_preview_bytes(
            obj,
            req.viewport_size,
            req.transparent_background,
        )
    except Exception:
        raise HTTPException(status_code=422, detail="Unable to render preview")
    return Response(
        content=preview_bytes,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )
