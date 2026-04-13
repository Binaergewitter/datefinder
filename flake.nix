{
  description = "Podcast Date Finder - A Django app for coordinating podcast recording dates";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    {
      nixosModules.datefinder = import ./nixos/module.nix;
      nixosModules.default = self.nixosModules.datefinder;
    }
    // flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        python = pkgs.python3;

        pythonPackages = python.pkgs;

        # Python dependencies (kept here for test and devShell)
        pythonDeps = with pythonPackages; [
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
          psycopg2
          opentelemetry-api
          opentelemetry-sdk
          redis
          channels-redis
        ];

        pythonWithDeps = python.withPackages (ps: pythonDeps);

        datefinder = pkgs.callPackage ./nixos/package.nix {};

      in {
        packages = {
          default = datefinder;
          datefinder = datefinder;

          # Test package - run with: nix build .#test
          test = pkgs.runCommand "datefinder-tests" {
            buildInputs = [ pythonWithDeps ];
            src = ./.;
          } ''
            export HOME=$TMPDIR

            # Copy source to writable directory
            cp -r $src source
            chmod -R u+w source
            cd source

            # Create staticfiles directory to avoid warnings
            mkdir -p staticfiles

            # Run migrations using in-memory SQLite
            python manage.py migrate --settings=datefinder.settings

            # Run integration tests
            echo "=== Running Integration Tests ==="
            python manage.py test calendar_app.tests.IntegrationTest --settings=datefinder.settings -v 2

            # Run all tests
            echo "=== Running All Tests ==="
            python manage.py test calendar_app health --settings=datefinder.settings -v 2

            echo "All tests passed!" > $out
          '';
        };

        checks = {
          nixos-test = import ./nixos/test.nix { inherit pkgs self; };
          nixos-test-migration = import ./nixos/test-migration.nix { inherit pkgs self; };
          nixos-test-websocket = import ./nixos/test-websocket.nix { inherit pkgs self; };
        };

        apps = {
          default = {
            type = "app";
            program = "${datefinder}/bin/datefinder-server";
          };
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pythonPackages.pip
            pythonPackages.virtualenv
            pythonPackages.pytest
            pythonPackages.pytest-django
            pythonPackages.pytest-asyncio
          ] ++ pythonDeps ++ [
            pkgs.redis
          ];

          shellHook = ''
            echo "Podcast Date Finder development environment"
            echo ""
            echo "To run the development server:"
            echo "  python manage.py migrate"
            echo "  python manage.py runserver"
            echo ""
            echo "Or with daphne (for WebSocket support):"
            echo "  daphne -b 0.0.0.0 -p 8000 datefinder.asgi:application"
            echo ""
            echo "To run tests:"
            echo "  python manage.py test calendar_app"
            echo ""
          '';
        };

      }
    );
}
