"""The 余烬 · Ember R06 flame "e": one geometry for the brand and the AI action key."""
from __future__ import annotations

import html

EMBER_MARK_PATH = "M68 146H194C197 106 186 68 162 36C154 58 128 68 100 86C76 102 62 124 62 150C62 194 94 222 134 222C160 222 180 212 194 196"


def brand_mark_svg(css: str = "ember-mark", path: str = EMBER_MARK_PATH) -> str:
    """Render a brand mark with currentColor; shared by sidebar and AI action keys."""
    return (
        f'<svg class="{html.escape(css, quote=True)}" viewBox="0 0 256 256" fill="none" aria-hidden="true" focusable="false">'
        f'<path d="{path}" stroke="currentColor" stroke-width="27" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )


def execution_confirm_button(label: str, *, disabled: bool = False, css: str = "") -> str:
    """Render the shared icon-only AI execution confirmation key."""
    classes = f"ember-action-trigger {css}".strip()
    safe = html.escape(label, quote=True)
    return (
        f'<button class="{classes}" type="submit" data-execution-confirm-trigger '
        f'aria-label="{safe}" title="{safe}"{" disabled" if disabled else ""}>'
        f'{brand_mark_svg()}</button>'
    )
