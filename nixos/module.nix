{ config, lib, pkgs, self, ... }:

let
  cfg = config.services.datefinder;
  pkg = cfg.package;

  env = {
    STATEDIR = cfg.stateDir;
    HOST = cfg.host;
    PORT = toString cfg.port;
    DEBUG = lib.boolToString cfg.settings.debug;
    ALLOWED_HOSTS = lib.concatStringsSep "," cfg.settings.allowedHosts;
    REGISTRATION_ENABLED = lib.boolToString cfg.settings.registrationEnabled;
    LOCAL_LOGIN_ENABLED = lib.boolToString cfg.settings.localLoginEnabled;
    ICAL_TIMEZONE = cfg.settings.icalTimezone;
  }
  // lib.optionalAttrs (cfg.settings.secretKey != null) {
    SECRET_KEY = cfg.settings.secretKey;
  }
  // lib.optionalAttrs (cfg.settings.siteUrl != null) {
    SITE_URL = cfg.settings.siteUrl;
  }
  // lib.optionalAttrs cfg.settings.useXForwardedHost {
    USE_X_FORWARDED_HOST = lib.boolToString cfg.settings.useXForwardedHost;
  }
  // lib.optionalAttrs cfg.settings.trustProxyHeaders {
    TRUST_PROXY_HEADERS = lib.boolToString cfg.settings.trustProxyHeaders;
  }
  // lib.optionalAttrs (cfg.settings.csrfTrustedOrigins != []) {
    CSRF_TRUSTED_ORIGINS = lib.concatStringsSep "," cfg.settings.csrfTrustedOrigins;
  }
  // lib.optionalAttrs (cfg.settings.redisUrl != null) {
    REDIS_URL = cfg.settings.redisUrl;
  }
  // lib.optionalAttrs (cfg.keycloak.serverUrl != null) {
    KEYCLOAK_SERVER_URL = cfg.keycloak.serverUrl;
  }
  // lib.optionalAttrs (cfg.keycloak.realm != null) {
    KEYCLOAK_REALM = cfg.keycloak.realm;
  }
  // lib.optionalAttrs (cfg.keycloak.clientId != null) {
    KEYCLOAK_CLIENT_ID = cfg.keycloak.clientId;
  }
  // (if cfg.database.type == "postgres" && cfg.database.createLocally then {
    DATABASE_URL = "postgres:///${cfg.database.name}";
    DATABASE_SOCKET_DIR = cfg.database.socketDir;
  } else if cfg.database.type == "postgres" then {
    DATABASE_URL =
      let
        hostPart = if cfg.database.host != null
          then "@${cfg.database.host}:${toString cfg.database.port}"
          else "";
      in "postgres://${cfg.database.user}${hostPart}/${cfg.database.name}";
  } // lib.optionalAttrs (cfg.database.host == null) {
    DATABASE_SOCKET_DIR = cfg.database.socketDir;
  } else {});

in {
  options.services.datefinder = {
    enable = lib.mkEnableOption "datefinder podcast scheduling service";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.system}.default;
      description = "The datefinder package to use.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
      description = "Port to listen on.";
      example = 8080;
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Bind address for the server.";
      example = "0.0.0.0";
    };

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/datefinder";
      description = "Directory for persistent state (database, static files, calendar export). Managed via systemd StateDirectory.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "datefinder";
      description = "System user to run datefinder as.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "datefinder";
      description = "System group to run datefinder as.";
    };

    environmentFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Path to a systemd EnvironmentFile containing secrets.
        Supports SECRET_KEY, KEYCLOAK_CLIENT_SECRET, APPRISE_URLS.
      '';
      example = "/run/secrets/datefinder";
    };

    settings = {
      secretKey = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = ''
          Django secret key. WARNING: This is stored in the world-readable Nix store.
          Prefer using {option}`environmentFile` for production deployments.
        '';
      };

      debug = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Enable Django debug mode. Do not use in production.";
      };

      allowedHosts = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ "localhost" "127.0.0.1" ];
        description = "List of allowed hostnames for Django's ALLOWED_HOSTS.";
        example = [ "plan.example.com" "localhost" ];
      };

      siteUrl = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "External URL of the site, used for reverse proxy setups.";
        example = "https://plan.example.com";
      };

      useXForwardedHost = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Trust the X-Forwarded-Host header from a reverse proxy.";
      };

      trustProxyHeaders = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Trust X-Forwarded-Proto header to detect HTTPS behind a reverse proxy.";
      };

      csrfTrustedOrigins = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [];
        description = "CSRF trusted origins for HTTPS behind a reverse proxy.";
        example = [ "https://plan.example.com" ];
      };

      registrationEnabled = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Allow new user registration.";
      };

      localLoginEnabled = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Allow local username/password login (as opposed to SSO only).";
      };

      redisUrl = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Redis URL for Django Channels layer. Uses in-memory layer if unset.";
        example = "redis://localhost:6379";
      };

      icalTimezone = lib.mkOption {
        type = lib.types.str;
        default = "Europe/Berlin";
        description = "Timezone for iCal event exports.";
        example = "UTC";
      };
    };

    database = {
      type = lib.mkOption {
        type = lib.types.enum [ "sqlite" "postgres" ];
        default = "sqlite";
        description = "Database backend to use.";
        example = "postgres";
      };

      name = lib.mkOption {
        type = lib.types.str;
        default = "datefinder";
        description = "Database name. Used for both SQLite filename and PostgreSQL database name.";
      };

      user = lib.mkOption {
        type = lib.types.str;
        default = "datefinder";
        description = "Database user for PostgreSQL authentication. Must match the system user when using unix socket auth.";
      };

      host = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Database host. Null means unix socket connection.";
        example = "localhost";
      };

      port = lib.mkOption {
        type = lib.types.port;
        default = 5432;
        description = "Database port (for TCP connections).";
      };

      socketDir = lib.mkOption {
        type = lib.types.str;
        default = "/run/postgresql";
        description = "Directory for PostgreSQL unix socket.";
      };

      createLocally = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = ''
          Automatically configure a local PostgreSQL instance with peer authentication.
          Only takes effect when {option}`database.type` is set to `"postgres"`.
        '';
      };
    };

    keycloak = {
      serverUrl = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Keycloak server URL for OIDC authentication.";
        example = "https://keycloak.example.com/";
      };

      realm = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Keycloak realm name.";
        example = "myrealm";
      };

      clientId = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Keycloak OIDC client ID.";
        example = "datefinder";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.user} = {
      isSystemUser = true;
      group = cfg.group;
      home = cfg.stateDir;
    };

    users.groups.${cfg.group} = {};

    services.postgresql = lib.mkIf (cfg.database.type == "postgres" && cfg.database.createLocally) {
      enable = true;
      ensureDatabases = [ cfg.database.name ];
      ensureUsers = [
        {
          name = cfg.database.user;
          ensureDBOwnership = true;
        }
      ];
    };

    systemd.services.datefinder = {
      description = "Datefinder podcast scheduling service";
      after = [ "network.target" ]
        ++ lib.optionals (cfg.database.type == "postgres" && cfg.database.createLocally) [ "postgresql.service" ];
      requires =
        lib.optionals (cfg.database.type == "postgres" && cfg.database.createLocally) [ "postgresql.service" ];
      wantedBy = [ "multi-user.target" ];

      environment = env;

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        StateDirectory = "datefinder";
        WorkingDirectory = cfg.stateDir;
        ExecStartPre = "${pkg}/bin/datefinder-manage migrate --noinput";
        ExecStart = "${pkg}/bin/datefinder-server";
      } // lib.optionalAttrs (cfg.environmentFile != null) {
        EnvironmentFile = cfg.environmentFile;
      };
    };
  };
}
