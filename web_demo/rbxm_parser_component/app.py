"""RBXM upload parser used by the public web demo."""

import json
import sys
from pathlib import Path
from typing import Any

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


def _find_renderable(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        cls = node.get("className", "")
        if cls in _SCREEN_GUI_CLASSES:
            children = node.get("children", [])
            if not children:
                continue
            if len(children) == 1:
                return children[0]
            return {
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
            }
        if cls in _RENDERABLE_CLASSES:
            return node
        found = _find_renderable(node.get("children", []))
        if found:
            return found
    return None


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

    obj = postprocess_pinevex_object(flatten_node(renderable))
    return JSONResponse(
        {
            "ok": True,
            "source_name": filename,
            "root_type": obj.get("type"),
            "root_name": obj.get("name"),
            "node_count": _count_nodes(obj),
            "pinevex_object": json.dumps(obj, ensure_ascii=False, indent=2),
        }
    )
