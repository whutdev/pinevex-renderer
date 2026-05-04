"""Compatibility shim for UI text rendering.

Implementation now lives in split modules:
- text_constants
- text_fonts
- text_runs
- text_fit
- text_rich
- text_renderers
"""

from .text_renderers import *  # noqa: F401,F403
