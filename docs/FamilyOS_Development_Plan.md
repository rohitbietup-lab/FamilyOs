# FamilyOS staged development plan

## Source and baseline

This version-controlled plan records the staged decisions approved in “Branch · Carry FamilyOS Context” on 20 September 2026. The original generated document was not available in the repository; this is a transcription of the recoverable approved scope, not a claim to reproduce that document verbatim.

Repository inspection: `main` at `6943c23` contained only `README.md` (`# FamilyOs`, `Hello`). No application, dependencies, tests, or prior plan existed on any remote branch. Older local and hosted prototypes are separate work and are not imported, overwritten, or deployed by this release. Their private data must not be committed to this public repository.

## Delivery stages

| Stage | Outcome | Scope |
| --- | --- | --- |
| 0 — GitHub foundation | A canonical, reviewable codebase | Feature branches, plan in docs, reproducible setup, tests and validated commits |
| 1 — Authentication | Owner-only private access | Owner login, secure sessions, protected pages/APIs, User/Family/Membership/Role/Audit models, logout and session revocation; invitations disabled |
| 2 — Central FamilyOS | Persistent shared family data | Server-side records, reliable editing, backup/recovery, later module migration from prototypes |
| 3 — Family Vault | Relevant documents and information | Private storage before read-only Gmail ingestion; no email archive; deduplication and refresh |
| 4 — Tasks and reminders | Daily execution | Responsibilities, recurring tasks, assignment, completion and reminders |
| 5 — Family enrollment | Controlled membership | Invitations, adult/parent/child/dependent permissions, personal dashboards |
| 6 — Family intelligence / V2.0 | Useful connected insights | Source-grounded assistance and integrated planning |

The latest approved sequence supersedes earlier version labels that called V1.4 “Gmail Auto Sync.” **V1.4 now means Authentication Foundation.** Gmail and Vault integration are explicitly deferred.

## V1.4 acceptance criteria

- One owner is provisioned through an operator-only command, without public registration or shipped credentials.
- Only an active owner membership can reach the Command Center or private APIs.
- Passwords are hashed, sessions are server-side, login rotates session identifiers, and state changes require CSRF validation.
- Session idle expiry, absolute expiry, logout, individual revocation and revoke-all work.
- Login attempts are bounded by persistent throttling with generic failure responses.
- Family and profile edits persist on the server; stale family edits cannot overwrite newer ones silently.
- Database migrations define the family/user/membership/role/audit foundation. Invitations remain disabled.
- Tests cover unauthorized access, persistence, validation, revocation, CSRF and deployment settings.
- Code is committed on a feature branch; GitHub contains no credentials, databases, real family records or attachments.

## Implementation decisions for this increment

Django 5.2 LTS supplies authentication, PBKDF2 hashing, session rotation, CSRF and migrations. SQLite is the initial single-server persistent store, on a durable local volume; it is not a cloud synchronization service. A single central deployment can serve multiple devices after HTTPS hosting is configured. The server owns all authoritative records; browser localStorage is not used.

Roles are a validated enum on Membership, with one owner per family. User is Django's built-in user model. No staff/superuser privilege bypasses owner membership. No family members are pre-enrolled. The invitation schema is reserved with a database constraint enforcing disabled status, without tokens or acceptance routes.

Current APIs use form-encoded writes with CSRF tokens. Family writes require a revision for optimistic concurrency control. Audit entries store action, actor and family IDs and timestamps, not form payloads, passwords or session credentials.

Deployment, real owner provisioning, MFA, password-recovery email, managed cloud storage and migration of the older dashboard's data are separate follow-up work. No production release is implied by the feature-branch commit.
