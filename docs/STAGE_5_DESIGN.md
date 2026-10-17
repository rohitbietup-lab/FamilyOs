# Stage 5 design: controlled family enrollment

Status: proposed design, 17 October 2026. PR #8 is merged and Stage 4's first
increment is available locally. This document does not enable invitations,
provision accounts, send messages or change existing access.

## First release boundary

Start with owner-controlled adult enrollment and a personal task dashboard.
Children and dependents remain labels rather than login accounts in this first
release. Shared financial access, delegated administration and automatic access
to all family documents are not included. Owner transfer remains an operator
procedure; invitations can never create another owner.

### Proposed access matrix

| Resource / action | Owner | Enrolled adult | Child/dependent first release |
| --- | --- | --- | --- |
| Owner settings, invitations, roles, revocation | Manage | Denied | No login |
| Family display name | Read/edit | Read | No login |
| Family mission and private profiles | Read/edit | Denied initially | No login |
| Own profile/password/sessions | Manage own | Manage own | No login |
| Finance records and aggregate totals | Read/edit | Denied | No login |
| Gmail credentials, OAuth, import controls, backup/restore | Owner/operator | Denied | No login |
| Tasks | All; create/edit/assign | Read and complete only explicitly assigned tasks | Labels only |
| Task evidence and source documents | All | Separate document grant required | No login |
| Documents and encrypted metadata | All | Read/download explicitly granted documents | No login |
| Full audit history | Read | Denied | No login |

Being an adult or parent is not a grant to the entire Vault. Task assignment does
not implicitly share its source PDF, filename or evidence excerpt. Until a source
grant exists, the adult task page omits these fields. Owner approval of task
assignment deliberately shares that task's title/notes with its assignee; the UI
must make that consequence clear before saving.

## Invitations and identity

1. Only the active owner may create an adult invitation for this family. Require
   a fresh authenticated owner session and CSRF for issuance, resend and revoke.
2. Use a cryptographically random one-use token. Store only its digest, intended
   normalized email, role, creator, timestamps and state. Proposed lifetime: 48
   hours. Rate-limit issuance and acceptance; maintain generic failure responses.
3. A GET may display the acceptance form but cannot consume the invitation,
   enroll a user or change a password. An email scanner opening the link must not
   accept it. Use no-store, no-referrer and no third-party assets on acceptance.
4. Require proof of the intended email address through the configured delivery
   channel before acceptance. Do not equate a typed email address with proof.
   Enrollment activation is blocked until verified-address delivery is configured
   and tested. No delivery provider is configured by this design.
5. Accept atomically: lock/check the pending token, expiry, role, family and email,
   create or link only the verified identity, consume once, and record an audit
   event. Concurrent/replayed acceptance must not create multiple memberships.
   Existing-account identities must not be silently replaced or taken over.
6. Use existing password validation, hashing, throttling and tracked sessions.
   No default passwords or passwords in invitation URLs, logs, chat or GitHub.
7. The owner explicitly triggers invitation delivery. No email is sent during
   migration or app startup. Production acceptance requires the configured HTTPS
   origin; the current loopback development server is not a remote-family rollout.

These are design defaults, not activated settings. Invitations remain disabled
throughout implementation until the access tests and delivery gate pass.

## Authorization and data model changes

- Introduce shared authorization helpers that check active user, active family
  membership, tracked session and action-specific role/resource grants on every
  request. Replace the owner-only middleware deliberately, preserving owner-only
  checks on sensitive routes. Django staff/superuser must not bypass these rules.
- Generalize tracked sessions without losing existing owner sessions. Revoke all
  sessions when a member is disabled; an already-open tab loses access on its next
  request. Continue idle and absolute expiry, CSRF and login rotation.
- Replace the disabled invitation constraint in an explicit migration with
  pending/accepted/revoked/expired states and the required uniqueness checks.
  Never auto-activate reserved invitation rows during migration.
- Bind an enrolled membership to at most one existing FamilyPerson label after
  owner confirmation. Do not infer this binding from a name match. Labels created
  in Stage 4 remain labels until deliberately linked.
- Add explicit revocable per-document read grants referencing active same-family
  memberships. Query-level filtering covers lists, counts, search, view, download,
  previews and APIs. A grant in one family cannot expose another family's object.
- For adult task access, enforce the confirmed label/membership binding and task
  assignment server-side. Adults cannot edit evidence, dates, recurrence or
  assignment in the first increment. Completion uses current revisions and the
  existing recurrence transaction, without granting visibility to other tasks.
- Task titles, notes and evidence remain encrypted. Grant metadata and invitation
  digests follow private database storage. Audit events record actions/IDs, not
  invitation tokens, email prose, document names, evidence or credentials.

## Implementation order and release gates

1. Authorization core and table-driven permission tests with synthetic accounts;
   preserve the live owner-only behavior and disabled enrollment flag.
2. Membership/label binding, personal task dashboard and revision-safe adult task
   completion; prove no source/evidence leakage without separate grants.
3. Owner-managed document grants and immediate revocation across every route.
4. Expiring one-use invitation lifecycle and verified-address delivery adapter;
   remain disabled while delivery/HTTPS prerequisites are missing.
5. Back up and test migrations/restores against a protected copy, then let the
   owner deliberately enable enrollment and invite a chosen adult.

Required tests include owner regression, anonymous/inactive/expired sessions,
every role/resource combination, guessed object IDs, list/count leakage, forged
family/role/assignee input, cross-family grant attempts, stale task completions,
grant revocation, member removal, invitation expiry/replay/races, mismatched email,
account takeover attempts, token/log sanitization and backup/restore. Role checks
must apply to HTTP APIs and direct view/download routes, not just navigation.

## Existing operational work is separate

The initial Gmail import remains incomplete. Its latest inspected stop was HTTP
403 with allowlisted reason `rateLimitExceeded`, after 42 imports since renewed
consent. The worker checkpoint was queued after a cooldown. Preserve it and the
relevant-document filter; do not restart from an empty mailbox or broaden scopes.
Completion requires a successful full-sync watermark, a subsequent incremental
refresh, and a replay check demonstrating no duplicate content. None is asserted
by this design document. The registered agreement's external download failure
also remains separate from enrollment.

## References

- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html): deny by default and validate permissions on every request.
- [Google Gmail error handling](https://developers.google.com/workspace/gmail/api/guides/handle-errors): bounded backoff and request reduction for rate-limit errors.
- Current application contracts: [OPERATIONS.md](OPERATIONS.md),
  [STAGE_4.md](STAGE_4.md), [GMAIL_RELIABILITY.md](GMAIL_RELIABILITY.md).
