# SPDX-License-Identifier: GPL-2.0
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import Gio, GLib  # noqa: E402
import mpris  # noqa: E402
import playback  # noqa: E402
from haltia_kit.testing import FakePlayer  # noqa: E402
from tests import fake  # noqa: E402
from tests.fake import track  # noqa: E402

APP_ID = "io.github.haltia_de.Test"
NAME = "org.mpris.MediaPlayer2." + APP_ID


@unittest.skipUnless(shutil.which("dbus-daemon"), "no dbus-daemon")
class Case(unittest.TestCase):
    """The desktop's side: another connection on a bus of the test's own."""

    @classmethod
    def setUpClass(cls):
        cls.dbus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        cls.dbus.up()

    @classmethod
    def tearDownClass(cls):
        cls.dbus.down()

    def setUp(self):
        address = self.dbus.get_bus_address()
        flags = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                 | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        self.ours = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
        self.desk = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
        self.player = FakePlayer(on_pause=lambda on: self.s.paused(on))
        events = fake.Events()
        events.changed = lambda t: self.m.changed()
        events.playing = lambda on: self.m.changed()
        self.s = playback.Session(fake.Source(), lambda: self.player, fake.Work(),
                                  fake.Later(), events)
        self.stopped = self.shown = 0
        self.m = mpris.Mpris(self.ours, APP_ID, "Тест", self.s, self.stop, self.show,
                             lambda t: "file:///covers/%s.jpg" % t["id"])
        self.signals = []
        self.desk.signal_subscribe(None, None, None, mpris.PATH, None,
                                   Gio.DBusSignalFlags.NONE, self.heard)
        self.until(lambda: self.owner())

    def tearDown(self):
        self.m.close()
        self.ours.close_sync(None)
        self.desk.close_sync(None)

    def stop(self):
        self.stopped += 1
        self.s.stop()

    def show(self):
        self.shown += 1

    def heard(self, _bus, _sender, _path, _iface, signal, args):
        self.signals.append((signal, args.unpack()))

    def until(self, done):
        ctx = GLib.MainContext.default()
        for _ in range(500):
            if done():
                return
            ctx.iteration(True) if ctx.pending() else GLib.usleep(2000)
        self.fail("no answer on the bus")

    def ask(self, iface, method, args=None, reply=None):
        out = []
        self.desk.call(NAME, mpris.PATH, iface, method, args,
                       GLib.VariantType(reply) if reply else None,
                       Gio.DBusCallFlags.NONE, 2000, None,
                       lambda c, res: out.append(c.call_finish(res)))
        self.until(lambda: out)
        return out[0].unpack()

    def owner(self):
        out = []
        self.desk.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                       "NameHasOwner", GLib.Variant("(s)", (NAME,)), None,
                       Gio.DBusCallFlags.NONE, 2000, None,
                       lambda c, res: out.append(c.call_finish(res)))
        self.until(lambda: out)
        return out[0].unpack()[0]

    def get(self, name, iface=mpris.PLAYER):
        return self.ask("org.freedesktop.DBus.Properties", "Get",
                        GLib.Variant("(ss)", (iface, name)))[0]

    def control(self, method, args=None):
        return self.ask(mpris.PLAYER, method, args)

    def statuses(self):
        return [args[1]["PlaybackStatus"] for sig, args in self.signals
                if sig == "PropertiesChanged"]

    def test_who_it_is(self):
        root = "org.mpris.MediaPlayer2"
        self.assertEqual(self.get("Identity", root), "Тест")
        self.assertEqual(self.get("DesktopEntry", root), APP_ID)
        self.assertFalse(self.get("CanQuit", root))
        self.ask(root, "Raise")
        self.assertEqual(self.shown, 1)

    def test_nothing_plays(self):
        self.assertEqual(self.get("PlaybackStatus"), "Stopped")
        self.assertEqual(self.get("Metadata")["mpris:trackid"], mpris.NO_TRACK)
        self.control("PlayPause")
        self.assertEqual(self.player.calls, [])

    def test_what_plays(self):
        t = dict(track(2), artist="Chris Rea", album="Auberge", duration=290)
        self.s.play_list([track(1), t], 1)
        self.assertEqual(self.get("PlaybackStatus"), "Playing")
        meta = self.get("Metadata")
        self.assertEqual(meta["xesam:title"], "Трек 2")
        self.assertEqual(meta["xesam:artist"], ["Chris Rea"])
        self.assertEqual(meta["xesam:album"], "Auberge")
        self.assertEqual(meta["mpris:length"], 290000000)
        self.assertEqual(meta["mpris:artUrl"], "file:///covers/2.jpg")
        self.player.tick(12)
        self.assertEqual(self.get("Position"), 12000000)

    def test_the_desktop_is_told_every_change(self):
        self.s.play_list([track(1), track(2)], 0)
        self.control("Pause")
        self.control("Play")
        self.control("Stop")
        self.until(lambda: self.statuses()[-1:] == ["Stopped"])
        told = self.statuses()
        changes = [s for i, s in enumerate(told) if i == 0 or s != told[i - 1]]
        self.assertEqual(changes, ["Playing", "Paused", "Playing", "Stopped"])
        self.assertEqual(self.stopped, 1)

    def test_pause_and_go_on(self):
        self.s.play_list([track(1)], 0)
        self.control("PlayPause")
        self.assertEqual(self.get("PlaybackStatus"), "Paused")
        self.control("Pause")  # already paused: stays so
        self.assertEqual(self.get("PlaybackStatus"), "Paused")
        self.control("Play")
        self.assertEqual(self.get("PlaybackStatus"), "Playing")
        self.control("Play")
        self.assertEqual(self.get("PlaybackStatus"), "Playing")

    def test_next_and_previous(self):
        self.s.play_list([track(1), track(2)], 0)
        self.control("Next")
        self.assertEqual(self.s.current["id"], "2")
        self.control("Previous")
        self.assertEqual(self.s.current["id"], "1")

    def test_seek(self):
        self.s.play_list([track(1), track(2)], 0)
        self.player.tick(10)
        self.control("Seek", GLib.Variant("(x)", (5000000,)))
        self.assertEqual(self.player.position, 15)
        trackid = self.get("Metadata")["mpris:trackid"]
        self.control("SetPosition", GLib.Variant("(ox)", (trackid, 40000000)))
        self.assertEqual(self.player.position, 40)
        self.control("Seek", GLib.Variant("(x)", (500000000,)))  # past the end
        self.assertEqual(self.s.current["id"], "2")


if __name__ == "__main__":
    unittest.main()
