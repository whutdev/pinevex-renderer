import os

from .text_constants import *


def _iter_configured_font_dirs() -> list[Path]:
    raw = os.getenv("PINEVEX_RENDERER_ROBLOX_FONT_DIRS", "")
    dirs: list[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            dirs.append(Path(part))
    return dirs

def _get_emoji_typeface(fonts_dir: Path | None) -> skia.Typeface | None:
    """Load and cache emoji typefaces.

    Primary: Twemoji (Roblox parity for standard Unicode emoji)
    Fallback: RobloxEmoji (for Roblox-specific PUA glyphs)
    """
    global _emoji_typeface, _emoji_fallback_typeface, _emoji_load_attempted
    if _emoji_load_attempted:
        return _emoji_typeface
    _emoji_load_attempted = True

    def _load_first(paths: list[Path]) -> skia.Typeface | None:
        for path in paths:
            if not path.exists():
                continue
            tf = skia.Typeface.MakeFromFile(str(path))
            if tf:
                return tf
        return None

    roblox_fonts = _get_roblox_fonts_by_name()

    twemoji_paths: list[Path] = []
    robloxemoji_paths: list[Path] = []
    if fonts_dir:
        twemoji_paths.extend([
            fonts_dir / "TwemojiMozilla.ttf",
            fonts_dir / "Twemoji.ttf",
        ])
        robloxemoji_paths.append(fonts_dir / "RobloxEmoji.ttf")

    twemoji_roblox = roblox_fonts.get("twemojimozilla.ttf")
    if twemoji_roblox:
        twemoji_paths.append(twemoji_roblox)
    twemoji_alt = roblox_fonts.get("twemoji.ttf")
    if twemoji_alt:
        twemoji_paths.append(twemoji_alt)
    robloxemoji = roblox_fonts.get("robloxemoji.ttf")
    if robloxemoji:
        robloxemoji_paths.append(robloxemoji)

    # Prefer Twemoji for Unicode emoji parity with Roblox.
    _emoji_typeface = _load_first(twemoji_paths)
    if _emoji_typeface is None:
        _emoji_typeface = _load_first(robloxemoji_paths)

    if _emoji_typeface is not None:
        primary_uid = _emoji_typeface.uniqueID()
        pua_tf = _load_first(robloxemoji_paths)
        if pua_tf and pua_tf.uniqueID() != primary_uid:
            _emoji_fallback_typeface = pua_tf
        else:
            alt_twemoji = _load_first(twemoji_paths)
            if alt_twemoji and alt_twemoji.uniqueID() != primary_uid:
                _emoji_fallback_typeface = alt_twemoji

    return _emoji_typeface


def _get_emoji_fallback_typeface(fonts_dir: Path | None) -> skia.Typeface | None:
    _get_emoji_typeface(fonts_dir)
    return _emoji_fallback_typeface


def _with_emoji_fallback_typefaces(
    fallback_typefaces: list[skia.Typeface],
    fonts_dir: Path | None,
) -> list[skia.Typeface]:
    out = list(fallback_typefaces)
    emoji_fallback = _get_emoji_fallback_typeface(fonts_dir)
    if emoji_fallback is None:
        return out
    fb_uid = emoji_fallback.uniqueID()
    if any(tf.uniqueID() == fb_uid for tf in out):
        return out
    out.append(emoji_fallback)
    return out


def _typeface_has_glyph(typeface: skia.Typeface, ch: str = _ARABIC_TEST_CHAR) -> bool:
    font = skia.Font(typeface, 16)
    glyphs = font.textToGlyphs(ch)
    return bool(glyphs and glyphs[0] != 0)


def _iter_roblox_font_candidates() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for root in _iter_configured_font_dirs():
        for name in _FALLBACK_FONT_FILES:
            path = root / name
            key = str(path)
            if path.exists() and key not in seen:
                seen.add(key)
                out.append(path)
    try:
        out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        pass
    return out


def _get_roblox_fonts_by_name() -> dict[str, Path]:
    global _roblox_fonts_load_attempted
    if _roblox_fonts_load_attempted:
        return _roblox_fonts_by_name
    _roblox_fonts_load_attempted = True

    candidates: list[Path] = []
    for root in _iter_configured_font_dirs():
        if not root.exists():
            continue
        candidates.extend(root.glob("*.ttf"))
        candidates.extend(root.glob("*.otf"))

    for path in candidates:
        name = path.name.lower()
        cur = _roblox_fonts_by_name.get(name)
        if cur is None:
            _roblox_fonts_by_name[name] = path
            continue
        try:
            if path.stat().st_mtime > cur.stat().st_mtime:
                _roblox_fonts_by_name[name] = path
        except Exception:
            pass

    return _roblox_fonts_by_name


def _get_fallback_typefaces(fonts_dir: Path | None) -> list[skia.Typeface]:
    global _fallback_load_attempted
    if _fallback_load_attempted:
        return _fallback_typefaces
    _fallback_load_attempted = True

    seen_ids: set[int] = set()
    seen_families: set[str] = set()

    def add_typeface(tf: skia.Typeface | None) -> None:
        if not tf:
            return
        uid = tf.uniqueID()
        if uid in seen_ids:
            return
        family_name = tf.getFamilyName().strip().lower()
        if family_name in seen_families:
            return
        if _typeface_has_glyph(tf):
            seen_ids.add(uid)
            seen_families.add(family_name)
            _fallback_typefaces.append(tf)

    if fonts_dir:
        for filename in _FALLBACK_FONT_FILES:
            path = fonts_dir / filename
            if path.exists():
                add_typeface(skia.Typeface.MakeFromFile(str(path)))

    # Do not ask the host system for fallback fonts in serverless runtimes.
    # On Vercel this triggers Fontconfig lookups, which are noisy and unreliable.
    for path in _iter_roblox_font_candidates():
        add_typeface(skia.Typeface.MakeFromFile(str(path)))

    return _fallback_typefaces


def _contains_rtl(text: str) -> bool:
    for ch in text:
        if unicodedata.bidirectional(ch) in _RTL_BIDI_CLASSES:
            return True
    return False


def _strong_direction(text: str) -> str:
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in _RTL_BIDI_CLASSES:
            return "rtl"
        if bidi in _LTR_BIDI_CLASSES:
            return "ltr"
    return "ltr"


def _has_break_opportunities(text: str) -> bool:
    return any(ch.isspace() for ch in text)


def _resolve_udim_component(val, parent_dim: float) -> float:
    if isinstance(val, dict):
        scale = val.get("scale", val.get("Scale", 0))
        offset = val.get("offset", val.get("Offset", 0))
        return float(scale) * parent_dim + float(offset)
    if val is None:
        return 0.0
    return float(val)


def _resolve_text_content_rect(node: dict, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Apply UIPadding (when present) to the text layout region."""
    padding = node.get("padding")
    if not isinstance(padding, dict) or not padding:
        return x, y, w, h

    top = _resolve_udim_component(padding.get("top"), h)
    bottom = _resolve_udim_component(padding.get("bottom"), h)
    left = _resolve_udim_component(padding.get("left"), w)
    right = _resolve_udim_component(padding.get("right"), w)

    inner_x = x + left
    inner_y = y + top
    inner_w = max(0.0, w - left - right)
    inner_h = max(0.0, h - top - bottom)
    return inner_x, inner_y, inner_w, inner_h


def _textscaled_size_limits(node: dict) -> tuple[float, float]:
    """Return TextScaled size limits, honoring UITextSizeConstraint when present."""
    min_size = _TEXTSCALED_DEFAULT_MIN
    max_size = _TEXTSCALED_DEFAULT_MAX
    tsc = node.get("textSizeConstraint")
    if isinstance(tsc, dict):
        raw_min = tsc.get("min")
        raw_max = tsc.get("max")
        if raw_min is not None:
            min_size = float(raw_min)
        if raw_max is not None:
            max_size = float(raw_max)
    min_size = max(0.1, min_size)
    max_size = max(min_size, max_size)
    return min_size, max_size


def _get_unicode_engine() -> skia.Unicode | None:
    global _unicode_engine, _unicode_load_attempted
    if _unicode_load_attempted:
        return _unicode_engine
    _unicode_load_attempted = True
    try:
        _unicode_engine = skia.Unicode.ICU_Make()
    except Exception:
        _unicode_engine = None
    return _unicode_engine


def _map_text_align(x_align: str):
    if x_align == "Left":
        return skia.textlayout.TextAlign.kLeft
    if x_align == "Right":
        return skia.textlayout.TextAlign.kRight
    return skia.textlayout.TextAlign.kCenter


def _build_paragraph(text: str,
                     font_families: list[str],
                     font_typefaces: list[tuple[str, skia.Typeface]] | None,
                     font_style: skia.FontStyle,
                     text_size: float,
                     paint: skia.Paint,
                     text_align,
                     max_width: float,
                     wrapped: bool):
    if not _TEXTLAYOUT_AVAILABLE:
        return None
    unicode_engine = _get_unicode_engine()
    if unicode_engine is None:
        return None

    collection = skia.textlayout.FontCollection()
    provider = None
    if font_typefaces and hasattr(skia.textlayout, "TypefaceFontProvider"):
        try:
            provider = skia.textlayout.TypefaceFontProvider()
            seen_aliases: set[str] = set()
            for alias, typeface in font_typefaces:
                if not alias or typeface is None or alias in seen_aliases:
                    continue
                provider.registerTypeface(typeface, alias)
                seen_aliases.add(alias)
        except Exception:
            provider = None
    # Use only the explicitly registered/bundled typefaces for paragraph layout.
    # Falling back to the host font manager triggers Fontconfig on Vercel.
    collection.setDefaultFontManager(provider or skia.FontMgr.New_Custom_Empty())

    para_style = skia.textlayout.ParagraphStyle()
    para_style.setTextAlign(text_align)

    text_style = skia.textlayout.TextStyle()
    text_style.setFontFamilies(font_families)
    text_style.setFontStyle(font_style)
    text_style.setFontSize(text_size)
    text_style.setForegroundPaint(paint)
    para_style.setTextStyle(text_style)

    builder = skia.textlayout.ParagraphBuilder.make(para_style, collection, unicode_engine)
    builder.pushStyle(text_style)
    builder.addText(text)
    builder.pop()
    paragraph = builder.Build()

    layout_width = max_width if wrapped else max(max_width, 10000.0)
    paragraph.layout(layout_width)
    return paragraph


def _fit_paragraph_font_size(text: str,
                             font_families: list[str],
                             font_typefaces: list[tuple[str, skia.Typeface]] | None,
                             font_style: skia.FontStyle,
                             max_w: float,
                             max_h: float,
                             wrapped: bool,
                             min_size: float = _TEXTSCALED_DEFAULT_MIN,
                             max_size: float = _TEXTSCALED_DEFAULT_MAX) -> float:
    lo = max(0.1, float(min_size))
    hi = max(lo, float(max_size))
    best = lo
    probe = skia.Paint()
    probe.setColor(skia.ColorWHITE)
    probe.setAntiAlias(True)

    for _ in range(30):
        mid = (lo + hi) / 2
        paragraph = _build_paragraph(
            text=text,
            font_families=font_families,
            font_typefaces=font_typefaces,
            font_style=font_style,
            text_size=mid,
            paint=probe,
            text_align=skia.textlayout.TextAlign.kLeft,
            max_width=max_w,
            wrapped=wrapped,
        )
        if paragraph is None:
            return best

        fits = paragraph.LongestLine <= max_w + 0.01 and paragraph.Height <= max_h + 0.01
        if fits:
            best = mid
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.5:
            break

    return best


def _font_aliases_for_run(
    main_font: skia.Font,
    fallback_fonts: tuple[skia.Font, ...],
) -> tuple[list[str], list[tuple[str, skia.Typeface]]]:
    names: list[str] = []
    aliases: list[tuple[str, skia.Typeface]] = []
    main_tf = main_font.getTypeface()
    if main_tf:
        main_name = main_tf.getFamilyName()
        if main_name:
            alias = f"pvx_{main_tf.uniqueID()}_{main_name}"
            names.append(alias)
            aliases.append((alias, main_tf))
    for ff in fallback_fonts:
        tf = ff.getTypeface()
        if not tf:
            continue
        name = tf.getFamilyName()
        if name:
            alias = f"pvx_{tf.uniqueID()}_{name}"
            names.append(alias)
            aliases.append((alias, tf))
    dedup_names = list(dict.fromkeys(names))
    dedup_aliases: list[tuple[str, skia.Typeface]] = []
    seen: set[str] = set()
    for alias, tf in aliases:
        if alias in seen:
            continue
        seen.add(alias)
        dedup_aliases.append((alias, tf))
    return dedup_names, dedup_aliases


def _measure_rtl_piece_width(text: str, style: "_RichStyle", main_font: skia.Font,
                             fallback_fonts: tuple[skia.Font, ...]) -> float | None:
    families = _font_families_for_run(main_font, fallback_fonts)
    families, typefaces = _font_aliases_for_run(main_font, fallback_fonts)
    if not families:
        return None
    weight = max(style.font_weight, 700) if style.bold else style.font_weight
    slant = skia.FontStyle.Slant.kItalic_Slant if style.italic else skia.FontStyle.Slant.kUpright_Slant
    font_style = skia.FontStyle(weight, 5, slant)
    probe = skia.Paint()
    probe.setColor(skia.ColorWHITE)
    probe.setAntiAlias(True)
    para = _build_paragraph(
        text=text,
        font_families=families,
        font_typefaces=typefaces,
        font_style=font_style,
        text_size=main_font.getSize(),
        paint=probe,
        text_align=skia.textlayout.TextAlign.kLeft,
        max_width=10000.0,
        wrapped=False,
    )
    if para is None:
        return None
    return float(para.LongestLine)


def _draw_rtl_piece(canvas: skia.Canvas, text: str, style: "_RichStyle",
                    x: float, baseline_y: float, paint: skia.Paint,
                    main_font: skia.Font, fallback_fonts: tuple[skia.Font, ...]) -> float | None:
    families, typefaces = _font_aliases_for_run(main_font, fallback_fonts)
    if not families:
        return None
    weight = max(style.font_weight, 700) if style.bold else style.font_weight
    slant = skia.FontStyle.Slant.kItalic_Slant if style.italic else skia.FontStyle.Slant.kUpright_Slant
    font_style = skia.FontStyle(weight, 5, slant)
    para = _build_paragraph(
        text=text,
        font_families=families,
        font_typefaces=typefaces,
        font_style=font_style,
        text_size=main_font.getSize(),
        paint=paint,
        text_align=skia.textlayout.TextAlign.kLeft,
        max_width=10000.0,
        wrapped=False,
    )
    if para is None:
        return None
    top_y = baseline_y - float(para.AlphabeticBaseline)
    para.paint(canvas, x, top_y)
    return float(para.LongestLine)


# Maps Roblox font names to (file stem, skia FontStyle weight constant)
# skia weight constants: 100=Thin, 300=Light, 400=Normal, 500=Medium, 700=Bold, 900=Black
_FONT_MAP: dict[str, tuple[str, int]] = {
    "GothamSSm":       ("Montserrat", 700),  # Deprecated GothamSSm maps closest to Montserrat Bold
    "SourceSansPro":   ("SourceSansPro", 400),
    "Source Sans Pro":  ("SourceSansPro", 400),
    "LegacyArial":     ("Roboto", 400),
    "Arial":           ("Roboto", 400),
    "RobotoMono":      ("Inconsolata", 400),
    "RobotoCondensed": ("Roboto", 400),
    "BuilderSans":     ("Montserrat", 500),
    "FredokaOne":      ("FredokaOne", 400),
}

# Roblox FontWeight enum → skia weight value
_WEIGHT_MAP: dict[str, int] = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
    "ExtraBold": 800,
    "Heavy": 900,
}
_WEIGHT_MAP_CI = {k.lower(): v for k, v in _WEIGHT_MAP.items()}
_SYNTHETIC_ITALIC_SKEW_X = -0.22


def _parse_weight_value(raw: str | None) -> int | None:
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    if s.isdigit():
        v = int(s)
        if 100 <= v <= 900 and v % 100 == 0:
            return v
        return None
    return _WEIGHT_MAP_CI.get(s.lower())


def _is_italic_style(raw: str | None) -> bool:
    if not raw:
        return False
    s = str(raw).strip()
    if not s:
        return False
    if s.startswith("Enum."):
        parts = s.split(".")
        s = parts[-1] if parts else s
    s = s.lower()
    return s in {"italic", "oblique"}


def _needs_synthetic_italic(typeface: skia.Typeface | None, italic: bool) -> bool:
    if not italic or typeface is None:
        return False
    try:
        return typeface.fontStyle().slant() == skia.FontStyle.Slant.kUpright_Slant
    except Exception:
        return False


def _apply_font_draw_style(
    font: skia.Font,
    typeface: skia.Typeface | None,
    requested_weight: int,
    *,
    italic: bool = False,
) -> None:
    font.setEdging(skia.Font.Edging.kAntiAlias)
    if _needs_faux_embolden(typeface, requested_weight):
        font.setEmbolden(True)
    if _needs_synthetic_italic(typeface, italic):
        font.setSkewX(_SYNTHETIC_ITALIC_SKEW_X)


def _resolve_font(raw: str | None, weight_hint: str | None = None) -> tuple[str, int]:
    """Extract font family + weight from a possibly token-wrapped string.

    Returns (file_stem, skia_weight).
    """
    parsed_weight = _parse_weight_value(weight_hint)
    fallback_weight = parsed_weight if parsed_weight is not None else 900

    if not raw:
        return ("Montserrat", fallback_weight)

    m = _TOKEN_RE.search(raw)
    family = m.group(1) if m else raw
    family = str(family).strip()

    if not family:
        return ("Montserrat", fallback_weight)

    family_path = _FONT_FAMILY_PATH_RE.search(family)
    if family_path:
        family = family_path.group(1)

    if family in _FONT_MAP:
        stem, default_weight = _FONT_MAP[family]
    else:
        stem = family
        default_weight = 400

    if parsed_weight is not None:
        weight = parsed_weight
    elif weight_hint and weight_hint in _WEIGHT_MAP:
        weight = _WEIGHT_MAP[weight_hint]
    else:
        weight = default_weight

    return (stem, weight)


_WGHT_TAG = (ord('w') << 24) | (ord('g') << 16) | (ord('h') << 8) | ord('t')


def _font_stem_candidates(family: str, weight: int, italic: bool) -> list[str]:
    """Return filename stem candidates (highest priority first)."""
    stems: list[str] = []

    if family == "FredokaOne":
        stems.append("FredokaOne-Regular")
        if italic:
            stems.append("FredokaOne-Italic")

    # Prefer Roblox's split Montserrat files when available.
    # This better matches Studio than the generic bundled variable TTF.
    if family == "Montserrat":
        if weight >= 850:
            base = "Montserrat-Black"
        elif weight >= 650:
            base = "Montserrat-Bold"
        elif weight >= 450:
            base = "Montserrat-Medium"
        else:
            base = "Montserrat-Regular"
        stems.append(base)
        if italic:
            stems.append(f"{base}Italic")

    # Prefer Roblox's split SourceSansPro files for better weight parity.
    if family == "SourceSansPro":
        if weight >= 650:
            base = "SourceSansPro-Bold"
        elif weight >= 550:
            base = "SourceSansPro-Semibold"
        elif weight <= 300:
            base = "SourceSansPro-Light"
        else:
            base = "SourceSansPro-Regular"
        stems.append(base)
        if italic:
            stems.append("SourceSansPro-It")

    if italic:
        stems.extend([f"{family}-Italic", f"{family}-It"])

    stems.extend([family, f"{family}-Regular"])
    # Deduplicate while preserving order.
    return list(dict.fromkeys(stems))


def _try_load_exact_typeface(
    family: str,
    weight: int,
    fonts_dir: Path | None,
    *,
    italic: bool = False,
) -> skia.Typeface | None:
    """Load an exact family file without any system/default fallback."""
    # Prefer Roblox-installed Ubuntu for parity; bundled Ubuntu.ttf differs in metrics.
    if family == "Ubuntu":
        roblox_fonts = _get_roblox_fonts_by_name()
        fname = "ubuntu-italic.ttf" if italic else "ubuntu-regular.ttf"
        roblox_path = roblox_fonts.get(fname)
        if roblox_path and roblox_path.exists():
            tf = skia.Typeface.MakeFromFile(str(roblox_path))
            if tf:
                return tf

    if family:
        roblox_fonts = _get_roblox_fonts_by_name()
        stems = _font_stem_candidates(family, weight, italic)
        for suffix in (".ttf", ".otf"):
            for stem in stems:
                roblox_path = roblox_fonts.get(f"{stem}{suffix}".lower())
                if not roblox_path or not roblox_path.exists():
                    continue
                tf = skia.Typeface.MakeFromFile(str(roblox_path))
                if tf:
                    return tf

    if fonts_dir and family:
        stems = _font_stem_candidates(family, weight, italic)
        for suffix in (".ttf", ".otf"):
            for stem in stems:
                path = fonts_dir / f"{stem}{suffix}"
                if path.exists():
                    tf = skia.Typeface.MakeFromFile(str(path))
                    if tf:
                        # For variable fonts, set the weight axis when possible.
                        coord = skia.FontArguments.VariationPosition.Coordinate(
                            _WGHT_TAG, float(weight))
                        coords = skia.FontArguments.VariationPosition.Coordinates([coord])
                        position = skia.FontArguments.VariationPosition(coords)
                        params = skia.FontArguments()
                        params.setVariationDesignPosition(position)
                        tf_var = tf.makeClone(params)
                        if tf_var:
                            return tf_var
                        return tf
    return None


def _load_typeface(family: str, weight: int, fonts_dir: Path | None,
                   italic: bool = False) -> skia.Typeface:
    """Load a typeface from fonts_dir with specified weight/slant, or fall back."""
    tf = _try_load_exact_typeface(family, weight, fonts_dir, italic=italic)
    if tf:
        return tf

    # Never fall back to system font resolution here. It causes Fontconfig usage
    # on Vercel and can silently substitute the wrong face. Use bundled defaults.
    tf = _try_load_exact_typeface("Montserrat", weight, fonts_dir, italic=italic)
    if tf:
        return tf
    tf = _try_load_exact_typeface("Montserrat", 400, fonts_dir, italic=False)
    if tf:
        return tf
    tf = _try_load_exact_typeface("SourceSansPro", 400, fonts_dir, italic=False)
    if tf:
        return tf
    # Final hard fallback should still be a bundled file if available.
    if fonts_dir:
        for name in ("Montserrat-Regular.ttf", "SourceSansPro.ttf", "Roboto.ttf"):
            path = fonts_dir / name
            if path.exists():
                tf = skia.Typeface.MakeFromFile(str(path))
                if tf:
                    return tf
    return skia.Typeface.MakeDefault()


def audit_required_font_variants(fonts_dir: Path | None) -> dict[str, list[str]]:
    """Return missing exact font variants that must exist to avoid substitution."""
    required_variants = {
        "FredokaOne": [(400, False)],
        "Montserrat": [(400, False), (500, False), (700, False), (900, False)],
    }
    missing: dict[str, list[str]] = {}
    for family, variants in required_variants.items():
        missing_variants: list[str] = []
        for weight, italic in variants:
            tf = _try_load_exact_typeface(family, weight, fonts_dir, italic=italic)
            if tf is None:
                label = f"{family}-{weight}"
                if italic:
                    label += "-Italic"
                missing_variants.append(label)
        if missing_variants:
            missing[family] = missing_variants
    if fonts_dir is None or not (fonts_dir / "FredokaOne-Regular.ttf").exists():
        missing.setdefault("FredokaOne", []).append("FredokaOne-Regular.ttf (bundled file)")
    return missing


def _needs_faux_embolden(typeface: skia.Typeface | None, requested_weight: int) -> bool:
    """Approximate heavier Roblox weights when only lighter faces are available."""
    if typeface is None:
        return False
    if requested_weight < 700:
        return False
    actual_weight = int(typeface.fontStyle().weight())
    return actual_weight + 200 <= requested_weight


def _should_reinforce_faux_fill(font: skia.Font, paint: skia.Paint) -> bool:
    """Extra fill pass for faux-bold fallback faces to better match Studio heft."""
    if not font.isEmbolden():
        return False
    tf = font.getTypeface()
    if tf is None:
        return False
    if int(tf.fontStyle().weight()) > 500:
        return False
    if paint.getStyle() != skia.Paint.kFill_Style:
        return False
    return paint.getBlendMode() == skia.BlendMode.kSrcOver


def _faux_reinforce_dx(font: skia.Font) -> float:
    return max(0.28, float(font.getSize()) * 0.016)


__all__ = [name for name in globals() if not name.startswith("__")]
