# SPDX-License-Identifier: GPL-2.0
"""A Music Assistant server for tests: its /ws on a free local port, the
commands it answers set by the test, events it sends when told."""
import asyncio

from aiohttp import web

TOKEN = "долгий"


class Server:
    def __init__(self):
        self.answers = {}  # command -> func(args) (may raise Fail) or a value
        self.asked = []  # (command, args)
        self.sockets = []
        self.accounts = {"кот": "верный"}
        self.tokens = {TOKEN}
        self.breaks = 0  # sign-ins it breaks off still, as when it restarts
        self.sendspin = 0  # tries of the Sendspin player, each broken off
        self.runner = None
        self.url = ""

    async def start(self):
        app = web.Application()
        app.router.add_get("/ws", self._ws)
        app.router.add_get("/sendspin", self._sendspin)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = "http://127.0.0.1:%d" % port

    async def stop(self):
        await self.runner.cleanup()

    async def drop(self):
        """Every connection breaks, as when the network goes."""
        for ws in list(self.sockets):
            await ws.close()

    async def send(self, event, object_id, data):
        for ws in self.sockets:
            await ws.send_json({"event": event, "object_id": object_id, "data": data})

    async def _ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"server_id": "fake", "server_version": "test",
                            "schema_version": 96, "min_supported_schema_version": 28})
        signed = False
        self.sockets.append(ws)
        try:
            async for msg in ws:
                data = msg.json()
                mid, command, args = data["message_id"], data["command"], data.get("args") or {}
                self.asked.append((command, args))
                if command == "auth/login":
                    ok = self.accounts.get(args.get("username")) == args.get("password")
                    result = ({"success": True, "access_token": "короткий",
                               "user": {"username": args["username"]}} if ok else
                              {"success": False, "error": "Invalid username or password"})
                    if ok:
                        self.tokens.add("короткий")
                    await ws.send_json({"message_id": mid, "result": result})
                elif command == "auth" and self.breaks:
                    self.breaks -= 1
                    await ws.close()
                    break
                elif command == "auth":
                    if args.get("token") in self.tokens:
                        signed = True
                        await ws.send_json({"message_id": mid, "result": {
                            "authenticated": True, "user": {"username": "кот",
                                                            "display_name": "Кот"}}})
                    else:
                        await ws.send_json({"message_id": mid, "error_code": 20,
                                            "details": "Invalid or expired token"})
                elif not signed:
                    await ws.send_json({"message_id": mid, "error_code": 20,
                                        "details": "Authentication required"})
                elif command == "auth/token/create":
                    self.tokens.add(TOKEN)
                    await ws.send_json({"message_id": mid, "result": TOKEN})
                else:
                    await self._answer(ws, mid, command, args)
        finally:
            self.sockets.remove(ws)
        return ws

    async def _sendspin(self, request):
        """The player's proxy, which lets it in and goes away during the
        handshake that follows."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sendspin += 1
        await ws.receive()  # the player's token
        await ws.send_json({"type": "auth_ok"})
        try:
            await asyncio.wait_for(ws.receive(), 0.2)  # the handshake's first message
        except asyncio.TimeoutError:
            pass
        await ws.close()
        return ws

    async def _answer(self, ws, mid, command, args):
        answer = self.answers.get(command)
        if answer is None:
            await ws.send_json({"message_id": mid, "error_code": 1,
                                "details": "no such command: %s" % command})
            return
        try:
            result = answer(args) if callable(answer) else answer
            if asyncio.iscoroutine(result):
                result = await result
        except Fail as exc:
            await ws.send_json({"message_id": mid, "error_code": exc.code,
                                "details": str(exc)})
            return
        if isinstance(result, list) and len(result) > 2:
            # Long lists come in parts, as the server sends them.
            await ws.send_json({"message_id": mid, "result": result[:2], "partial": True})
            result = result[2:]
        await ws.send_json({"message_id": mid, "result": result})


class Fail(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code
