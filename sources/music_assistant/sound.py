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
a seek, a pause or a play) the pipe ends at once and what the old stream
still sends is dropped until the server starts a new one (or FLUSH_WAIT
passes); after a clear from the server the next sound starts a new pipe. A stream that
ended alone (a pause, a stop) ends the pipe, so the player stops and the
machine may sleep. A player that stops reading does not make the sound
pile up: past QUEUED bytes waiting the pipe ends, and what comes is
dropped for FLUSH_WAIT seconds before a new one starts.

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

await start()   connects, and keeps connecting after a drop or a failed
                try, whatever broke it, until close(); raises
                ConnectionError when the first try fails or takes over
                START seconds
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
import time

import aiohttp
from gi.repository import GLib

from .. import loop
from .client import RETRY, RETRY_MAX, START, ws_url

LOG = logging.getLogger("haltia-music.sendspin")
JOIN = 0.5
FLUSH_WAIT = 3  # seconds the old stream's sound is dropped after flush(), at most
BUFFER = 200_000  # bytes the server may send ahead: ~1 s of PCM
QUEUED = 2_000_000  # bytes waiting for the player, at most: ~10 s of PCM


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
        self.queued = 0  # bytes in chunks
        self.lock = threading.Lock()
        threading.Thread(target=self._write, daemon=True).start()
        GLib.idle_add(lambda: (player().play("fdclose://%d" % read, **options), False)[1])

    def _write(self):
        try:
            while True:
                data = self.chunks.get()
                if data is None:
                    break
                os.write(self.fd, data) if len(data) < 65536 else self._all(data)
                with self.lock:
                    self.queued -= len(data)
        except OSError:
            pass  # the player stopped reading
        finally:
            os.close(self.fd)

    def _all(self, data):
        view = memoryview(data)
        while view:
            view = view[os.write(self.fd, view):]

    def write(self, data):
        """False, and nothing kept, when QUEUED bytes wait already: the
        player does not read."""
        with self.lock:
            if self.queued + len(data) > QUEUED:
                return False
            self.queued += len(data)
        self.chunks.put(data)
        return True

    def end(self):
        """What waits is written out, then the pipe closes."""
        self.chunks.put(None)

    def drop(self):
        """The pipe closes after what is being written, the rest let go."""
        gone = 0
        try:
            while True:
                data = self.chunks.get_nowait()
                gone += len(data) if data else 0
        except queue.Empty:
            pass
        with self.lock:
            self.queued -= gone  # what is being written counts itself off
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
        self.dropping = 0.0  # until when the old stream's sound is dropped
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
        c.add_stream_start_listener(lambda _m: self._started())
        c.add_stream_end_listener(lambda _roles: self._ended())
        c.add_stream_clear_listener(lambda _roles: self._cleared())
        return c

    async def start(self):
        first = asyncio.get_running_loop().create_future()
        self._closing = False
        self._task = asyncio.ensure_future(self._run(first))
        try:
            await asyncio.wait_for(first, START)
        except asyncio.TimeoutError:
            raise ConnectionError("the server's Sendspin does not answer")

    async def _run(self, first):
        wait = RETRY
        while not self._closing:
            closed = asyncio.Event()
            try:
                self.client = await self._client()
                self.client.add_disconnect_listener(lambda *_a: closed.set())
                await asyncio.wait_for(self._connect(self.client), START)
            except Exception as exc:  # the server went away during the handshake, or worse
                LOG.debug("no connection: %r", exc)
                await self._drop_client()
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
                if not self._closing:
                    await self._drop_client()
            if self._closing:
                break
            await asyncio.sleep(wait)
            wait = min(wait * 2, RETRY_MAX)

    async def _drop_client(self):
        """A client whose connection failed or went is let go, with its
        session."""
        c, self.client = self.client, None
        if c is None:
            return
        try:
            await asyncio.wait_for(c.disconnect(), 5)
        except Exception:
            pass
        session = getattr(c, "_session", None)
        if session is not None and not session.closed:
            await session.close()

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
        if self.dropping and time.monotonic() < self.dropping:
            return  # the old stream's, after the program asked for another
        self.dropping = 0.0
        kind = (fmt.codec, fmt.pcm_format)
        if self.pipe is not None and (self.flushing or kind != self.format):
            self._end()
        if self.pipe is None:
            LOG.debug("new pipe (%s)", "flushed" if self.flushing else "first")
            self.format, self.flushing = kind, False
            self.pipe = Pipe(self.player, raw(fmt.pcm_format))
        if not self.pipe.write(data):
            LOG.warning("the player does not read: its sound dropped")
            self.pipe.drop()
            self.pipe = None
            self.dropping = time.monotonic() + FLUSH_WAIT

    def flush(self):
        """What is heard next starts anew: the program asked for it. From
        any thread."""
        loop.call(self._flush)

    def _flush(self):
        self.flushing = True
        self.dropping = time.monotonic() + FLUSH_WAIT
        self._end()

    def _started(self):
        LOG.debug("stream start")
        self.dropping = 0.0

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
