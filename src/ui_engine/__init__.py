def render_json(*args, **kwargs):
    from .renderer import render_json as _render_json

    return _render_json(*args, **kwargs)


def capture_steps(*args, **kwargs):
    from .debug_stepper import capture_steps as _capture_steps

    return _capture_steps(*args, **kwargs)


def save_steps(*args, **kwargs):
    from .debug_stepper import save_steps as _save_steps

    return _save_steps(*args, **kwargs)


def get_objects_at_region(*args, **kwargs):
    from .hit_test import get_objects_at_region as _get_objects_at_region

    return _get_objects_at_region(*args, **kwargs)


def get_objects_at_instance(*args, **kwargs):
    from .hit_test import get_objects_at_instance as _get_objects_at_instance

    return _get_objects_at_instance(*args, **kwargs)
