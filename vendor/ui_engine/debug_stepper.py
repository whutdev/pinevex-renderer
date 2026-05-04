"""Step-by-step paint debugger for Pinevex UI trees.

The renderer already annotates its draw operations when the canvas supports
``annotate(text)``.  This module supplies that canvas, captures a PNG after
each visual operation, and writes a small browser viewer so the output is easy
to inspect without any private Pinevex archive paths.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import signal
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import skia
from PIL import Image

from .layout import Rect
from .renderer import _normalize_z_index_behavior, _render_global, render_node


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_FONTS_DIR = PACKAGE_DIR / "fonts"
DEFAULT_ICONS_DIR = PACKAGE_DIR.parent / "icon_library"


@dataclass(frozen=True)
class PaintStep:
    index: int
    annotation: str
    image: Image.Image


class StepCanvas:
    """Proxy around ``skia.Canvas`` that snapshots after visual draw calls."""

    def __init__(self, width: int, height: int):
        self._surface = skia.Surface(width, height)
        self._canvas = self._surface.getCanvas()
        self._steps: list[PaintStep] = []
        self._pending_annotation: str | None = None

    def annotate(self, text: str) -> None:
        """Attach text to the next visual draw operation."""
        self._pending_annotation = text

    def __getattr__(self, name: str) -> Any:
        return getattr(self._canvas, name)

    @property
    def steps(self) -> list[PaintStep]:
        return list(self._steps)

    def _snapshot(self, fallback: str) -> None:
        annotation = self._pending_annotation or fallback
        self._pending_annotation = None
        img = self._surface.makeImageSnapshot()
        png = img.encodeToData(skia.EncodedImageFormat.kPNG, 100)
        pil_image = Image.open(io.BytesIO(bytes(png))).convert("RGBA")
        self._steps.append(PaintStep(len(self._steps), annotation, pil_image))

    def clear(self, color):
        self._canvas.clear(color)
        self._snapshot("Clear canvas")

    def drawRect(self, rect, paint):
        self._canvas.drawRect(rect, paint)
        self._snapshot(_paint_label("drawRect", paint))

    def drawRRect(self, rrect, paint):
        self._canvas.drawRRect(rrect, paint)
        self._snapshot(_paint_label("drawRRect", paint))

    def drawString(self, text, x, y, font, paint):
        self._canvas.drawString(text, x, y, font, paint)
        self._snapshot(_paint_label(f"drawString {str(text)[:32]!r}", paint))

    def drawTextBlob(self, blob, x, y, paint):
        self._canvas.drawTextBlob(blob, x, y, paint)
        self._snapshot(_paint_label("drawTextBlob", paint))

    def drawImageRect(self, *args):
        self._canvas.drawImageRect(*args)
        self._snapshot("drawImageRect")

    def saveLayer(self, *args):
        result = self._canvas.saveLayer(*args)
        self._snapshot("saveLayer")
        return result


def _paint_label(name: str, paint: skia.Paint) -> str:
    style = "stroke" if paint.getStyle() == skia.Paint.kStroke_Style else "fill"
    return f"{name} ({style})"


def capture_steps(
    obj: dict,
    *,
    width: int = 1920,
    height: int = 1080,
    icons_dir: Path | None = DEFAULT_ICONS_DIR,
    fonts_dir: Path | None = DEFAULT_FONTS_DIR,
    bg_color: tuple[int, int, int] | tuple[int, int, int, int] = (255, 255, 255),
    z_index_behavior: str = "Sibling",
    default_size_ref: str = "parent",
    debug: bool = False,
    crop: bool = False,
    crop_padding: float = 0.0,
) -> tuple[list[PaintStep], dict[str, Any]]:
    """Capture paint steps for a renderable PinevexObject."""

    canvas = StepCanvas(width, height)
    canvas.annotate("Clear canvas")
    if len(bg_color) == 4:
        canvas.clear(skia.Color(*bg_color))
    else:
        canvas.clear(skia.Color(*bg_color, 255))

    root_rect = Rect(0, 0, width, height)
    ctx: dict[str, Any] = {
        "icons_dir": icons_dir,
        "fonts_dir": fonts_dir,
        "debug": debug,
        "_viewport_rect": root_rect,
        "_default_size_ref": str(default_size_ref or "parent").lower(),
    }

    requested_behavior = _normalize_z_index_behavior(z_index_behavior) or "Sibling"
    root_behavior = _normalize_z_index_behavior(obj.get("zIndexBehavior")) or requested_behavior

    if root_behavior == "Global":
        _render_global(canvas, obj, root_rect, ctx)
    else:
        render_node(canvas, obj, root_rect, ctx)

    steps = canvas.steps
    crop_rect = ctx.get("_crop_rect")
    if crop and crop_rect is not None:
        steps = _crop_steps(steps, crop_rect, width, height, crop_padding)

    metadata: dict[str, Any] = {
        "width": width,
        "height": height,
        "z_index_behavior": root_behavior,
        "default_size_ref": str(default_size_ref or "parent").lower(),
        "debug": debug,
        "step_count": len(steps),
    }
    if crop_rect is not None:
        metadata["crop_rect"] = {
            "x": crop_rect.x,
            "y": crop_rect.y,
            "w": crop_rect.w,
            "h": crop_rect.h,
        }
    return steps, metadata


def save_steps(
    steps: list[PaintStep],
    *,
    output_dir: Path | None = None,
    metadata: dict[str, Any] | None = None,
    write_viewer: bool = True,
) -> Path:
    """Write step PNGs, ``steps.json``, and optionally ``index.html``."""

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="pinevex_steps_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_steps = []
    total = len(steps)
    for step in steps:
        step_number = step.index + 1
        filename = f"step_{step_number:04d}.png"
        step.image.save(out_dir / filename)
        manifest_steps.append(
            {
                "index": step.index,
                "step": step_number,
                "total_steps": total,
                "annotation": step.annotation,
                "file": filename,
            }
        )

    payload = {"metadata": metadata or {}, "steps": manifest_steps}
    (out_dir / "steps.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if write_viewer:
        (out_dir / "index.html").write_text(_viewer_html(payload), encoding="utf-8")
    return out_dir


def show_steps(steps: list[PaintStep]) -> None:
    """Open a small Tk viewer. Arrow keys move through the captured frames."""

    import tkinter as tk
    from PIL import ImageTk

    if not steps:
        print("No steps to display.")
        return

    root = tk.Tk()
    root.title("Pinevex Paint Step Debugger")
    root.configure(bg="#151823")
    root.geometry("1040x720")

    pos = {"idx": 0}
    photo_ref = {"image": None}

    image_label = tk.Label(root, bg="#202434")
    image_label.pack(fill="both", expand=True, padx=10, pady=(10, 0))

    footer = tk.Frame(root, bg="#151823")
    footer.pack(fill="x", padx=10, pady=8)
    counter = tk.Label(footer, bg="#151823", fg="#8b93a7", font=("Consolas", 10), anchor="w")
    counter.pack(side="left")
    annotation = tk.Label(
        footer,
        bg="#151823",
        fg="#e4e8f4",
        font=("Consolas", 10),
        anchor="w",
        wraplength=820,
    )
    annotation.pack(side="left", padx=(20, 0), fill="x", expand=True)

    def show(idx: int) -> None:
        idx = max(0, min(idx, len(steps) - 1))
        pos["idx"] = idx
        step = steps[idx]
        max_w = max(200, root.winfo_width() - 20)
        max_h = max(200, root.winfo_height() - 86)
        preview = step.image.copy()
        preview.thumbnail((max_w, max_h))
        photo = ImageTk.PhotoImage(preview)
        photo_ref["image"] = photo
        image_label.configure(image=photo)
        counter.configure(text=f"Step {idx + 1}/{len(steps)}")
        annotation.configure(text=step.annotation)

    def on_key(event):
        if event.keysym in ("Right", "space"):
            show(pos["idx"] + 1)
        elif event.keysym == "Left":
            show(pos["idx"] - 1)
        elif event.keysym == "Home":
            show(0)
        elif event.keysym == "End":
            show(len(steps) - 1)
        elif event.keysym == "Escape":
            root.destroy()

    signal.signal(signal.SIGINT, lambda *_: root.destroy())
    root.bind("<Key>", on_key)
    root.bind("<Configure>", lambda _event: show(pos["idx"]))
    root.after(100, lambda: show(0))
    root.mainloop()


def _crop_steps(
    steps: list[PaintStep],
    crop_rect: Rect,
    width: int,
    height: int,
    padding: float,
) -> list[PaintStep]:
    pad_x = crop_rect.w * max(0.0, padding)
    pad_y = crop_rect.h * max(0.0, padding)
    x1 = max(0, int(crop_rect.x - pad_x))
    y1 = max(0, int(crop_rect.y - pad_y))
    x2 = min(width, int(crop_rect.x + crop_rect.w + pad_x))
    y2 = min(height, int(crop_rect.y + crop_rect.h + pad_y))
    if x2 <= x1 or y2 <= y1:
        return steps
    return [
        PaintStep(step.index, step.annotation, step.image.crop((x1, y1, x2, y2)))
        for step in steps
    ]


def _viewer_html(payload: dict[str, Any]) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    title = "Pinevex Paint Step Debugger"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; background: #10131b; color: #f1f5f9; }}
    .shell {{ min-height: 100vh; display: grid; grid-template-rows: auto 1fr auto; }}
    header, footer {{ padding: 12px 16px; background: #151a24; border-color: #283142; }}
    header {{ border-bottom: 1px solid #283142; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    footer {{ border-top: 1px solid #283142; display: grid; gap: 8px; }}
    h1 {{ font-size: 14px; margin: 0; font-weight: 650; }}
    button {{ background: #222a3a; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 7px 10px; cursor: pointer; }}
    button:hover {{ background: #2c3548; }}
    input[type="range"] {{ flex: 1 1 260px; }}
    .stage {{ overflow: auto; display: grid; place-items: center; padding: 18px; }}
    img {{ max-width: 100%; height: auto; background: #fff; box-shadow: 0 10px 40px rgba(0,0,0,.35); }}
    .meta {{ color: #94a3b8; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .annotation {{ font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <h1>{html.escape(title)}</h1>
      <button id="prev" type="button">Prev</button>
      <button id="next" type="button">Next</button>
      <input id="range" type="range" min="0" value="0">
      <span id="count" class="meta"></span>
    </header>
    <main class="stage"><img id="frame" alt="paint step"></main>
    <footer>
      <div id="annotation" class="annotation"></div>
      <div class="meta">Left/Right or Space to navigate. Home/End jump to first/last.</div>
    </footer>
  </div>
  <script>
    const manifest = JSON.parse(atob("{encoded}"));
    const steps = manifest.steps || [];
    let index = 0;
    const frame = document.getElementById("frame");
    const range = document.getElementById("range");
    const count = document.getElementById("count");
    const annotation = document.getElementById("annotation");
    range.max = String(Math.max(0, steps.length - 1));
    function show(nextIndex) {{
      if (!steps.length) return;
      index = Math.max(0, Math.min(steps.length - 1, nextIndex));
      const step = steps[index];
      frame.src = step.file;
      range.value = String(index);
      count.textContent = `Step ${{index + 1}}/${{steps.length}}`;
      annotation.textContent = step.annotation || "";
    }}
    document.getElementById("prev").onclick = () => show(index - 1);
    document.getElementById("next").onclick = () => show(index + 1);
    range.oninput = () => show(Number(range.value));
    window.addEventListener("keydown", (event) => {{
      if (event.key === "ArrowRight" || event.key === " ") show(index + 1);
      if (event.key === "ArrowLeft") show(index - 1);
      if (event.key === "Home") show(0);
      if (event.key === "End") show(steps.length - 1);
    }});
    show(0);
  </script>
</body>
</html>
"""


def _parse_size(value: str) -> tuple[int, int]:
    try:
        left, right = value.lower().replace(" ", "").split("x", 1)
        width = int(left)
        height = int(right)
        if width <= 0 or height <= 0:
            raise ValueError
        return width, height
    except Exception as exc:
        raise argparse.ArgumentTypeError("Expected WIDTHxHEIGHT, for example 1920x1080") from exc


def _load_json(path: str) -> dict:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("Input JSON must be a PinevexObject JSON object")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture step-by-step Pinevex renderer paint frames.")
    parser.add_argument("json", help="Pinevex JSON file, or '-' for stdin")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("pinevex_steps"))
    parser.add_argument("--viewport-size", type=_parse_size, default=(1920, 1080), help="WIDTHxHEIGHT")
    parser.add_argument("--z-index-behavior", choices=["Sibling", "Global"], default="Sibling")
    parser.add_argument("--default-size-ref", choices=["parent", "viewport"], default="parent")
    parser.add_argument("--transparent", action="store_true", help="Use a transparent canvas")
    parser.add_argument("--debug", action="store_true", help="Draw renderer debug outlines")
    parser.add_argument("--crop", action="store_true", help="Crop frames when the object sets _crop: true")
    parser.add_argument("--crop-padding", type=float, default=0.0)
    parser.add_argument("--open", action="store_true", help="Open the generated browser viewer")
    parser.add_argument("--tk", action="store_true", help="Open the Tk viewer after writing files")
    parser.add_argument("--no-viewer-file", action="store_true", help="Do not write index.html")
    args = parser.parse_args(argv)

    obj = _load_json(args.json)
    width, height = args.viewport_size
    bg = (255, 255, 255, 0) if args.transparent else (255, 255, 255)
    steps, metadata = capture_steps(
        obj,
        width=width,
        height=height,
        bg_color=bg,
        z_index_behavior=args.z_index_behavior,
        default_size_ref=args.default_size_ref,
        debug=args.debug,
        crop=args.crop,
        crop_padding=args.crop_padding,
    )
    output_dir = save_steps(
        steps,
        output_dir=args.output_dir,
        metadata=metadata,
        write_viewer=not args.no_viewer_file,
    )
    print(f"Wrote {len(steps)} paint steps to {output_dir}")
    if not args.no_viewer_file:
        print(f"Open {output_dir / 'index.html'} to inspect them.")
    if args.open and not args.no_viewer_file:
        webbrowser.open((output_dir / "index.html").resolve().as_uri())
    if args.tk:
        show_steps(steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
