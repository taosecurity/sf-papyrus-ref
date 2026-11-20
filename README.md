# sf-papyrus-ref

sf-papyrus-ref answers "does this Papyrus function exist in Starfield, on which script, and is it safe on Xbox?" offline, from the command line, in about a tenth of a second. It also checks your mod's scripts for calls that never work on consoles or should never ship.

Download the latest zip from the [releases page](https://github.com/taosecurity/sf-papyrus-ref/releases), unzip it, open a Command Prompt in the folder and look a name up:

```
sf-papyrus-ref lookup Debug.Notification
```

For AI assistants: step-by-step instructions are in [AGENTS.md](AGENTS.md). They include the MCP server setup for Claude Code.

## Example

Look up a function. This run is on a fresh install, before `build-local`, so it shows the official flags and wiki page but no signature yet:

```
> sf-papyrus-ref lookup Debug.Notification
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
Debug.Notification  (function)
  Flags: DebugOnly
  Official page: https://starfield.creationkit.bethesda.net/w/index.php?title=Notification_-_Debug
Run 'sf-papyrus-ref build-local' once to see signatures from your own Creation Kit sources.
```

Check a script. The release zip holds a small made-up test script in `tests\fixtures`, as source (`.psc`) and compiled (`.pex`):

```
> sf-papyrus-ref check tests\fixtures\SfprFixture.psc --allow Debug.Trace
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
tests\fixtures\SfprFixture.psc:8: warning: Debug.Notification is DebugOnly: it does nothing in release builds on Xbox and PlayStation
tests\fixtures\SfprFixture.psc:11: warning: Utility.Wait is Latent and is called inside a loop: each pass waits for it to finish
tests\fixtures\SfprFixture.psc:15: error: Game.Warning is BetaOnly: it is meant for beta builds and should never ship
tests\fixtures\SfprFixture.psc:31: warning: Debug.MessageBox is DebugOnly: it does nothing in release builds on Xbox and PlayStation
Checked 1 files: 1 errors, 3 warnings.
```

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

sf-papyrus-ref needs Python 3.9 or newer, on Windows or Linux. There's nothing else to install, because it uses Python's standard library only.

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/). On the first screen of the installer, tick **Add python.exe to PATH**. To check that it worked, open a new Command Prompt and type `python --version`. It should print a version number.
2. Download `sf-papyrus-ref-0.1.0.zip` and its `.sha256` file from the [releases page](https://github.com/taosecurity/sf-papyrus-ref/releases).
3. Check the zip. On Windows, run `certutil -hashfile sf-papyrus-ref-0.1.0.zip SHA256` and compare the result with the `.sha256` file. On Linux, run `sha256sum -c sf-papyrus-ref-0.1.0.zip.sha256`.
4. Unzip it anywhere, for example `C:\Tools\sf-papyrus-ref`. Keep its files together.
5. Open the unzipped folder in File Explorer, click the address bar at the top, type `cmd` and press Enter. A Command Prompt window opens in that folder, ready for the commands below.
6. Try it:

   ```
   sf-papyrus-ref lookup Utility.Wait
   ```

On Linux, use `./sf-papyrus-ref lookup Utility.Wait`. The launchers simply run `python -I sf_papyrus_ref.py` with your arguments, so `python -I sf_papyrus_ref.py lookup Utility.Wait` works too.

## Words used here

- **Papyrus:** Starfield's scripting language. Scripts are written as `.psc` source files and compiled into `.pex` files that the game runs. A mod's scripts are what make things happen in the game, such as starting a quest or giving an item.
- **Function, event and struct:** a function is something a script can call (`Debug.Notification`), an event is something the game calls on a script when a thing happens (`OnActivate`), and a struct is a small group of named values.
- **Creation Kit (CK):** Bethesda's official editor for making Starfield mods. Its download includes the source of the game's own scripts, in `Tools\ContentResources.zip`.
- **Latent:** a function that makes the script wait until it finishes, such as `Utility.Wait`.
- **DebugOnly and BetaOnly:** functions that work only in debug or beta builds of the game. On Xbox and PlayStation they do nothing.
- **SFSE:** the Starfield Script Extender, which adds features the game lacks, on PC only. Its functions aren't on the official list.
- **MCP (Model Context Protocol):** a standard way for AI assistants to call a tool.

## lookup: where a name lives

Give it a name, or a script and a name. The Example above shows a name that exists. A misspelled name is reported as not found, with near matches, and exits with code 1:

```
> sf-papyrus-ref lookup Notifcation
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
Notifcation: Not in the official list. It may be a script extender (SFSE) function, a function from another mod's script, or a made-up name. The Papyrus compiler is the final judge.
Did you mean: Notification, OnStoryInfection, GetClassification, IsInFaction, GetLocation
```

## script: everything on one script

`script` lists a script's functions, events and structs, with each one's flags:

```
> sf-papyrus-ref script Utility
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
Utility - Functions (25)
  CallGlobalFunction  [Latent, Non-delayed]
  CallGlobalFunctionNoWait  [Non-delayed]
  ExpiryDay
  GameTimeToString
...
  Wait  [Latent]
...
```

## list: everything with one flag

`list --flag` takes latent, nondelayed, debugonly, betaonly or invsafe. Add `--script` to look at one script only:

```
> sf-papyrus-ref list --flag latent --script Utility
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
Utility.CallGlobalFunction  (function)
Utility.Wait  (function)
Utility.WaitGameTime  (function)
Utility.WaitMenuPause  (function)
4 entries flagged Latent on Utility.
```

## data: where the list comes from

```
> sf-papyrus-ref data
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
Data file: ...\sf-papyrus-ref\data\official-names.json
Official wiki revision 8392, list built 2026-11-20.
103 scripts, 1390 functions, 260 events, 3 structs.
Flags: Latent 63, Non-delayed 194, DebugOnly 56, BetaOnly 2, Inventory-safe 37
Names and flag categories from the official Starfield Creation Kit wiki (starfield.creationkit.bethesda.net). Names, flags and links only: no wiki text, no signatures and no game script sources.
```

## build-local: read signatures from your own Creation Kit (recommended)

The shipped list holds names and flags only. Run this once to add signatures and parent scripts from your own Creation Kit:

```
> sf-papyrus-ref build-local
sf-papyrus-ref 0.1.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
Read 1702 scripts (8381 functions, events and structs) from C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip.
102 of the 103 scripts on the official list are among them.
Saved the local cache to C:\Users\<you>\AppData\Local\sf-papyrus-ref\local.json (it stays on this machine; never share it).
```

(The user name in the cache path is replaced with `<you>`.)

It finds `Tools\ContentResources.zip` in your Steam Starfield folder (in any Steam library) and reads the script sources inside it without extracting them. That takes about a second. It saves a cache to `%LOCALAPPDATA%\sf-papyrus-ref\local.json` on Windows, or `~/.cache/sf-papyrus-ref/local.json` on Linux. The cache is made from Bethesda's files, so keep it on your machine.

- **Steam:** found on its own. The Creation Kit is a free Steam tool ("Starfield Creation Kit").
- **Game Pass:** the Creation Kit ships only on Steam. If you have the sources somewhere else, pass their location with `--sources`.
- **Extracted sources, MO2 or Vortex:** if you unpacked the sources into a folder (for example `Data\Scripts\Source`, or an MO2 mod folder), pass it with `--sources <folder>`. Use the folder that holds `Debug.psc`.

Once the cache exists, these commands improve:

- `lookup` and `script` show each signature, and `lookup` also finds functions on the game's other scripts, such as quest scripts. After `build-local`, the Example lookup gains the line `Signature (your sources): Function Notification(string asNotificationText) native global`.
- `check` follows parent scripts. For example, a call to `MoveTo` on an Actor is matched to `ObjectReference.MoveTo`.
- `diff` compares the official list with your sources (see below).

## diff: the official list against your sources

`diff` shows names and flags present in only one of the two lists. The sources mark more functions DebugOnly than the wiki does, and `check` uses both.

```
> sf-papyrus-ref diff --quiet
Official list (wiki revision 8392) against your sources (C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip).
Scripts on the official list but not in your sources: 1: Array
Names on the wiki but not in your sources: 2
  Game.EnableFastTravel
  ObjectReference.OnDeath
Names in your sources but not on the wiki: 497
  ActiveMagicEffect.OnActivate
...
```

## check: check your scripts

```
sf-papyrus-ref check "C:\MyMod\Scripts\Source" --allow Debug.Trace
```

The Example above shows its output on the bundled test script.

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

Exit code 2 always means a problem with the input: a bad option, a file that could not be read, or no sources found.

Every command takes `--json`, `--quiet` (no byline), `--verbose`, `--log <file>`, `--cache <file>`, `--no-local` and `--data <file>`. `--version` shows the version and credits.

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

## Found a mistake?

Open an issue: https://github.com/taosecurity/sf-papyrus-ref/issues

## Credits and License

- sf-papyrus-ref is by Richard Bejtlich. It uses only the [Python](https://www.python.org/) standard library.
- The function and event names and their flags are from Bethesda's [official Starfield Creation Kit wiki](https://starfield.creationkit.bethesda.net/).
- The `.pex` reader is adapted from [sf-pex-tools](https://github.com/taosecurity/sf-pex-tools).
- Starfield, the Creation Kit and Papyrus belong to Bethesda Softworks. This is a community tool, and Bethesda neither made nor endorses it.
- [PRIVACY.md](PRIVACY.md) says what the tool reads and writes.

sf-papyrus-ref is free software under the [MIT License](LICENSE), with no warranty.
