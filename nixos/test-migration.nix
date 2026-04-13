{ pkgs, self }:

let
  # Create a SQLite database pre-populated with test data.
  # Runs migrations on SQLite, then inserts users, availability,
  # confirmed dates, and reminders via Django's ORM.
  seedSqlite = pkgs.runCommand "seed-sqlite" {
    buildInputs = [
      (pkgs.python3.withPackages (ps: with ps; [
        django
        django-allauth
        channels
        daphne
        apprise
        whitenoise
        python-dotenv
        jinja2
        asgiref
        requests
        pyjwt
        cryptography
      ]))
    ];
    src = self;
  } ''
    export HOME=$TMPDIR
    cp -r $src/. source
    chmod -R u+w source
    cd source
    mkdir -p staticfiles

    export STATEDIR=$TMPDIR
    python manage.py migrate --settings=datefinder.settings --noinput 2>&1

    python manage.py shell --settings=datefinder.settings <<'PYEOF'
from django.contrib.auth.models import User
from calendar_app.models import Availability, ConfirmedDate, Reminder
from datetime import date

# Create test users
alice = User.objects.create_user("alice", "alice@test.local", "pass1234")
alice.first_name = "Alice"
alice.last_name = "Wonder"
alice.save()

bob = User.objects.create_user("bob", "bob@test.local", "pass1234")

# Availability entries
Availability.objects.create(user=alice, date=date(2026, 5, 1), status="available")
Availability.objects.create(user=alice, date=date(2026, 5, 8), status="tentative")
Availability.objects.create(user=bob, date=date(2026, 5, 1), status="available")

# Confirmed date
ConfirmedDate.objects.create(
    date=date(2026, 5, 1),
    description="Episode 500",
    confirmed_by=alice,
)

# Reminder
Reminder.objects.create(
    title="Prepare show notes",
    date=date(2026, 5, 1),
    description="Don't forget the changelog",
    created_by=bob,
)

print(f"Users: {User.objects.count()}")
print(f"Availability: {Availability.objects.count()}")
print(f"ConfirmedDate: {ConfirmedDate.objects.count()}")
print(f"Reminder: {Reminder.objects.count()}")
PYEOF

    mkdir -p $out
    cp $TMPDIR/db.sqlite3 $out/db.sqlite3
  '';
in

pkgs.testers.nixosTest {
  name = "datefinder-migration";

  nodes.machine = { ... }: {
    imports = [ self.nixosModules.datefinder ];

    services.datefinder = {
      enable = true;
      host = "0.0.0.0";
      settings = {
        secretKey = "test-secret-key-for-migration-test";
        allowedHosts = [ "localhost" "machine" ];
      };
      database = {
        type = "postgres";
        createLocally = true;
      };
    };
  };

  testScript = ''
    machine.wait_for_unit("postgresql.service")
    machine.wait_for_unit("datefinder.service")
    machine.wait_for_open_port(8000)

    # Copy the pre-seeded SQLite database into the VM
    machine.succeed("cp ${seedSqlite}/db.sqlite3 /tmp/source.sqlite3")

    # Verify PostgreSQL is currently empty (only migration-created rows)
    user_count = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM auth_user\""
    ).strip()
    assert user_count == "0", f"Expected 0 users before migration, got {user_count}"

    avail_count = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM calendar_app_availability\""
    ).strip()
    assert avail_count == "0", f"Expected 0 availability before migration, got {avail_count}"

    # Run the migration command (needs the same env vars as the systemd service)
    migrate_env = "DATABASE_URL=postgres:///datefinder DATABASE_SOCKET_DIR=/run/postgresql STATEDIR=/var/lib/datefinder SECRET_KEY=test-secret-key-for-migration-test"
    machine.succeed(
      f"sudo -u datefinder env {migrate_env} ${self.packages.x86_64-linux.default}/bin/datefinder-manage "
      "migrate_from_sqlite --sqlite-path /tmp/source.sqlite3"
    )

    # Verify users were migrated
    user_count = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM auth_user\""
    ).strip()
    assert user_count == "2", f"Expected 2 users after migration, got {user_count}"

    alice_exists = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT first_name FROM auth_user WHERE username='alice'\""
    ).strip()
    assert alice_exists == "Alice", f"Expected alice's first_name='Alice', got '{alice_exists}'"

    # Verify availability was migrated
    avail_count = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM calendar_app_availability\""
    ).strip()
    assert avail_count == "3", f"Expected 3 availability rows, got {avail_count}"

    # Verify confirmed dates
    confirmed_count = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM calendar_app_confirmeddate\""
    ).strip()
    assert confirmed_count == "1", f"Expected 1 confirmed date, got {confirmed_count}"

    confirmed_desc = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT description FROM calendar_app_confirmeddate\""
    ).strip()
    assert confirmed_desc == "Episode 500", f"Expected 'Episode 500', got '{confirmed_desc}'"

    # Verify reminders
    reminder_count = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM calendar_app_reminder\""
    ).strip()
    assert reminder_count == "1", f"Expected 1 reminder, got {reminder_count}"

    reminder_title = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT title FROM calendar_app_reminder\""
    ).strip()
    assert reminder_title == "Prepare show notes", f"Expected 'Prepare show notes', got '{reminder_title}'"

    # Verify foreign key integrity: confirmed_by points to alice
    confirmed_by = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc "
      "\"SELECT u.username FROM calendar_app_confirmeddate c JOIN auth_user u ON c.confirmed_by_id = u.id\""
    ).strip()
    assert confirmed_by == "alice", f"Expected confirmed_by=alice, got '{confirmed_by}'"

    # Verify idempotency: running again should not duplicate data
    machine.succeed(
      f"sudo -u datefinder env {migrate_env} ${self.packages.x86_64-linux.default}/bin/datefinder-manage "
      "migrate_from_sqlite --sqlite-path /tmp/source.sqlite3"
    )

    user_count2 = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM auth_user\""
    ).strip()
    assert user_count2 == "2", f"Expected 2 users after re-run (idempotent), got {user_count2}"

    avail_count2 = machine.succeed(
      "sudo -u datefinder psql -d datefinder -tAc \"SELECT count(*) FROM calendar_app_availability\""
    ).strip()
    assert avail_count2 == "3", f"Expected 3 availability after re-run (idempotent), got {avail_count2}"
  '';
}
