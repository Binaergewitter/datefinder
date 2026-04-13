{
  description = "Podcast Date Finder - A Django app for coordinating podcast recording dates";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    {
      nixosModules.datefinder = {
        imports = [ ./nixos/module.nix ];
        _module.args.self = self;
      };
      nixosModules.default = self.nixosModules.datefinder;
    }
    // flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        python = pkgs.python3;

        pythonPackages = python.pkgs;

        # Python dependencies
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
          pyjwt  # PyJWT library for JWT handling (required by django-allauth)
          cryptography  # Required for RS256 JWT verification
          psycopg2
        ];

        # Python with all dependencies (for tests and dev shell)
        pythonWithDeps = python.withPackages (ps: pythonDeps);

        datefinder = pythonPackages.buildPythonApplication {
          pname = "datefinder";
          version = "0.1.0";
          pyproject = true;

          src = ./.;

          build-system = with pythonPackages; [
            setuptools
            wheel
          ];

          dependencies = pythonDeps;

          nativeCheckInputs = [
            pkgs.ruff
            pkgs.ty
          ];

          checkPhase = ''
            runHook preCheck
            ruff check .
            ty check --python ${pythonWithDeps}/bin/python --extra-search-path . .
            runHook postCheck
          '';

          meta = with pkgs.lib; {
            description = "Podcast Date Finder - coordinate podcast recording dates";
            license = licenses.mit;
            platforms = platforms.linux ++ platforms.darwin;
          };
        };

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
            python manage.py test calendar_app --settings=datefinder.settings -v 2

            echo "All tests passed!" > $out
          '';
        };

        checks = {
          nixos-test = import ./nixos/test.nix { inherit pkgs self; };
          nixos-test-migration = import ./nixos/test-migration.nix { inherit pkgs self; };
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
