# Document task list

This records the initial document-task foundation. [Stage 4](STAGE_4.md) extends
it with manual tasks, assignment labels, repeating schedules and in-app reminders.

`/tasks/` provides an owner-only task list linked from the main navigation.
Reviewed tasks cite an existing Vault document, an optional page and supporting
evidence. Source dates are displayed separately from user-confirmed task due
dates. No deadline is inferred merely from an old expiry date, historical
statement, guide, admission notice or filename.

Owners can edit titles/notes, set or clear a due date, mark tasks complete and
reopen completed tasks. Completion requires CSRF-protected POST. Edits and status
changes use document-style revisions and reject stale requests. All access uses
the existing tracked owner session and family scope, including the source link.
Unreadable encrypted details fail closed. Completing a task does not alter its
source document.

Task titles, notes and source evidence are encrypted with the existing Vault key.
Source references, page/date fields, due dates and completion state are database
metadata protected by the private instance directory. No new encryption key is
created. The table is included in normal full-database backups; retain the Vault
key and encrypted source objects when restoring.

Apply `manage.py migrate` to create `vault_documenttask`. Local deployment was
backed up with SQLite's consistent backup API before migration and again before
adding the reviewed task list. Private task creation input and source content
are not part of the repository. `create_document_task` uses a stable family/rule
key to avoid duplicating or overwriting previously created, edited or completed
tasks. Archived documents cannot be used to generate new tasks. If an existing
source is later archived, its task continues to link to the preserved source.

This is a reviewed task list, not automatic extraction from every incoming
document. New documents do not silently create obligations. Recurring tasks,
family assignment, notifications, calendar events and payment execution are not
configured by this feature.

Validation: 102 Django tests pass; migration drift check and Ruff pass. New tests
cover owner access, CSRF/method protection, encrypted task details, source/date
provenance, deduplication, edit conflicts, completion/reopen, archived sources and
wrong-key behavior. Live task count, content and evidence links were verified in
the browser after migration.
