# b8k-music

Музыка для планшета Lenovo YOGA Tablet 10 (B8000-H) с оболочкой
[lenovo-b8000h-linux](https://github.com/trudenboy/lenovo-b8000h-linux):
крупные плитки и список, игра в фоне.

- Вход — кодом устройства: открыть `ya.ru/device` на телефоне и ввести код
  с экрана; токен обновления продлевает вход сам.
- Плитки: **Моя волна** (играет бесконечно, сервис узнаёт, что вы слушаете
  и пропускаете), **Мне нравится**, свои плейлисты; поиск треков.
- Внизу — обложка, трек, назад / пауза / дальше и полоса перемотки.
- Закрытое окно не останавливает музыку; плитка на домашнем экране
  возвращает то же окно. Пока играет музыка, планшет не засыпает
  (`$XDG_RUNTIME_DIR/b8k-awake/<pid>.suspend`), экран гаснуть может.

Сервисы — модули в `sources/` (описание — в `sources/__init__.py`): сейчас
Яндекс Музыка через [yandex-music](https://github.com/MarshalX/yandex-music-api)
и [ya-passport-auth](https://github.com/trudenboy/ya-passport-auth); Звук,
Apple Music и другие добавляются так же, файлом в `sources/`.

Нужны Python 3 с PyGObject (GTK 3), python-mpv с libmpv, aiohttp, aiofiles,
yarl, requests и typing-extensions. Установка: `sh install.sh [ROOT]` —
скрипт скачивает обе библиотеки с PyPI и сверяет их sha256.

Вход хранится в `~/.local/share/b8k-music/yandex.json` (права 600), обложки —
в `~/.cache/b8k-music/`. Неофициальный клиент; без подписки Плюс часть
треков может не играть.

Лицензия — GPL-2.0.
