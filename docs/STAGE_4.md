# Stage 4: responsibilities, repeat schedules and in-app reminders

The owner can create encrypted manual tasks without a Vault source and retain
source-linked tasks. Titles and notes remain encrypted with the Vault key. Existing
task details, dates and completion state are preserved by migration 0004.

## Task schedules and responsibilities

- Choose Owner or an active family-person label. Labels can be added in Family
  Vault; they grant no sign-in or document access. Stage 5 enrollment stays disabled.
- Set a confirmed due date, optional daily/weekly/monthly/yearly repetition and a
  reminder lead time of 0-30 days. Repetition requires a due date.
- Completing a repeating task records the scheduled occurrence and advances one
  interval. It does not silently discard missed occurrences or infer payments.
- Month-end anchors survive short months (31 January -> 28 February -> 31 March).
  Yearly leap-day anchors return to 29 February in leap years. Changing the due
  date resets the anchor; editing notes alone preserves it.
- Revision checks prevent duplicate or stale completion requests from advancing
  the schedule twice. Completion history records task revision, scheduled date and
  completion timestamp without copying sensitive titles or notes.

## Reminders

The Tasks page filters overdue, due today, next seven days and undated work. The
Command Center shows reminder counts and up to five tasks within their chosen
lead time. Completed tasks do not appear in reminders. Date-only schedules use
`FAMILYOS_TIME_ZONE` (default Asia/Kolkata); database timestamps remain UTC.

These are in-app reminders shown when FamilyOS is used. No email, push, background
notification or calendar schedule is installed. Existing tasks do not acquire due
dates, repeat schedules or assignments automatically. An old source expiry date
remains separate from the owner's task deadline.

## Deployment and validation

Back up the live SQLite database and Vault objects before applying migrations.
Run `manage.py migrate`. The local deployment compared all seven existing task
IDs, revisions, completion states, due dates and encrypted details before and
after migration and verified that they were unchanged.

108 Django tests, migration drift check, Ruff, separate-process persistence and
encrypted Vault backup/restore checks pass. Coverage includes manual task creation,
assignment validation, missing schedule dates, month-end/leap-year recurrence,
duplicate completion, occurrence history, reminder lead times, completed-task
exclusion, timezone rollover and existing owner/CSRF/encryption protections.
The live reminder page and task form were inspected without adding synthetic
tasks or changing real task schedules.

Stage 4 first increment is delivered. Outbound notification channels and richer
recurrence rules are not implemented. Stage 5 family login/invitation roles remain
disabled until their separate authorization design is implemented and tested.
