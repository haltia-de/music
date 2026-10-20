# SPDX-License-Identifier: GPL-2.0
"""A Music Assistant server's API: JSON over its websocket (/ws), signed in
with a token. Everything here runs on the sources' loop (sources/loop.py).

Client(url, token, event=None, state=None, locale="ru")
  url       the server's address, http(s)://host[:port]
  token     an access token of an account on it
  event(name, object_id, data)
            each event the server sends (it sends them all once signed in)
  state(on) the connection came up (True) or went down (False)

await start()       connects, and keeps connecting after a drop (RETRY,
                    each wait longer, to RETRY_MAX) until close(); returns
                    once the first try is over, raising what kept it from
                    signing in (Refused for a token the server does not
                    take: then it does not try again)
await call(command, **args)
                    the result (partial results joined); raises Error with
                    the server's code and words, or ConnectionError when
                    there is no connection
await close()
connected           whether it is up and signed in
user                the account's name, once signed in

await sign_in(url, username, password, name, locale="ru") makes a token
that lasts (a year) for an account: logs in, then asks for one named name.
Raises Refused for a wrong name or password, ConnectionError when the
server cannot be reached.
"""
import asyncio
import itertools

import aiohttp

RETRY = 1  # seconds before connecting again after a drop, doubled up to
RETRY_MAX = 30
TIMEOUT = 60  # seconds a command may take


class Error(Exception):
    def __init__(self, code, details):
        super().__init__(details or "error %s" % code)
        self.code = code


class Refused(Exception):
    """The server does not take the token, name or password."""


def ws_url(url, path="/ws"):
    url = url.rstrip("/")
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):] + path
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):] + path
    return "ws://" + url + path


class Client:
    def __init__(self, url, token, event=None, state=None, locale="ru"):
        self.url, self.token, self.locale = url, token, locale
        self.event, self.state = event, state
        self.connected = False
        self.user = ""
        self.info = {}
        self._session = None
        self._ws = None
        self._ids = itertools.count(1)
        self._waiting = {}  # message id -> [future, partial results]
        self._task = None
        self._closing = False

    async def start(self):
        first = asyncio.get_running_loop().create_future()
        self._closing = False
        self._task = asyncio.ensure_future(self._run(first))
        await first

    async def _run(self, first):
        wait = RETRY
        while not self._closing:
            try:
                await self._connect()
            except Refused as exc:
                if not first.done():
                    first.set_exception(exc)
                return
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError, Error) as exc:
                if not first.done():
                    first.set_exception(ConnectionError(str(exc) or "no connection"))
            else:
                wait = RETRY
                if not first.done():
                    first.set_result(None)
                await self._read()
            if self._closing:
                break
            await asyncio.sleep(wait)
            wait = min(wait * 2, RETRY_MAX)

    async def _connect(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(ws_url(self.url), heartbeat=30)
        try:
            self.info = await asyncio.wait_for(self._ws.receive_json(), TIMEOUT)
            await self._ws.send_json({"message_id": "auth", "command": "auth",
                                      "args": {"token": self.token, "locale": self.locale}})
            while True:
                answer = await asyncio.wait_for(self._ws.receive_json(), TIMEOUT)
                if answer.get("message_id") == "auth":
                    break
            if "error_code" in answer or not (answer.get("result") or {}).get("authenticated"):
                raise Refused(answer.get("details") or "the token was refused")
        except BaseException:
            await self._ws.close()
            raise
        user = answer["result"].get("user") or {}
        self.user = user.get("display_name") or user.get("username") or ""
        self.connected = True
        self._tell(True)

    async def _read(self):
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                self._got(msg.json())
        finally:
            self.connected = False
            for fut, _part in self._waiting.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("the connection dropped"))
            self._waiting.clear()
            if not self._closing:
                self._tell(False)

    def _got(self, data):
        if "event" in data:
            if self.event:
                self.event(data["event"], data.get("object_id"), data.get("data"))
            return
        entry = self._waiting.get(str(data.get("message_id")))
        if entry is None:
            return
        fut, part = entry
        if "error_code" in data:
            del self._waiting[str(data["message_id"])]
            fut.set_exception(Error(data["error_code"], data.get("details")))
        elif data.get("partial"):
            part.extend(data.get("result") or [])
        else:
            del self._waiting[str(data["message_id"])]
            result = data.get("result")
            fut.set_result(part + result if part and isinstance(result, list) else result)

    def _tell(self, on):
        if self.state:
            self.state(on)

    async def call(self, command, **args):
        if not self.connected:
            raise ConnectionError("no connection to the server")
        mid = str(next(self._ids))
        fut = asyncio.get_running_loop().create_future()
        self._waiting[mid] = [fut, []]
        try:
            await self._ws.send_json({"message_id": mid, "command": command, "args": args})
            return await asyncio.wait_for(fut, TIMEOUT)
        finally:
            self._waiting.pop(mid, None)

    async def close(self):
        self._closing = True
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
        if self._session is not None:
            await self._session.close()
            self._session = None
        self.connected = False


async def sign_in(url, username, password, name, locale="ru"):
    async with aiohttp.ClientSession() as session:
        try:
            ws = await session.ws_connect(ws_url(url), heartbeat=30)
        except (aiohttp.ClientError, OSError) as exc:
            raise ConnectionError(str(exc) or "the server cannot be reached")
        async with ws:
            await asyncio.wait_for(ws.receive_json(), TIMEOUT)  # the server's info

            async def ask(mid, command, **args):
                await ws.send_json({"message_id": mid, "command": command, "args": args})
                while True:
                    answer = await asyncio.wait_for(ws.receive_json(), TIMEOUT)
                    if answer.get("message_id") == mid:
                        return answer

            answer = await ask("login", "auth/login", username=username, password=password,
                               device_name=name)
            result = answer.get("result") or {}
            if "error_code" in answer or not result.get("success"):
                raise Refused(result.get("error") or answer.get("details") or "refused")
            answer = await ask("auth", "auth", token=result["access_token"], locale=locale)
            if "error_code" in answer:
                raise Refused(answer.get("details") or "refused")
            answer = await ask("token", "auth/token/create", name=name)
            if "error_code" in answer:
                raise Error(answer["error_code"], answer.get("details"))
            return answer["result"]
