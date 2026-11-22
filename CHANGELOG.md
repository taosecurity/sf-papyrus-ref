# Changelog

## 0.2.3 (2026-11-22)

### Fixes

- **Long script names no longer run into each other.** On the A-Z page, fragment names such as `DLC03:Fragments:TopicInfos:TIF_SFBGS003_DialogueTAHQ_FD000DE9` were wider than their column and overlapped the next one, at any zoom level.
  - When a script's namespace is exactly its folder (for example `DLC03:Fragments:Quests:` in `DLC03/Fragments/Quests`), the list shows only the last part of its name, because the heading already gives the folder. The namespace stays in the page, visually hidden, so Ctrl+F and screen readers still find the full name, and the full name is also the link's tooltip. Any other name is shown in full.
  - Each folder's list is sorted A to Z by the name you see.
  - A name that is still too long wraps inside its own column.
  - The other column lists wrap the same way, including names shown as plain text: What's new, Most extended, Inherited, the stand-alone scripts and "places call this function".

### Example

    > sf-papyrus-ref html --include-fragments --out PapyrusSource
    sf-papyrus-ref 0.2.3 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    It read 5033 scripts (24731 functions, events and structs) from C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip.
    It linked 87540 calls to the function they reach.
    It wrote 5036 pages to C:\Users\<you>\Documents\PapyrusSource. Open C:\Users\<you>\Documents\PapyrusSource\index.html in your browser.
    These pages hold Bethesda's script text from your own install: keep them on your PC or home network, and never publish them.

The example ran from the Documents folder; the user name in the path is replaced with `<you>`.

## 0.2.2 (2026-11-22)

### What's new

- **Every page carries a personal-use warning.** A small line under the header says that the pages are built from the owner's own Starfield game files, contain Bethesda's proprietary content, and must not be shared, published or distributed.
- **The site links back to sf-papyrus-ref.** Each page's footer names the tool and its version with a link to this repository, and the front page shows the exact command that built it.
- **The front page explains how the site was made.** The section "This is how the site is made." opens with the intellectual-property warning. It then gives the command, the sources and versions read, the five steps the tool took, a short description of every command, and how to build your own copy.

### Example

    > sf-papyrus-ref html --include-fragments --out PapyrusSource
    sf-papyrus-ref 0.2.2 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    It read 5033 scripts (24731 functions, events and structs) from C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip.
    It linked 87540 calls to the function they reach.
    It wrote 5036 pages to C:\Users\<you>\Documents\PapyrusSource. Open C:\Users\<you>\Documents\PapyrusSource\index.html in your browser.
    These pages hold Bethesda's script text from your own install: keep them on your PC or home network, and never publish them.

### Notes

- The example ran from the Documents folder; the user name in the path is replaced with `<you>`.
- The warning text also appears in the README's `html` section and in AGENTS.md, so people and AI assistants read it before they build.

## 0.2.1 (2026-11-21)

### What's new

- **The `html` front page explains the scripts.** It says what a script is and how the game uses it, with a diagram. It names the game and Creation Kit versions (read from `Starfield.exe` and `CreationKit.exe`) and the content the sources cover: the base game, the free update in SFBGS00D.esm and the Trackers Alliance.
- **One script is explained line by line.** The front page walks a novice through `DefaultSetGlobalOnTriggerEnter`. The release ships only the explanations; the lines come from your own Creation Kit when the site is built.
- **Each folder has a description.** The "Scripts by folder" table and the A-Z page say what kind of scripts each folder holds.
- **What's new lists script changes.** Each rebuild compares the scripts with the last build and lists the ones that were added, removed or changed, for example after a Creation Kit update.

### Example

    > sf-papyrus-ref html
    sf-papyrus-ref 0.2.1 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    It read 1702 scripts (8381 functions, events and structs) from C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip.
    It linked 30068 calls to the function they reach.
    It wrote 1705 pages to C:\Users\<you>\AppData\Local\sf-papyrus-ref\site. Open C:\Users\<you>\AppData\Local\sf-papyrus-ref\site\index.html in your browser.
    These pages hold Bethesda's script text from your own install: keep them on your PC or home network, and never publish them.

### Fixes

- The site's headings, summaries and footer are now full sentences, and so are the summary lines that `html`, `compare`, `check`, `build-local`, `data` and `diff` print.

## 0.2.0 (2026-11-21)

### What's new

- **`html` builds a website of your Creation Kit's scripts.** It reads the script sources from your own Creation Kit and writes pages you open in your browser, offline. They include search, one page per script, the inheritance tree, every place a function is called from, and the highlighted source.
- **`compare` tells you which scripts came from the Creation Kit.** It checks `.psc` files against your Creation Kit's sources and reports each one as identical, changed (with lines added and removed) or not from the Creation Kit. Use it to see which of Bethesda's scripts a mod changes.

### Example

    > sf-papyrus-ref html
    sf-papyrus-ref 0.2.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    Read 1702 scripts (8381 functions, events and structs) from C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip.
    Linked 30068 calls to the function they reach.
    Wrote 1705 pages to C:\Users\<you>\AppData\Local\sf-papyrus-ref\site. Open C:\Users\<you>\AppData\Local\sf-papyrus-ref\site\index.html in your browser.
    These pages hold Bethesda's script text from your own install: keep them on your PC or home network, and never publish them.

    > sf-papyrus-ref compare MyMod\Scripts\Source --all
    sf-papyrus-ref 0.2.0 by Richard Bejtlich - MIT - https://github.com/taosecurity/sf-papyrus-ref
    identical  MyMod\Scripts\Source\Debug.psc
    not in CK  MyMod\Scripts\Source\MyQuestScript.psc  (Scriptname MyQuestScript)
    changed    MyMod\Scripts\Source\Utility.psc  (+4 -0 lines against Scripts/Source/Utility.psc)
    Compared 3 scripts with C:\Program Files (x86)\Steam\steamapps\common\Starfield\Tools\ContentResources.zip: 1 identical, 1 changed, 1 not from the Creation Kit.

### Notes

- The release still ships no script sources. The website exists only on the PC that runs `html`, made from that PC's own Creation Kit. Keep it there, or on your home network.
- The pages work offline and under a strict Content-Security-Policy, because they have no inline scripts.

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
