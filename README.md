# django-migcare

**Prevents data loss during Django migration rollbacks and git branch switches.**

---

## The problem

Two common scenarios silently destroy production data:

1. **Rolling back a migration** that contained `RemoveField` or `DeleteModel` — Django drops the column/table and the data is gone.
2. **Switching git branches** — migration files from the old branch are still marked as applied in the database, leaving the DB in an inconsistent state that can cause `manage.py migrate` to fail or silently corrupt data.

`django-migcare` addresses both.

---

## Features

| Feature | Description |
|---|---|
| **Risk analysis engine** | Classifies every operation in a migration plan as `SAFE`, `WARNING`, or `DANGER` |
| **Auto-snapshot** | Automatically backs up affected rows to `MigrationSnapshot` before any destructive migration |
| **`safe_migrate` command** | Drop-in replacement for `manage.py migrate` — shows a risk report, creates snapshots, and (optionally) prompts for confirmation |
| **`migcare_check` command** | Inspect pending migrations, risk summary, and existing snapshots at any time |
| **`migcare_backup` command** | Manually snapshot any table or column |
| **`migcare_restore` command** | Restore data from a saved snapshot |
| **Git hook integration** | Installs a `post-checkout` hook that warns about ghost migrations after branch switches |

---

## Installation

```bash
pip install django-migcare
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    "migcare",
]
```

Run migrations to create the snapshot table:

```bash
python manage.py migrate migcare
```

---

## Quick start

### Use `safe_migrate` instead of `migrate`

```bash
python manage.py safe_migrate
```

Output example when a destructive migration is detected:

```
django-migcare risk analysis:

  django-migcare — 1 DANGER operation(s):
    • [DANGER] myapp.0003_remove_user_ssn: RemoveField will DROP column 'ssn'
      from 'user' — all data in that column will be permanently lost.

  django-migcare: snapshot #7 created — myapp_user.ssn (45,210 rows)

Operations to perform:
  Apply all migrations: myapp
Running migrations:
  Applying myapp.0003_remove_user_ssn... OK
```

### Check migration state at any time

```bash
python manage.py migcare_check
python manage.py migcare_check --app myapp
python manage.py migcare_check --json   # machine-readable output
```

### Manually snapshot before a risky operation

```bash
python manage.py migcare_backup myapp 0003_remove_user_ssn \
    --table myapp_user \
    --column ssn \
    --notes "Before quarterly archive run"
```

### Restore a snapshot

```bash
# List available snapshots
python manage.py migcare_restore --list

# Restore snapshot #7
python manage.py migcare_restore 7
```

### Protect against branch-switch surprises

```bash
python manage.py migcare_install_hooks
```

After installation, switching branches triggers an automatic check. Example output after `git checkout feature/payments`:

```
GHOST MIGRATIONS — 2 migration(s) applied in DB but missing from the current branch:
  • myapp.0012_add_payment_table
  • myapp.0013_populate_payment_data

  To resolve: run `python manage.py migrate` to reconcile, or switch back to
  the branch where these migrations were created.
```

Remove the hook at any time:

```bash
python manage.py migcare_install_hooks --remove
```

---

## Configuration

All settings are optional. Override via `settings.MIGCARE`:

```python
MIGCARE = {
    # Auto-snapshot before every DANGER-level migration (default: True)
    "AUTO_BACKUP": True,

    # Prompt for confirmation before applying DANGER migrations via safe_migrate
    # (default: False — useful in CI to prevent accidental rollbacks)
    "REQUIRE_CONFIRMATION": False,

    # Max rows captured per table per snapshot (default: 10_000)
    "BACKUP_ROW_LIMIT": 10_000,

    # Purge snapshots older than N days; 0 = never (default: 30)
    "MAX_BACKUP_AGE_DAYS": 30,

    # Emit warnings when ghost migrations are detected after git checkout (default: True)
    "WARN_ON_BRANCH_SWITCH": True,
}
```

---

## Risk levels

| Level | Operations |
|---|---|
| **DANGER** | `RemoveField` (forward), `DeleteModel` (forward), `AddField` (rollback), `CreateModel` (rollback) |
| **WARNING** | `AlterField`, `RenameField`, `RenameModel`, `RunSQL`, `RunPython` |
| **SAFE** | Everything else (`AddField` forward, `CreateModel` forward, index/constraint changes, …) |

---

## Restoring after accidental data loss

If you ran a destructive migration and need the data back:

1. Roll back the migration to re-create the schema:
   ```bash
   python manage.py migrate myapp 0002_previous_migration
   ```
2. Restore the snapshot:
   ```bash
   python manage.py migcare_restore --list
   python manage.py migcare_restore <snapshot_id>
   ```

---

## How it works

- **Analysis** (`migcare/analysis.py`): Calls `MigrationExecutor.migration_plan()` and inspects each operation's type and direction to produce a `PlanReport`.
- **Backup** (`migcare/backup.py`): Uses Django's database introspection layer to serialize table/column data into `MigrationSnapshot` JSON records.
- **Signals** (`migcare/signals.py`): Hooks into Django's `pre_migrate` signal to trigger auto-backup when `AUTO_BACKUP = True`.
- **Git hooks** (`migcare/git_hooks.py`): Installs a `post-checkout` shell script that calls `migcare_check --git-post-checkout` to detect ghost migrations.

---

## Running the tests

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT
