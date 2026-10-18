#!/usr/bin/env python3
"""Load the human-editable Ember workbench prompt catalog.

The Markdown catalog owns stable prompt wording and button-location metadata.
Python builders provide only validated runtime values such as task IDs, paths,
selected objects, revisions, and user input.
"""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import re
from dataclasses import dataclass
from pathlib import Path

from .ember_system_bridge import PROMPT_BOUNDARY


ROOT = _deployment_root()
CATALOG_PATH = ROOT / "skills" / "ember" / "references" / "workbench-prompt-catalog.md"
PROMPT_TITLE = "## 余烬 · Ember 共享任务提示"
SECTION_HEADINGS = (
    "任务",
    "上下文",
    "输入与真源",
    "授权边界",
    "成功标准",
    "输出",
)
_BLOCK_RE = re.compile(
    r'<!--\s*EMBER_PROMPT\s+id="([a-z0-9-]+)"\s*-->(.*?)'
    r'<!--\s*/EMBER_PROMPT\s*-->',
    re.DOTALL,
)
_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_VARIABLE_RE = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


class PromptCatalogError(RuntimeError):
    """The prompt catalog is missing, malformed, or called incorrectly."""


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    metadata: str
    sections: dict[str, str]

    @property
    def variables(self) -> set[str]:
        return {
            match.group(1)
            for body in self.sections.values()
            for match in _VARIABLE_RE.finditer(body)
        }


def _parse_block(prompt_id: str, block: str) -> PromptTemplate:
    matches = list(_HEADING_RE.finditer(block))
    headings = [match.group(1).strip() for match in matches]
    if headings != list(SECTION_HEADINGS):
        raise PromptCatalogError(
            f"{prompt_id} 的栏目顺序必须是：{'、'.join(SECTION_HEADINGS)}"
        )
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading not in SECTION_HEADINGS:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        sections[heading] = block[match.end():end].strip()
    missing = [heading for heading in SECTION_HEADINGS if heading not in sections]
    if missing:
        raise PromptCatalogError(f"{prompt_id} 缺少栏目：{'、'.join(missing)}")
    metadata_end = matches[0].start() if matches else len(block)
    return PromptTemplate(prompt_id, block[:metadata_end].strip(), sections)


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, PromptTemplate]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptCatalogError(f"无法读取提示词目录：{path}") from exc
    templates: dict[str, PromptTemplate] = {}
    for match in _BLOCK_RE.finditer(text):
        prompt_id = match.group(1)
        if prompt_id in templates:
            raise PromptCatalogError(f"提示词 ID 重复：{prompt_id}")
        templates[prompt_id] = _parse_block(prompt_id, match.group(2))
    if not templates:
        raise PromptCatalogError("提示词目录中没有可用模板。")
    return templates


def render_prompt(prompt_id: str, /, **values: object) -> str:
    templates = load_catalog()
    template = templates.get(prompt_id)
    if not template:
        raise PromptCatalogError(f"未登记的提示词：{prompt_id}")
    expected = template.variables
    provided = set(values)
    missing = sorted(expected - provided)
    extra = sorted(provided - expected)
    if missing:
        raise PromptCatalogError(f"{prompt_id} 缺少变量：{'、'.join(missing)}")
    if extra:
        raise PromptCatalogError(f"{prompt_id} 包含未使用变量：{'、'.join(extra)}")

    rendered: list[str] = [PROMPT_TITLE]
    for heading in SECTION_HEADINGS:
        body = template.sections[heading]
        body = _VARIABLE_RE.sub(lambda match: str(values[match.group(1)]).strip(), body).strip()
        if not body:
            body = "-无"
        if heading == "授权边界":
            body += "\n" + PROMPT_BOUNDARY
        rendered.extend(["", f"### {heading}", "", body])
    prompt = "\n".join(rendered)
    for heading in SECTION_HEADINGS:
        if len(re.findall(rf"^### {re.escape(heading)}\s*$", prompt, re.MULTILINE)) != 1:
            raise PromptCatalogError(f"{prompt_id} 的动态输入重定义了固定栏目：{heading}")
    return prompt


def catalog_inventory(path: Path = CATALOG_PATH) -> dict[str, dict[str, object]]:
    """Return stable metadata for audits without rendering a task prompt."""
    return {
        prompt_id: {
            "metadata": template.metadata,
            "variables": sorted(template.variables),
            "sections": list(template.sections),
        }
        for prompt_id, template in load_catalog(path).items()
    }
