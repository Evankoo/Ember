# Ember contributors

Keep this package local, small and readable. Workspaces contain user data; never add a real workspace, secret, account configuration or production system history to this repository.

- Markdown task cards and actual files are canonical. Preserve source evidence and refuse silent overwrite.
- Project ownership, task-line references, presentation importance and task lifecycle are separate.
- Review reports do not authorize merge, split, completion or deletion.
- Keep the server on loopback. Software launch is limited to the explicitly confirmed saved default: open a local app or a new terminal with a quoted executable path. Never accept request-provided commands, prompt arguments, model credentials or remote bridges.
- Machine software preferences belong only in the user's private Core configuration, never in a workspace or this repository. Discovery and checks are read-only; launches must not submit prompts or mark tasks executed.
- `web/assets/workbench.css` is copied verbatim from the full workbench by `tools/sync_workbench_styles.py`; never hand-edit it. Put Core-only styles in `web/app.css` and reuse the workbench's markup and class names.
- Pages must render the full workbench's markup and class names. `tools/check_workbench_parity.py --source <workbench>` compares every page with the running full workbench; each remaining difference needs an entry with a reason in `docs/workbench-parity.json` (`intentional` or `pending`). After changing `web/` run it with `--write-record`; the tests fail while `docs/workbench-parity-record.json` does not match the shipped UI files.
- Release only after `tools/release_check.py --source <workbench>` passes: tests, stylesheet sync, page parity and a changelog section for the version.
- Reuse the shared visual tokens and reading hierarchy. Verify populated, empty and error states and narrow layouts.
- Run `python -m unittest discover -s tests -v` after changing storage or HTTP behavior. Verify a built wheel includes the UI, fictional examples and font license before release.
- Keep changes within the requested scope. Do not rewrite unrelated code or data.
