# SPDX-License-Identifier: GPL-2.0
"""The desktop and the header share the view stack's back action, without GTK."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from gi.repository import Gio


TREE = ast.parse((Path(__file__).resolve().parents[1] / "haltia-music").read_text())
MUSIC = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Music")
METHODS = {"do_startup", "show_nav", "go_root", "push", "go_back", "show_top",
           "drop_views", "drop", "remake_pages", "settings_view"}
# Run the window's navigation methods with stand-in pages; no display or player.
NAVIGATION = ast.Module(body=[ast.ClassDef(
    name="Navigation", bases=[], keywords=[], decorator_list=[],
    body=[node for node in MUSIC.body if isinstance(node, ast.FunctionDef)
          and node.name in METHODS])], type_ignores=[])
namespace = {"Gio": Gio, "Gtk": SimpleNamespace(Application=SimpleNamespace(do_startup=lambda _: None))}
exec(compile(ast.fix_missing_locations(NAVIGATION), "haltia-music", "exec"), namespace)
Navigation = namespace["Navigation"]


class Back(unittest.TestCase):
    def setUp(self):
        self.app = app = Navigation()
        self.actions = Gio.SimpleActionGroup()
        app.add_action = self.actions.add_action
        app.do_startup()
        app.views, app.roots, app.radio_view = [], {}, None
        app.stale = False
        app.sources = SimpleNamespace(shown=SimpleNamespace(id="test", label="Test"), on=lambda: [1])
        for name in ("back_btn", "home_btn", "browse_btn", "gear", "source_btn", "stack"):
            setattr(app, name, Mock())
        app.make_page = lambda view: view.update(page=Mock(), alive=True)
        app.update_hearts = app.mark_playing = app.refresh_home = Mock()

    def activate(self):
        self.actions.activate_action("back", None)

    def test_roots_have_no_back_step(self):
        self.assertFalse(self.actions.get_action_enabled("back"))
        for section in ("home", "browse"):
            self.app.go_root(section)
            self.assertFalse(self.actions.get_action_enabled("back"))
            root = self.app.views[0]
            self.activate()
            self.assertEqual(self.app.views, [root])
            self.app.back_btn.set_visible.assert_called_with(False)

    def test_every_deeper_page_goes_back_one_step(self):
        for section in ("home", "browse"):
            self.app.go_root(section)
            root = self.app.views[0]
            for kind in ("browse", "list", "search", "radio", "settings"):
                self.app.push({"kind": kind})
                self.assertTrue(self.actions.get_action_enabled("back"))
                self.app.back_btn.set_visible.assert_called_with(True)
            for depth in range(5, 0, -1):
                page = self.app.views[-1]
                self.activate()
                self.assertFalse(page["alive"])
                self.assertEqual(len(self.app.views), depth)
                self.assertEqual(self.actions.get_action_enabled("back"), depth > 1)
            self.assertIs(self.app.views[0], root)

    def test_reset_and_changed_settings_return_to_root(self):
        self.app.go_root("home")
        self.app.push({"kind": "settings"})
        self.app.stale = True
        self.activate()
        self.assertEqual([v["kind"] for v in self.app.views], ["home"])
        self.assertFalse(self.actions.get_action_enabled("back"))
        self.app.push({"kind": "search"})
        self.app.go_root("browse")
        self.assertFalse(self.actions.get_action_enabled("back"))
        self.app.push({"kind": "list"})
        self.app.drop_views()
        self.assertFalse(self.actions.get_action_enabled("back"))

    def test_header_reserves_left_corner_for_bound_arrow(self):
        method = next(node for node in MUSIC.body if getattr(node, "name", None) == "do_activate")
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
        def arguments(owner, method):
            return [[ast.unparse(arg) for arg in call.args] for call in calls
                    if isinstance(call.func, ast.Attribute) and call.func.attr == method
                    and ast.unparse(call.func.value) == owner]
        self.assertEqual(arguments("header", "pack_start"), [["corner"]])
        self.assertEqual(arguments("corner", "set_size_request"), [["110", "-1"]])
        self.assertEqual(arguments("corner", "pack_start"), [["self.back_btn", "False", "False", "0"]])
        self.assertEqual(arguments("self.back_btn", "set_action_name"), [["'app.back'"]])


if __name__ == "__main__":
    unittest.main()
