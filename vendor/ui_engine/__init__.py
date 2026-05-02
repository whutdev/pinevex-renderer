def render_json(*args, **kwargs):
    from .renderer import render_json as _render_json

    return _render_json(*args, **kwargs)
