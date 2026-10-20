# SPDX-License-Identifier: GPL-2.0
"""This device as a Music Assistant player: a Sendspin client (aiosendspin)
through the server's signed-in proxy (/sendspin), its sound played by the
program's player (haltia_kit's, libmpv).

The server sees an app player of its own (product "Mobile Application":
the server's test for one that plays by itself, not as a part of another),
private to the account, whose id is the Sendspin peer id made from the key
kept with the account; guest access lets it play without pairing by a PIN.
It asks for PCM 48 kHz (FLAC would carry a header of its own for every
track, which one pipe cannot), and holds about a second (BUFFER).

The streams go to the player as a pipe (fdclose://) of raw PCM, with the
options that say so to libmpv (raw()), through play(what, **options). A stream that follows one that ended within
JOIN seconds (the next track) goes on in the same pipe, so nothing of the
end of a track is lost. After flush() (the program asked for another track,
a seek, a pause or a play) or a clear from the server, the next sound
starts a new pipe at once, dropping what the old one held. A stream that
ended alone (a pause, a stop) ends the pipe, so the player stops and the
machine may sleep.

Sound(url, token, key, name, player, state=None, allowed=None)
  url, token    the server and the account's token
  key           the device's 32-byte X25519 private key
  name          what the server calls the device
  player()      the program's player (play(what, **mpv options), stop()),
                made once, called on the GTK side
  state(on)     connected (True) or not (False), from the loop's thread
  allowed()     whether sound may be played now (not while another
                source plays): what comes otherwise is dropped

flush()         what is heard next starts anew (from any thread)

await start()   connects, and keeps connecting after a drop until close()
await close()
player_id       the device's id on the server (its queue's id too)
"""
import asyncio
import dataclasses
import json
import logging
import os
import queue
import threading

import aiohttp
from gi.repository import GLib

from .client import RETRY, RETRY_MAX, ws_url

LOG = logging.getLogger("haltia-music.sendspin")
JOIN = 0.5
BUFFER = 200_000  # bytes the server may send ahead: ~1 s of PCM


def raw(pcm):
    """libmpv's options for a pipe of raw PCM: read at once, nothing probed
    (a probe of a stream that comes as it plays waits seconds)."""
    return {"demuxer": "rawaudio", "demuxer_rawaudio_format": "s%dle" % pcm.bit_depth,
            "demuxer_rawaudio_rate": str(pcm.sample_rate),
            "demuxer_rawaudio_channels": str(pcm.channels)}


class Pipe:
    """One stream to the player: written from the loop, read by libmpv."""

    def __init__(self, player, options):
        read, self.fd = os.pipe()
        self.chunks = queue.Queue()
        threading.Thread(target=self._write, daemon=True).start()
        GLib.idle_add(lambda: (player().play("fdclose://%d" % read, **options), False)[1])

    def _write(self):
        try:
            while True:
                data = self.chunks.get()
                if data is None:
                    break
                os.write(self.fd, data) if len(data) < 65536 else self._all(data)
        except OSError:
            pass  # the player stopped reading
        finally:
            os.close(self.fd)

    def _all(self, data):
        view = memoryview(data)
        while view:
            view = view[os.write(self.fd, view):]

    def write(self, data):
        self.chunks.put(data)

    def end(self):
        self.chunks.put(None)


class Sound:
    def __init__(self, url, token, key, name, player, state=None, allowed=None):
        from aiosendspin.noise.keys import Identity
        self.url, self.token, self.name = url, token, name
        self.player, self.state = player, state
        self.allowed = allowed or (lambda: True)
        self.identity = Identity.from_private_bytes(key)
        self.player_id = self.identity.peer_id
        self.client = None
        self.pipe = None
        self.format = None  # the pipe's: (codec, PCM format)
        self.flushing = False  # the next sound starts a new pipe
        self._ending = None  # the timer that ends a pipe whose stream ended
        self._task = None
        self._closing = False

    async def _client(self):
        from aiosendspin.client import SendspinClient
        from aiosendspin.models.core import DeviceInfo
        from aiosendspin.models.player import ClientHelloPlayerSupport, SupportedAudioFormat
        from aiosendspin.models.types import AudioCodec, Roles
        from aiosendspin.noise.trust_store import InMemoryClientPairingStore

        store = InMemoryClientPairingStore()
        config = await store.get_pairing_config()
        await store.store_pairing_config(dataclasses.replace(config,
                                                             unpaired_access_enabled=True))
        formats = [SupportedAudioFormat(codec=codec, channels=2, sample_rate=48000,
                                        bit_depth=16)
                   for codec in (AudioCodec.PCM,)]
        c = SendspinClient(
            self.identity, self.name, [Roles.PLAYER], pairing_store=store,
            device_info=DeviceInfo(product_name="Mobile Application", manufacturer="Haltia",
                                   software_version="haltia-music"),
            player_support=ClientHelloPlayerSupport(supported_formats=formats,
                                                    buffer_capacity=BUFFER,
                                                    supported_commands=[]))
        c.add_audio_chunk_listener(self._chunk)
        c.add_stream_start_listener(lambda _m: LOG.debug("stream start"))
        c.add_stream_end_listener(lambda _roles: self._ended())
        c.add_stream_clear_listener(lambda _roles: self._cleared())
        return c

    async def start(self):
        first = asyncio.get_running_loop().create_future()
        self._closing = False
        self._task = asyncio.ensure_future(self._run(first))
        await first

    async def _run(self, first):
        wait = RETRY
        while not self._closing:
            closed = asyncio.Event()
            try:
                self.client = await self._client()
                self.client.add_disconnect_listener(lambda *_a: closed.set())
                await self._connect(self.client)
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError, RuntimeError) as exc:
                if not first.done():
                    first.set_exception(ConnectionError(str(exc) or "no connection"))
            else:
                wait = RETRY
                if not first.done():
                    first.set_result(None)
                if self.state:
                    self.state(True)
                await closed.wait()
                self._end()
                if self.state and not self._closing:
                    self.state(False)
            if self._closing:
                break
            await asyncio.sleep(wait)
            wait = min(wait * 2, RETRY_MAX)

    async def _connect(self, c):
        """SendspinClient.connect, with the proxy's sign-in first: the
        library dials by itself, so the bring-up is done here as it does it."""
        from aiosendspin.client.connection import SendspinConnection

        if c._session is None:
            c._session = aiohttp.ClientSession()
        raw = await c._session.ws_connect(ws_url(self.url, "/sendspin"), heartbeat=30)
        await raw.send_str(json.dumps({"type": "auth", "token": self.token,
                                       "client_id": self.player_id}))
        msg = await asyncio.wait_for(raw.receive(), 30)
        if msg.type != aiohttp.WSMsgType.TEXT or json.loads(msg.data).get("type") != "auth_ok":
            await raw.close()
            raise RuntimeError("the server did not let the player in")
        conn = SendspinConnection(c)
        c._provisional_connections.add(conn)
        try:
            await conn.connect(raw, expected_server_id=None)
        finally:
            c._provisional_connections.discard(conn)
        async with c._admission_lock:
            await c._admit_connection(conn)
        await conn.start()

    def _chunk(self, _timestamp, data, fmt):
        if not self.allowed():
            self._end()
            return
        if self._ending is not None:
            self._ending.cancel()
            self._ending = None
        kind = (fmt.codec, fmt.pcm_format)
        if self.pipe is not None and (self.flushing or kind != self.format):
            self._end()
        if self.pipe is None:
            LOG.debug("new pipe (%s)", "flushed" if self.flushing else "first")
            self.format, self.flushing = kind, False
            self.pipe = Pipe(self.player, raw(fmt.pcm_format))
        self.pipe.write(data)

    def flush(self):
        """What is heard next starts anew: the program asked for it."""
        self.flushing = True

    def _cleared(self):
        LOG.debug("stream clear")
        self.flushing = True

    def _ended(self):
        """The stream ended: the next track's may follow at once."""
        LOG.debug("stream end")
        if self.pipe is not None and self._ending is None:
            self._ending = asyncio.get_running_loop().call_later(JOIN, self._end)

    def _end(self):
        if self._ending is not None:
            self._ending.cancel()
            self._ending = None
        if self.pipe is not None:
            self.pipe.end()
            self.pipe = None

    async def close(self):
        self._closing = True
        self._end()
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
