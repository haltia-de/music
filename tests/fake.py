# SPDX-License-Identifier: GPL-2.0
"""Stand-ins for a music service, the player and the window, for tests."""


def track(n):
    return {"kind": "track", "source": "fake", "id": str(n), "title": "Трек %d" % n,
            "artist": "", "duration": 100, "cover": ""}


class Source:
    """A service with a few lists and a radio that hands out batches; it
    records what it is told. It keeps to the sources contract."""

    id, label = "fake", "Фейк"
    qualities = [("low", "Экономное", ""), ("high", "Высокое", "")]
    likes_list = "likes"

    def __init__(self, batches=(), feedback=True):
        self.batches = list(batches)  # each a list of tracks, or an Exception
        self.asked = []  # (radio_id, last_track) of every radio_next
        self.told = []  # (radio_id, event, track id, seconds)
        self.broken = set()  # ids of tracks without a stream
        if not feedback:
            self.feedback = None

    def logged_in(self):
        return True

    def login_start(self):
        return {"code": "", "url": "", "qr": ""}

    def login_wait(self):
        return True

    def logout(self):
        pass

    def account(self):
        return "тест"

    def home(self):
        return [{"id": "lists", "title": "Списки"}, {"id": "hits", "title": "Хиты", "list": "hits"}]

    def home_row(self, row_id):
        if row_id == "hits":
            return self.tracks("hits")
        return [{"kind": "radio", "id": "r", "title": "Радио", "subtitle": "", "cover": "",
                 "glyph": "∞"},
                {"kind": "list", "id": self.likes_list, "title": "Мне нравится",
                 "subtitle": "", "cover": ""}]

    def browse(self, folder_id):
        if folder_id == "":
            return [{"kind": "folder", "id": "all", "title": "Всё", "subtitle": "",
                     "cover": ""}]
        return self.home_row("lists")

    def tracks(self, list_id):
        return [track(n) for n in range(1, 4)]

    def search(self, query):
        return [track(1)] + self.home_row("lists")

    def liked(self):
        return set()

    def like(self, track, on):
        pass

    def stream_url(self, track, quality):
        if track["id"] in self.broken:
            raise OSError("нет потока")
        return "fake://%s/%s" % (quality, track["id"])

    def radio_next(self, radio_id, last_track):
        self.asked.append((radio_id, last_track))
        batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        return batch

    def feedback(self, radio_id, event, track, seconds):
        self.told.append((radio_id, event, track["id"], seconds))


class Player:
    def __init__(self):
        self.url = None
        self.paused = False
        self.at = 0
        self.stops = 0

    def play(self, url):
        self.url, self.paused, self.at = url, False, 0

    def toggle(self):
        self.paused = not self.paused

    def seek(self, sec):
        self.at = sec

    def time(self):
        return self.at

    def stop(self):
        self.url = None
        self.stops += 1


class Work:
    """Runs work at once, or holds it until run() when held."""

    def __init__(self):
        self.held = False
        self.waiting = []

    def __call__(self, func, arg, done):
        self.waiting.append((func, arg, done))
        if not self.held:
            self.run()

    def run(self):
        while self.waiting:
            func, arg, done = self.waiting.pop(0)
            try:
                res, err = func(arg), None
            except Exception as exc:
                res, err = None, exc
            if done:
                done(res, err)


class Later:
    """Holds timed calls until fire()."""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds, func):
        self.calls.append(func)

    def fire(self):
        calls, self.calls = self.calls, []
        for func in calls:
            func()


class Events:
    """What the window would be told."""

    def __init__(self):
        self.tracks = []  # every changed(track)
        self.grown = []
        self.on = None  # the last playing(on)
        self.failures = []

    def changed(self, track):
        self.tracks.append(track)

    def grew(self, tracks):
        self.grown.append(tracks)

    def playing(self, on):
        self.on = on

    def failed(self, text):
        self.failures.append(text)
