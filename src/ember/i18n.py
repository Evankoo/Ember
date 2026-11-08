"""Interface language of the open-source edition.

Interface strings are written in Chinese. Chinese is the default and is returned unchanged,
so a Chinese workspace renders exactly as before. The English catalog is registered with
`register()`; the server selects the workspace's language for each request with `use()`.
Server code translates with `t()`; pages rendered by the shared templates and scripts are
translated in the browser by web/i18n.js from the catalog that `script_html()` provides.

    t("收藏项目")                      -> "收藏项目" or the registered English text
    t("{count} 项", count=3)           -> placeholders are filled after translation
    translate("文档库不存在：/x")       -> also matches catalog patterns with {placeholders}
"""
from __future__ import annotations

import contextvars
import json
import re

DEFAULT = "zh"
_CURRENT: contextvars.ContextVar[str] = contextvars.ContextVar("ember_ui_language", default=DEFAULT)
_CATALOGS: dict[str, dict[str, str]] = {}
_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {}
_SCRIPT_PATTERNS: dict[str, list[tuple[str, str]]] = {}
_FIELD = re.compile(r"\{(\w+)\}")
_SCRIPT_SPECIAL = re.compile(r"[.*+?^${}()|[\]\\/]")


def register(language: str, catalog: dict[str, str]) -> None:
    """Add translations for `language`; later entries replace earlier ones with the same source."""
    merged = {**_CATALOGS.get(language, {}), **catalog}
    _CATALOGS[language] = merged
    patterns, scripts = [], []
    for source, target in merged.items():
        if _FIELD.search(source):
            pieces = _FIELD.split(source)
            regex = "".join(re.escape(piece) if index % 2 == 0 else f"(?P<{piece}>.+?)" for index, piece in enumerate(pieces))
            script = "".join(_SCRIPT_SPECIAL.sub(r"\\\g<0>", piece) if index % 2 == 0 else f"(?<{piece}>.+?)" for index, piece in enumerate(pieces))
            literal = len(_FIELD.sub("", source))
            patterns.append((re.compile(regex + r"\Z", re.S), target, literal))
            scripts.append((script, target, literal))
    # More fixed text first, so a specific message wins over a general one.
    _PATTERNS[language] = [(pattern, target) for pattern, target, _ in sorted(patterns, key=lambda item: -item[2])]
    _SCRIPT_PATTERNS[language] = [(script, target) for script, target, _ in sorted(scripts, key=lambda item: -item[2])]


def use(language: str):
    """Select the language for the current context; returns a token for `reset()`."""
    return _CURRENT.set(language if language in _CATALOGS else DEFAULT)


def reset(token) -> None:
    _CURRENT.reset(token)


def language() -> str:
    return _CURRENT.get()


def html_lang() -> str:
    return "en" if language() == "en" else "zh-CN"


def _fill(text: str, values: dict) -> str:
    return _FIELD.sub(lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0), text) if values else text


def t(text: str, **values) -> str:
    catalog = _CATALOGS.get(language())
    return _fill(catalog.get(text, text) if catalog else text, values)


def translate(text: str) -> str:
    """Translate finished text: an exact catalog entry, or a pattern whose placeholders are copied over."""
    catalog = _CATALOGS.get(language())
    if not catalog or not text:
        return text
    if text in catalog:
        return catalog[text]
    for pattern, target in _PATTERNS.get(language(), ()):
        match = pattern.match(text)
        if match:
            return _fill(target, {key: translate(value) for key, value in match.groupdict().items()})
    return text


def catalog_script() -> str:
    """The catalog for web/i18n.js, served as /i18n-catalog.js; empty in the default language."""
    catalog = _CATALOGS.get(language())
    if not catalog:
        return ""
    exact = {source: target for source, target in catalog.items() if not _FIELD.search(source)}
    data = json.dumps({"exact": exact, "patterns": _SCRIPT_PATTERNS[language()]}, ensure_ascii=False)
    return "window.EMBER_TEXT=" + data + ";\n"
