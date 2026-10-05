# GStudio Core contributors

Keep this package local, small and readable. Workspaces contain user data; never add a real workspace, secret, account configuration or production system history to this repository.

- Markdown task cards and actual files are canonical. Preserve source evidence and refuse silent overwrite.
- Project ownership, task-line references, presentation importance and task lifecycle are separate.
- Review reports do not authorize merge, split, completion or deletion.
- Keep the server on loopback. Do not add shell execution, executor credentials or remote bridges without an explicit design change.
- Reuse the shared visual tokens and reading hierarchy. Verify populated, empty and error states and narrow layouts.
- Run `python -m unittest discover -s tests -v` after changing storage or HTTP behavior. Verify a built wheel includes the UI, fictional examples and font license before release.
- Keep changes within the requested scope. Do not rewrite unrelated code or data.
