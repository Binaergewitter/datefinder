{ pkgs, self }:

pkgs.testers.nixosTest {
  name = "datefinder-websocket";

  nodes.machine = { pkgs, ... }: {
    imports = [ self.nixosModules.datefinder ];

    services.redis.servers.datefinder = {
      enable = true;
      port = 6379;
    };

    services.datefinder = {
      enable = true;
      host = "0.0.0.0";
      settings = {
        secretKey = "test-secret-key-for-websocket-test";
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

    environment.systemPackages = [
      (pkgs.python3.withPackages (ps: [ ps.websockets ]))
    ];
  };

  testScript = ''
    machine.wait_for_unit("redis-datefinder.service")
    machine.wait_for_unit("postgresql.service")
    machine.wait_for_unit("datefinder.service")
    machine.wait_for_open_port(6379)
    machine.wait_for_open_port(8000)

    # Verify channels_redis is importable by the application
    machine.succeed(
      "curl -s http://localhost:8000/.health | python3 -c 'import sys,json; "
      "h=json.load(sys.stdin); "
      "assert h[\"checks\"][\"redis\"][\"status\"]==\"healthy\", h'"
    )

    # Create a test user via signup
    machine.succeed("curl -s -c /tmp/ws_cookies.txt http://localhost:8000/accounts/signup/ > /dev/null")
    csrf = machine.succeed("grep csrftoken /tmp/ws_cookies.txt | awk '{print $NF}'").strip()
    machine.succeed(
      f"curl -s -o /dev/null -w '%{{http_code}}' -b /tmp/ws_cookies.txt "
      f"-d 'csrfmiddlewaretoken={csrf}&username=wsuser&password1=TestPass123!&password2=TestPass123!' "
      f"http://localhost:8000/accounts/signup/"
    )

    # Log in to get a session cookie
    machine.succeed("curl -s -c /tmp/ws_cookies2.txt http://localhost:8000/accounts/login/ > /dev/null")
    csrf2 = machine.succeed("grep csrftoken /tmp/ws_cookies2.txt | awk '{print $NF}'").strip()
    machine.succeed(
      f"curl -s -c /tmp/ws_cookies3.txt -b /tmp/ws_cookies2.txt "
      f"-d 'csrfmiddlewaretoken={csrf2}&login=wsuser&password=TestPass123!' "
      f"-L http://localhost:8000/accounts/login/ > /dev/null"
    )

    # Extract session cookie for WebSocket auth
    sessionid = machine.succeed("grep sessionid /tmp/ws_cookies3.txt | awk '{print $NF}'").strip()

    # Test WebSocket connection with Redis channel layer
    # The consumer requires authentication and joins the calendar_updates group
    ws_test = machine.succeed(
      "python3 -c '"
      "import asyncio, websockets\n"
      "async def test():\n"
      "    uri = \"ws://localhost:8000/ws/calendar/\"\n"
      "    headers = {\"Cookie\": f\"sessionid=" + sessionid + "\"}\n"
      "    async with websockets.connect(uri, additional_headers=headers, origin=\"http://localhost\") as ws:\n"
      "        # If we get here, the WebSocket connected successfully\n"
      "        # which means channels_redis.core.RedisChannelLayer loaded\n"
      "        await ws.close()\n"
      "        return \"ok\"\n"
      "print(asyncio.run(test()))\n"
      "'"
    ).strip()
    assert ws_test == "ok", f"WebSocket test failed: {ws_test}"

    # Verify no channels_redis import errors in journal
    journal = machine.succeed("journalctl -u datefinder.service --no-pager")
    assert "No module named 'channels_redis'" not in journal, \
      "channels_redis import error found in journal"
  '';
}
