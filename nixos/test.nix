{ pkgs, self }:

pkgs.testers.nixosTest {
  name = "datefinder";

  nodes.machine = { ... }: {
    imports = [ self.nixosModules.datefinder ];

    services.datefinder = {
      enable = true;
      host = "0.0.0.0";
      settings = {
        secretKey = "test-secret-key-for-nixos-vm-test";
        registrationEnabled = true;
        localLoginEnabled = true;
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

    # Test 6: User registration and login
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
      f"curl -s -o /dev/null -w '%{{http_code}}' -b /tmp/cookies2.txt "
      f"-d 'csrfmiddlewaretoken={csrf2}&login=testuser&password=TestPass123!' "
      f"http://localhost:8000/accounts/login/"
    )
    assert login_status in ("200", "302"), f"Login failed with status {login_status}"
  '';
}
