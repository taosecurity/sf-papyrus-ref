# Changelog

## 0.1.0 (not yet released)

This is the first release.

- `lookup`, `script`, `list --flag` and `data` answer from a shipped list of the official Starfield Creation Kit wiki's Papyrus names and flags (wiki revision 8392: 103 scripts, 1,390 functions, 260 events and 3 structs). The list holds names, flags and links only.
- `build-local` reads your own Creation Kit's script sources into a local cache, so that `lookup` and `script` show signatures and `check` follows parent scripts.
- `diff` compares the official list with your sources.
- `check` reports BetaOnly calls, DebugOnly calls and Latent calls inside loops in `.psc` and `.pex` scripts, as text or JSON.
- `mcp` runs a read-only Model Context Protocol server, so that AI agents such as Claude Code can query the reference.
