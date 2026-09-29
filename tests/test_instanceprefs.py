"""Tests. They run on example folders written by the tests themselves.

No real instance is read anywhere in this suite, which is also said in the README.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from collections import OrderedDict
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from instanceprefs import instances, nbt  # noqa: E402
from instanceprefs.cli import main  # noqa: E402


def server_entry(name: str, address: str, icon: bool = False) -> nbt.Tag:
    fields = OrderedDict()
    fields["name"] = nbt.Tag(nbt.STRING, name)
    fields["ip"] = nbt.Tag(nbt.STRING, address)
    fields["acceptTextures"] = nbt.Tag(nbt.BYTE, 1)
    if icon:
        fields["icon"] = nbt.Tag(nbt.STRING, "iVBORw0KGgo=")
    return nbt.Tag(nbt.COMPOUND, fields)


def servers_file(entries, compressed: bool = False) -> bytes:
    root = nbt.Tag(nbt.COMPOUND, OrderedDict())
    root.value["servers"] = nbt.Tag(nbt.LIST, list(entries), nbt.COMPOUND)
    return nbt.dumps("", root, compressed)


def make_instance(
    parent: Path,
    folder: str,
    name: str,
    servers=(),
    options=None,
    game_folder: str = ".minecraft",
    compressed: bool = False,
) -> Path:
    instance = parent / folder
    root = instance / game_folder
    root.mkdir(parents=True)
    (instance / "instance.cfg").write_text(
        f"InstanceType=OneSix\nname={name}\n", encoding="utf-8"
    )
    if servers:
        (root / "servers.dat").write_bytes(servers_file(servers, compressed))
    if options:
        (root / "options.txt").write_text(
            "".join(f"{key}:{value}\n" for key, value in options.items()), encoding="utf-8"
        )
    return instance


class NbtRoundTrip(unittest.TestCase):
    def test_plain_round_trip(self):
        data = servers_file([server_entry("Home", "play.example.test")])
        name, root, compressed = nbt.loads(data)
        self.assertEqual(name, "")
        self.assertFalse(compressed)
        self.assertEqual(nbt.dumps(name, root, compressed), data)

    def test_gzip_is_detected_and_kept(self):
        data = servers_file([server_entry("Home", "play.example.test")], compressed=True)
        self.assertEqual(data[:2], nbt.GZIP_MAGIC)
        name, root, compressed = nbt.loads(data)
        self.assertTrue(compressed)
        again = nbt.dumps(name, root, compressed)
        self.assertEqual(nbt.loads(again)[1].value["servers"].value[0].value["ip"].value,
                         "play.example.test")

    def test_strings_outside_the_basic_plane_survive(self):
        for text in ["plain", "accentué", "emoji \U0001F600 here", "with\x00null"]:
            with self.subTest(text=text):
                root = nbt.Tag(nbt.COMPOUND, OrderedDict([("s", nbt.Tag(nbt.STRING, text))]))
                data = nbt.dumps("", root, False)
                self.assertEqual(nbt.loads(data)[1].value["s"].value, text)

    def test_every_tag_type_round_trips(self):
        fields = OrderedDict()
        fields["b"] = nbt.Tag(nbt.BYTE, -3)
        fields["s"] = nbt.Tag(nbt.SHORT, 300)
        fields["i"] = nbt.Tag(nbt.INT, -70000)
        fields["l"] = nbt.Tag(nbt.LONG, 2**40)
        fields["d"] = nbt.Tag(nbt.DOUBLE, 0.5)
        fields["ba"] = nbt.Tag(nbt.BYTE_ARRAY, b"\x01\x02")
        fields["ia"] = nbt.Tag(nbt.INT_ARRAY, [1, 2, 3])
        fields["la"] = nbt.Tag(nbt.LONG_ARRAY, [1, 2])
        fields["empty"] = nbt.Tag(nbt.LIST, [], nbt.COMPOUND)
        root = nbt.Tag(nbt.COMPOUND, fields)
        data = nbt.dumps("root", root, False)
        read_name, read_root, _ = nbt.loads(data)
        self.assertEqual(read_name, "root")
        self.assertEqual(nbt.dumps(read_name, read_root, False), data)

    def test_truncated_file_is_refused(self):
        data = servers_file([server_entry("Home", "play.example.test")])
        with self.assertRaises(nbt.NbtError):
            nbt.loads(data[:8])


class Reading(unittest.TestCase):
    def test_game_root_is_found_under_both_names(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            dotted = make_instance(parent, "a", "A", game_folder=".minecraft")
            plain = make_instance(parent, "b", "B", game_folder="minecraft")
            self.assertEqual(instances.game_root(dotted).name, ".minecraft")
            self.assertEqual(instances.game_root(plain).name, "minecraft")

    def test_game_folder_itself_is_accepted(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            instance = make_instance(
                parent, "a", "A", servers=[server_entry("Home", "play.example.test")]
            )
            root = instance / ".minecraft"
            self.assertEqual(instances.game_root(root), root)

    def test_a_folder_without_a_game_folder_is_refused(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(instances.InstanceError):
                instances.game_root(Path(tmp))

    def test_missing_servers_file_reads_as_empty(self):
        with TemporaryDirectory() as tmp:
            instance = make_instance(Path(tmp), "a", "A")
            found = instances.read_servers(instances.game_root(instance))
            self.assertEqual(found.entries, [])

    def test_display_name_comes_from_the_config(self):
        with TemporaryDirectory() as tmp:
            instance = make_instance(Path(tmp), "a", "Adventure 1.20")
            self.assertEqual(instances.instance_name(instance), "Adventure 1.20")

    def test_instances_are_listed(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            make_instance(parent, "b", "B")
            make_instance(parent, "a", "A")
            (parent / "not-an-instance").mkdir()
            found = [p.name for p in instances.find_instances(parent)]
            self.assertEqual(found, ["a", "b"])

    def test_icons_are_reported_but_never_printed(self):
        with TemporaryDirectory() as tmp:
            instance = make_instance(
                Path(tmp), "a", "A", servers=[server_entry("Home", "play.example.test", icon=True)]
            )
            rows = instances.read_servers(instances.game_root(instance)).as_dicts()
            self.assertEqual(rows[0]["icon"], "present")
            self.assertNotIn("iVBORw0KGgo=", json.dumps(rows))


class Merging(unittest.TestCase):
    def test_servers_merge_on_the_address_and_repeat_cleanly(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = make_instance(
                parent,
                "a",
                "A",
                servers=[server_entry("Home", "home.example.test"),
                         server_entry("Friend", "friend.example.test")],
            )
            target = make_instance(
                parent, "b", "B", servers=[server_entry("Home again", "home.example.test")]
            )
            source_list = instances.read_servers(instances.game_root(source))
            target_list = instances.read_servers(instances.game_root(target))
            added, skipped = instances.merge_servers(source_list, target_list)
            self.assertEqual(added, ["Friend"])
            self.assertEqual(skipped, ["Home"])
            self.assertEqual(len(target_list.entries), 2)

            added_again, _ = instances.merge_servers(source_list, target_list)
            self.assertEqual(added_again, [])
            self.assertEqual(len(target_list.entries), 2)

    def test_options_do_not_invent_keys(self):
        source = OrderedDict([("fov", "0.7"), ("unknownKey", "1")])
        target = OrderedDict([("fov", "0.5")])
        changed, skipped = instances.merge_options(source, target)
        self.assertEqual(changed, ["fov"])
        self.assertEqual(skipped, ["unknownKey"])
        self.assertEqual(target["fov"], "0.7")
        self.assertNotIn("unknownKey", target)

    def test_options_can_be_restricted_to_named_keys(self):
        source = OrderedDict([("fov", "0.7"), ("gamma", "1.0")])
        target = OrderedDict([("fov", "0.5"), ("gamma", "0.0")])
        changed, _ = instances.merge_options(source, target, keys=["gamma"])
        self.assertEqual(changed, ["gamma"])
        self.assertEqual(target["fov"], "0.5")

    def test_an_identical_option_is_not_reported_as_changed(self):
        source = OrderedDict([("fov", "0.5")])
        target = OrderedDict([("fov", "0.5")])
        changed, skipped = instances.merge_options(source, target)
        self.assertEqual(changed, [])
        self.assertEqual(skipped, ["fov"])

    def test_a_line_without_a_separator_is_dropped_on_rewrite(self):
        """Known limit, written in the README: the file is rebuilt from the keys read."""
        with TemporaryDirectory() as tmp:
            instance = make_instance(Path(tmp), "a", "A")
            root = instance / ".minecraft"
            (root / "options.txt").write_text("fov:0.5\n\nnot a setting\n", encoding="utf-8")
            options = instances.read_options(root)
            self.assertEqual(list(options), ["fov"])
            self.assertEqual(instances.render_options(options), "fov:0.5\n")

    def test_option_order_is_kept(self):
        options = OrderedDict([("b", "1"), ("a", "2")])
        self.assertEqual(instances.render_options(options), "b:1\na:2\n")


class CommandLine(unittest.TestCase):
    def run_cli(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def two_instances(self, parent: Path):
        source = make_instance(
            parent,
            "a",
            "A",
            servers=[server_entry("Friend", "friend.example.test")],
            options=OrderedDict([("fov", "0.7")]),
        )
        target = make_instance(
            parent, "b", "B", servers=[], options=OrderedDict([("fov", "0.5")])
        )
        return source, target

    def test_copy_writes_nothing_without_apply(self):
        with TemporaryDirectory() as tmp:
            source, target = self.two_instances(Path(tmp))
            before = (target / ".minecraft" / "options.txt").read_bytes()
            code, out = self.run_cli(
                ["copy", "--from", str(source), "--to", str(target), "--servers", "--options"]
            )
            self.assertEqual(code, 0)
            self.assertIn("add server Friend", out)
            self.assertIn("nothing was written", out)
            self.assertEqual((target / ".minecraft" / "options.txt").read_bytes(), before)
            self.assertFalse((target / ".minecraft" / "servers.dat").exists())

    def test_apply_writes_and_keeps_a_backup(self):
        with TemporaryDirectory() as tmp:
            source, target = self.two_instances(Path(tmp))
            code, _ = self.run_cli(
                ["copy", "--from", str(source), "--to", str(target),
                 "--servers", "--options", "--apply"]
            )
            self.assertEqual(code, 0)
            root = target / ".minecraft"
            self.assertEqual(instances.read_options(root)["fov"], "0.7")
            self.assertEqual(
                (root / "options.txt.instanceprefs-backup").read_text(encoding="utf-8"),
                "fov:0.5\n",
            )
            written = instances.read_servers(root)
            self.assertEqual([row["ip"] for row in written.as_dicts()], ["friend.example.test"])

    def test_copy_refuses_the_same_instance(self):
        with TemporaryDirectory() as tmp:
            source, _ = self.two_instances(Path(tmp))
            code, _ = self.run_cli(
                ["copy", "--from", str(source), "--to", str(source), "--servers"]
            )
            self.assertEqual(code, 2)

    def test_copy_needs_something_to_copy(self):
        with TemporaryDirectory() as tmp:
            source, target = self.two_instances(Path(tmp))
            code, _ = self.run_cli(["copy", "--from", str(source), "--to", str(target)])
            self.assertEqual(code, 2)

    def test_show_prints_json(self):
        with TemporaryDirectory() as tmp:
            source, _ = self.two_instances(Path(tmp))
            code, out = self.run_cli(["show", str(source), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["servers"][0]["ip"], "friend.example.test")
            self.assertEqual(payload["options"]["fov"], "0.7")

    def test_list_prints_one_line_per_instance(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            self.two_instances(parent)
            code, out = self.run_cli(["list", str(parent)])
            self.assertEqual(code, 0)
            self.assertEqual(len(out.strip().splitlines()), 2)
            self.assertIn("1 server(s)", out)

    def test_list_on_an_empty_folder_is_an_error(self):
        with TemporaryDirectory() as tmp:
            code, out = self.run_cli(["list", tmp])
            self.assertEqual(code, 1)
            self.assertIn("no instance found", out)

    def test_a_bad_path_is_reported_not_raised(self):
        code = main(["show", "/definitely/not/here"])
        self.assertEqual(code, 1)

    def test_no_command_prints_help(self):
        code, out = self.run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("instanceprefs", out)


if __name__ == "__main__":
    unittest.main()
