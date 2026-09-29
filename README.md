# instanceprefs

```
pip install instanceprefs
```

Show the server list and the game options of one launcher instance as text, and copy them into another instance. One command instead of retyping server addresses one at a time, or hand made symlinks.

Python 3.9 or newer. No dependencies.

Built with AI assistance, reviewed and tested by me.

## What it does

```
cd <the folder holding your instance folders>

instanceprefs list .
instanceprefs show Adventure

instanceprefs copy --from Adventure --to Fabric --servers --options

instanceprefs copy --from Adventure --to Fabric --servers --apply
```

`list` prints one line per instance, with how many servers and options it holds.

`show` prints the servers and the options of one instance. Add `--json` for machine readable output.

`copy` brings the server list and the game options of one instance into another. **Without `--apply` it writes nothing** and only prints what it would do.

## What it will not do

- It never overwrites a server that is already in the target. Servers are matched on their address, so running the same copy twice changes nothing the second time.
- It never invents an option key the target does not already have. A key from another game version would be dropped on the next launch anyway, so it is reported as skipped instead of written.
- It only ever writes two files, `servers.dat` and `options.txt`, and it reads nothing else except `instance.cfg`, opened read only to get the display name of an instance. Account files, session files, logs, worlds and mods are never opened at all.
- It does not sync anything in the background. It runs when you run it.

Before writing, it keeps a copy of the file it is about to change, next to it, named `servers.dat.instanceprefs-backup` or `options.txt.instanceprefs-backup`. Writes go through a temporary file and a rename, so a crash in the middle leaves the old file intact.

## Options

- `--servers` copies the server list.
- `--options` copies the game options.
- `--only KEY` restricts `--options` to this key. Repeat it for several keys.
- `--apply` actually writes. Without it nothing is written.
- `--json` makes `show` print JSON.

## Copying options between two different game versions

`--options` copies every key the target already has, and that includes the bookkeeping keys the game writes for itself, such as the one holding the file version. Copying those from a newer instance into an older one may tell the game the file is newer than it is. I have not measured what the game does in that case. Between two different game versions, prefer naming the keys you actually want:

```
instanceprefs copy --from Adventure --to Fabric --options --only fov --only gamma --apply
```

## Where the files are

An instance folder holds `instance.cfg` and a game folder named `.minecraft` or `minecraft`, and the two files live inside that game folder. You can pass either the instance folder or the game folder. The names come from the upstream source file `launcher/InstanceCopyPrefs.cpp`, which matches `[.]?minecraft/`. Where the instance folders themselves live depends on your system and your launcher settings, so the examples above start with a `cd` rather than guessing a path for you.

A server entry may carry an icon. It is copied along with its server, but it is never printed: `show` only reports whether one is there.

## What is not verified

No real instance has been read while building this. The file layout comes from the public source of the launcher, and the tests run on example folders written by the tests themselves. The binary format of `servers.dat` was not read from any first hand specification, so the reader assumes nothing about the file being compressed: it looks at the first two bytes and writes back in the form it found.

If you run it on a real instance, please say so in an issue, whether it worked or not.

## Limits worth knowing

- Writing `options.txt` rewrites the whole file from the keys it understands. A line with no `:` in it, or a blank line, is not kept. The backup next to the file holds the original.
- Badly encoded text is carried through unchanged rather than repaired.
- A server entry carrying fields this tool does not know is copied whole, unchanged, but those fields are not printed.
- The game must be closed while copying, or it may write the old list back when it exits.

## Where this came from

The request this answers: https://github.com/PrismLauncher/PrismLauncher/issues/2205

## License

MIT. Younes Z.

This project is not affiliated with, endorsed by, or connected to any launcher or game vendor. Names are used only to say which files the tool reads.
