"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from .. import gstudio_workbench as runtime

def render_skills(token: str, notice: str = "", error: str = "") -> str:
    return runtime._render_skills_settings(token, notice, error)
