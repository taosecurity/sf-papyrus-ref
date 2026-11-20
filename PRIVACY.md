# Privacy

sf-papyrus-ref runs on your own computer, offline. It collects no data and sends nothing anywhere.

## What it does not do

- It makes no network connections, in any mode, including `mcp`.
- It has no telemetry, analytics, crash reporting or update checks.
- It starts no other programs.

## What it reads

- `data/official-names.json`, which ships with it.
- The scripts and folders you name for `check`.
- For `build-local`: the Creation Kit's script sources. These are `Tools\ContentResources.zip`, or the folder you name with `--sources`. To find them, it reads Steam's `libraryfolders.vdf`, which lists your Steam library folders.
- The local cache that `build-local` wrote.

## What it writes

- `build-local` writes one file, the local cache. On Windows it goes in `%LOCALAPPDATA%\sf-papyrus-ref\local.json`, and on Linux in `~/.cache/sf-papyrus-ref/local.json` (or the path you give with `--cache`). It holds the names, signatures and parent scripts read from your own Creation Kit sources. **Keep it on your machine and don't share it**, because it is made from Bethesda's files.
- `--log <file>` writes a troubleshooting log to that file.

Nothing else.

## What the output contains

The output shows the paths of the files you named, the names in your scripts, and, after `build-local`, signatures from your own sources. A log can also show your Steam library paths and your user folder. Read a log before you post it.

## Downloading it

Downloading sf-papyrus-ref from GitHub is covered by GitHub's own [privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement). The author receives only the public download counts that GitHub shows.

## Questions

Open an issue at https://github.com/taosecurity/sf-papyrus-ref/issues.
