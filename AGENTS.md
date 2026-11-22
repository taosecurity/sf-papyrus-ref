# AGENTS.md: sf-papyrus-ref for AI assistants

These are plain steps for an AI assistant helping someone use sf-papyrus-ref. Every command here was run once on sf-papyrus-ref 0.2.0 before release. The [README](README.md) has the full description.

## 1. What it is for

sf-papyrus-ref is an offline reference for Starfield's Papyrus scripting language.

- **Use it before you write or suggest a Papyrus call.** Look the name up to confirm that it exists, see which script it is on, and see its flags.
  - A name that comes back `found: false` is not on the official list. Don't use it unless you can read the script that defines it, for example the user's own scripts or a script extender's documented source.
- **Use `check` after you change a script.** It reports BetaOnly calls (errors), DebugOnly calls (warnings; they do nothing on Xbox and PlayStation) and Latent calls inside `While` loops.
- **Don't use it** to decide whether a script compiles. The Papyrus compiler decides that. It also doesn't cover Skyrim or Fallout 4, or script extender (SFSE) functions.

## 2. Prerequisites

- Python 3.9 or newer (tested on 3.9, 3.10 and 3.13). Standard library only. Windows or Linux.
- Optional, for signatures: the Starfield Creation Kit from Steam, which provides `Tools\ContentResources.zip`.

## 3. Install

Download `sf-papyrus-ref-0.2.0.zip` and `sf-papyrus-ref-0.2.0.zip.sha256` from https://github.com/taosecurity/sf-papyrus-ref/releases, then check the zip:

    certutil -hashfile sf-papyrus-ref-0.2.0.zip SHA256

On Linux, run `sha256sum -c sf-papyrus-ref-0.2.0.zip.sha256` instead. Unzip it anywhere and keep its files together; `sf_papyrus_ref.py` loads `pexread.py`, `pscread.py` and `data/` from its own folder.

## 4. Prove the install works

From the unzipped folder:

    python -I sf_papyrus_ref.py lookup Debug.Notification --no-local

It prints `Debug.Notification  (function)`, then `Flags: DebugOnly`, and exits with code 0. The full test suite is `python -I -m unittest discover -s tests`, and it ends with `OK`.

## 5. Common tasks

- Look a name up, with or without its script (JSON for reading by a program):

      python -I sf_papyrus_ref.py lookup GetValue --json

- Read signatures from the user's own Creation Kit (once; it takes about a second and writes only the cache):

      python -I sf_papyrus_ref.py build-local

  If it says no sources were found, ask the user where the Creation Kit's script sources are, and pass `--sources <folder or ContentResources.zip>`.

- List a script's functions and events:

      python -I sf_papyrus_ref.py script ObjectReference

- List every Latent function:

      python -I sf_papyrus_ref.py list --flag latent

- Check a mod's scripts, letting Debug.Trace through (try the bundled example first):

      python -I sf_papyrus_ref.py check tests/fixtures --allow Debug.Trace

  In each of the two files, it finds `Debug.Notification` and `Debug.MessageBox` (DebugOnly; the second is in a property's Set handler), `Utility.Wait` in a loop (Latent) and `Game.Warning` (BetaOnly). It exits with code 1.

- Before a Bethesda Creations upload, check with DebugOnly as an error:

      python -I sf_papyrus_ref.py check "<mod folder>" --allow Debug.Trace --creations --json

- Compare the official list with the user's sources:

      python -I sf_papyrus_ref.py diff

- Build a browsable website of the user's Creation Kit scripts (about ten seconds; add `--include-fragments` for all of them):

      python -I sf_papyrus_ref.py html --out "<empty or new folder>"

  It prints the path of `index.html` to open. It refuses a folder that holds files it didn't write. The pages hold Bethesda's script text: tell the user to keep them on their PC or home network, and never upload, commit or publish them yourself.

- Find which of a mod's `.psc` files are Bethesda's scripts, changed or not:

      python -I sf_papyrus_ref.py compare "<mod folder>" --json

  Each result has `status` (`identical`, `changed` or `not-in-ck`), `ck_file`, and for changed files `lines_added` and `lines_removed`. It exits with 0 when everything is identical, and with 1 otherwise.

## 6. MCP server for Claude Code

Register it once (use the real path of the unzipped folder):

    claude mcp add sf-papyrus-ref -- python -I <folder>/sf_papyrus_ref.py mcp --quiet

It offers four read-only tools:

- `papyrus_lookup` takes `{"name"}`.
- `papyrus_script` takes `{"script"}`.
- `papyrus_list_flag` takes `{"flag", "script"?}`.
- `papyrus_check` takes `{"paths", "allow"?, "creations"?}`.

Each returns the same JSON as the matching command with `--json`, plus `exit_code`. The server speaks MCP over stdin and stdout, one JSON-RPC message per line, and makes no network connections.

## 7. Inputs, outputs, exit codes and logs

- **Inputs:** names on the command line; `.psc` and `.pex` files or folders for `check`; the Creation Kit's sources for `build-local`.
- **Outputs:** text on stdout, or JSON with `--json`. JSON includes `author`, `license`, `url`, `version` and `wiki_revision`. A one-line byline goes to stderr unless `--quiet` is given.
- **Exit codes:**
  - `lookup` and `script`: 0 found, 1 not found.
  - `list`: 0 some, 1 none.
  - `check`: 0 clean, 1 findings.
  - `compare`: 0 all identical, 1 some changed or not from the Creation Kit.
  - `html`, `build-local`, `diff` and `data`: 0 done.
  - Every command: 2 for bad options, unreadable files or no sources.
- **Logs:** `--verbose` prints what was read and decided to stderr, and `--log <file>` writes the same to a file.
- **Cache:** `build-local` writes `%LOCALAPPDATA%\sf-papyrus-ref\local.json` on Windows, or `~/.cache/sf-papyrus-ref/local.json` on Linux. `--cache` changes the path and `--no-local` ignores the cache.

## 8. Limits

- It never changes the user's scripts, plugins or game files. It writes only its cache, the `html` site folder and the `--log` file.
- **Don't share, upload or commit the `html` site.** It holds Bethesda's script text from the user's own install.
- It never uploads anything and makes no network connections.
- **Don't share or commit the local cache.** It is made from Bethesda's script sources.
- The shipped list holds names, flags and wiki links only. Without `build-local` there are no signatures, and inherited calls are matched by name. Findings marked `name only` are less certain.
- `check` reads scripts lightly. It is not a compiler, and calls on chained expressions (`a.b.Name()`) are matched by name only.
