# V1.4 validation record

Validated locally on 20 September 2026 with Windows and Python 3.10.5, Django 5.2.17.

- 31 automated tests pass, including owner-only permissions, inactive users/memberships, CSRF and origin rejection, session rotation/replay/expiry/revocation, password-change invalidation, rate limits, stale-edit conflicts, escaped output, credential-free audit responses, bootstrap rules, database constraints, backup-path protection, pruning and transactional rollback.
- Fresh database migrations succeed; `makemigrations --check --dry-run` reports no drift.
- Separate-process smoke test confirms persisted owner profile, family details, session and audit data. Consistent SQLite backup, integrity check and restore pass. A Windows file-handle cleanup failure found during validation was fixed by explicitly closing SQLite connections.
- `check --deploy --fail-level WARNING` passes with production environment settings.
- `pip check` passes.
- Browser check with an isolated synthetic account: login → Command Center → edit/save family mission → sessions → sign out all → login. Dashboard layout visually inspected. No actual owner credentials or family data were used.

GitHub Actions is configured for Windows/Linux on Python 3.10/3.12. Its remote outcome must be checked separately after pushing. No production deployment, TLS endpoint, real owner provisioning, old prototype migration, Gmail or Vault integration was performed.
