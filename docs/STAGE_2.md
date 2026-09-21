# Stage 2 — Central FamilyOS, first increment

Built on the merged V1.4 Authentication Foundation (`main` at `1eed18a`). This increment makes the Command Center useful with persistent finance records and long-term goals. It is not the entire later-module roadmap or a migration of older prototypes.

## Delivered behavior

- Add/edit assets and liabilities with a name, compatible category, nonnegative INR value, valuation date and optional notes.
- Show active assets, liabilities and net worth (assets minus liabilities), alongside the range of entered valuation dates. No claim of live market/account synchronization.
- Add/edit goals in finance, education, health, lifestyle or other areas. Each has a target date, manual progress, status and notes. 100% progress marks completion; completed status requires 100%. Paused and completed goals do not count as overdue.
- Archive/restore either record type through a confirmation form. Archived finance records leave totals; archived goals leave all dashboard counts. No delete endpoint exists.
- Require current revisions on all edits/archive/restore actions. A stale or already changed record returns 409 without overwriting newer work. Each successful mutation and its audit event commit together.
- Keep existing owner-only protection, server-side persistence, CSRF, escaped output and no-store headers. Record ownership is assigned from authenticated membership, not form fields.

## Money semantics

INR only; no currency conversions. Values are stored as integer paise, not SQLite floating-point decimal columns. Input supports at most two decimals and values from 0 through 9,999,999,999,999.99 rupees. Totals use Python integers and can be negative for net worth. `/api/v1/summary/` returns monetary minor-unit values as strings to avoid JavaScript precision loss. The interface uses Indian digit grouping. Each record's entered date is displayed; no revaluation is implied.

Assets: cash, investment, property, retirement, other. Liabilities: loan, mortgage, credit, other. Both form validation and database constraints enforce this relationship. This is bookkeeping, not financial advice or verification of real balances.

## Routes

- `/finance/`, `/finance/new/`, `/finance/<uuid>/edit/`, `/finance/<uuid>/archive/`, `/finance/<uuid>/restore/`
- `/goals/`, `/goals/new/`, `/goals/<uuid>/edit/`, `/goals/<uuid>/archive/`, `/goals/<uuid>/restore/`
- `/api/v1/summary/` (GET only): INR totals and active/completed/overdue goal counts.

Lists paginate at 20 records. `?archived=1` views archived records; pagination retains that filter. GET of an archive/restore URL only shows confirmation, never mutates. Writes are form-encoded POST with CSRF tokens. Empty state is genuine: no invented balances, pre-enrolled members or real data imported.

## Upgrade and verification

Back up the database with the existing operator command, then `python manage.py migrate`. Migration 0002 creates FinancialRecord and Goal tables without altering V1.4 tables. The persistence smoke script creates a V1.4 database, provisions synthetic data, applies the upgrade and verifies sessions/owner/family records survive. It then verifies finance/goals across processes and through backup/restore.

Stage 2 does not start Gmail/Vault, recurring assignments/reminders, enrollment, cloud hosting, automated market feeds or historical prototype import. The real owner setup and deployment remain separate from the synthetic local preview.
