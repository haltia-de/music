# SPDX-License-Identifier: GPL-2.0
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sources  # noqa: E402
from tests import fake  # noqa: E402
from tests.fake import track  # noqa: E402


class Other(fake.Source):
    id, label = "other", "Другой"
    qualities = [("flac", "Без потерь", "")]

    def __init__(self):
        super().__init__()
        self.signed = True
        self.codes = [{"kind": "code", "code": "1234", "url": "https://example.org/device",
                       "qr": ""}]
        self.confirm = True

    def logged_in(self):
        return self.signed

    def login_start(self):
        return self.codes.pop(0)

    def login_next(self, values):
        self.signed = self.confirm
        return self.confirm

    def logout(self):
        self.signed = False

    def account(self):
        return "кот" if self.signed else ""

    def tracks(self, list_id):
        return [dict(track(1), source=self.id, title="Чужой")]


class Yandex(fake.Source):
    id = "yandex"


class Server(Other):
    """A server: its address, then an account on it."""
    id = "server"
    FORM = {"kind": "form", "note": "", "fields": [
        {"id": "url", "label": "Адрес", "secret": False, "value": "",
         "choices": [("http://found:8095", "Найден")]},
        {"id": "login", "label": "Логин", "secret": False, "value": ""},
        {"id": "password", "label": "Пароль", "secret": True, "value": ""}]}

    def __init__(self):
        super().__init__()
        self.signed = False
        self.sent = []

    def login_start(self):
        return self.FORM

    def login_next(self, values):
        self.sent.append(values)
        if values.get("password") != "верный":
            raise PermissionError("Неверный логин или пароль.")
        self.signed = True
        return True


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.settings = fake.Settings()
        self.work, self.later = fake.Work(), fake.Later()
        self.yandex, self.other = Yandex(), Other()
        self.signed, self.failures = [], []

    def tearDown(self):
        self.dir.cleanup()

    def make(self):
        self.s = sources.Sources({"other": self.other, "yandex": self.yandex}, self.settings,
                                 self.dir.name, self.work, self.later, self.signed.append,
                                 lambda: None, self.failures.append)
        return self.s


class Which(Case):
    def test_yandex_first_then_by_id(self):
        self.assertEqual([s.id for s in self.make().all()], ["yandex", "other"])

    def test_the_first_switched_on_is_shown(self):
        s = self.make()
        self.assertIs(s.shown, self.yandex)
        self.assertTrue(s.switch("yandex", False))
        self.assertIs(s.shown, self.other)
        self.assertFalse(s.switch("yandex", False))
        s.switch("other", False)
        self.assertIsNone(s.shown)
        self.assertEqual(s.on(), [])

    def test_the_next_is_shown_and_kept(self):
        s = self.make()
        s.show_next()
        self.assertIs(s.shown, self.other)
        self.assertIs(self.make().shown, self.other)
        s.show_next()
        self.assertIs(s.shown, self.yandex)

    def test_one_switched_on_stays_shown(self):
        s = self.make()
        s.switch("other", False)
        s.show_next()
        self.assertIs(s.shown, self.yandex)

    def test_an_experimental_one_is_off_until_switched_on(self):
        self.other.experimental = True
        s = self.make()
        self.assertEqual(s.on(), [self.yandex])
        self.assertTrue(s.switch("other", True))
        self.assertEqual(s.on(), [self.yandex, self.other])
        self.assertEqual(self.make().on(), [self.yandex, self.other])
        self.assertFalse(s.switch("other", True))
        self.assertTrue(s.switch("other", False))
        self.assertEqual(s.on(), [self.yandex])

    def test_switched_off_keeps_the_sign_in(self):
        s = self.make()
        s.switch("other", False)
        self.assertEqual(s.signin("other"), {"kind": "in", "name": "кот"})


class Apart(Case):
    def test_answers_apart(self):
        s = self.make()
        seen = {}
        for sid in ("yandex", "other"):
            s.answers(sid).get("tracks", "likes", lambda a, e, sid=sid: seen.setdefault(sid, a))
        self.assertEqual(seen["yandex"][0]["title"], "Трек 1")
        self.assertEqual(seen["other"][0]["title"], "Чужой")

    def test_hearts_apart(self):
        s = self.make()
        s.likes("other").toggle(dict(track(1), source="other"))
        self.assertTrue(s.likes("other").liked(dict(track(1), source="other")))
        self.assertFalse(s.likes("yandex").liked(track(1)))

    def test_quality_apart(self):
        s = self.make()
        self.assertEqual(s.quality("yandex"), "low")
        self.assertEqual(s.quality("other"), "flac")
        s.set_quality("yandex", "high")
        self.assertEqual(s.quality("yandex"), "high")
        self.assertEqual(s.quality("other"), "flac")

    def test_a_quality_the_source_lacks_gives_its_lowest(self):
        self.settings.set("quality.yandex", "nonsense")
        self.assertEqual(self.make().quality("yandex"), "low")

    def test_signing_out_forgets_that_source_only(self):
        s = self.make()
        for sid in ("yandex", "other"):
            s.answers(sid).get("tracks", "x", lambda a, e: None)
        s.sign_out("other")
        self.assertEqual(s.signin("other"), {"kind": "out"})
        self.assertEqual(self.signed, ["other"])
        self.assertEqual(s.answers("other").kept, {})
        self.assertTrue(s.answers("yandex").kept)


class Before(Case):
    """What a person had before 2.4, with Яндекс alone, stays."""

    def test_the_kept_answers_become_yandex_ones(self):
        with open(os.path.join(self.dir.name, "data.json"), "w") as fh:
            json.dump([["tracks", "x", 1.0, ["было"]]], fh)
        s = self.make()
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "data.json")))
        self.assertEqual(s.answers("yandex").kept[("tracks", "x")][1], ["было"])
        self.assertEqual(s.answers("other").kept, {})

    def test_the_quality_becomes_yandex_one(self):
        self.settings.set("quality", "high")
        self.assertEqual(self.make().quality("yandex"), "high")
        self.settings.set("quality.yandex", "low")
        self.assertEqual(self.make().quality("yandex"), "low")  # moved only once


class Form(Case):
    def setUp(self):
        super().setUp()
        self.server = Server()

    def make(self):
        self.s = sources.Sources({"server": self.server}, self.settings, self.dir.name,
                                 self.work, self.later, self.signed.append, lambda: None,
                                 self.failures.append)
        return self.s

    def test_a_form_then_signed_in(self):
        s = self.make()
        s.sign_in("server")
        state = s.signin("server")
        self.assertEqual(state["kind"], "form")
        self.assertEqual([f["id"] for f in state["fields"]], ["url", "login", "password"])
        s.send("server", {"url": "http://found:8095", "login": "кот", "password": "верный"})
        self.assertEqual(s.signin("server"), {"kind": "in", "name": "кот"})
        self.assertEqual(self.server.sent[0]["login"], "кот")

    def test_a_wrong_password_shows_the_form_again_with_why(self):
        s = self.make()
        s.sign_in("server")
        s.send("server", {"url": "x", "login": "кот", "password": "нет"})
        state = s.signin("server")
        self.assertEqual(state["kind"], "form")
        self.assertEqual(state["note"], "Неверный логин или пароль.")
        values = {f["id"]: f["value"] for f in state["fields"]}
        self.assertEqual(values, {"url": "x", "login": "кот", "password": ""})
        s.send("server", {"url": "x", "login": "кот", "password": "верный"})
        self.assertEqual(s.signin("server")["kind"], "in")

    def test_checking_while_the_source_answers(self):
        s = self.make()
        s.sign_in("server")
        self.work.held = True
        s.send("server", {"password": "верный"})
        self.assertEqual(s.signin("server"), {"kind": "getting"})
        s.send("server", {"password": "верный"})  # no form shown now: ignored
        self.work.run()
        self.assertEqual(len(self.server.sent), 1)


class SignIn(Case):
    def setUp(self):
        super().setUp()
        self.other.signed = False

    def test_a_code_then_signed_in(self):
        s = self.make()
        self.work.held = True
        s.sign_in("other")
        self.assertEqual(s.signin("other"), {"kind": "getting"})
        self.work.run()
        self.assertEqual(s.signin("other"), {"kind": "in", "name": "кот"})
        self.assertEqual(self.signed, ["other"] * 3)

    def test_shows_the_code_while_waiting(self):
        s = self.make()
        self.work.held = True
        s.sign_in("other")
        func, arg, done = self.work.waiting.pop(0)
        done(func(arg), None)
        self.assertEqual(s.signin("other")["kind"], "waiting")
        self.assertEqual(s.signin("other")["code"], "1234")

    def test_not_confirmed(self):
        self.other.confirm = False
        s = self.make()
        s.sign_in("other")
        self.assertEqual(s.signin("other"), {"kind": "failed", "note": "Вход не подтверждён."})

    def test_no_code(self):
        self.other.codes = [{"code": "", "url": "", "qr": ""}]
        s = self.make()
        s.sign_in("other")
        self.assertEqual(s.signin("other")["kind"], "failed")

    def test_signed_out_while_waiting(self):
        s = self.make()
        self.work.held = True
        s.sign_in("other")
        s.sign_out("other")
        self.work.run()
        self.assertEqual(s.signin("other"), {"kind": "out"})


if __name__ == "__main__":
    unittest.main()
