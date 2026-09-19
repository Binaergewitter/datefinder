{ pkgs, self }:

pkgs.testers.nixosTest {
  name = "datefinder";

  nodes.machine = { ... }: {
    imports = [ self.nixosModules.datefinder ];

    services.redis.servers.datefinder = {
      enable = true;
      port = 6379;
    };

    services.datefinder = {
      enable = true;
      host = "0.0.0.0";
      settings = {
        secretKey = "test-secret-key-for-nixos-vm-test";
        registrationEnabled = true;
        localLoginEnabled = true;
        allowedHosts = [ "localhost" "machine" ];
        redisUrl = "redis://localhost:6379";
      };
      database = {
        type = "postgres";
        createLocally = true;
      };
    };
  };

  testScript = ''
    machine.wait_for_unit("redis-datefinder.service")
    machine.wait_for_unit("postgresql.service")
    machine.wait_for_unit("datefinder.service")
    machine.wait_for_open_port(6379)
    machine.wait_for_open_port(8000)

    # Test 1: Web interface reachable
    status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/")
    assert status == "302", f"Expected redirect 302 from /, got {status}"

    # Test 2: Login page accessible
    status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/accounts/login/")
    assert status == "200", f"Expected 200 from /accounts/login/, got {status}"

    # Test 3: Database tables exist in postgres
    tables = machine.succeed("sudo -u datefinder psql -d datefinder -c '\\dt' 2>&1")
    assert "django_migrations" in tables, f"django_migrations table missing: {tables}"
    assert "calendar_app" in tables, f"No calendar_app tables found: {tables}"

    # Test 4: Static files served (pico.css or similar)
    status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/static/css/pico.min.css")
    assert status == "200", f"Expected 200 for static file, got {status}"

    # Test 5: iCal export endpoint
    status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/calendar/export/calendar.ics")
    assert status == "200", f"Expected 200 for iCal export, got {status}"

    # Test 6: Health endpoint accessible without authentication
    import json

    health_response = machine.succeed("curl -s http://localhost:8000/.health")
    health = json.loads(health_response)
    assert health["status"] == "healthy", f"Expected healthy status, got {health['status']}: {health}"

    # Verify database check is healthy
    assert health["checks"]["database"]["status"] == "healthy", \
      f"Database check unhealthy: {health['checks']['database']}"

    # Verify redis check is present and healthy
    assert "redis" in health["checks"], \
      f"Redis check missing from health response: {list(health['checks'].keys())}"
    assert health["checks"]["redis"]["status"] == "healthy", \
      f"Redis check unhealthy: {health['checks']['redis']}"

    # Verify health endpoint returns proper HTTP status
    health_status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/.health")
    assert health_status == "200", f"Expected 200 from /.health, got {health_status}"

    # Test 7: User registration and login
    # Get CSRF token from signup page
    machine.succeed("curl -s -c /tmp/cookies.txt http://localhost:8000/accounts/signup/ > /dev/null")
    csrf = machine.succeed("grep csrftoken /tmp/cookies.txt | awk '{print $NF}'").strip()

    # Sign up
    signup_status = machine.succeed(
      f"curl -s -o /dev/null -w '%{{http_code}}' -b /tmp/cookies.txt "
      f"-d 'csrfmiddlewaretoken={csrf}&username=testuser&password1=TestPass123!&password2=TestPass123!' "
      f"http://localhost:8000/accounts/signup/"
    )
    assert signup_status in ("200", "302"), f"Signup failed with status {signup_status}"

    # Get fresh CSRF token for login
    machine.succeed("curl -s -c /tmp/cookies2.txt http://localhost:8000/accounts/login/ > /dev/null")
    csrf2 = machine.succeed("grep csrftoken /tmp/cookies2.txt | awk '{print $NF}'").strip()

    # Log in
    login_status = machine.succeed(
      f"curl -s -o /dev/null -w '%{{http_code}}' -b /tmp/cookies2.txt -c /tmp/cookies2.txt "
      f"-d 'csrfmiddlewaretoken={csrf2}&login=testuser&password=TestPass123!' "
      f"http://localhost:8000/accounts/login/"
    )
    assert login_status in ("200", "302"), f"Login failed with status {login_status}"

    # Test 8: CalDAV routes enforce Basic auth and .well-known redirects
    dav_status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' -X PROPFIND http://localhost:8000/dav/calendar/")
    assert dav_status == "401", f"Expected 401 for unauthenticated PROPFIND, got {dav_status}"

    wrong_status = machine.succeed("curl -s -u testuser:wrongkey -o /dev/null -w '%{http_code}' -X PROPFIND http://localhost:8000/dav/calendar/")
    assert wrong_status == "401", f"Expected 401 for wrong calendar key, got {wrong_status}"

    wk_status = machine.succeed("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/.well-known/caldav")
    assert wk_status == "301", f"Expected 301 from .well-known/caldav, got {wk_status}"

    # Positive path: generate a real calendar key with the logged-in session
    # over plain HTTP (session cookie is sent), then PROPFIND must succeed
    # (an always-401 regression fails here) and rotation must revoke the old key.
    import json

    def generate_key():
        csrf3 = machine.succeed("grep csrftoken /tmp/cookies2.txt | awk '{print $NF}'").strip()
        out = machine.succeed(
          f"curl -s -b /tmp/cookies2.txt -c /tmp/cookies2.txt "
          f"-d 'csrfmiddlewaretoken={csrf3}' "
          f"http://localhost:8000/calendar/api/dav-key/generate/"
        )
        return json.loads(out)["data"]["key"]

    calendar_key = generate_key()
    assert len(calendar_key) == 40, f"Unexpected calendar key: {calendar_key!r}"

    ok_status = machine.succeed(
      f"curl -s -u testuser:{calendar_key} -o /dev/null -w '%{{http_code}}' "
      f"-X PROPFIND http://localhost:8000/dav/calendar/"
    )
    assert ok_status == "207", f"Expected 207 for PROPFIND with valid key, got {ok_status}"

    rotated = generate_key()
    assert rotated != calendar_key, "key rotation returned the same key"
    stale_status = machine.succeed(
      f"curl -s -u testuser:{calendar_key} -o /dev/null -w '%{{http_code}}' "
      f"-X PROPFIND http://localhost:8000/dav/calendar/"
    )
    assert stale_status == "401", f"Expected 401 for rotated-out key, got {stale_status}"
  '';
}
