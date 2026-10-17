# FamilyOS checkpoint — 17 October 2026

## Resume here

Stage 5 design PR #9 and implementation PR #10 are merged into main.
Merged implementation: 7c22f19fad326f76e91ad87d822b04b18d437477.
All 126 Django tests and GitHub security checks passed before merge.

Implemented adult invitation gates, personal task/document pages, explicit
document grants, member/session revocation and self-service password changes.
Children/dependents remain labels. Finance and administration remain owner-only.
Task assignment exposes its title/notes; source evidence and documents need a
separate grant. See STAGE_5.md and STAGE_5_DESIGN.md for details.

## Verified demo

A separate loopback instance on port 8001 uses only synthetic records and its own
database, encryption key and storage. No real family records were copied into it.
Browser demonstration verified adult sign-in, assigned tasks, source details only
for the shared document, opening that document, task completion and the completed
list, and rejection of finance access. Demo fixtures were scanned by ClamAV.
The demo browser was left signed in as the sample adult. It is temporary; check
whether the process and session still exist before resuming.

The live installation remains on port 8000, with enrollment disabled. The prior
live migration preserved existing users, memberships, sessions and task records;
no real adult invitations, memberships or document grants were created.

## Next session

1. Inspect repository status, live launcher/server/worker health and logs before
   making changes. Do not assume the demo or live processes survived overnight.
2. Review Stage 5 activation prerequisites with the owner: public HTTPS origin
   and private TLS SMTP configuration. Real email delivery and public invitation
   acceptance are unverified; keep live enrollment disabled until configured and
   verified. Do not place credentials in Git or checkpoint files.
3. Verify owner-controlled invitation, acceptance, grant/revoke and session
   revocation end-to-end in the intended deployment before onboarding adults.
4. Resume incomplete Gmail synchronization verification: previous runs encountered
   rateLimitExceeded. Inspect current checkpoints/status and allow retry cooldown;
   do not claim full or incremental completion without evidence. Import only
   relevant family document attachments, never all email.
5. Reconcile the development plan against completed Stage 5 work and remaining
   operational prerequisites before selecting the next development increment.

Actual Windows sign-out/reboot startup behavior remains unverified. Scanner
updates were subsequently configured with private writable storage; older notes
in RESUME_2026_10_17.md describing the Program Files update blocker are historical.

The real document task set was last known as six open and one completed, with
no due dates. Inspect current state rather than changing dates or regenerating
duplicates. No reminder automation was requested or created at this checkpoint.
