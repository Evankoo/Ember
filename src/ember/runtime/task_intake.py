#!/usr/bin/env python3
"""Executable Ember task-card necessity gate."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import json


def decide(args: argparse.Namespace) -> dict[str, object]:
    reasons: list[str] = []
    if args.has_input:
        reasons.append("external_input")
    if args.independent_deliverable:
        reasons.append("independent_deliverable")
    if args.multi_step:
        reasons.append("multi_step")
    if args.needs_confirmation:
        reasons.append("follow_up_or_confirmation")
    if args.external_mutation:
        reasons.append("external_state_mutation")
    if args.system_change:
        reasons.append("system_change")

    if args.system_change:
        mode = "system_governance"
    elif reasons:
        mode = "standard_task" if (args.independent_deliverable or args.multi_step or args.external_mutation) else "lightweight_task"
    elif args.confirmed_simple_copy:
        mode = "board_only"
    else:
        mode = "chat_only"
    return {
        "mode": mode,
        "task_card_required": mode not in {"chat_only", "board_only"},
        "copy_board_write": mode == "board_only",
        "artifact_mode": (
            "system" if args.system_change
            else "delivery" if args.independent_deliverable
            else "external" if args.external_mutation
            else "none"
        ),
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    for flag in (
        "has_input", "independent_deliverable", "multi_step",
        "needs_confirmation", "external_mutation", "system_change",
        "confirmed_simple_copy",
    ):
        parser.add_argument("--" + flag.replace("_", "-"), action="store_true")
    args = parser.parse_args()
    print(json.dumps(decide(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
