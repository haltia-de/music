# SPDX-License-Identifier: GPL-2.0
"""Where a service's sign-in is kept: in the desktop's keyring (the Secret
Service through libsecret, the Secret portal inside Flatpak), or, where no
keyring answers, in a file only its owner reads. A file (from before, or
written while no keyring answered) is the newest: it is moved into the
keyring when one answers, and deleted only when the keyring has taken it.

Vault(account, path, keyring):
  account       what is kept, e.g. "yandex"
  path          the file used without a keyring
  keyring       Keyring(app_id) or a stand-in: lookup(account),
                store(account, label, text), clear(account); each raises
                when no keyring answers

load()          the kept dict, or None
save(data)      keeps a dict
delete()        forgets it, in the keyring and in the file
"""
import json
import os
import threading


class Keyring:
    """The Secret Service, a schema named by the program's id and keyed by
    the account."""

    def __init__(self, app_id, name):
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        self.secret, self.name = Secret, name
        self.schema = Secret.Schema.new(app_id, Secret.SchemaFlags.NONE,
                                        {"account": Secret.SchemaAttributeType.STRING})

    def lookup(self, account):
        return self.secret.password_lookup_sync(self.schema, {"account": account}, None)

    def store(self, account, label, text):
        if not self.secret.password_store_sync(self.schema, {"account": account},
                                               self.secret.COLLECTION_DEFAULT,
                                               "%s: %s" % (self.name, label), text, None):
            raise OSError("the keyring did not take it")

    def clear(self, account):
        self.secret.password_clear_sync(self.schema, {"account": account}, None)


def keyring(app_id, name):
    """Keyring(app_id, name), or None without libsecret."""
    try:
        return Keyring(app_id, name)
    except (ImportError, ValueError):
        return None


class Vault:
    def __init__(self, account, path, keyring):
        self.account, self.path, self.keyring = account, path, keyring
        self.lock = threading.Lock()
        self.kept = None  # what was loaded or saved last
        self.known = False

    def load(self):
        with self.lock:
            if not self.known:
                self.kept, self.known = self._load(), True
            return self.kept

    def save(self, data):
        with self.lock:
            if self._store(data):
                self._unlink()
            else:
                self._write(data)
            self.kept, self.known = data, True

    def delete(self):
        with self.lock:
            try:
                if self.keyring:
                    self.keyring.clear(self.account)
            except Exception:
                pass
            self._unlink()
            self.kept, self.known = None, True

    # --- inside -------------------------------------------------------------------
    def _load(self):
        # A file is the newest: written from before, or when no keyring answered.
        data = self._read()
        if data is not None:
            if self._store(data):
                self._unlink()  # moved into the keyring
            return data
        try:
            text = self.keyring.lookup(self.account) if self.keyring else None
            return json.loads(text) if text else None
        except Exception:
            return None  # no keyring answers, or what it has is broken

    def _store(self, data):
        """Whether the keyring has it now."""
        if not self.keyring:
            return False
        text = json.dumps(data)
        try:
            self.keyring.store(self.account, data.get("login") or self.account, text)
            return self.keyring.lookup(self.account) == text
        except Exception:
            return False

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _write(self, data):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        fd = os.open(self.path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(self.path + ".new", self.path)

    def _unlink(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass
