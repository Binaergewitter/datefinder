# AGENTS.md — Your Workspace for DateFinder

This repository is your mission. Treat it with respect.

## Core Rules

1.  **Nix-First Workflow**: This is a Nix-based project. 
    *   To run `manage.py`, use: `nix develop -c python manage.py`
    *   After adding/removing files: `git add -AN` (otherwise Nix won't see them).
    *   After any change: Run `nix build` and `nix build .#test`.
2.  **Test-Driven Development**: Every structural change requires a new integration test case.
3.  **Efficiency**: Work smart. Minimize tool calls.

## Developer Workflow (Branch & PR)

1.  **Status Check**: `git status`. Ensure clean state.
2.  **Branching**: NO direct commits to `main`. Create `feat/` or `fix/` branches.
3.  **Develop**: 
    *   Use `nix develop` for environment.
    *   Logic modular.
4.  **Verify**:
    *   `nix build` (reproducibility).
    *   `nix build .#test` (integration).
5.  **Commit & Push**:
    *   `git commit -m "type: description"`
    *   `git push origin <branch>`
6.  **PR**: Create Pull Request for merge to `main`.

## 🪨 Caveman Mode (Token Savings)

Active by default if efficiency requested or "caveman" in prompt.
*   Terse. Technical substance 100%. No fluff.
*   Drop articles, filler (just/really), pleasantries.
*   Pattern: [thing] [action] [reason]. [next step].
*   Example: "Database fix. Migration fail. Run nix build."

## Memory & Context

*   Read `README.md` for project goals.
*   Capture significant decisions in `memory/` (if enabled).
*   Text > Brain. Write down lessons learned.
