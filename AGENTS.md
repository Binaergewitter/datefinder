# AGENTS.md — Your Workspace for DateFinder

This repository is your mission. Treat it with respect.

## Core Rules

1.  **Nix-First Workflow**: This is a Nix-based project. 
    *   To run `manage.py`, use: `nix develop -c python manage.py`
    *   After adding/removing files: `git add -AN` (otherwise Nix won't see them).
    *   After any change: Run `nix build` and `nix build .#test`.
2.  **Test-Driven Development**: Every structural change requires a new integration test case.
3.  **Efficiency**: Work smart. Minimize tool calls.

## Developer Workflow

1.  **Plan**: Identify the task. Check `README.md` and `pyproject.toml`.
2.  **Develop**: 
    *   Use `nix develop` for your environment.
    *   Keep logic modular.
3.  **Verify**:
    *   Run `nix build` to ensure the environment is reproducible.
    *   Run `nix build .#test` for integration tests.
4.  **Commit**: Use clear, concise commit messages.

## 🪨 Caveman Mode (Token Savings)

If efficiency is critical or requested:
*   Terse output. Technical substance exact. 
*   Drop articles, filler words, pleasantries.
*   Pattern: [thing] [action] [reason]. [next step].
*   Example: "Fixing database. Migration failed. Running nix build."

## Memory & Context

*   Read `README.md` for project goals.
*   Capture significant decisions in `memory/` (if enabled in workspace).
*   Text > Brain. Write down lessons learned.
