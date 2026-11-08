"""The workspace language, chosen once when the workspace is created.

A workspace is either Chinese or English. The choice is stored as `language` in the system
folder's config/workspace.json and is never changed afterwards; a workspace without the field
is Chinese, which is how every workspace before 0.21.0 was made.

The program keeps the Chinese names as its internal identifiers. `Vocabulary` maps each one to
the name written on disk, so a Chinese workspace is unchanged and an English workspace uses
English folder names, task-card headings and labels throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import i18n

LANGUAGES = ("zh", "en")
DEFAULT = "zh"
NAMES = {"zh": "中文", "en": "English"}


@dataclass(frozen=True)
class Vocabulary:
    language: str
    documents_suffix: str
    inputs: str
    draft: str
    formal: str
    projects: str
    project_card: str
    reports: str
    views: str
    inbox_ledger: str
    task_line_note: str
    task_line_index: str
    # Longest task title and project category, in characters.
    title_limit: int = 20
    category_limit: int = 20
    # Internal (Chinese) heading or label -> name written in this workspace.
    words: dict = field(default_factory=dict)

    def word(self, internal: str) -> str:
        return self.words.get(internal, internal)

    def internal(self, written: str) -> str:
        for key, value in self.words.items():
            if value == written:
                return key
        return written


ZH = Vocabulary(
    language="zh", documents_suffix="文档", inputs="任务资料", draft="交付/草稿", formal="交付/正式交付",
    projects="项目", project_card="项目看板.md", reports="管理中心/整理记录",
    views="管理中心/运行状态/任务视图/workbench-views.json",
    inbox_ledger="管理中心/运行状态/Inbox标签/inbox-labels.json",
    task_line_note="00_任务线说明.md", task_line_index="01_关联任务索引.md",
)

EN = Vocabulary(
    language="en", documents_suffix="Docs", inputs="Inputs", draft="Deliverables/Drafts", formal="Deliverables/Final",
    projects="Projects", project_card="Project.md", reports="Admin/Reviews",
    views="Admin/Runtime/TaskViews/workbench-views.json",
    inbox_ledger="Admin/Runtime/InboxLabels/inbox-labels.json",
    task_line_note="00_Task-line.md", task_line_index="01_Related-tasks.md",
    title_limit=60, category_limit=40,
    words={
        "任务目标": "Goal", "任务描述": "Description", "当前结果": "Current Result", "下一步": "Next Steps",
        "执行日志": "Execution Log", "未分类": "Uncategorized", "处理中": "In progress", "待归档": "To archive",
        "可删除": "Deletable",
        # Project card headings.
        "项目总览": "Project Overview", "当前概况": "Current Overview", "系统总览": "System Overview",
        "工作位置与入口": "Locations and Entry Points", "系统入口": "System Entry Points",
        "范围与要求": "Scope and Requirements", "当前阶段": "Current Stage", "时间线": "Timeline",
    },
)

VOCABULARIES = {"zh": ZH, "en": EN}


def vocabulary(language: str | None) -> Vocabulary:
    return VOCABULARIES.get(language or DEFAULT, ZH)


def checked(value) -> str:
    """A language given on the command line or by the installer; there is no silent default."""
    if value not in LANGUAGES:
        raise ValueError(f"语言必须是 {' 或 '.join(LANGUAGES)}。")
    return value


def text(language: str, message: str, **values) -> str:
    """Workspace text (log lines, generated notes, prompts) in the workspace's language."""
    token = i18n.use(language)
    try:
        return i18n.t(message, **values)
    finally:
        i18n.reset(token)


def finished(language: str, message: str) -> str:
    """Translate an already formatted message, matching catalog patterns."""
    token = i18n.use(language)
    try:
        return i18n.translate(message)
    finally:
        i18n.reset(token)


def _load() -> None:
    from .locales import en
    i18n.register("en", en.CATALOG)


_load()
