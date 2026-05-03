"""RBXM upload parser used by the public web demo."""

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .rbxm_adapter import parse_rbxm_to_tree
from .tree_to_pinevexobject import flatten_node

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_OUTPUT_ROOT = PROJECT_ROOT / "vendor" / "product_output"

sys.path.insert(0, str(PRODUCT_OUTPUT_ROOT.parent))

from product_output.pinevex_postprocess import postprocess_pinevex_object  # noqa: E402

app = FastAPI(title="Pinevex Renderer Web Demo RBXM Parser")

_SCREEN_GUI_CLASSES = {"ScreenGui", "SurfaceGui", "BillboardGui"}
_RENDERABLE_CLASSES = {
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


class RenderableMatch(NamedTuple):
    node: dict[str, Any]
    visibility_root: dict[str, Any]
    screen_gui_disabled: bool


def _prop_is_false(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.lower() == "false")


def _find_renderable(
    nodes: list[dict[str, Any]],
    screen_gui_disabled: bool = False,
) -> RenderableMatch | None:
    for node in nodes:
        cls = node.get("className", "")
        if cls in _SCREEN_GUI_CLASSES:
            props = node.get("properties") or {}
            gui_disabled = screen_gui_disabled or _prop_is_false(props.get("Enabled"))
            children = node.get("children", [])
            if not children:
                continue
            if len(children) == 1:
                return RenderableMatch(children[0], children[0], gui_disabled)
            return RenderableMatch(
                {
                    "className": "Frame",
                    "name": node.get("name", "ScreenGui"),
                    "properties": {
                        "Size": {
                            "x": {"scale": 1, "offset": 0},
                            "y": {"scale": 1, "offset": 0},
                        },
                        "BackgroundTransparency": 1,
                    },
                    "children": children,
                },
                node,
                gui_disabled,
            )
        if cls in _RENDERABLE_CLASSES:
            return RenderableMatch(node, node, screen_gui_disabled)
        found = _find_renderable(node.get("children", []), screen_gui_disabled)
        if found:
            return found
    return None


def _has_effectively_visible_renderable(
    node: dict[str, Any],
    inherited_visible: bool = True,
) -> bool:
    cls = node.get("className", "")
    props = node.get("properties") or {}
    visible = inherited_visible

    if cls in _SCREEN_GUI_CLASSES:
        visible = visible and not _prop_is_false(props.get("Enabled"))
    elif cls in _RENDERABLE_CLASSES:
        visible = visible and not _prop_is_false(props.get("Visible"))
        if visible:
            return True

    if not visible:
        return False

    children = node.get("children", [])
    if not isinstance(children, list):
        return False
    return any(
        _has_effectively_visible_renderable(child, visible)
        for child in children
        if isinstance(child, dict)
    )


def _count_nodes(node: dict[str, Any]) -> int:
    children = node.get("children", [])
    if not isinstance(children, list):
        return 1
    return 1 + sum(_count_nodes(child) for child in children if isinstance(child, dict))


@app.post("/parse-rbxm")
async def parse_rbxm(file: UploadFile = File(...)):
    filename = file.filename or "upload.rbxm"
    lower = filename.lower()
    if not lower.endswith(".rbxm"):
        raise HTTPException(status_code=400, detail="Expected a binary .rbxm file")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        nodes = parse_rbxm_to_tree(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse RBXM: {exc}") from exc

    renderable = _find_renderable(nodes)
    if not renderable:
        raise HTTPException(
            status_code=400,
            detail="No renderable ScreenGui or GuiObject was found in the file",
        )

    obj = postprocess_pinevex_object(flatten_node(renderable.node))
    warnings: list[str] = []
    if renderable.screen_gui_disabled:
        warnings.append(
            "Heads up: this ScreenGui is disabled, so the render may be blank until Enabled=true."
        )
    elif not _has_effectively_visible_renderable(renderable.visibility_root):
        warnings.append(
            "Heads up: all renderable GUI objects in this RBXM have Visible=false, so the render may be blank."
        )
    return JSONResponse(
        {
            "ok": True,
            "source_name": filename,
            "root_type": obj.get("type"),
            "root_name": obj.get("name"),
            "node_count": _count_nodes(obj),
            "warnings": warnings,
            "pinevex_object": json.dumps(obj, ensure_ascii=False, indent=2),
        }
    )
