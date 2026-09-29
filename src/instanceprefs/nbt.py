"""A small reader and writer for the binary tag format used by ``servers.dat``.

No dependency. Only the tag types that a server list actually contains are
exercised by the tests, but every type defined by the format is handled so an
unknown file is never silently truncated.

The file may or may not be gzip compressed. This module never assumes: it looks
at the first two bytes when reading, and writes back in the form it found.
"""

from __future__ import annotations

import gzip
import struct
from typing import Any, BinaryIO, Dict, List, Tuple

END = 0
BYTE = 1
SHORT = 2
INT = 3
LONG = 4
FLOAT = 5
DOUBLE = 6
BYTE_ARRAY = 7
STRING = 8
LIST = 9
COMPOUND = 10
INT_ARRAY = 11
LONG_ARRAY = 12

GZIP_MAGIC = b"\x1f\x8b"


class NbtError(ValueError):
    """Raised when a file is not readable as a binary tag file."""


class Tag:
    """A value together with the tag type it was read as.

    Keeping the type means a file can be written back with the same types it
    came with, instead of guessing them from the Python value.
    """

    __slots__ = ("type", "value", "subtype")

    def __init__(self, type_: int, value: Any, subtype: int = END) -> None:
        self.type = type_
        self.value = value
        self.subtype = subtype

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Tag(type={self.type}, value={self.value!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tag):
            return NotImplemented
        return (self.type, self.value, self.subtype) == (other.type, other.value, other.subtype)


def _decode_string(raw: bytes) -> str:
    """Decode the modified UTF-8 used by the format.

    Two things differ from plain UTF-8: a null character is written as two
    bytes, and a character outside the basic multilingual plane is written as
    the two halves of its surrogate pair, three bytes each.
    """
    raw = raw.replace(b"\xc0\x80", b"\x00")
    text = raw.decode("utf-8", errors="surrogatepass")
    if any("\ud800" <= ch <= "\udfff" for ch in text):
        text = text.encode("utf-16-le", errors="surrogatepass").decode(
            "utf-16-le", errors="surrogatepass"
        )
    return text


def _encode_string(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        point = ord(ch)
        if point == 0:
            out += b"\xc0\x80"
        elif point > 0xFFFF:
            point -= 0x10000
            high = 0xD800 + (point >> 10)
            low = 0xDC00 + (point & 0x3FF)
            out += chr(high).encode("utf-8", errors="surrogatepass")
            out += chr(low).encode("utf-8", errors="surrogatepass")
        else:
            out += ch.encode("utf-8", errors="surrogatepass")
    return bytes(out)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise NbtError("file ends in the middle of a tag")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        length = self.unpack(">H")
        return _decode_string(self.take(length))

    def payload(self, type_: int) -> Tag:
        if type_ == BYTE:
            return Tag(type_, self.unpack(">b"))
        if type_ == SHORT:
            return Tag(type_, self.unpack(">h"))
        if type_ == INT:
            return Tag(type_, self.unpack(">i"))
        if type_ == LONG:
            return Tag(type_, self.unpack(">q"))
        if type_ == FLOAT:
            return Tag(type_, self.unpack(">f"))
        if type_ == DOUBLE:
            return Tag(type_, self.unpack(">d"))
        if type_ == BYTE_ARRAY:
            return Tag(type_, self.take(max(0, self.unpack(">i"))))
        if type_ == STRING:
            return Tag(type_, self.string())
        if type_ == LIST:
            subtype = self.unpack(">b")
            count = self.unpack(">i")
            items = [self.payload(subtype) for _ in range(max(0, count))]
            return Tag(type_, items, subtype)
        if type_ == COMPOUND:
            entries: Dict[str, Tag] = {}
            while True:
                child_type = self.unpack(">b")
                if child_type == END:
                    return Tag(type_, entries)
                name = self.string()
                entries[name] = self.payload(child_type)
        if type_ in (INT_ARRAY, LONG_ARRAY):
            count = max(0, self.unpack(">i"))
            fmt = ">i" if type_ == INT_ARRAY else ">q"
            return Tag(type_, [self.unpack(fmt) for _ in range(count)])
        raise NbtError(f"unknown tag type {type_}")


def _write_payload(out: bytearray, tag: Tag) -> None:
    type_ = tag.type
    if type_ == BYTE:
        out += struct.pack(">b", tag.value)
    elif type_ == SHORT:
        out += struct.pack(">h", tag.value)
    elif type_ == INT:
        out += struct.pack(">i", tag.value)
    elif type_ == LONG:
        out += struct.pack(">q", tag.value)
    elif type_ == FLOAT:
        out += struct.pack(">f", tag.value)
    elif type_ == DOUBLE:
        out += struct.pack(">d", tag.value)
    elif type_ == BYTE_ARRAY:
        out += struct.pack(">i", len(tag.value)) + bytes(tag.value)
    elif type_ == STRING:
        encoded = _encode_string(tag.value)
        out += struct.pack(">H", len(encoded)) + encoded
    elif type_ == LIST:
        subtype = tag.subtype if tag.value == [] else tag.value[0].type
        out += struct.pack(">b", subtype) + struct.pack(">i", len(tag.value))
        for item in tag.value:
            _write_payload(out, item)
    elif type_ == COMPOUND:
        for name, child in tag.value.items():
            encoded = _encode_string(name)
            out += struct.pack(">b", child.type)
            out += struct.pack(">H", len(encoded)) + encoded
            _write_payload(out, child)
        out += struct.pack(">b", END)
    elif type_ in (INT_ARRAY, LONG_ARRAY):
        fmt = ">i" if type_ == INT_ARRAY else ">q"
        out += struct.pack(">i", len(tag.value))
        for number in tag.value:
            out += struct.pack(fmt, number)
    else:  # pragma: no cover - guarded by the reader
        raise NbtError(f"unknown tag type {type_}")


def loads(data: bytes) -> Tuple[str, Tag, bool]:
    """Read a whole file. Returns the root name, the root tag, and whether it was gzipped."""
    compressed = data[:2] == GZIP_MAGIC
    if compressed:
        data = gzip.decompress(data)
    reader = _Reader(data)
    root_type = reader.unpack(">b")
    if root_type != COMPOUND:
        raise NbtError("the file does not start with a compound tag")
    name = reader.string()
    return name, reader.payload(COMPOUND), compressed


def dumps(name: str, root: Tag, compressed: bool) -> bytes:
    """Write a whole file back, in the same form it was read."""
    out = bytearray()
    encoded = _encode_string(name)
    out += struct.pack(">b", COMPOUND)
    out += struct.pack(">H", len(encoded)) + encoded
    _write_payload(out, root)
    data = bytes(out)
    if compressed:
        # mtime is pinned so that writing the same content twice gives the same file.
        return gzip.compress(data, mtime=0)
    return data


def read_file(handle: BinaryIO) -> Tuple[str, Tag, bool]:
    return loads(handle.read())


__all__ = [
    "Tag",
    "NbtError",
    "loads",
    "dumps",
    "read_file",
    "BYTE",
    "STRING",
    "LIST",
    "COMPOUND",
]
