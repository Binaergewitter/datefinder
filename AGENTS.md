After adding or removing any files, these files must be added to the git index with `git add -AN`, otherwise they will not be usable in a `nix build`
to run `manage.py` you must use `nix develop -c python manage.py`
after performing any changes always run `nix build` and finalize the run with running `nix build .#test`
Every change in the underlying structure shall result in a new test case which can be tested via integrationtest
