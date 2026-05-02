from .text_fit import *

@dataclass(frozen=True)
class _RichStroke:
    color: tuple[int, int, int]
    thickness: float
    transparency: float
    joins: str = "round"
    sizing: str = "fixed"


@dataclass(frozen=True)
class _RichMark:
    color: tuple[int, int, int]
    transparency: float


@dataclass(frozen=True)
class _RichStyle:
    font_raw: str
    font_weight: int
    bold: bool
    italic: bool
    underline: bool
    strikethrough: bool
    text_size: float
    color: tuple[int, int, int]
    transparency: float
    stroke: _RichStroke | None
    mark: _RichMark | None
    case_mode: str  # none|uppercase|smallcaps


@dataclass(frozen=True)
class _RichRun:
    text: str
    style: _RichStyle
    hard_break: bool = False


@dataclass
class _RichSegment:
    text: str
    style: _RichStyle
    width: float


@dataclass
class _RichLine:
    segments: list[_RichSegment]
    width: float


def _parse_color(raw: str) -> tuple[int, int, int] | None:
    s = raw.strip()
    if not s:
        return None
    if s.startswith("#") and len(s) == 7:
        try:
            return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
        except ValueError:
            return None
    m = _RGB_RE.fullmatch(s)
    if m:
        return (
            max(0, min(255, int(m.group(1)))),
            max(0, min(255, int(m.group(2)))),
            max(0, min(255, int(m.group(3)))),
        )
    return None


def _parse_float(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except Exception:
        return None


def _parse_tag(raw_tag: str) -> tuple[bool, str, dict[str, str], bool] | None:
    """Parse <...> to (is_close, normalized_name, attrs, self_closing)."""
    if len(raw_tag) < 3 or raw_tag[0] != "<" or raw_tag[-1] != ">":
        return None
    inner = raw_tag[1:-1].strip()
    if not inner:
        return None

    self_closing = False
    if inner.endswith("/"):
        self_closing = True
        inner = inner[:-1].strip()

    is_close = inner.startswith("/")
    if is_close:
        inner = inner[1:].strip()

    if not inner:
        return None

    m = re.match(r"([A-Za-z]+)(.*)", inner)
    if not m:
        return None

    name = m.group(1).lower()
    attrs_raw = m.group(2).strip()
    attrs: dict[str, str] = {}
    for am in _ATTR_RE.finditer(attrs_raw):
        key = am.group(1).lower()
        val = am.group(3) if am.group(3) is not None else am.group(4)
        attrs[key] = val

    # Alias normalization
    if name == "uc":
        name = "uppercase"
    elif name == "sc":
        name = "smallcaps"

    return is_close, name, attrs, self_closing


def _apply_open_tag(style: _RichStyle, tag_name: str, attrs: dict[str, str]) -> _RichStyle:
    if tag_name == "b":
        return replace(style, bold=True)
    if tag_name == "i":
        return replace(style, italic=True)
    if tag_name == "u":
        return replace(style, underline=True)
    if tag_name == "s":
        return replace(style, strikethrough=True)
    if tag_name == "uppercase":
        return replace(style, case_mode="uppercase")
    if tag_name == "smallcaps":
        return replace(style, case_mode="smallcaps")

    if tag_name == "font":
        next_style = style

        color_raw = attrs.get("color")
        if color_raw is not None:
            c = _parse_color(color_raw)
            if c is not None:
                next_style = replace(next_style, color=c)

        size_raw = attrs.get("size")
        if size_raw is not None:
            v = _parse_float(size_raw)
            if v is not None and v > 0:
                next_style = replace(next_style, text_size=v)

        trans_raw = attrs.get("transparency")
        if trans_raw is not None:
            v = _parse_float(trans_raw)
            if v is not None:
                next_style = replace(next_style, transparency=max(0.0, min(1.0, v)))

        weight_raw = attrs.get("weight")
        if weight_raw is not None:
            w = _parse_weight_value(weight_raw)
            if w is not None:
                next_style = replace(next_style, font_weight=w)

        # family has higher precedence than face when both are provided
        family_raw = attrs.get("family")
        if family_raw:
            next_style = replace(next_style, font_raw=family_raw)
        elif attrs.get("face"):
            next_style = replace(next_style, font_raw=attrs["face"])

        return next_style

    if tag_name == "stroke":
        base = style.stroke or _RichStroke(
            color=style.color,
            thickness=1.0,
            transparency=0.0,
            joins="round",
            sizing="fixed",
        )
        color = base.color
        color_raw = attrs.get("color")
        if color_raw is not None:
            c = _parse_color(color_raw)
            if c is not None:
                color = c

        thickness = base.thickness
        thick_raw = attrs.get("thickness", attrs.get("th"))
        if thick_raw is not None:
            v = _parse_float(thick_raw)
            if v is not None and v >= 0:
                thickness = v

        transparency = base.transparency
        trans_raw = attrs.get("transparency", attrs.get("tr"))
        if trans_raw is not None:
            v = _parse_float(trans_raw)
            if v is not None:
                transparency = max(0.0, min(1.0, v))

        joins = attrs.get("joins", base.joins).lower()
        if joins not in _JOIN_MAP:
            joins = "round"

        sizing = attrs.get("sizing", base.sizing).lower()
        if sizing not in ("fixed", "scaled"):
            sizing = "fixed"

        return replace(style, stroke=_RichStroke(color, thickness, transparency, joins, sizing))

    if tag_name == "mark":
        base = style.mark or _RichMark(style.color, 0.0)

        color = base.color
        color_raw = attrs.get("color")
        if color_raw is not None:
            c = _parse_color(color_raw)
            if c is not None:
                color = c

        transparency = base.transparency
        trans_raw = attrs.get("transparency")
        if trans_raw is not None:
            v = _parse_float(trans_raw)
            if v is not None:
                transparency = max(0.0, min(1.0, v))

        return replace(style, mark=_RichMark(color, transparency))

    return style


def _parse_rich_runs(text: str, base_style: _RichStyle) -> list[_RichRun]:
    """Parse Roblox RichText into styled runs and hard line breaks."""
    out: list[_RichRun] = []
    buf: list[str] = []
    current = base_style
    stack: list[tuple[str, _RichStyle]] = []

    def flush_buf() -> None:
        if not buf:
            return
        s = html.unescape("".join(buf))
        buf.clear()
        if s:
            out.append(_RichRun(s, current, hard_break=False))

    i = 0
    n = len(text)
    while i < n:
        if text.startswith("<!--", i):
            flush_buf()
            j = text.find("-->", i + 4)
            if j == -1:
                # Unclosed comment consumes rest of the string.
                break
            i = j + 3
            continue

        ch = text[i]
        if ch != "<":
            buf.append(ch)
            i += 1
            continue

        j = text.find(">", i + 1)
        if j == -1:
            # Unterminated tag => literal remainder
            buf.append(text[i:])
            break

        raw_tag = text[i:j + 1]
        parsed = _parse_tag(raw_tag)
        if not parsed:
            buf.append(raw_tag)
            i = j + 1
            continue

        is_close, name, attrs, self_closing = parsed

        if name == "br" and not is_close:
            flush_buf()
            out.append(_RichRun("", current, hard_break=True))
            i = j + 1
            continue

        supported = {
            "font", "stroke", "mark", "b", "i", "u", "s", "uppercase", "smallcaps"
        }
        if name not in supported:
            # Unknown tags are ignored, inner text still renders.
            i = j + 1
            continue

        flush_buf()
        if is_close:
            match_idx = -1
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    match_idx = k
                    break
            if match_idx >= 0:
                current = stack[match_idx][1]
                del stack[match_idx:]
            i = j + 1
            continue

        prev = current
        current = _apply_open_tag(current, name, attrs)
        stack.append((name, prev))

        if self_closing:
            current = prev
            stack.pop()

        i = j + 1

    flush_buf()
    return out


def _is_plain_rich_runs(runs: list[_RichRun], base_style: _RichStyle) -> bool:
    if not runs:
        return False
    for run in runs:
        if run.hard_break:
            return False
        if run.style != base_style:
            return False
    return True


def _case_pieces(text: str, mode: str) -> list[tuple[str, float]]:
    """Return (text_piece, size_scale) pieces for case transforms."""
    if not text:
        return []

    if mode == "uppercase":
        return [(text.upper(), 1.0)]

    if mode != "smallcaps":
        return [(text, 1.0)]

    pieces: list[tuple[str, float]] = []
    current: list[str] = []
    current_scale: float | None = None

    for ch in text:
        is_small = ch.isalpha() and ch.lower() == ch and ch.upper() != ch
        scale = 0.8 if is_small else 1.0
        out_ch = ch.upper() if is_small else ch

        if current and scale != current_scale:
            pieces.append(("".join(current), current_scale if current_scale is not None else 1.0))
            current = []
        current.append(out_ch)
        current_scale = scale

    if current:
        pieces.append(("".join(current), current_scale if current_scale is not None else 1.0))

    return pieces


class _FontResolver:
    def __init__(self, fonts_dir: Path | None, emoji_typeface: skia.Typeface | None):
        self._fonts_dir = fonts_dir
        self._emoji_typeface = emoji_typeface
        self._fallback_typefaces = _with_emoji_fallback_typefaces(
            _get_fallback_typefaces(fonts_dir), fonts_dir
        )
        self._cache: dict[
            tuple[str, int, bool, float],
            tuple[skia.Font, skia.Font | None, tuple[skia.Font, ...]],
        ] = {}

    def _effective_weight(self, style: _RichStyle) -> int:
        return max(style.font_weight, 700) if style.bold else style.font_weight

    def get(self, style: _RichStyle, size_scale: float = 1.0) -> tuple[skia.Font, skia.Font | None, tuple[skia.Font, ...]]:
        family, _ = _resolve_font(style.font_raw, None)
        weight = self._effective_weight(style)
        size = max(0.1, style.text_size * size_scale)
        key = (family, weight, style.italic, round(size, 4))

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        tf = _load_typeface(family, weight, self._fonts_dir, italic=style.italic)
        main_font = skia.Font(tf, size)
        _apply_font_draw_style(main_font, tf, weight, italic=style.italic)

        emoji_font = None
        if self._emoji_typeface:
            emoji_font = skia.Font(self._emoji_typeface, size)
            _apply_font_draw_style(emoji_font, self._emoji_typeface, weight)

        fallback_fonts = _build_fallback_fonts(self._fallback_typefaces, size)
        self._cache[key] = (main_font, emoji_font, fallback_fonts)
        return main_font, emoji_font, fallback_fonts


def _measure_rich_text(text: str, style: _RichStyle, fonts: _FontResolver) -> float:
    total = 0.0
    for piece_text, scale in _case_pieces(text, style.case_mode):
        main_font, emoji_font, fallback_fonts = fonts.get(style, scale)
        if _contains_rtl(piece_text):
            rtl_w = _measure_rtl_piece_width(piece_text, style, main_font, fallback_fonts)
            if rtl_w is not None:
                total += rtl_w
                continue
        total += _measure_mixed(piece_text, main_font, emoji_font, fallback_fonts)
    return total


def _draw_rich_text_piece(canvas: skia.Canvas, text: str, style: _RichStyle,
                          x: float, baseline_y: float, paint: skia.Paint,
                          fonts: _FontResolver) -> float:
    cursor = x
    for piece_text, scale in _case_pieces(text, style.case_mode):
        main_font, emoji_font, fallback_fonts = fonts.get(style, scale)
        if _contains_rtl(piece_text):
            rtl_w = _draw_rtl_piece(
                canvas, piece_text, style, cursor, baseline_y, paint, main_font, fallback_fonts
            )
            if rtl_w is not None:
                cursor += rtl_w
                continue
        _draw_mixed(canvas, piece_text, cursor, baseline_y, main_font, emoji_font, paint, fallback_fonts)
        cursor += _measure_mixed(piece_text, main_font, emoji_font, fallback_fonts)
    return cursor - x


def _trim_trailing_spaces(line: _RichLine) -> None:
    while line.segments and line.segments[-1].text.isspace():
        seg = line.segments.pop()
        line.width = max(0.0, line.width - seg.width)


def _split_long_token(token: str, style: _RichStyle, max_width: float,
                      fonts: _FontResolver) -> list[str]:
    if max_width <= 0:
        return [token]

    chunks: list[str] = []
    cur = ""
    cur_w = 0.0
    for ch in token:
        ch_w = _measure_rich_text(ch, style, fonts)
        if cur and cur_w + ch_w > max_width:
            chunks.append(cur)
            cur = ch
            cur_w = ch_w
        else:
            cur += ch
            cur_w += ch_w
    if cur:
        chunks.append(cur)
    return chunks


def _layout_rich_lines(runs: list[_RichRun], wrapped: bool, max_width: float,
                       fonts: _FontResolver) -> list[_RichLine]:
    lines: list[_RichLine] = [_RichLine([], 0.0)]

    def new_line() -> None:
        lines.append(_RichLine([], 0.0))

    def add_seg(text: str, style: _RichStyle) -> None:
        if text == "":
            return
        w = _measure_rich_text(text, style, fonts)
        lines[-1].segments.append(_RichSegment(text, style, w))
        lines[-1].width += w

    for run in runs:
        if run.hard_break:
            _trim_trailing_spaces(lines[-1])
            new_line()
            continue

        parts = re.findall(r"\s+|\S+", run.text)
        for part in parts:
            if part == "":
                continue

            is_space = part.isspace()
            if wrapped and is_space:
                # Ignore leading spaces on a new line.
                if not lines[-1].segments:
                    continue
                add_seg(part, run.style)
                continue

            part_w = _measure_rich_text(part, run.style, fonts)
            if wrapped and not is_space and lines[-1].segments and lines[-1].width + part_w > max_width:
                _trim_trailing_spaces(lines[-1])
                new_line()

            if wrapped and not is_space and part_w > max_width:
                chunks = _split_long_token(part, run.style, max_width, fonts)
                for idx, chunk in enumerate(chunks):
                    if idx > 0:
                        _trim_trailing_spaces(lines[-1])
                        new_line()
                    add_seg(chunk, run.style)
                continue

            add_seg(part, run.style)

    for line in lines:
        _trim_trailing_spaces(line)

    return lines if lines else [_RichLine([], 0.0)]


def _line_metrics(line: _RichLine, default_style: _RichStyle,
                  fonts: _FontResolver) -> tuple[float, float, float]:
    if not line.segments:
        main_font, _, _ = fonts.get(default_style, 1.0)
        m = main_font.getMetrics()
        return -m.fAscent, m.fDescent, max(0.0, m.fLeading)

    ascent = 0.0
    descent = 0.0
    leading = 0.0
    for seg in line.segments:
        main_font, _, _ = fonts.get(seg.style, 1.0)
        m = main_font.getMetrics()
        ascent = max(ascent, -m.fAscent)
        descent = max(descent, m.fDescent)
        leading = max(leading, max(0.0, m.fLeading))
    return ascent, descent, leading


def _build_fill_paint(style: _RichStyle, gradient: dict | None,
                      x: float, y: float, w: float, h: float) -> skia.Paint | None:
    alpha = round((1.0 - style.transparency) * 255)
    if alpha <= 0:
        return None

    r, g, b = style.color
    paint = skia.Paint()
    paint.setAntiAlias(True)

    if gradient:
        shader = make_gradient_shader(
            gradient, x, y, w, h,
            base_color=(r, g, b), base_transparency=style.transparency,
        )
        if shader:
            paint.setShader(shader)
        else:
            paint.setColor(skia.Color(r, g, b, alpha))
    else:
        paint.setColor(skia.Color(r, g, b, alpha))

    return paint


def _build_legacy_text_stroke(node: dict) -> tuple[float, skia.Paint] | None:
    """Build legacy TextStroke paint from TextStrokeColor3/TextStrokeTransparency."""
    transparency = float(node.get("textStrokeTransparency", 1.0))
    if transparency >= 1.0:
        return None

    color = node.get("textStrokeColor", [0, 0, 0])
    alpha = round((1.0 - transparency) * 255)
    if alpha <= 0:
        return None

    sp = skia.Paint()
    sp.setAntiAlias(True)
    sp.setStyle(skia.Paint.kStroke_Style)
    # TextStroke in Roblox is effectively a fixed-width outer outline.
    thickness = 1.0
    sp.setStrokeWidth(_stroke_width_from_thickness(thickness))
    sp.setStrokeJoin(skia.Paint.Join.kRound_Join)
    sr, sg, sb = int(color[0]), int(color[1]), int(color[2])
    sp.setColor(skia.Color(sr, sg, sb, alpha))
    return (thickness, sp)


def _build_segment_strokes(style: _RichStyle, node_strokes: list[dict], text_size: float,
                           x: float, y: float, w: float, h: float,
                           gradient: dict | None = None,
                           legacy_text_stroke: tuple[float, skia.Paint] | None = None) -> list[tuple[float, skia.Paint]]:
    strokes: list[tuple[float, skia.Paint]] = []

    # Inline rich stroke
    if style.stroke is not None:
        s = style.stroke
        th = s.thickness * text_size if s.sizing == "scaled" else s.thickness
        if th > 0 and s.transparency < 1:
            sp = skia.Paint()
            sp.setAntiAlias(True)
            sp.setStyle(skia.Paint.kStroke_Style)
            sp.setStrokeWidth(_stroke_width_from_thickness(float(th)))
            sp.setStrokeJoin(_JOIN_MAP.get(s.joins, skia.Paint.Join.kRound_Join))
            sr, sg, sb = s.color
            sa = round((1.0 - s.transparency) * 255)
            sp.setColor(skia.Color(sr, sg, sb, sa))
            strokes.append((th, sp))

    # Node UIStroke (contextual)
    for s in node_strokes:
        if s.get("applyMode") == "Border":
            continue
        th = s.get("thickness", 1)
        if s.get("thicknessScale"):
            th = th * text_size
        trans = s.get("transparency", 0)
        if th <= 0 or trans >= 1:
            continue

        sp = skia.Paint()
        sp.setAntiAlias(True)
        sp.setStyle(skia.Paint.kStroke_Style)
        sp.setStrokeWidth(_stroke_width_from_thickness(float(th)))
        join = str(s.get("lineJoin", "Round")).lower()
        sp.setStrokeJoin(_JOIN_MAP.get(join, skia.Paint.Join.kRound_Join))

        sr, sg, sb = s.get("color", [0, 0, 0])
        sa = round((1.0 - trans) * 255)
        s_grad = s.get("gradient") or gradient
        if s_grad:
            shader = make_gradient_shader(
                s_grad, x, y, w, h,
                base_color=(int(sr), int(sg), int(sb)),
                base_transparency=trans,
            )
            if shader:
                sp.setShader(shader)
            else:
                sp.setColor(skia.Color(int(sr), int(sg), int(sb), sa))
        else:
            sp.setColor(skia.Color(int(sr), int(sg), int(sb), sa))

        strokes.append((float(th), sp))

    if legacy_text_stroke is not None:
        strokes.append(legacy_text_stroke)

    strokes.sort(key=lambda t: t[0], reverse=True)
    return strokes


def _fit_rich_scale(runs: list[_RichRun], wrapped: bool, max_w: float, max_h: float,
                    default_style: _RichStyle, fonts: _FontResolver,
                    line_height_mult: float,
                    min_scale: float = 0.1,
                    max_scale: float | None = None) -> float:
    if max_w <= 0 or max_h <= 0:
        return 1.0

    if max_scale is None:
        max_scale = max(max_h / max(default_style.text_size, 1.0), 12.0)
    lo = max(0.01, min_scale)
    hi = max(lo, max_scale)
    best = lo

    for _ in range(24):
        mid = (lo + hi) / 2.0
        scaled_runs = [
            _RichRun(r.text, replace(r.style, text_size=max(1.0, r.style.text_size * mid)), r.hard_break)
            for r in runs
        ]
        lines = _layout_rich_lines(scaled_runs, wrapped, max_w, fonts)

        asc = 0.0
        des = 0.0
        lead = 0.0
        for line in lines:
            a, d, l = _line_metrics(line, replace(default_style, text_size=max(1.0, default_style.text_size * mid)), fonts)
            asc = max(asc, a)
            des = max(des, d)
            lead = max(lead, l)

        single = asc + des
        step = single * line_height_mult + lead
        total_h = single + step * (len(lines) - 1) if lines else 0.0
        widest = max((line.width for line in lines), default=0.0)

        if widest <= max_w + 0.01 and total_h <= max_h + 0.01:
            best = mid
            lo = mid
        else:
            hi = mid

        if hi - lo < 0.01:
            break

    return best


def _draw_text_rich(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
                    node: dict, fonts_dir: Path | None, gradient: dict | None) -> None:
    text = node.get("text", "")
    if not text:
        return

    base_color_list = node.get("textColor", [0, 0, 0])
    base_color = (int(base_color_list[0]), int(base_color_list[1]), int(base_color_list[2]))

    # Base font and weight resolution
    base_font_raw = str(node.get("font") or "SourceSansPro")
    _, base_weight = _resolve_font(base_font_raw, node.get("fontWeight"))
    base_italic = _is_italic_style(node.get("fontStyle"))
    base_size = float(node.get("textSize", 14.0))
    base_trans = max(0.0, min(1.0, float(node.get("textTransparency", 0.0))))

    base_style = _RichStyle(
        font_raw=base_font_raw,
        font_weight=base_weight,
        bold=False,
        italic=base_italic,
        underline=False,
        strikethrough=False,
        text_size=base_size,
        color=base_color,
        transparency=base_trans,
        stroke=None,
        mark=None,
        case_mode="none",
    )

    runs = _parse_rich_runs(text, base_style)
    if not runs:
        return

    # For nodes that have RichText=true but no rich tags, prefer the plain renderer.
    # It provides tighter Paragraph kerning/fit parity with Studio for non-markup text.
    # Keep PUA-heavy runs on the rich path to preserve custom Robux glyph handling.
    if _is_plain_rich_runs(runs, base_style) and not _has_pua(text):
        plain_node = dict(node)
        plain_node.pop("richText", None)
        # Lazy import avoids split-module circular dependency at import time.
        from .text_renderers import _draw_text_plain
        _draw_text_plain(canvas, x, y, w, h, plain_node, fonts_dir, gradient)
        return

    content_x, content_y, content_w, content_h = _resolve_text_content_rect(node, x, y, w, h)
    if content_w <= 0 or content_h <= 0:
        return

    wrapped = bool(node.get("textWrapped", False))
    line_height_mult = float(node.get("lineHeight", 1.0))
    emoji_typeface = _get_emoji_typeface(fonts_dir)
    fonts = _FontResolver(fonts_dir, emoji_typeface)

    scale_factor = 1.0
    if node.get("textScaled", False):
        min_size, max_size = _textscaled_size_limits(node)
        base_scale_ref = max(1.0, base_style.text_size)
        scale_factor = _fit_rich_scale(
            runs, wrapped, content_w, content_h, base_style, fonts, line_height_mult,
            min_scale=min_size / base_scale_ref,
            max_scale=max_size / base_scale_ref,
        )

    if scale_factor != 1.0:
        runs = [
            _RichRun(r.text, replace(r.style, text_size=max(1.0, r.style.text_size * scale_factor)), r.hard_break)
            for r in runs
        ]
        base_style = replace(base_style, text_size=max(1.0, base_style.text_size * scale_factor))

    lines = _layout_rich_lines(runs, wrapped, content_w, fonts)

    # Global metrics for block alignment (matching existing single-metric behavior)
    block_ascent = 0.0
    block_descent = 0.0
    block_leading = 0.0
    for line in lines:
        a, d, l = _line_metrics(line, base_style, fonts)
        block_ascent = max(block_ascent, a)
        block_descent = max(block_descent, d)
        block_leading = max(block_leading, l)

    single_line_h = block_ascent + block_descent
    line_step = single_line_h * line_height_mult + block_leading
    total_text_h = single_line_h + line_step * (len(lines) - 1) if lines else 0.0

    y_align = node.get("textYAlignment", "Center")
    if y_align == "Top":
        start_y = content_y + block_ascent
    elif y_align == "Bottom":
        start_y = content_y + content_h - total_text_h + block_ascent
    else:
        start_y = content_y + (content_h - total_text_h) / 2 + block_ascent

    x_align = node.get("textXAlignment", "Center")

    node_strokes = node.get("strokes", [])
    legacy_text_stroke = _build_legacy_text_stroke(node)
    # Use the largest potential stroke for clip expansion.
    max_node_stroke = 0.0
    for s in node_strokes:
        if s.get("applyMode") == "Border":
            continue
        th = float(s.get("thickness", 1))
        if s.get("thicknessScale"):
            th *= max(1.0, base_style.text_size)
        max_node_stroke = max(max_node_stroke, th)
    if legacy_text_stroke is not None:
        max_node_stroke = max(max_node_stroke, legacy_text_stroke[0])

    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(
        content_x - max_node_stroke * 2,
        content_y - max_node_stroke * 2,
        content_w + max_node_stroke * 4,
        content_h + max_node_stroke * 4,
    ))

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    for i, line in enumerate(lines):
        baseline_y = start_y + i * line_step
        line_text = "".join(seg.text for seg in line.segments)
        line_is_rtl = _strong_direction(line_text) == "rtl"
        line_grad_x = x
        line_grad_y = y
        line_grad_w = max(1.0, w)
        line_grad_h = max(1.0, h)

        if line_is_rtl:
            if x_align == "Left":
                cursor_x = content_x + line.width
            elif x_align == "Right":
                cursor_x = content_x + content_w
            else:
                cursor_x = content_x + (content_w + line.width) / 2
            segments = list(reversed(line.segments))
        else:
            if x_align == "Left":
                cursor_x = content_x
            elif x_align == "Right":
                cursor_x = content_x + content_w - line.width
            else:
                cursor_x = content_x + (content_w - line.width) / 2
            segments = line.segments

        for seg in segments:
            seg_x = cursor_x - seg.width if line_is_rtl else cursor_x
            main_font, _, _ = fonts.get(seg.style, 1.0)
            m = main_font.getMetrics()
            ascent = -m.fAscent
            descent = m.fDescent
            fill_paint = _build_fill_paint(
                seg.style, gradient, line_grad_x, line_grad_y, line_grad_w, line_grad_h
            )
            if fill_paint is None:
                cursor_x = cursor_x - seg.width if line_is_rtl else cursor_x + seg.width
                continue

            # Mark highlight behind text.
            if seg.style.mark is not None:
                mark = seg.style.mark
                mark_alpha = round((1.0 - mark.transparency) * 255)
                if mark_alpha > 0:
                    pad_top = max(1.0, seg.style.text_size * 0.08)
                    pad_bot = max(0.5, seg.style.text_size * 0.03)
                    mr, mg, mb = mark.color
                    mark_paint = skia.Paint()
                    mark_paint.setAntiAlias(True)
                    mark_paint.setColor(skia.Color(int(mr), int(mg), int(mb), mark_alpha))
                    rect = skia.Rect.MakeXYWH(
                        seg_x,
                        baseline_y - ascent - pad_top,
                        seg.width,
                        ascent + descent + pad_top + pad_bot,
                    )
                    canvas.drawRect(rect, mark_paint)

            stroke_paints = _build_segment_strokes(
                seg.style,
                node_strokes,
                seg.style.text_size,
                line_grad_x,
                line_grad_y,
                line_grad_w,
                line_grad_h,
                gradient=gradient,
                legacy_text_stroke=legacy_text_stroke,
            )
            if stroke_paints:
                max_stroke = max((t for t, _ in stroke_paints), default=0.0)
                stroke_bounds = skia.Rect.MakeXYWH(
                    seg_x - max_stroke * 2,
                    baseline_y - ascent - max_stroke * 2,
                    seg.width + max_stroke * 4,
                    ascent + descent + max_stroke * 4,
                )
                _annotate(canvas, f"Rich text stroke layer: {name}")
                canvas.saveLayer(stroke_bounds)
                for _, sp in stroke_paints:
                    _annotate(canvas, f"Rich text stroke: {name}")
                    _draw_rich_text_piece(canvas, seg.text, seg.style, seg_x, baseline_y, sp, fonts)
                # Roblox icon PUA glyphs keep clearer inner contour lines without knockout clear.
                if not _has_pua(seg.text):
                    clear_paint = skia.Paint()
                    clear_paint.setAntiAlias(True)
                    clear_paint.setBlendMode(skia.BlendMode.kDstOut)
                    _draw_rich_text_piece(canvas, seg.text, seg.style, seg_x, baseline_y, clear_paint, fonts)
                canvas.restore()

            _annotate(canvas, f"Rich text fill: {name}")
            _draw_rich_text_piece(canvas, seg.text, seg.style, seg_x, baseline_y, fill_paint, fonts)

            if seg.style.underline or seg.style.strikethrough:
                dr, dg, db = seg.style.color
                da = round((1.0 - seg.style.transparency) * 255)
                deco_paint = skia.Paint()
                deco_paint.setAntiAlias(True)
                deco_paint.setStyle(skia.Paint.kStroke_Style)
                deco_paint.setStrokeWidth(max(1.0, seg.style.text_size * 0.06))
                deco_paint.setColor(skia.Color(dr, dg, db, da))

                if seg.style.underline:
                    uy = baseline_y + max(1.0, descent * 0.35)
                    canvas.drawLine(seg_x, uy, seg_x + seg.width, uy, deco_paint)
                if seg.style.strikethrough:
                    sy = baseline_y - ascent * 0.45
                    canvas.drawLine(seg_x, sy, seg_x + seg.width, sy, deco_paint)

            cursor_x = cursor_x - seg.width if line_is_rtl else cursor_x + seg.width

    canvas.restore()


# ---------------------------------------------------------------------------
# Existing plain-text renderer (kept for non-rich text)
# ---------------------------------------------------------------------------


__all__ = [name for name in globals() if not name.startswith("__")]
