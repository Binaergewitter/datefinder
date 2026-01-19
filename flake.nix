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
        
        python = pkgs.python311;
        
        pythonPackages = python.pkgs;
        
        # Python dependencies
        pythonDeps = with pythonPackages; [
          django_4
          django-allauth
          channels
          daphne
          whitenoise
          python-dotenv
          asgiref
        ];
        
        # channels-redis is not in nixpkgs, we'll make it optional
        # For production, users can install it via pip in the environment
        
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
#!/usr/bin/env bash
set -e

# Set up environment
export PYTHONPATH="$out/lib/datefinder:\$PYTHONPATH"
export DJANGO_SETTINGS_MODULE="datefinder.settings"

# Default to current directory for writable data if not set
export DATEFINDER_DATA_DIR="\''${DATEFINDER_DATA_DIR:-\$PWD}"

# Create a wrapper settings module that uses writable paths
cd "$out/lib/datefinder"

# Run migrations and collect static files if needed
if [ "\$1" = "migrate" ]; then
    exec ${python}/bin/python manage.py migrate --database default
elif [ "\$1" = "collectstatic" ]; then
    exec ${python}/bin/python manage.py collectstatic --noinput
elif [ "\$1" = "createsuperuser" ]; then
    exec ${python}/bin/python manage.py createsuperuser
elif [ "\$1" = "shell" ]; then
    exec ${python}/bin/python manage.py shell
elif [ "\$1" = "manage" ]; then
    shift
    exec ${python}/bin/python manage.py "\$@"
else
    # Default: run the development server with daphne
    exec ${pythonPackages.daphne}/bin/daphne -b "\''${HOST:-0.0.0.0}" -p "\''${PORT:-8000}" datefinder.asgi:application
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
          '';
        };
      }
    );
}
