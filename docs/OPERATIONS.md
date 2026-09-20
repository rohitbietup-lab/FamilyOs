# Authentication and persistent data operations

## Access boundaries

Every application route except login/static assets requires an authenticated active User, active owner Membership and tracked unexpired session. Staff/superuser status does not bypass this. Anonymous pages redirect to login; APIs return 401. The database enforces one Family and one owner membership. Future roles have no access in this release.

There is no public setup, signup, admin UI, invitation issuance or acceptance path. Bootstrap is an operator command. Password recovery requires local operator access: `python manage.py changepassword owner@example.com` prompts privately and invalidates old authenticated sessions on their next request. Never put credentials into chat, command arguments or source control.

Login rotates the session identifier. Cookies are HttpOnly, SameSite=Lax and Secure in production. Session contents live in SQLite. Revocation URLs use unrelated UUIDs; session keys are never rendered or returned by APIs. Sessions expire after 30 minutes idle or 12 hours absolute. Logout/revocation deletes server-side sessions; disabling the owner membership removes access on the next request.

All writes require Django CSRF validation. Login redirects only to the dashboard. Family writes require the last-read `revision`; stale edits return 409. Mutable fields are whitelisted. Identity, family ID and role come from the session, never request payloads. Rendered text is escaped.

Persistent login throttling reserves attempts before password verification: 10 per peer and 50 globally per 15 minutes. Successful logins also count. Global limiting bounds distributed guesses but can temporarily lock out the owner under attack. Add edge throttling for Internet hosting. `REMOTE_ADDR`, not arbitrary forwarded headers, identifies peers; a proxy shares that peer budget unless carefully configured. Buckets expire without user-facing reset endpoints.

AuditEvent stores action, actor/family IDs and timestamps, not passwords, session credentials or copied form values. Failed login records are unattributed. The API exposes the latest 100 family events. No API modifies audit records; database operators still can. This is an audit foundation, not tamper-proof archival storage.

## Persistent storage

SQLite supports this small single-server foundation on durable local disk. Do not use ephemeral serverless storage, network shares or separate databases across multiple hosts. Keep the same data directory and secret across restarts. `FAMILYOS_DATA_DIR` should be outside the checkout for deployment, accessible only to the service account through Windows ACLs / Unix permissions. Databases/backups are not application-encrypted: use private encrypted disks/backups. PostgreSQL and managed cloud synchronization are not configured.

Migrations are under `core/migrations`; apply with `python manage.py migrate`. Back up before changes to an existing deployment. Test upgrades/restores against a protected copy before touching live data. Do not roll code back against a newer schema without a tested recovery path.

### Backup and recovery

`python manage.py backup_database <absolute-destination-outside-repository>` uses SQLite's consistent backup API and verifies integrity. It refuses existing files. Backups contain password hashes and sessions: keep them private, encrypted and out of GitHub.

To recover: stop all workers, preserve the failed database, restore a verified backup as `familyos.sqlite3` in the configured data directory, then run migrations. Before restarting, invalidate restored sessions inside `python manage.py shell`:

```python
from django.contrib.sessions.models import Session
from core.models import OwnerSession
Session.objects.all().delete()
OwnerSession.objects.all().delete()
```

Start the server and verify owner sign-in and expected records. `scripts/verify_persistence.py` tests separate-process persistence and backup/restore with synthetic data. Schedule `python manage.py prune_sessions` daily through the deployment scheduler; this removes expired sessions/throttles and retains audit history. No schedule is installed automatically.

## Production configuration (not deployed by this branch)

| Variable | Value |
| --- | --- |
| `FAMILYOS_ENV` | `production` or unset; only literal `development` relaxes HTTPS controls |
| `FAMILYOS_SECRET_KEY` | Privately stored random secret, at least 50 characters |
| `FAMILYOS_ALLOWED_HOSTS` | Explicit comma-separated hostnames; no wildcard |
| `FAMILYOS_DATA_DIR` | Private durable directory outside checkout |
| `FAMILYOS_CSRF_TRUSTED_ORIGINS` | Optional explicit HTTPS origins, only if topology requires them |

Startup fails without production secret/hosts. DEBUG is always false. HTTPS redirect, secure cookies, HSTS, frame denial, restrictive CSP and private response no-store are enabled. HSTS includes subdomains, so use a domain whose subdomains all support HTTPS.

Run `python manage.py migrate`, `python manage.py collectstatic --noinput`, and `python manage.py check --deploy --fail-level WARNING`. WhiteNoise serves collected static CSS without exposing source or data directories.

For a trusted loopback TLS proxy, a Windows-compatible backend command is:

```text
waitress-serve --listen=127.0.0.1:8000 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto config.wsgi:application
```

The proxy must terminate HTTPS, overwrite X-Forwarded-Proto with the real scheme, forward an approved Host, and be the sole route to the loopback backend. Waitress validates proxy headers and sets the WSGI scheme; Django does not trust arbitrary forwarded headers itself. Never expose this backend or trust `*` as a proxy. Configure proxy request size/time limits and edge rate limiting. Deployment, DNS/TLS and real owner provisioning remain operator work. The older hosted FamilyOS site is unchanged.

## API contract

| Route | Methods | Result |
| --- | --- | --- |
| `/api/v1/me/` | GET | Current owner ID, email, display name, role |
| `/api/v1/family/` | GET, POST | Read family; form-encoded name/mission/revision update with CSRF |
| `/api/v1/audit/` | GET | Latest 100 family audit events |
| `/api/v1/invitations/` | GET, POST | Always 403 for owner; enrollment disabled |

Forms contain CSRF tokens. No bearer tokens or cross-origin access. Unsupported methods return 405, invalid fields 400, stale revisions 409. All private APIs use the same session as pages. Anonymous mutations may get CSRF 403 before auth is evaluated.

## References and limits

Built on [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/), [sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/) and the [deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/). MFA, email recovery, managed hosting, old data migration, Gmail and Vault are outside this release. Review deployment before storing real family data.
