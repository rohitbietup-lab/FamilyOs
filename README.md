# FamilyOS · V1.4 Authentication Foundation

Owner-only authentication and a persistent central foundation, starting from the repository's README-only baseline. This does not replace the older local/hosted prototypes.

Included: private Command Center, editable owner profile and family details, database sessions, CSRF protection, persistent login throttling, session expiry/revocation, family/user/membership/role/audit models, migrations, backups and tests. Invitations remain disabled. No Gmail or Vault integration is included.

## Local setup (Python 3.10+)

PowerShell, from this repository:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
$env:FAMILYOS_ENV = 'development'
./.venv/Scripts/python.exe manage.py migrate
./.venv/Scripts/python.exe manage.py bootstrap_owner --email 'you@example.com' --name 'Your name' --family 'Your family'
./.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --insecure
```

Bootstrap privately prompts twice for a password (12+ characters). No default credentials exist; it refuses to replace an existing owner. Open `http://127.0.0.1:8000/`. `--insecure` only lets the development server serve static assets while DEBUG stays false; never use this server in production. Development disables HTTPS enforcement for loopback use only. Do not expose this mode on a network.

On macOS/Linux, use `.venv/bin/python` and `export FAMILYOS_ENV=development`. Environment variables are read from the process; `.env` files are not automatically loaded.

## Validate

```powershell
$env:FAMILYOS_ENV = 'development'
./.venv/Scripts/python.exe manage.py collectstatic --noinput
./.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
./.venv/Scripts/python.exe manage.py test --verbosity 2
./.venv/Scripts/python.exe scripts/verify_persistence.py
```

Tests use isolated databases and synthetic accounts. CI targets Windows/Linux with Python 3.10/3.12, including production checks. See [validation results](docs/VALIDATION.md), [the approved plan](docs/FamilyOS_Development_Plan.md), and [operations/security](docs/OPERATIONS.md).

GitHub stores code, not family data. Environments, databases and logs are ignored. Keep backups, credentials, documents and real records outside this public repository. This branch does not deploy the app or create a real owner account.
