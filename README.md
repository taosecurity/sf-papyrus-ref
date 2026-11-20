# sf-papyrus-ref

**Does this Papyrus function exist in Starfield, on which script, and is it safe on Xbox?** sf-papyrus-ref answers that offline, from the command line, in about a tenth of a second. It also checks your mod's scripts for calls that never work on consoles or should never ship.

```
> sf-papyrus-ref lookup Debug.Notification
Debug.Notification  (function)
  Signature (your sources): Function Notification(string asNotificationText) native global
  Flags: DebugOnly
  Official page: https://starfield.creationkit.bethesda.net/w/index.php?title=Notification_-_Debug
```

**For AI assistants:** read [AGENTS.md](AGENTS.md). It gives install and use steps you can follow as written, including the MCP server setup for Claude Code.

## What it does for you

- **It looks up a name.** `lookup` tells you which script has a function, event or struct, gives its official flags and links to its page on the official Creation Kit wiki. A name that isn't on the official list is reported as not found, with near matches. The tool never guesses.
- **It lists a script.** `script Actor` shows every function and event on Actor.
- **It filters by flag.** `list --flag latent` shows every Latent function.
- **It checks your scripts.** `check` reads your `.psc` sources or compiled `.pex` files, and reports:
  - **BetaOnly** calls, as errors. They are meant for Bethesda's beta builds and should never ship.
  - **DebugOnly** calls, as warnings, or as errors with `--creations`. These calls do nothing in release builds on Xbox and PlayStation, so a `Debug.Notification` or `Debug.MessageBox` that the player should see is invisible on a console.
  - **Latent** calls inside a `While` loop, as warnings. The script waits for each one to finish on every pass.
- **It helps AI agents.** `mcp` runs a small read-only server that Claude Code and other agents can query, so they look a name up instead of inventing one.

The five flags come from the official wiki: Latent, Non-delayed, DebugOnly, BetaOnly and Inventory-safe. The wiki's [Latent Functions](https://starfield.creationkit.bethesda.net/w/index.php?title=Category:Latent_Functions) and [Non-Delayed Native Functions](https://starfield.creationkit.bethesda.net/w/index.php?title=Category:Non-Delayed_Native_Functions) pages explain the two timing flags.

## Install

You need Python 3.9 or newer, on Windows or Linux. There's nothing else to install: it uses the standard library only.

1. Download `sf-papyrus-ref-0.1.0.zip` and its `.sha256` file from the [releases page](https://github.com/taosecurity/sf-papyrus-ref/releases).
2. Check the zip. On Windows, run `certutil -hashfile sf-papyrus-ref-0.1.0.zip SHA256` and compare the result with the `.sha256` file. On Linux, run `sha256sum -c sf-papyrus-ref-0.1.0.zip.sha256`.
3. Unzip it anywhere, for example `C:\Tools\sf-papyrus-ref`.
4. Try it from that folder:

   ```
   sf-papyrus-ref lookup Utility.Wait
   ```

   On Linux, use `./sf-papyrus-ref lookup Utility.Wait`. The launchers simply run `python -I sf_papyrus_ref.py` with your arguments, so `python -I sf_papyrus_ref.py lookup Utility.Wait` works too.

## Read signatures from your own Creation Kit (recommended)

The shipped list holds names and flags only. Run this once to add signatures and parent scripts from your own Creation Kit:

```
sf-papyrus-ref build-local
```

It finds `Tools\ContentResources.zip` in your Steam Starfield folder (in any Steam library) and reads the script sources inside it without extracting them. That takes about a second. It saves a cache to `%LOCALAPPDATA%\sf-papyrus-ref\local.json` on Windows, or `~/.cache/sf-papyrus-ref/local.json` on Linux. The cache is made from Bethesda's files, so keep it on your machine.

- **Steam:** found on its own. The Creation Kit is a free Steam tool ("Starfield Creation Kit").
- **Game Pass:** the Creation Kit ships only on Steam. If you have the sources somewhere else, pass their location with `--sources`.
- **Extracted sources, MO2 or Vortex:** if you unpacked the sources into a folder (for example `Data\Scripts\Source`, or an MO2 mod folder), pass it with `--sources <folder>`. Use the folder that holds `Debug.psc`.

Once the cache exists, these commands improve:

- `lookup` and `script` show each signature, and `lookup` also finds functions on the game's other scripts, such as quest scripts.
- `check` follows parent scripts. For example, a call to `MoveTo` on an Actor is matched to `ObjectReference.MoveTo`.
- `diff` compares the official list with your sources and shows names and flags present in only one of them. The sources mark more functions DebugOnly than the wiki does, and `check` uses both.

## Check your scripts

```
sf-papyrus-ref check "C:\MyMod\Scripts\Source" --allow Debug.Trace
```

```
Source\MyQuest.psc:42: warning: Debug.Notification is DebugOnly: it does nothing in release builds on Xbox and PlayStation
Source\MyQuest.psc:87: warning: Utility.Wait is Latent and is called inside a loop: each pass waits for it to finish
Checked 6 files: 0 errors, 2 warnings.
```

- Give it files or folders (folders are searched below them), holding `.psc` sources or compiled `.pex` scripts.
- `--allow Script.Name` never reports that call. `--allow Debug.Trace` suits mods that log on purpose, because a Trace that vanishes on a console does no harm. Repeat the option, or separate names with commas.
- `--creations` makes DebugOnly an error. Use it before you publish to Bethesda Creations, where console players will run your mod.
- `--json` writes the findings for a script or a build step.
- A finding marked `[name only]` was matched by its name alone, because the tool could not tell the object's type. Run `build-local` for exact matches. `--strict` also reports names that only some scripts flag.
- It is a light reader, not a compiler. The Papyrus compiler stays the final judge of whether a script is correct.

## Use it from Claude Code (MCP)

Add it once (use the folder where you unzipped it):

```
claude mcp add sf-papyrus-ref -- python -I C:\Tools\sf-papyrus-ref\sf_papyrus_ref.py mcp --quiet
```

The agent then has four read-only tools: `papyrus_lookup`, `papyrus_script`, `papyrus_list_flag` and `papyrus_check`. A good line for your project's `CLAUDE.md` is "Look up every Papyrus function with papyrus_lookup before using it, and run papyrus_check on scripts you change." Other MCP clients start the same command.

## Commands and exit codes

| Command | What it does | Exit code |
|---|---|---|
| `lookup <Name or Script.Name>` | Where a name lives, its flags, its page, its signature | 0 found, 1 not found |
| `script <Script>` | Every function, event and struct on a script | 0 found, 1 not found |
| `list --flag <flag> [--script X]` | Every entry with a flag (latent, nondelayed, debugonly, betaonly, invsafe) | 0 some, 1 none |
| `data` | Which wiki revision the shipped list comes from | 0 |
| `build-local [--sources <path>]` | Builds the local cache from your Creation Kit sources | 0 done |
| `diff [--all]` | The official list against your sources | 0 done |
| `check <paths> [--allow X] [--creations] [--strict]` | BetaOnly, DebugOnly and Latent-in-loop calls | 0 clean, 1 findings |
| `mcp` | Read-only MCP server on stdin and stdout | 0 when the client closes it |

Exit code 2 always means a problem with the input: a bad option, a file that could not be read, or no sources found. Every command takes `--json`, `--quiet` (no byline), `--verbose`, `--log <file>`, `--cache <file>`, `--no-local` and `--data <file>`. `--version` shows the version and credits.

## Logs

If something goes wrong, run the same command with `--verbose` to see on screen what it read and decided, or with `--log sf-papyrus-ref.log` to save that to a file. The log names every file read and every call it matched by name only. It can show your user folder and Steam library paths, so read it before you post it.

## What is in the data, and what isn't

`data/official-names.json` lists, for each official Papyrus function, event and struct: its name, its script, its kind, its flags and a link to its official wiki page. The flags are the official wiki's category pages, and the list was built with `tools/build_names.py` from wiki revision 8392.

The tool ships **no** text from the wiki, **no** signatures and **no** script sources. Signatures appear only after you run `build-local`, and they come from the copy of the Creation Kit on your own machine.

## Similar tools

- [Papyrus Index](https://papyrus.bellcube.dev/) by BellCube is a searchable site for Papyrus in several games. Its Starfield data is from game version 1.15.216.
- [papyrus-tools](https://github.com/Kiyozz/papyrus-tools) by Kiyozz is a Papyrus linter, formatter and language server.
- Bethesda's VS Code extension (in the Creation Kit's `Tools\VSCodePapyrusAddon`) and [Papyrus Language Tools](https://github.com/joelday/papyrus-lang) give completion and hover help while you edit.
- The [official Creation Kit wiki](https://starfield.creationkit.bethesda.net/) has the full description of every function.

## Updates

When Bethesda updates the wiki, a new release of the name list follows. `sf-papyrus-ref data` shows which revision you have. Maintainers rebuild the list with `python -I tools/build_names.py --mirror <saved copy of the wiki> --diff`.

## License and credits

sf-papyrus-ref is by Richard Bejtlich and is free software under the [MIT license](LICENSE), with no warranty. The function and event names and their flags are from Bethesda's official Starfield Creation Kit wiki. Starfield, the Creation Kit and Papyrus belong to Bethesda Softworks. This is a community tool, and Bethesda neither made nor endorses it. The `.pex` reader is adapted from [sf-pex-tools](https://github.com/taosecurity/sf-pex-tools). [PRIVACY.md](PRIVACY.md) says what the tool reads and writes.

Report problems at https://github.com/taosecurity/sf-papyrus-ref/issues.
