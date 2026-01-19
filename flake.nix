{
  description = "Podcast Date Finder - A Django app for coordinating podcast recording dates";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
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
          whitenoise
          python-dotenv
          asgiref
          requests
          pyjwt  # PyJWT library for JWT handling (required by django-allauth)
          cryptography  # Required for RS256 JWT verification
        ];
        
        # channels-redis is not in nixpkgs, we'll make it optional
        # For production, users can install it via pip in the environment
        
        # Python with all dependencies
        pythonWithDeps = python.withPackages (ps: pythonDeps);
        
        datefinder = pythonPackages.buildPythonApplication {
          pname = "datefinder";
          version = "0.1.0";
          format = "other";
          
          src = ./.;
          
          propagatedBuildInputs = pythonDeps;
          
          # No build phase needed for Django
          dontBuild = true;
          
          installPhase = ''
            mkdir -p $out/lib/datefinder
            mkdir -p $out/bin
            
            # Copy all project files
            cp -r datefinder $out/lib/datefinder/
            cp -r calendar_app $out/lib/datefinder/
            cp -r templates $out/lib/datefinder/
            cp manage.py $out/lib/datefinder/
            
            # Create static directory
            mkdir -p $out/lib/datefinder/static
            mkdir -p $out/lib/datefinder/staticfiles
            
            # Create wrapper script for running the server
            cat > $out/bin/datefinder-server <<EOF
#!/bin/sh
set -e

# Set up environment
export PYTHONPATH="$out/lib/datefinder:\$PYTHONPATH"
export DJANGO_SETTINGS_MODULE="datefinder.settings"

# Default to current directory for writable data if not set
export DATEFINDER_DATA_DIR="\''${DATEFINDER_DATA_DIR:-\$PWD}"

# Set database path to writable location (defaults to current directory)
export DATABASE_PATH="\''${DATABASE_PATH:-\$DATEFINDER_DATA_DIR/db.sqlite3}"

# Create data directory if it doesn't exist
mkdir -p "\$DATEFINDER_DATA_DIR"

cd "$out/lib/datefinder"

# Run migrations and collect static files if needed
echo "Using database: ''${DATABASE_PATH:-unset}"
if [ "\$1" = "migrate" ]; then
    exec ${pythonWithDeps}/bin/python manage.py migrate --database default
elif [ "\$1" = "collectstatic" ]; then
    exec ${pythonWithDeps}/bin/python manage.py collectstatic --noinput
elif [ "\$1" = "createsuperuser" ]; then
    exec ${pythonWithDeps}/bin/python manage.py createsuperuser
elif [ "\$1" = "shell" ]; then
    exec ${pythonWithDeps}/bin/python manage.py shell
elif [ "\$1" = "manage" ]; then
    shift
    exec ${pythonWithDeps}/bin/python manage.py "\$@"
else
    # Default: run the development server with daphne
    exec ${pythonWithDeps}/bin/daphne -b "\''${HOST:-0.0.0.0}" -p "\''${PORT:-8000}" datefinder.asgi:application
fi
EOF
            chmod +x $out/bin/datefinder-server
            
            # Create a convenience symlink
            ln -s datefinder-server $out/bin/datefinder
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
            buildInputs = [ (python.withPackages (ps: pythonDeps)) ];
            src = ./.;
          } ''
            export HOME=$TMPDIR
            
            # Copy source to writable directory
            cp -r $src source
            chmod -R u+w source
            cd source
            
            # Create staticfiles directory to avoid warnings
            mkdir -p staticfiles
            
            # Debug: show directory structure
            echo "=== Directory structure ==="
            ls -la
            ls -la calendar_app/
            
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
        
        # Add a check for running tests
        checks.default = pkgs.runCommand "datefinder-tests" {
          buildInputs = [ python ] ++ pythonDeps;
        } ''
          export HOME=$TMPDIR
          cp -r ${./.}/* .
          chmod -R u+w .
          
          # Run migrations
          python manage.py migrate --settings=datefinder.settings
          
          # Run tests
          python manage.py test calendar_app --settings=datefinder.settings -v 2
          
          touch $out
        '';
      }
    );
}
