{ lib, python3, ruff, ty }:

let
  pythonPackages = python3.pkgs;

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

  pythonWithDeps = python3.withPackages (_ps: pythonDeps);

in pythonPackages.buildPythonApplication {
  pname = "datefinder";
  version = "0.1.0";
  pyproject = true;

  src = ./..;

  build-system = with pythonPackages; [
    setuptools
    wheel
  ];

  dependencies = pythonDeps;

  nativeCheckInputs = [
    ruff
    ty
  ];

  checkPhase = ''
    runHook preCheck
    ruff check .
    ty check --python ${pythonWithDeps}/bin/python --extra-search-path . .
    runHook postCheck
  '';

  meta = with lib; {
    description = "Podcast Date Finder - coordinate podcast recording dates";
    license = licenses.mit;
    platforms = platforms.linux ++ platforms.darwin;
  };
}
