# Ember Workbench Design

Inherits Ember's warm paper reading surface, dark sidebar and light serif headings; uses the shared styles and never creates a separate visual system per page.

- Base colors: paper #f7f6f2, surface #fdfcf9, body text #24231f, secondary text #767169, dividers #dedad1, sidebar #111827, AI action #7a242a.
- Permanent entries: Task desk, Projects, Review, Library, Settings. The workspace lists only registered projects; there is no archive center entry or page.
- The Task desk states the current intent and searches existing work; Projects shows current focus, active tasks and those completed in the last 30 days; a project's details show the description and timeline alongside its tasks, deliverables and inputs.
- Review reads records, selects a scope and forms suggestions and reports; the Library is organized by file.
- Task details read the goal, description, result, optional next steps and log in that order; material references keep their real source.
- Settings shows the saved default software, its type, path and configuration status at the top, with a “Change configuration” entry; for a valid configuration the editor opens on demand, and on first use or when unavailable it opens with an explanation. Drafts, a passed but unsaved path check, a failed save and discarded changes each give their own feedback, and a draft never overwrites the summary of the current environment.
- Local software is chosen from the list the user confirmed; common software can be found read-only or added by hand, and it is never fixed to two particular tools. Buttons on the Settings page share a light paper background and a thin border, with the main action emphasized by its border and weight, and keep hover, keyboard focus and disabled states; private Agent buttons and dependency failure lists are not copied.
- The AI context can always be copied on its own. An explicit “Copy and open” opens only the saved default software; if copying fails nothing is started, and the user is told to paste and send it themselves; no model is called and no task status changes automatically.
- Wide screens read side by side, medium screens move content to full rows, and phones use a reading drawer and a closable navigation; visible controls never overflow horizontally. Dialogs support Tab, Escape and returning focus.

Interaction is trimmed to the public edition's capabilities; data, authorization and lifecycle belong to AGENTS.md and the storage methods.
