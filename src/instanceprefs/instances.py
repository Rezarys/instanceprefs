"""Locating an instance on disk, and reading the two files this tool touches.

Only two file names are ever opened, and they are listed here. Nothing else in
an instance is read, written or copied, which is why no account file, session
file or log can leave through this tool.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import nbt

#: The only file names this tool ever opens inside an instance.
ALLOWED_FILES = ("servers.dat", "options.txt")

#: The game folder inside an instance is called one of these. Read from the
#: upstream source file launcher/InstanceCopyPrefs.cpp, which matches "[.]?minecraft/".
GAME_ROOT_NAMES = (".minecraft", "minecraft")

#: The keys a server entry is known to carry. Anything else found in the file is
#: kept as is when copying, but is not printed, so an unexpected field never
#: reaches the terminal by accident.
SERVER_FIELDS = ("name", "ip", "acceptTextures", "hidden")


class InstanceError(ValueError):
    """Raised when a path is not usable as an instance."""


def game_root(instance_dir: Path) -> Path:
    """Return the game folder of an instance.

    Accepts either the instance folder or the game folder itself, because people
    hand over whichever one their file manager was showing.
    """
    instance_dir = Path(instance_dir)
    if not instance_dir.is_dir():
        raise InstanceError(f"not a directory: {instance_dir}")
    for name in GAME_ROOT_NAMES:
        candidate = instance_dir / name
        if candidate.is_dir():
            return candidate
    for name in ALLOWED_FILES:
        if (instance_dir / name).is_file():
            return instance_dir
    raise InstanceError(
        f"no game folder in {instance_dir}: expected one of {', '.join(GAME_ROOT_NAMES)}"
    )


def instance_name(instance_dir: Path) -> Optional[str]:
    """Read the display name from instance.cfg, or None when there is no such file."""
    config = Path(instance_dir) / "instance.cfg"
    if not config.is_file():
        return None
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "name":
            return value.strip()
    return None


def find_instances(root: Path) -> List[Path]:
    """List the instance folders directly under a folder, sorted by name."""
    root = Path(root)
    if not root.is_dir():
        raise InstanceError(f"not a directory: {root}")
    found = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir():
            continue
        if (entry / "instance.cfg").is_file() or any(
            (entry / name).is_dir() for name in GAME_ROOT_NAMES
        ):
            found.append(entry)
    return found


# ---------------------------------------------------------------- server list


class ServerList:
    """The server list of one instance, with the file shape it was read from."""

    def __init__(self, root_name: str, root: nbt.Tag, compressed: bool, path: Path) -> None:
        self.root_name = root_name
        self.root = root
        self.compressed = compressed
        self.path = path

    @property
    def entries(self) -> List[nbt.Tag]:
        servers = self.root.value.get("servers")
        if servers is None:
            servers = nbt.Tag(nbt.LIST, [], nbt.COMPOUND)
            self.root.value["servers"] = servers
        return servers.value

    def as_dicts(self) -> List[Dict[str, object]]:
        """The entries as plain values, limited to the known fields."""
        out = []
        for entry in self.entries:
            row: Dict[str, object] = OrderedDict()
            for field in SERVER_FIELDS:
                tag = entry.value.get(field)
                if tag is not None:
                    row[field] = tag.value
            row["icon"] = "present" if "icon" in entry.value else "absent"
            out.append(row)
        return out

    def address_of(self, entry: nbt.Tag) -> str:
        tag = entry.value.get("ip")
        return tag.value if tag is not None else ""

    def to_bytes(self) -> bytes:
        return nbt.dumps(self.root_name, self.root, self.compressed)


def empty_server_list(path: Path, compressed: bool = False) -> ServerList:
    root = nbt.Tag(nbt.COMPOUND, OrderedDict())
    root.value["servers"] = nbt.Tag(nbt.LIST, [], nbt.COMPOUND)
    return ServerList("", root, compressed, path)


def read_servers(root: Path) -> ServerList:
    path = Path(root) / "servers.dat"
    if not path.is_file():
        return empty_server_list(path)
    name, tag, compressed = nbt.loads(path.read_bytes())
    return ServerList(name, tag, compressed, path)


def merge_servers(source: ServerList, target: ServerList) -> Tuple[List[str], List[str]]:
    """Add the source servers missing from the target, matching on the address.

    Returns the names added and the names skipped. An entry already present is
    never modified, so running this twice changes nothing the second time.
    """
    known = {target.address_of(entry) for entry in target.entries}
    added: List[str] = []
    skipped: List[str] = []
    for entry in source.entries:
        address = source.address_of(entry)
        label = entry.value["name"].value if "name" in entry.value else address
        if address in known:
            skipped.append(label)
            continue
        target.entries.append(entry)
        known.add(address)
        added.append(label)
    return added, skipped


# -------------------------------------------------------------- game options


def read_options(root: Path) -> "OrderedDict[str, str]":
    """Read options.txt as key to value, keeping the order of the file."""
    path = Path(root) / "options.txt"
    options: "OrderedDict[str, str]" = OrderedDict()
    if not path.is_file():
        return options
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        options[key.strip()] = value
    return options


def merge_options(
    source: "OrderedDict[str, str]",
    target: "OrderedDict[str, str]",
    keys: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    """Bring options over. Returns the keys changed and the keys left alone.

    A key the target does not know is never invented: the game writes back only
    what it understands, and a key from another game version would be dropped
    on the next launch anyway. Unknown keys are reported as skipped, and so is a
    key that already holds the same value.
    """
    changed: List[str] = []
    skipped: List[str] = []
    for key, value in source.items():
        if keys is not None and key not in keys:
            continue
        if key not in target or target[key] == value:
            skipped.append(key)
            continue
        target[key] = value
        changed.append(key)
    return changed, skipped


def render_options(options: "OrderedDict[str, str]") -> str:
    return "".join(f"{key}:{value}\n" for key, value in options.items())


def write_text_atomic(path: Path, text: str) -> None:
    _write_atomic(path, text.encode("utf-8"))


def write_bytes_atomic(path: Path, data: bytes) -> None:
    _write_atomic(path, data)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write through a temporary file in the same folder, then replace.

    A half written server list is worse than no change at all, and a power cut
    in the middle of a copy is exactly the case this guards against.
    """
    path = Path(path)
    temporary = path.with_name(path.name + ".instanceprefs-new")
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def backup(path: Path) -> Optional[Path]:
    """Copy a file next to itself before it is changed. Returns the copy, or None."""
    path = Path(path)
    if not path.is_file():
        return None
    target = path.with_name(path.name + ".instanceprefs-backup")
    target.write_bytes(path.read_bytes())
    return target
