# V1.4 validation record

## Stage 2 increment — 21 September 2026

- 50 automated tests pass locally on Windows/Python 3.10.5: the 31 V1.4 checks plus 19 central-data tests for exact money arithmetic, invalid input, owner protection, CSRF, stale revisions, archive/restore, goal status, audit rollback, pagination and escaped output.
- The updated persistence script creates V1.4 tables/data, applies migration 0002, and verifies owner/family/session preservation, finance/goal persistence in new processes, database integrity and backup/restore.
- Migration drift and production deployment checks pass. Dependencies are unchanged.
- Browser verification with synthetic data: create finance record → archive → restore with recalculated totals; create goal → dashboard displays its progress. The narrow-screen dashboard was visually inspected.
- No real family records, production deployment, Gmail/Vault or member enrollment were used. GitHub CI for this new commit is checked after publication; the results above describe local verification.

## V1.4 baseline — 20 September 2026

Validated locally on 20 September 2026 with Windows and Python 3.10.5, Django 5.2.17.

- 31 automated tests pass, including owner-only permissions, inactive users/memberships, CSRF and origin rejection, session rotation/replay/expiry/revocation, password-change invalidation, rate limits, stale-edit conflicts, escaped output, credential-free audit responses, bootstrap rules, database constraints, backup-path protection, pruning and transactional rollback.
- Fresh database migrations succeed; `makemigrations --check --dry-run` reports no drift.
- Separate-process smoke test confirms persisted owner profile, family details, session and audit data. Consistent SQLite backup, integrity check and restore pass. A Windows file-handle cleanup failure found during validation was fixed by explicitly closing SQLite connections.
- `check --deploy --fail-level WARNING` passes with production environment settings.
- `pip check` passes.
- Browser check with an isolated synthetic account: login → Command Center → edit/save family mission → sessions → sign out all → login. Dashboard layout visually inspected. No actual owner credentials or family data were used.

GitHub Actions is configured for Windows/Linux on Python 3.10/3.12. Its remote outcome must be checked separately after pushing. No production deployment, TLS endpoint, real owner provisioning, old prototype migration, Gmail or Vault integration was performed.
