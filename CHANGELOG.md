# Changelog

## 0.1.0 (2026-11-20)

### What's new

This is the first release. sf-papyrus-ref is an offline reference for Starfield's Papyrus scripting language: it tells you whether a function or event exists, which script it is on, and whether it is safe on Xbox and PlayStation. It also checks your mod's `.psc` and `.pex` scripts for calls that do nothing on consoles or should never ship.

### Example

    > sf-papyrus-ref lookup Debug.Notification
    sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    Debug.Notification  (function)
      Flags: DebugOnly
      Official page: https://starfield.creationkit.bethesda.net/w/index.php?title=Notification_-_Debug
    Run 'sf-papyrus-ref build-local' once to see signatures from your own Creation Kit sources.

    > sf-papyrus-ref check tests\fixtures\SfprFixture.psc --allow Debug.Trace
    sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    tests\fixtures\SfprFixture.psc:8: warning: Debug.Notification is DebugOnly: it does nothing in release builds on Xbox and PlayStation
    tests\fixtures\SfprFixture.psc:11: warning: Utility.Wait is Latent and is called inside a loop: each pass waits for it to finish
    tests\fixtures\SfprFixture.psc:15: error: Game.Warning is BetaOnly: it is meant for beta builds and should never ship
    tests\fixtures\SfprFixture.psc:31: warning: Debug.MessageBox is DebugOnly: it does nothing in release builds on Xbox and PlayStation
    Checked 1 files: 1 errors, 3 warnings.

### Commands

- `lookup`, `script`, `list --flag` and `data` answer from a shipped list of the official Starfield Creation Kit wiki's Papyrus names and flags (wiki revision 8392: 103 scripts, 1,390 functions, 260 events and 3 structs). The list holds names, flags and links only.
- `build-local` reads your own Creation Kit's script sources into a local cache, so that `lookup` and `script` show signatures and `check` follows parent scripts.
- `diff` compares the official list with your sources.
- `check` reports BetaOnly calls, DebugOnly calls and Latent calls inside loops in `.psc` and `.pex` scripts, as text or JSON.
- `mcp` runs a read-only Model Context Protocol (MCP) server, so that AI assistants such as Claude Code can query the reference.

### Download

Download `sf-papyrus-ref-0.1.0.zip` and its `.sha256` file below, unzip it anywhere and follow the Install steps in the README. It needs Python 3.9 or newer and nothing else.
