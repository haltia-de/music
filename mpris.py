# SPDX-License-Identifier: GPL-2.0
"""What plays, told to the desktop by MPRIS on the session bus, as players
do: the Haltia shell marks the program's button (▶ or ‖) and offers pause and
stop; GNOME and KDE show it in their player widgets. The desktop can pause,
go on, stop, go to the next or the previous track, seek, or raise the window.

Mpris(bus, app_id, name, session, stop, show, art):
  bus           a Gio.DBusConnection (the application's); the name
                org.mpris.MediaPlayer2.<app_id> is asked for on it
  name          what the desktop calls the program
  session       playback.Session, what plays
  stop()        stops it all, as the window's own stop
  show()        raises the window
  art(track)    a file URI of the track's cover, or None

changed()       after every change of the track or of playing and pausing
close()         gives the name back
"""
from gi.repository import Gio, GLib

PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"
XML = """<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="read"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>"""


class Mpris:
    def __init__(self, bus, app_id, name, session, stop, show, art):
        self.bus, self.app_id, self.name = bus, app_id, name
        self.session, self.stop, self.show, self.art = session, stop, show, art
        self.ids = [bus.register_object(PATH, iface, self._call, self._get, None)
                    for iface in Gio.DBusNodeInfo.new_for_xml(XML).interfaces]
        self.owner = Gio.bus_own_name_on_connection(
            bus, "org.mpris.MediaPlayer2." + app_id, Gio.BusNameOwnerFlags.NONE, None, None)

    def close(self):
        Gio.bus_unown_name(self.owner)
        for i in self.ids:
            self.bus.unregister_object(i)

    # --- what it is -------------------------------------------------------------
    def status(self):
        return self.session.state.capitalize()

    def position(self):
        player = self.session.player
        if self.session.current is None or player is None:
            return 0
        return int((player.position or 0) * 1000000)

    def metadata(self):
        track = self.session.current
        if track is None:
            return {"mpris:trackid": GLib.Variant("o", NO_TRACK)}
        meta = {"mpris:trackid": GLib.Variant(
                    "o", "/%s/track/%d" % (self.app_id.replace(".", "/"), self.session.index)),
                "xesam:title": GLib.Variant("s", track["title"])}
        if track.get("artist"):
            meta["xesam:artist"] = GLib.Variant("as", [track["artist"]])
        if track.get("album"):
            meta["xesam:album"] = GLib.Variant("s", track["album"])
        if track.get("duration"):
            meta["mpris:length"] = GLib.Variant("x", int(track["duration"] * 1000000))
        art = self.art(track)
        if art:
            meta["mpris:artUrl"] = GLib.Variant("s", art)
        return meta

    def _get(self, _bus, _sender, _path, _iface, name):
        on = self.session.current is not None
        values = {
            "CanQuit": ("b", False), "CanRaise": ("b", True), "HasTrackList": ("b", False),
            "Identity": ("s", self.name), "DesktopEntry": ("s", self.app_id),
            "SupportedUriSchemes": ("as", []), "SupportedMimeTypes": ("as", []),
            "PlaybackStatus": ("s", self.status()), "Metadata": ("a{sv}", self.metadata()),
            "Rate": ("d", 1.0), "MinimumRate": ("d", 1.0), "MaximumRate": ("d", 1.0),
            "Volume": ("d", 1.0), "Position": ("x", self.position()),
            "CanGoNext": ("b", True), "CanGoPrevious": ("b", True),
            "CanPlay": ("b", True), "CanPause": ("b", True),
            "CanSeek": ("b", on), "CanControl": ("b", True)}
        if name in values:
            return GLib.Variant(*values[name])
        return None

    # --- what the desktop asks ----------------------------------------------------
    def _call(self, _bus, _sender, _path, _iface, method, params, invocation):
        session, status = self.session, self.status()
        if method == "Raise":
            self.show()
        elif method == "PlayPause" and status != "Stopped":
            session.toggle()
        elif method == "Pause" and status == "Playing":
            session.toggle()
        elif method == "Play" and status == "Paused":
            session.toggle()
        elif method == "Stop":
            self.stop()
        elif method == "Next":
            session.next()
        elif method == "Previous":
            session.prev()
        elif method == "Seek" and status != "Stopped":
            self._seek(self.position() + params.unpack()[0])
        elif method == "SetPosition" and status != "Stopped":
            track_id, pos = params.unpack()
            if track_id == self.metadata()["mpris:trackid"].unpack():
                self._seek(pos)
        invocation.return_value(None)

    def _seek(self, usec):
        sec = max(0, usec / 1000000)
        duration = (self.session.current or {}).get("duration")
        if duration and sec >= duration:
            self.session.next()
            return
        self.session.seek(sec)
        self._emit(PATH, PLAYER, "Seeked", GLib.Variant("(x)", (int(sec * 1000000),)))

    def changed(self):
        """Tells the desktop what plays now."""
        on = self.session.current is not None
        props = {"PlaybackStatus": GLib.Variant("s", self.status()),
                 "Metadata": GLib.Variant("a{sv}", self.metadata()),
                 "CanSeek": GLib.Variant("b", on)}
        self._emit(PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                   GLib.Variant("(sa{sv}as)", (PLAYER, props, [])))

    def _emit(self, path, iface, signal, args):
        try:
            self.bus.emit_signal(None, path, iface, signal, args)
        except GLib.Error:
            pass
