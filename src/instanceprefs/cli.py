"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import instances
from .instances import InstanceError
from .nbt import NbtError

DESCRIPTION = (
    "Show the server list and game options of a launcher instance as text, "
    "and copy them into another instance."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="instanceprefs", description=DESCRIPTION)
    sub = parser.add_subparsers(dest="command")

    listing = sub.add_parser("list", help="list the instances under a folder")
    listing.add_argument("folder", type=Path, help="the folder holding instance folders")

    show = sub.add_parser("show", help="print the servers and options of one instance")
    show.add_argument("instance", type=Path, help="an instance folder, or its game folder")
    show.add_argument("--json", action="store_true", help="print JSON instead of plain text")

    copy = sub.add_parser("copy", help="copy servers and options from one instance to another")
    copy.add_argument("--from", dest="source", type=Path, required=True, help="source instance")
    copy.add_argument("--to", dest="target", type=Path, required=True, help="target instance")
    copy.add_argument("--servers", action="store_true", help="copy the server list")
    copy.add_argument("--options", action="store_true", help="copy the game options")
    copy.add_argument(
        "--only",
        metavar="KEY",
        action="append",
        default=None,
        help="restrict --options to this key; repeat for several keys",
    )
    copy.add_argument(
        "--apply",
        action="store_true",
        help="actually write. Without it, nothing is written and the plan is printed.",
    )
    return parser


def _cmd_list(args: argparse.Namespace) -> int:
    found = instances.find_instances(args.folder)
    if not found:
        print(f"no instance found in {args.folder}")
        return 1
    for folder in found:
        name = instances.instance_name(folder) or folder.name
        try:
            root = instances.game_root(folder)
        except InstanceError:
            print(f"{folder.name}\t{name}\tno game folder")
            continue
        servers = instances.read_servers(root)
        options = instances.read_options(root)
        print(
            f"{folder.name}\t{name}\t{len(servers.entries)} server(s)\t{len(options)} option(s)"
        )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    root = instances.game_root(args.instance)
    servers = instances.read_servers(root)
    options = instances.read_options(root)
    if args.json:
        print(
            json.dumps(
                {"servers": servers.as_dicts(), "options": options},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print(f"game folder: {root}")
    print(f"servers ({len(servers.entries)}):")
    for row in servers.as_dicts():
        print(f"  {row.get('name', '')}\t{row.get('ip', '')}\ticon {row['icon']}")
    print(f"options ({len(options)}):")
    for key, value in options.items():
        print(f"  {key}:{value}")
    return 0


def _cmd_copy(args: argparse.Namespace) -> int:
    if not args.servers and not args.options:
        print("nothing to do: pass --servers, --options, or both", file=sys.stderr)
        return 2
    source_root = instances.game_root(args.source)
    target_root = instances.game_root(args.target)
    if source_root.resolve() == target_root.resolve():
        print("source and target are the same instance", file=sys.stderr)
        return 2

    planned: List[str] = []

    if args.servers:
        source_servers = instances.read_servers(source_root)
        target_servers = instances.read_servers(target_root)
        added, skipped = instances.merge_servers(source_servers, target_servers)
        for label in added:
            planned.append(f"add server {label}")
        for label in skipped:
            planned.append(f"keep server {label}, already there")
        if args.apply and added:
            instances.backup(target_servers.path)
            instances.write_bytes_atomic(target_servers.path, target_servers.to_bytes())

    if args.options:
        source_options = instances.read_options(source_root)
        target_options = instances.read_options(target_root)
        changed, skipped_keys = instances.merge_options(
            source_options, target_options, keys=args.only
        )
        for key in changed:
            planned.append(f"set option {key}")
        for key in skipped_keys:
            planned.append(f"keep option {key}")
        if args.apply and changed:
            path = target_root / "options.txt"
            instances.backup(path)
            instances.write_text_atomic(path, instances.render_options(target_options))

    if not planned:
        print("nothing to change")
        return 0
    for line in planned:
        print(line)
    if not args.apply:
        print("")
        print("nothing was written. Run the same command with --apply to write.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    handlers = {"list": _cmd_list, "show": _cmd_show, "copy": _cmd_copy}
    try:
        return handlers[args.command](args)
    except (InstanceError, NbtError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
