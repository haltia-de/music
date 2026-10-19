# SPDX-License-Identifier: GPL-2.0
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vault  # noqa: E402

TOKENS = {"x_token": "x", "music_token": "m", "login": "kot"}


class Keyring:
    """A keyring that may be away, or may take nothing."""

    def __init__(self):
        self.kept = {}
        self.away = False  # no Secret Service answers
        self.full = False  # it answers but keeps nothing

    def lookup(self, account):
        self._check()
        return self.kept.get(account)

    def store(self, account, label, text):
        self._check()
        if not self.full:
            self.kept[account] = text

    def clear(self, account):
        self._check()
        self.kept.pop(account, None)

    def _check(self):
        if self.away:
            raise OSError("no Secret Service")


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "haltia-music", "yandex.json")
        self.ring = Keyring()

    def tearDown(self):
        self.dir.cleanup()

    def vault(self, ring="default"):
        return vault.Vault("yandex", self.path, self.ring if ring == "default" else ring)

    def old_file(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            json.dump(TOKENS, fh)

    def test_kept_in_the_keyring_not_in_a_file(self):
        self.vault().save(TOKENS)
        self.assertEqual(json.loads(self.ring.kept["yandex"]), TOKENS)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.vault().load(), TOKENS)

    def test_a_file_without_a_keyring(self):
        self.ring.away = True
        self.vault().save(TOKENS)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(self.vault().load(), TOKENS)

    def test_a_file_without_libsecret(self):
        self.vault(None).save(TOKENS)
        self.assertEqual(self.vault(None).load(), TOKENS)

    def test_an_old_file_moves_into_the_keyring(self):
        self.old_file()
        self.assertEqual(self.vault().load(), TOKENS)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(json.loads(self.ring.kept["yandex"]), TOKENS)

    def test_the_file_stays_when_the_keyring_did_not_take_it(self):
        self.old_file()
        self.ring.full = True
        self.assertEqual(self.vault().load(), TOKENS)
        self.assertTrue(os.path.exists(self.path))
        self.ring.full = False
        self.ring.away = True
        self.assertEqual(self.vault().load(), TOKENS)
        self.assertTrue(os.path.exists(self.path))

    def test_a_save_the_keyring_refuses_goes_to_the_file(self):
        self.ring.full = True
        self.vault().save(TOKENS)
        self.assertEqual(self.vault().load(), TOKENS)

    def test_a_file_written_while_the_keyring_was_away_wins(self):
        self.ring.kept["yandex"] = json.dumps({"x_token": "old"})
        self.old_file()
        self.assertEqual(self.vault().load(), TOKENS)
        self.assertEqual(json.loads(self.ring.kept["yandex"]), TOKENS)
        self.assertFalse(os.path.exists(self.path))

    def test_delete_forgets_both(self):
        self.old_file()
        self.ring.kept["yandex"] = json.dumps(TOKENS)
        v = self.vault()
        v.delete()
        self.assertIsNone(v.load())
        self.assertEqual(self.ring.kept, {})
        self.assertFalse(os.path.exists(self.path))

    def test_asks_the_keyring_once(self):
        v = self.vault()
        v.save(TOKENS)
        self.ring.away = True
        self.assertEqual(v.load(), TOKENS)


@unittest.skipUnless(vault.keyring("io.github.haltia_de.Test", "Тест"), "no libsecret")
class Real(unittest.TestCase):
    def test_without_a_secret_service_it_raises(self):
        """What the Vault takes for "no keyring", as on the tablet."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ("import vault\n"
                "try:\n"
                "    vault.keyring('io.github.haltia_de.Test', 'Тест').lookup('test')\n"
                "except Exception:\n"
                "    print('raised')\n")
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")
        out = subprocess.run([sys.executable, "-c", code], cwd=here, env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "raised", out.stderr)


if __name__ == "__main__":
    unittest.main()
