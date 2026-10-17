# Stage 5: controlled adult access

The first Stage 5 implementation follows [the design](STAGE_5_DESIGN.md). It adds
adult invitation acceptance, a personal task dashboard, explicit document shares,
owner revocation controls and self-service password changes. Children/dependents
remain labels, not login roles. Finance, goals, audit history, Gmail operations,
family administration and task editing remain owner-only.

## Access boundaries

An active adult must have a confirmed, active same-family FamilyPerson binding.
Assignments grant only task titles/notes and completion of current assigned
occurrences. Source filenames, IDs, evidence excerpts and downloads remain hidden
without a separate active document share. Grants and membership are rechecked in
resource queries, not just navigation. Staff/superuser flags do not bypass roles.

The owner manages access at `/members/`; adults use `/my/`, `/my/tasks/` and
`/my/documents/`. Disabling an adult deletes tracked sessions and revokes document
shares. Grant revocation blocks later list/view/download requests. No revocation
can remove copies a member already downloaded. Assignment labels alone still
grant no sign-in access.

The existing `OwnerSession` table now tracks both accepted roles; its historical
name is preserved to avoid replacing existing sessions. Idle/absolute expiry,
session rotation, CSRF, per-user revocation and password hashing remain in place.
The profile page links to password change; changing a password invalidates other
sessions while preserving the current tracked session.

## Invitation lifecycle

Only an authenticated owner session created within the last 15 minutes can send
an invitation, through an explicit CSRF-protected POST. Issuance is capped at ten
per family per day. The owner chooses a validated email and unlinked family label.
Only the adult role may be accepted; role/family values supplied by a client are
ignored. Existing email identities are refused rather than overwritten or linked
without an additional account-ownership flow.

A 48-hour random one-use token and an eight-digit verification code are delivered
only to the intended email. Only digests are stored. The URL token is in a fragment,
not an HTTP query/path; the acceptance script removes it from browser history and
submits it in the CSRF-protected form body. GET cannot accept an invitation.
The intended email, token and code must match; five failures exhaust acceptance.
Login/acceptance share persistent global and peer attempt throttling. Acceptance
uses a transaction, checks current membership/label state and consumes once.
Resending revokes earlier pending links for the email or label. Delivery failure
revokes the new invitation and returns sanitized operator guidance.

No tokens, codes or email bodies are written to audit events. Acceptance/password
views mark sensitive POST parameters for error-report filtering. Adult accounts
choose their own validated password and sign in separately after acceptance.

## Activation is intentionally separate

The live Windows installation remains owner-only. No accounts were created,
invitations sent, grants added or labels bound during deployment. Activation needs:

| Private environment setting | Required configuration |
| --- | --- |
| `FAMILYOS_FAMILY_ENROLLMENT` | Literal `enabled`, only after operator validation |
| `FAMILYOS_ENV` | Production; development cannot issue/accept invitations |
| `FAMILYOS_PUBLIC_ORIGIN` | Exact public HTTPS origin, hostname in allowed hosts |
| `FAMILYOS_ALLOWED_HOSTS` | Existing explicit deployment allowlist |
| `FAMILYOS_SMTP_HOST` | Verified delivery provider's SMTP host |
| `FAMILYOS_SMTP_PORT` | STARTTLS port, default 587 |
| `FAMILYOS_SMTP_USER` / `FAMILYOS_SMTP_PASSWORD` | Provider credentials stored privately, where required |
| `FAMILYOS_FROM_EMAIL` | Provider-approved sender address |

Delivery is TLS SMTP with a bounded timeout. No provider credentials are supplied
by the repository. Enrollment refuses development mode, HTTP/unapproved origins,
missing delivery configuration and non-SMTP backends. The existing loopback-only
server has not been exposed to the network. HTTPS hosting and a real delivery test
are still needed before enabling remote family use. No real email was sent by
the tests; delivery was mocked.

After setup, restart the service, sign the owner out/in, open Family access, and
deliberately send one chosen invitation. Verify intended-adult acceptance,
permission boundaries and revocation before broader use. Keep the feature disabled
while any prerequisite is missing; the owner workflow and Vault continue working.

## Upgrade, verification and limits

Back up first and run `manage.py migrate` plus `collectstatic --noinput`.
Migrations preserve existing disabled invitation rows, owner membership, session
identifiers and document-task data. Database constraints reject active invitations
without an adult identity, source label, token digest and expiry, and pending
invitations without a verification digest. The local deployment compared users,
memberships, sessions and all task state before/after and found them unchanged.

126 tests pass. The 18 new tests cover the owner/adult role matrix, hidden task
evidence, explicit shares and revocation, assigned completion and stale revisions,
disabled gates/labels, expiry, replay, verification failures, weak passwords,
existing-account takeover prevention, CSRF, forged roles/families, resend, recent
owner sessions, delivery failure and self-service password change. Ruff and
Bandit (medium/high threshold) pass. Historical-schema upgrade/session persistence
and encrypted Vault backup/restore smoke checks pass. The upgrade smoke script now
seeds V1.4 through historical migration models rather than querying new columns
before their migrations exist. CI scans both core and Vault security code.

Live owner access management was inspected with activation disabled. Real SMTP
delivery, external HTTPS acceptance and a real adult rollout are not verified.
The first release refuses existing-account invitation linking and supports adult
accounts only; child/dependent enrollment and finance sharing remain future work.
Gmail initial-import completion remains a separate open operational check.
