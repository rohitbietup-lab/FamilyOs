# V1.6 Family Vault

This increment implements Stage 3 from the supplied `FamilyOS_Development_Plan_v1.docx`, starting at `e882dd3`. Its product requirements are private document storage, read-only website Gmail authorization, relevant attachment ingestion, deduplication, categories, family-member association, expiry/renewal dates, starred documents and incremental refresh. Earlier roadmap stages and the document's historical immediate-sprint instructions do not reset the repository or enroll real family members.

## Owner experience

Family Vault is available from the main navigation and Command Center. Upload PDF, PNG or JPEG documents up to 10 MiB; files must pass ClamAV and structural/type validation. Password-protected PDFs, active PDF features detected by validation, executables and other types are rejected. Member labels are document associations, not accounts or permissions. No real people or documents are seeded.

Edit title, notes, category, member, expiry/renewal dates and important/starred status. Revisions reject stale edits. Filter by category, starred, archive or renewals/expiries due within 30 days (including overdue). Archive/restore preserves files. All view/download and modification routes require the existing active owner session. Responses are not cached; inline documents use a sandbox CSP. Audit events record action, actor and family, without document content or OAuth credentials.

Objects use random UUID references in a private filesystem object store outside the repository/static root. File content, titles, filenames, notes, source message IDs and Gmail refresh/page tokens use authenticated Fernet encryption. Categories, association IDs, dates, hashes, sizes and operational counters remain searchable database metadata. Existing core data and member labels are not field-encrypted; deploy the database and backups on encrypted volumes with service-account-only access. There is no public media URL. The owner-authenticated application decrypts objects into bounded memory. Upload plaintext never uses Django temporary files.

## Gmail ingestion

The website requests only `gmail.readonly` through Google's web-server OAuth flow with session-bound, one-use database state, a 10-minute expiry and PKCE. Tokens stay server-side and encrypted. The owner selects and consents to the Gmail account. Disconnect erases local credentials and attempts Google revocation, reporting failure with instructions to remove access in Google Account connections. Existing documents remain accessible.

Gmail is never changed: no send, label, archive or delete API is used. No mailbox UI, message bodies, subject archive or inbox index is stored. A conservative keyword classifier checks attachment names and message subjects for the nine roadmap categories. Matching PDF/image attachments are scanned and stored; unmatched attachments remain in Gmail and can be uploaded manually as Other. This rule-based classifier can miss or misclassify documents; the owner can correct categories. It does not claim OCR, automatic date extraction or comprehensive recall. Unsupported, malformed, oversized and malware-positive attachments increment a skipped counter.

Opening the Command Center or Vault queues a CSRF-protected refresh via same-origin JavaScript, throttled to once every five minutes; the visible refresh button also works without JavaScript. A separate supervised `sync_gmail` process consumes the database queue. It processes one provider page at a time, checkpointing only after persistence. Initial import captures a history watermark before listing attachments. Later imports use `history.list` message-added events, and expired history restarts the full import. SHA-256 deduplication covers manual uploads, Gmail replay and archived records. A database lease prevents concurrent workers from processing one connection, and connection generations stop a disconnected/replaced worker from importing further documents.

Provider or scanner outages leave the checkpoint retryable and stored documents available. Error text is generic; upstream responses are not logged. Counters cover committed pages and may undercount new documents if a process crashes after storing a document but before committing its page checkpoint; document content remains deduplicated. OAuth reconnection restarts the import and resets counters. A message deleted before it can be fetched is skipped.

## Operator setup

1. Back up the existing installation, install `requirements.txt`, run `manage.py migrate` and `collectstatic --noinput`. Core migration 0002 is preserved. Vault migrations are additive.
2. Create an external private object directory and set `FAMILYOS_VAULT_ROOT`. Set `FAMILYOS_VAULT_KEY` to an independently generated Fernet key (`Fernet.generate_key()`), kept in secret storage. Never commit, print in shared logs, or discard the key. Losing it makes documents, metadata and backups unreadable. Rotation requires an offline decrypt/re-encrypt migration; simply replacing the key is not rotation.
3. Run ClamAV with current signature updates on a trusted local/private endpoint. Set `FAMILYOS_CLAMD_HOST` and optionally `FAMILYOS_CLAMD_PORT` (default 3310). INSTREAM must allow at least 10 MiB. Restrict network access; the daemon protocol itself is not authenticated or encrypted. Missing/unavailable scanning blocks ingestion; there is no production bypass.
4. Enable the Gmail API in a Google Cloud project and create a **Web application** OAuth client. Configure the consent screen, testing users or required verification. Set `FAMILYOS_GMAIL_CLIENT_ID`, `FAMILYOS_GMAIL_CLIENT_SECRET` and `FAMILYOS_GMAIL_REDIRECT_URI` to the exact registered `https://your-host/vault/gmail/callback/`. Only explicit loopback development permits HTTP. Keep callback query strings out of reverse-proxy/access logs.
5. Run `python manage.py sync_gmail` under a process supervisor alongside the web server. `--once` handles one queued page for scheduled execution. Monitor both processes. Without a worker, requests remain visibly queued. A worker crash releases its lease after five minutes.
6. Set a reverse-proxy request-body limit near 11 MiB and reasonable request/worker timeouts. Serve only the application and collected static assets. Keep database, object files, scanner and secrets private. Use encrypted volumes and restrictive filesystem ACLs on Windows; POSIX modes alone do not establish Windows ACLs.

No deployment, live Google consent, real document import or production scanner configuration is performed by this code release.

### Gmail client download and troubleshooting

Use a **Web application** client, not a Desktop client. For local use register exactly
`http://localhost:8000/vault/gmail/callback/`, including the trailing slash. Download
the client's JSON once and keep it private. Set `FAMILYOS_GMAIL_CLIENT_FILE` to its
absolute path. In development only, `<FAMILYOS_DATA_DIR>/gmail-client.json` (by
default `instance/gmail-client.json`) is also discovered automatically. Production
requires the explicit file setting. Restrict the file's OS permissions to the
account running FamilyOS; do not place it in static files or commit it.

The file's paired ID and secret take precedence over the individual credential
environment variables. A single registered redirect is selected automatically;
an explicit `FAMILYOS_GMAIL_REDIRECT_URI` must match a registered URI exactly.
For multiple registered URIs, that variable is required. Desktop, malformed,
missing explicit files and mismatched redirects fail at startup without printing
file contents. The original environment-only setup still works without a file.
Restart both the web server and Gmail worker after changing configuration.

Start connections from the Vault in the same browser and use the same hostname
throughout (`localhost` and `127.0.0.1` have different session cookies). Do not
refresh an old callback URL. Invalid or expired state remains rejected. Known
Google token errors now show fixed guidance for rejected credentials, expired
authorization and redirect mismatch; arbitrary provider text, tokens and secrets
are never included in those messages. Missing Gmail scope or offline access has
separate reconnect guidance. A successful redirect alone does not establish that
the token exchange succeeded.

## Backup and recovery

Use `python manage.py backup_vault <external-backup.enc>` for V1.6. It snapshots SQLite, authenticates every referenced immutable object and encrypts the combined archive. Keep the encryption key separately. The legacy `backup_database` command is insufficient by itself for Vault recovery. The backup command currently builds the encrypted archive in memory; provision memory for several times the database and stored encrypted document size, and schedule backups appropriately for a small single-family installation. Its intermediate SQLite snapshot uses the operating system temporary directory, which must be on encrypted storage with restricted permissions.

Restore offline with `python manage.py restore_vault <backup.enc> <new-external-directory>`. It refuses existing destinations, verifies the database and object checksums, and clears sessions and Gmail credentials so old access is not resurrected. Set `FAMILYOS_DATA_DIR` to the restored directory and `FAMILYOS_VAULT_ROOT` to its `objects` subdirectory; preserve the same encryption key, run migrations and restart services. Reconnect Gmail. A failed restore is never promoted to live data. Immutable objects left by a crash before database commit are harmless encrypted orphans; do not manually remove any object referenced by a backup or live database.

## Validation and limits

Unit/integration tests cover access controls, CSRF, content validation, scanner protocol failures, encrypted storage, download integrity, revisions, archive/restore, OAuth state/expiry/replay, token removal, pagination, replay deduplication, expired history, worker leases and disconnect races. `scripts/verify_vault.py` checks additive upgrade, real process restarts, encrypted backup/restore, incorrect keys and non-overwrite behavior with synthetic data. External Gmail and ClamAV behavior is mocked in these tests; operator setup requires a live consent/import/scanner smoke test before production use.

CI runs Windows/Linux with Python 3.10/3.12, static collection, migrations, tests, existing core persistence checks, Vault recovery checks and production Django checks. A separate job runs Vault undefined/unused-name lint, Bandit medium/high severity checks and a runtime dependency advisory audit. No cloud object-storage backend, OCR, enrollment, sharing, tasks/reminders or deployment is included.

Protocol references: [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Gmail synchronization](https://developers.google.com/workspace/gmail/api/guides/sync), [history.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list).
