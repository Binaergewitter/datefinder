"""
Management command to migrate data from a SQLite database to the current
(typically PostgreSQL) database.

Usage:
    datefinder-manage migrate_from_sqlite --sqlite-path /path/to/db.sqlite3
"""

import sqlite3

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from calendar_app.models import Availability, ConfirmedDate, Reminder


class Command(BaseCommand):
    help = "Migrate all data from a SQLite database to the current database backend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite-path",
            required=True,
            help="Path to the source SQLite database file.",
        )

    def handle(self, *args, **options):
        sqlite_path = options["sqlite_path"]

        if connection.vendor == "sqlite":
            raise CommandError(
                "Target database is SQLite. Set DATABASE_URL to a PostgreSQL database before running this command."
            )

        try:
            src = sqlite3.connect(sqlite_path)
            src.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            raise CommandError(f"Cannot open SQLite database at {sqlite_path}: {e}")

        try:
            self._check_source_tables(src)
            with transaction.atomic():
                users_map = self._migrate_users(src)
                self._migrate_confirmed_dates(src, users_map)
                self._migrate_reminders(src, users_map)
                self._migrate_availability(src, users_map)
        finally:
            src.close()

        self.stdout.write(self.style.SUCCESS("Migration completed successfully."))

    def _check_source_tables(self, src):
        """Verify the source database has the expected tables."""
        cursor = src.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor}
        required = {"auth_user", "calendar_app_availability"}
        missing = required - tables
        if missing:
            raise CommandError(f"Source database is missing required tables: {', '.join(sorted(missing))}")

    def _migrate_users(self, src):
        """Migrate auth_user rows. Returns {old_id: new_id} mapping."""
        rows = src.execute(
            "SELECT id, username, password, email, first_name, last_name, "
            "is_staff, is_active, is_superuser, date_joined, last_login "
            "FROM auth_user ORDER BY id"
        ).fetchall()

        id_map = {}
        for row in rows:
            existing = User.objects.filter(username=row["username"]).first()
            if existing:
                id_map[row["id"]] = existing.pk
                self.stdout.write(f"  User '{row['username']}' already exists (pk={existing.pk}), skipping.")
                continue

            user = User(
                username=row["username"],
                password=row["password"],
                email=row["email"] or "",
                first_name=row["first_name"] or "",
                last_name=row["last_name"] or "",
                is_staff=bool(row["is_staff"]),
                is_active=bool(row["is_active"]),
                is_superuser=bool(row["is_superuser"]),
            )
            user.save()
            # Preserve original timestamps via raw UPDATE to bypass auto_now
            if row["date_joined"]:
                User.objects.filter(pk=user.pk).update(date_joined=row["date_joined"])
            if row["last_login"]:
                User.objects.filter(pk=user.pk).update(last_login=row["last_login"])

            id_map[row["id"]] = user.pk

        self.stdout.write(f"Migrated {len(rows)} users ({len(rows) - len(id_map) + len(id_map)} total).")
        return id_map

    def _migrate_confirmed_dates(self, src, users_map):
        """Migrate calendar_app_confirmeddate rows."""
        try:
            rows = src.execute(
                "SELECT id, date, description, confirmed_by_id, created_at, updated_at "
                "FROM calendar_app_confirmeddate ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            self.stdout.write("  No confirmeddate table in source, skipping.")
            return

        count = 0
        for row in rows:
            if ConfirmedDate.objects.filter(date=row["date"]).exists():
                self.stdout.write(f"  ConfirmedDate {row['date']} already exists, skipping.")
                continue

            confirmed_by_id = users_map.get(row["confirmed_by_id"]) if row["confirmed_by_id"] else None
            obj = ConfirmedDate(
                date=row["date"],
                description=row["description"] or "",
                confirmed_by_id=confirmed_by_id,
            )
            obj.save()
            # Preserve timestamps
            ConfirmedDate.objects.filter(pk=obj.pk).update(
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            count += 1

        self.stdout.write(f"Migrated {count} confirmed dates.")

    def _migrate_reminders(self, src, users_map):
        """Migrate calendar_app_reminder rows."""
        try:
            rows = src.execute(
                "SELECT id, title, date, description, created_by_id, created_at, updated_at "
                "FROM calendar_app_reminder ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            self.stdout.write("  No reminder table in source, skipping.")
            return

        count = 0
        for row in rows:
            created_by_id = users_map.get(row["created_by_id"]) if row["created_by_id"] else None
            obj = Reminder(
                title=row["title"],
                date=row["date"],
                description=row["description"] or "",
                created_by_id=created_by_id,
            )
            obj.save()
            Reminder.objects.filter(pk=obj.pk).update(
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            count += 1

        self.stdout.write(f"Migrated {count} reminders.")

    def _migrate_availability(self, src, users_map):
        """Migrate calendar_app_availability rows."""
        rows = src.execute(
            "SELECT id, user_id, date, status, created_at, updated_at FROM calendar_app_availability ORDER BY id"
        ).fetchall()

        count = 0
        skipped = 0
        for row in rows:
            new_user_id = users_map.get(row["user_id"])
            if new_user_id is None:
                skipped += 1
                continue

            if Availability.objects.filter(user_id=new_user_id, date=row["date"]).exists():
                self.stdout.write(
                    f"  Availability for user_id={new_user_id} on {row['date']} already exists, skipping."
                )
                skipped += 1
                continue

            obj = Availability(
                user_id=new_user_id,
                date=row["date"],
                status=row["status"],
            )
            obj.save()
            Availability.objects.filter(pk=obj.pk).update(
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            count += 1

        self.stdout.write(f"Migrated {count} availability entries (skipped {skipped}).")
