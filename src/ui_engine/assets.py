"""Load icon/image files from the icon library and draw them onto a skia canvas."""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import skia

from .visuals import make_gradient_shader, resolve_corner


def _annotate(canvas, text):
    """Set annotation on StepCanvas; no-op on regular skia.Canvas."""
    if hasattr(canvas, 'annotate'):
        canvas.annotate(text)


# ---------------------------------------------------------------------------
# Icon manifest
# ---------------------------------------------------------------------------

_manifest: dict | None = None


def _get_manifest(icons_dir: Path) -> dict:
    global _manifest
    if _manifest is None:
        manifest_path = icons_dir / "manifest.json"
        if manifest_path.exists():
            _manifest = json.loads(manifest_path.read_text())
        else:
            _manifest = {}
    return _manifest


# ---------------------------------------------------------------------------
# Image loading (with LRU cache)
# ---------------------------------------------------------------------------

_ICON_TOKEN_RE = re.compile(r"<\|icon:(.+?)\|>")
_RBXASSET_RE = re.compile(r"rbxassetid://(\d+)")
_ROBLOX_ASSET_URL_RE = re.compile(r"https?://(?:www\.)?roblox\.com/asset/\?id=(\d+)", re.IGNORECASE)
_asset_icon_overrides: dict[str, str] | None = None


def _load_asset_icon_overrides(icons_dir: Path) -> dict[str, str]:
    global _asset_icon_overrides
    if _asset_icon_overrides is not None:
        return _asset_icon_overrides

    override_path = os.getenv("PINEVEX_RENDERER_ICON_OVERRIDES")
    candidates = []
    if override_path:
        candidates.append(Path(override_path))
    candidates.append(icons_dir.parent / "cache" / "icon_overrides.json")

    for path in candidates:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict):
            _asset_icon_overrides = {
                str(k): str(v)
                for k, v in raw.items()
                if str(k).strip() and str(v).strip()
            }
            return _asset_icon_overrides

    _asset_icon_overrides = {}
    return _asset_icon_overrides


def _asset_cache_dir(icons_dir: Path) -> Path:
    override = os.getenv("ICON_CACHE_DIR")
    if override:
        return Path(override)
    return icons_dir.parent / "cache" / "icons"


def _extract_asset_id(value: str) -> str | None:
    """Extract numeric Roblox asset ID from supported image reference formats."""
    m = _RBXASSET_RE.search(value)
    if m:
        return m.group(1)
    m = _ROBLOX_ASSET_URL_RE.search(value)
    if m:
        return m.group(1)
    return None


def _asset_cache_image(aid: str, icons_dir: Path) -> skia.Image | None:
    cache_path = _asset_cache_dir(icons_dir) / f"{aid}.png"
    if cache_path.exists():
        return _load_image_cached(str(cache_path))
    return None


@lru_cache(maxsize=256)
def _load_image_cached(path: str) -> skia.Image | None:
    try:
        return skia.Image.open(path)
    except Exception:
        return None


def load_icon(icon_key: str, icons_dir: Path) -> skia.Image | None:
    """Load an icon image from the icon library by its key.

    The key may be token-wrapped as ``<|icon:KEY|>``; the inner KEY is
    extracted automatically.
    """
    # Unwrap token if present
    m = _ICON_TOKEN_RE.search(icon_key)
    if m:
        icon_key = m.group(1)

    # Handle rbxassetid:// and roblox.com/asset/?id= references → cache/icons/
    aid = _extract_asset_id(icon_key)
    if aid:
        override_icon_key = _load_asset_icon_overrides(icons_dir).get(aid)
        if override_icon_key:
            icon_key = override_icon_key
        else:
            icon_key = aid

    # Check if it looks like a numeric Roblox asset id
    if icon_key.isdigit():
        return _asset_cache_image(icon_key, icons_dir)

    manifest = _get_manifest(icons_dir)
    normalized = icon_key.replace("\\", "/")
    candidate_keys = [icon_key, normalized]
    if normalized.lower().endswith(".png"):
        candidate_keys.append(normalized[:-4])
    else:
        candidate_keys.append(f"{normalized}.png")

    seen = set()
    for candidate in candidate_keys:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        entry = manifest.get(candidate)
        if entry is None:
            continue
        file_rel = entry.get("file")
        if file_rel:
            icon_path = icons_dir / "png" / file_rel
            if icon_path.exists():
                return _load_image_cached(str(icon_path))

        image_id = entry.get("imageId")
        if isinstance(image_id, str):
            aid = _extract_asset_id(image_id)
            if aid:
                cached = _asset_cache_image(aid, icons_dir)
                if cached is not None:
                    return cached
    return None


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _draw_image_with_gradient(
    canvas: skia.Canvas, image: skia.Image, src_rect: skia.Rect, dst: skia.Rect,
    alpha: int, gradient: dict, tint: list | None, transparency: float,
) -> None:
    """Draw image tinted by a gradient using saveLayer + kModulate compositing."""
    base_color = (int(tint[0]), int(tint[1]), int(tint[2])) if tint and len(tint) >= 3 else (255, 255, 255)
    shader = make_gradient_shader(
        gradient, float(dst.x()), float(dst.y()), float(dst.width()), float(dst.height()),
        base_color=base_color, base_transparency=transparency,
    )
    if not shader:
        return

    # Save a layer covering the destination rect
    _annotate(canvas, "Image gradient layer")
    canvas.saveLayer(dst)

    # Draw image at full opacity (no tint color filter — gradient handles it)
    img_paint = skia.Paint(AntiAlias=True)
    _annotate(canvas, "Image draw (gradient)")
    canvas.drawImageRect(image, src_rect, dst, skia.SamplingOptions(), img_paint)

    # Draw gradient rect with kModulate blend to tint the image
    grad_paint = skia.Paint(AntiAlias=True)
    grad_paint.setShader(shader)
    grad_paint.setBlendMode(skia.BlendMode.kModulate)
    _annotate(canvas, "Image gradient modulate")
    canvas.drawRect(dst, grad_paint)

    canvas.restore()


def draw_image(
    canvas: skia.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    node: dict,
    image: skia.Image | None,
    gradient: dict | None = None,
) -> None:
    """Draw an image within the element rect, respecting scaleType and tint."""
    if image is None or w <= 0 or h <= 0:
        return

    # Accept legacy aliases used by older outputs/models.
    scale_type_raw = node.get("scaleType", node.get("imageType", "Stretch"))
    if isinstance(scale_type_raw, str) and scale_type_raw.startswith("Enum."):
        scale_type = scale_type_raw.split(".")[-1]
    else:
        scale_type = str(scale_type_raw or "Stretch")
    tint: list | None = node.get("imageColor")
    transparency: float = node.get("imageTransparency", 0)

    alpha = max(0, min(255, round((1 - transparency) * 255)))
    if alpha == 0:
        return

    # Clip image to UICorner shape so it doesn't paint over rounded corners
    corner_r = resolve_corner(node, w, h)
    clipped_corner = False
    if corner_r > 0:
        canvas.save()
        clip_rect = skia.Rect.MakeXYWH(x, y, w, h)
        canvas.clipRRect(skia.RRect.MakeRectXY(clip_rect, corner_r, corner_r))
        clipped_corner = True

    paint = skia.Paint(AntiAlias=True)
    paint.setAlpha(alpha)

    if not gradient and tint and len(tint) >= 3:
        cf = skia.ColorFilters.Blend(
            skia.Color(int(tint[0]), int(tint[1]), int(tint[2]), 255),
            skia.BlendMode.kModulate,
        )
        paint.setColorFilter(cf)

    iw = image.width()
    ih = image.height()
    if iw <= 0 or ih <= 0:
        return

    src_x0 = 0.0
    src_y0 = 0.0
    src_w = float(iw)
    src_h = float(ih)

    def _to_float(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _parse_slice_center(raw_value):
        """Parse SliceCenter in list or Rect-like dict form."""
        if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 4:
            return [
                _to_float(raw_value[0], 0.0),
                _to_float(raw_value[1], 0.0),
                _to_float(raw_value[2], float(src_w)),
                _to_float(raw_value[3], float(src_h)),
            ]
        if isinstance(raw_value, dict):
            s_min = raw_value.get("min", raw_value.get("Min", {}))
            s_max = raw_value.get("max", raw_value.get("Max", {}))
            if isinstance(s_min, dict) and isinstance(s_max, dict):
                return [
                    _to_float(s_min.get("x", s_min.get("X", 0.0)), 0.0),
                    _to_float(s_min.get("y", s_min.get("Y", 0.0)), 0.0),
                    _to_float(s_max.get("x", s_max.get("X", float(src_w))), float(src_w)),
                    _to_float(s_max.get("y", s_max.get("Y", float(src_h))), float(src_h)),
                ]
        return None

    image_rect_size = node.get("imageRectSize")
    if isinstance(image_rect_size, (list, tuple)) and len(image_rect_size) >= 2:
        rect_w = _to_float(image_rect_size[0], 0.0)
        rect_h = _to_float(image_rect_size[1], 0.0)
        if rect_w > 0 and rect_h > 0:
            image_rect_offset = node.get("imageRectOffset")
            off_x = 0.0
            off_y = 0.0
            if isinstance(image_rect_offset, (list, tuple)) and len(image_rect_offset) >= 2:
                off_x = _to_float(image_rect_offset[0], 0.0)
                off_y = _to_float(image_rect_offset[1], 0.0)

            # Snapshot compatibility:
            # Some cached Roblox thumbnails are downscaled from authored sprite
            # sheets (e.g. 1020px -> 420px), while ImageRect* stays authored.
            # imageRectSheet carries the authored grid dimensions so we can map
            # authored ImageRect coordinates into sampled thumbnail space.
            image_rect_sheet = node.get("imageRectSheet")
            if isinstance(image_rect_sheet, (list, tuple)) and len(image_rect_sheet) >= 2:
                sheet_x = _to_float(image_rect_sheet[0], 1.0)
                sheet_y = _to_float(image_rect_sheet[1], 1.0)
                if sheet_x > 1.0 and sheet_y > 1.0:
                    authored_w = rect_w * sheet_x
                    authored_h = rect_h * sheet_y
                    if authored_w > float(iw) + 1.0 or authored_h > float(ih) + 1.0:
                        sx = float(iw) / authored_w if authored_w > 0 else 1.0
                        sy = float(ih) / authored_h if authored_h > 0 else 1.0
                        rect_w *= sx
                        rect_h *= sy
                        off_x *= sx
                        off_y *= sy

            left = max(0.0, min(float(iw), off_x))
            top = max(0.0, min(float(ih), off_y))
            right = max(0.0, min(float(iw), off_x + rect_w))
            bottom = max(0.0, min(float(ih), off_y + rect_h))
            if right > left and bottom > top:
                src_x0 = left
                src_y0 = top
                src_w = right - left
                src_h = bottom - top

    src_rect = skia.Rect.MakeLTRB(src_x0, src_y0, src_x0 + src_w, src_y0 + src_h)

    def _draw_or_gradient(dst: skia.Rect, clip: bool = False) -> None:
        if gradient:
            if clip:
                canvas.save()
                canvas.clipRect(skia.Rect.MakeXYWH(x, y, w, h))
            _draw_image_with_gradient(canvas, image, src_rect, dst, alpha, gradient, tint, transparency)
            if clip:
                canvas.restore()
        else:
            if clip:
                canvas.save()
                canvas.clipRect(skia.Rect.MakeXYWH(x, y, w, h))
            canvas.drawImageRect(image, src_rect, dst, skia.SamplingOptions(), paint)
            if clip:
                canvas.restore()

    name = node.get("name") or node.get("type", "?")

    def _infer_slice_reference_dim(
        image_dim: float,
        s_min: float,
        s_max: float,
        *,
        is_rbx_asset: bool,
    ) -> tuple[float, float]:
        """Infer source-space slice reference dimension for Roblox thumbnails.

        Thumbnail images (e.g. 420x420) can be normalized/padded compared to the
        original uploaded image whose pixel space SliceCenter is authored in.
        When slice borders become strongly asymmetric in thumbnail space, infer a
        nominal source dimension using centered-borders assumption:
            source_dim ~= s_min + s_max
        and map source coords into thumbnail sample coords.
        """
        border_ref = float(image_dim)
        sample_scale = 1.0
        if not is_rbx_asset:
            return border_ref, sample_scale
        if s_min <= 0 or s_max <= 0:
            return border_ref, sample_scale

        inferred = float(s_min + s_max)
        if inferred <= 1.0:
            return border_ref, sample_scale

        asym = abs((image_dim - s_max) - s_min)
        asym_threshold = max(2.0, image_dim * 0.15)
        shift_threshold = max(2.0, image_dim * 0.10)
        if asym <= asym_threshold:
            return border_ref, sample_scale
        if abs(inferred - image_dim) <= shift_threshold:
            return border_ref, sample_scale

        border_ref = inferred
        sample_scale = image_dim / inferred
        return border_ref, sample_scale

    if scale_type == "Stretch":
        _annotate(canvas, f"Image stretch: {name}")
        dst = skia.Rect.MakeXYWH(x, y, w, h)
        _draw_or_gradient(dst)

    elif scale_type == "Tile":
        _annotate(canvas, f"Image tile: {name}")
        tile_size = node.get("tileSize")
        if tile_size and len(tile_size) >= 4:
            tw = _to_float(tile_size[0], 0.0) * w + _to_float(tile_size[1], 0.0)
            th = _to_float(tile_size[2], 0.0) * h + _to_float(tile_size[3], 0.0)
        elif tile_size and len(tile_size) >= 2:
            tw = _to_float(tile_size[0], 0.0) * w
            th = _to_float(tile_size[1], 0.0) * h
        else:
            # Roblox default TileSize is UDim2.new(1, 0, 1, 0), which means
            # one tile matches the ImageLabel/ImageButton absolute rect.
            tw = float(w)
            th = float(h)
        if tw <= 0 or th <= 0:
            return
        element_rect = skia.Rect.MakeXYWH(x, y, w, h)
        tile_sampling = skia.SamplingOptions(skia.FilterMode.kNearest, skia.MipmapMode.kNone)
        if gradient:
            # Apply gradient once across the full element, not per-tile.
            # saveLayer → draw all tiles at full opacity → modulate with gradient → restore
            # Gradient shader already incorporates base_transparency, so draw tiles
            # without imageTransparency to avoid double-application.
            canvas.saveLayer(element_rect)
            tile_paint = skia.Paint(AntiAlias=True)
        else:
            canvas.save()
            tile_paint = paint
        canvas.clipRect(element_rect)
        # Pixel snapping helps seams for exact-pixel tiles, but distorts
        # fractional TileSize values (e.g. 0.3 scale). Snap only when near-int.
        snap_tiles = abs(tw - round(tw)) < 1e-3 and abs(th - round(th)) < 1e-3
        ty = y
        while ty < y + h:
            tx = x
            while tx < x + w:
                if snap_tiles:
                    tx_s = round(tx)
                    ty_s = round(ty)
                    dst = skia.Rect.MakeXYWH(
                        tx_s,
                        ty_s,
                        round(tx + tw) - tx_s,
                        round(ty + th) - ty_s,
                    )
                else:
                    dst = skia.Rect.MakeXYWH(tx, ty, tw, th)
                canvas.drawImageRect(image, src_rect, dst, tile_sampling, tile_paint)
                tx += tw
            ty += th
        if gradient:
            base_color = (int(tint[0]), int(tint[1]), int(tint[2])) if tint and len(tint) >= 3 else (255, 255, 255)
            shader = make_gradient_shader(
                gradient, x, y, w, h,
                base_color=base_color, base_transparency=transparency,
            )
            if shader:
                grad_paint = skia.Paint(AntiAlias=True)
                grad_paint.setShader(shader)
                grad_paint.setBlendMode(skia.BlendMode.kModulate)
                canvas.drawRect(element_rect, grad_paint)
        canvas.restore()

    elif scale_type == "Crop":
        _annotate(canvas, f"Image crop: {name}")
        img_aspect = src_w / src_h
        rect_aspect = w / h
        if img_aspect > rect_aspect:
            scale = h / src_h
            scaled_w = src_w * scale
            ox = x + (w - scaled_w) / 2
            dst = skia.Rect.MakeXYWH(ox, y, scaled_w, h)
        else:
            scale = w / src_w
            scaled_h = src_h * scale
            oy = y + (h - scaled_h) / 2
            dst = skia.Rect.MakeXYWH(x, oy, w, scaled_h)
        _draw_or_gradient(dst, clip=True)

    elif scale_type == "Slice":
        _annotate(canvas, f"Image slice: {name}")
        # Support both current key ("sliceCenter") and legacy key ("slice").
        slice_center = _parse_slice_center(node.get("sliceCenter"))
        if slice_center is None:
            slice_center = _parse_slice_center(node.get("slice"))
        if slice_center is None:
            slice_center = [0.0, 0.0, float(src_w), float(src_h)]
        slice_scale = _to_float(node.get("sliceScale", 1.0), 1.0)

        # Source dividers authored in asset pixel space.
        sx1 = _to_float(slice_center[0] if isinstance(slice_center, (list, tuple)) and len(slice_center) > 0 else 0.0, 0.0)
        sy1 = _to_float(slice_center[1] if isinstance(slice_center, (list, tuple)) and len(slice_center) > 1 else 0.0, 0.0)
        sx2 = _to_float(slice_center[2] if isinstance(slice_center, (list, tuple)) and len(slice_center) > 2 else float(src_w), float(src_w))
        sy2 = _to_float(slice_center[3] if isinstance(slice_center, (list, tuple)) and len(slice_center) > 3 else float(src_h), float(src_h))
        if sx2 < sx1:
            sx1, sx2 = sx2, sx1
        if sy2 < sy1:
            sy1, sy2 = sy2, sy1

        icon_key = node.get("icon", "")
        is_rbx_asset = isinstance(icon_key, str) and _extract_asset_id(icon_key) is not None
        border_ref_w, sample_scale_x = _infer_slice_reference_dim(
            float(src_w), sx1, sx2, is_rbx_asset=is_rbx_asset
        )
        border_ref_h, sample_scale_y = _infer_slice_reference_dim(
            float(src_h), sy1, sy2, is_rbx_asset=is_rbx_asset
        )

        # Map authored divider coords into current texture sample space.
        mx1 = max(0.0, min(float(src_w), sx1 * sample_scale_x))
        my1 = max(0.0, min(float(src_h), sy1 * sample_scale_y))
        mx2 = max(0.0, min(float(src_w), sx2 * sample_scale_x))
        my2 = max(0.0, min(float(src_h), sy2 * sample_scale_y))
        if mx2 < mx1:
            mx1, mx2 = mx2, mx1
        if my2 < my1:
            my1, my2 = my2, my1

        degenerate_x = sx2 <= sx1
        degenerate_y = sy2 <= sy1

        # Roblox collapsed-axis slices sample the divider seam with linear filtering.
        # Model this by assigning a tiny source span for the collapsed center patch.
        seam_eps_x = 1e-4
        seam_eps_y = 1e-4
        if degenerate_x:
            seam_x = mx1
            fx1 = max(0.0, seam_x - seam_eps_x)
            fx2 = min(float(src_w), seam_x + seam_eps_x)
            if fx2 <= fx1:
                fx1 = max(0.0, seam_x)
                fx2 = min(float(src_w), fx1 + seam_eps_x)
        else:
            fx1, fx2 = mx1, mx2
        if degenerate_y:
            seam_y = my1
            fy1 = max(0.0, seam_y - seam_eps_y)
            fy2 = min(float(src_h), seam_y + seam_eps_y)
            if fy2 <= fy1:
                fy1 = max(0.0, seam_y)
                fy2 = min(float(src_h), fy1 + seam_eps_y)
        else:
            fy1, fy2 = my1, my2

        # Border thickness comes from authored-space SliceCenter boundaries.
        src_left = max(0.0, sx1)
        src_top = max(0.0, sy1)
        src_right = max(0.0, border_ref_w - sx2)
        src_bottom = max(0.0, border_ref_h - sy2)

        left = src_left * slice_scale
        top = src_top * slice_scale
        right = src_right * slice_scale
        bottom = src_bottom * slice_scale
        # Keep border stroke isotropic under overflow: one fit factor for both axes.
        # Center collapses first when borders overflow either axis.
        border_w = left + right
        border_h = top + bottom
        fit = 1.0
        overflow_x = border_w > w and border_w > 0
        overflow_y = border_h > h and border_h > 0
        if border_w > w and border_w > 0:
            fit = min(fit, w / border_w)
        if border_h > h and border_h > 0:
            fit = min(fit, h / border_h)
        if fit < 1.0:
            left *= fit
            right *= fit
            top *= fit
            bottom *= fit

            # Studio appears to keep borders a touch heavier than pure isotropic
            # fit when overflow is extreme. Nudge a small fraction of remaining
            # center span back into overflowing borders to avoid visible thinning.
            overflow_border_bias = 0.08
            if overflow_x:
                bw = left + right
                if bw > 0 and w > bw:
                    bleed = (w - bw) * overflow_border_bias
                    left += bleed * (left / bw)
                    right += bleed * (right / bw)
            if overflow_y:
                bh = top + bottom
                if bh > 0 and h > bh:
                    bleed = (h - bh) * overflow_border_bias
                    top += bleed * (top / bh)
                    bottom += bleed * (bottom / bh)

        center_w = max(0.0, w - left - right)
        center_h = max(0.0, h - top - bottom)

        # Destination dividers
        dx0 = x
        dx1 = x + left
        dx2 = dx1 + center_w
        dx3 = x + w
        dy0 = y
        dy1 = y + top
        dy2 = dy1 + center_h
        dy3 = y + h

        # Pixel-snap destination dividers to avoid sub-pixel seams.
        # Degenerate modes keep float dividers to preserve authored ratios.
        if not (degenerate_x or degenerate_y):
            dx0 = round(dx0); dx1 = round(dx1); dx2 = round(dx2); dx3 = round(dx3)
            dy0 = round(dy0); dy1 = round(dy1); dy2 = round(dy2); dy3 = round(dy3)

        # Source/dest column and row divisions (3x3 grid).
        # For collapsed centers, keep authored border bounds and only expand the
        # center sample span by epsilon around the divider seam.
        if degenerate_x:
            src_cols = [(0.0, mx1), (fx1, fx2), (mx2, float(src_w))]
        else:
            src_cols = [(0.0, mx1), (mx1, mx2), (mx2, float(src_w))]
        if degenerate_y:
            src_rows = [(0.0, my1), (fy1, fy2), (my2, float(src_h))]
        else:
            src_rows = [(0.0, my1), (my1, my2), (my2, float(src_h))]
        dst_cols = [(dx0, dx1), (dx1, dx2), (dx2, dx3)]
        dst_rows = [(dy0, dy1), (dy1, dy2), (dy2, dy3)]

        # Roblox Slice rendering behavior is linear-filtered, including collapsed
        # center seams.
        linear_sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        paint.setAntiAlias(False)

        patches = []
        for row_i in range(3):
            sr_top, sr_bot = src_rows[row_i]
            dr_top, dr_bot = dst_rows[row_i]
            if dr_bot <= dr_top or sr_bot <= sr_top:
                continue
            for col_i in range(3):
                sc_left, sc_right = src_cols[col_i]
                dc_left, dc_right = dst_cols[col_i]
                if dc_right <= dc_left or sc_right <= sc_left:
                    continue
                s = skia.Rect.MakeLTRB(
                    src_x0 + sc_left, src_y0 + sr_top,
                    src_x0 + sc_right, src_y0 + sr_bot,
                )
                d = skia.Rect.MakeLTRB(dc_left, dr_top, dc_right, dr_bot)
                patches.append((s, d))

        if gradient:
            element_rect = skia.Rect.MakeXYWH(x, y, w, h)
            base_color = (int(tint[0]), int(tint[1]), int(tint[2])) if tint and len(tint) >= 3 else (255, 255, 255)
            shader = make_gradient_shader(
                gradient, x, y, w, h,
                base_color=base_color, base_transparency=transparency,
            )
            if shader:
                canvas.saveLayer(element_rect)
                tile_paint = skia.Paint()
                for s, d in patches:
                    canvas.drawImageRect(image, s, d, linear_sampling, tile_paint)
                grad_paint = skia.Paint()
                grad_paint.setShader(shader)
                grad_paint.setBlendMode(skia.BlendMode.kModulate)
                canvas.drawRect(element_rect, grad_paint)
                canvas.restore()
        else:
            for s, d in patches:
                canvas.drawImageRect(image, s, d, linear_sampling, paint)

    elif scale_type == "Fit":
        _annotate(canvas, f"Image fit: {name}")
        img_aspect = src_w / src_h
        rect_aspect = w / h
        if img_aspect > rect_aspect:
            fit_w = w
            fit_h = w / img_aspect
        else:
            fit_h = h
            fit_w = h * img_aspect
        fx = x + (w - fit_w) / 2
        fy = y + (h - fit_h) / 2
        dst = skia.Rect.MakeXYWH(fx, fy, fit_w, fit_h)
        _draw_or_gradient(dst)

    else:
        dst = skia.Rect.MakeXYWH(x, y, w, h)
        _draw_or_gradient(dst)

    if clipped_corner:
        canvas.restore()
