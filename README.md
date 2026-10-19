# Музыка (haltia-music)

Музыка (`haltia-music`, `io.github.haltia_de.Music`): Яндекс Музыка
плитками и списком, с игрой в фоне. Часть рабочего стола Haltia, сделана
для планшета Lenovo YOGA Tablet 10 (B8000-H)
([device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h)),
но работает как обычная GTK-программа и в GNOME, KDE и других средах.
До 2.0 называлась `b8k-music` (`io.github.trudenboy.Music`): вход, кэш и
настройки переезжают на новые места при первом запуске, а команда
`b8k-music` и старый id работают до 3.0.

Неофициальный клиент Яндекс Музыки, не связан с Яндексом; без подписки
Плюс часть треков может не играть.

- Вход — QR-кодом (навести камеру телефона) или кодом устройства: открыть
  `ya.ru/device` и ввести код с экрана; токен обновления продлевает вход сам.
- Главная (домик) — ряды обложек, как Discover в Music Assistant: **Моя
  волна** и её режимы (играет бесконечно, сервис узнаёт, что вы слушаете и
  пропускаете), своя коллекция, «Для вас», чарт, новые релизы и плейлисты,
  подборки по настроению, занятию и сезону.
- **Обзор** — папки, как Browse в Music Assistant: режимы волны, «Для вас»,
  коллекция (Мне нравится, плейлисты, альбомы, исполнители), радио по
  жанрам, настроению, занятию и эпохе, подборки; «←» — назад. Поиск треков и плейлистов.
- Нажатие на карточку или строку только открывает её; музыка начинается
  с нажатия на трек в списке или на «▶ Слушать» у списка и радио.
  Радио открывается, как плейлист, с первой порцией треков и дальше
  подбирает новые по ходу.
- Открытые страницы не строятся заново: «←» возвращает сразу и туда же.
  Ответы сервиса хранятся в `~/.cache/haltia-music/data.json` и показываются
  сразу, а обновляются, если им больше четверти часа.
- Сердечко у трека ставит или снимает «Мне нравится».
- Шестерёнка — настройки: аккаунт и «Выйти», качество звука (экономное ~64 кбит/с — по
  умолчанию, обычное ~192, высокое до 320 с подпиской); хранится в
  `~/.config/haltia/music.conf`.
- Внизу — обложка, трек, сердечко, назад / пауза / дальше и полоса перемотки.
- Музыка играет, пока открыты другие программы; закрытие окна
  останавливает её. Вне оболочки Haltia у окна обычные кнопки рабочего
  стола, и среди них «Закрыть» (в Haltia её ставит сама оболочка). Пока играет музыка (не на паузе), компьютер не засыпает
  (запрет сна через logind), экран гаснуть может.

Сервисы — модули в `sources/` (описание — в `sources/__init__.py`): сейчас
Яндекс Музыка через [yandex-music](https://github.com/MarshalX/yandex-music-api)
и [ya-passport-auth](https://github.com/trudenboy/ya-passport-auth); Звук,
Apple Music и другие добавляются так же, файлом в `sources/`.

Вход хранится в связке ключей рабочего стола (Secret Service), а где её нет — в
`~/.local/share/haltia-music/yandex.json` (права 600). Обложки —
в `~/.cache/haltia-music/`.

## Установка

**Ubuntu 24.04, Debian 13** (и elementary OS 8, Linux Mint 22) — из
репозитория apt Haltia:

```
sudo curl -fsSLo /usr/share/keyrings/haltia-archive-keyring.gpg https://haltia-de.github.io/packages/apt/haltia-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/haltia-archive-keyring.gpg] https://haltia-de.github.io/packages/apt $(. /etc/os-release; echo $VERSION_CODENAME) main" | sudo tee /etc/apt/sources.list.d/haltia.list
sudo apt update && sudo apt install haltia-music
```

**Flatpak** (любой дистрибутив; среда GNOME — с Flathub):

```
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-add --if-not-exists haltia https://haltia-de.github.io/packages/flatpak/haltia.flatpakrepo
flatpak install haltia io.github.haltia_de.Music
```

В Flatpak всё лежит в `~/.var/app/io.github.haltia_de.Music/`: настройки —
в `config/haltia/music.conf`, обложки и ответы сервиса — в
`cache/haltia-music/`, вход — в связке ключей (через портал), а без неё — в
`data/haltia-music/yandex.json`.

**Alpine и postmarketOS** — пакет `haltia-music` из
[репозитория apk Haltia](https://github.com/haltia-de/packages).

**Из исходников:** нужны Python 3 с PyGObject (GTK 3),
[haltia-kit](https://github.com/haltia-de/kit) (звук, настройки,
вопросы), python-mpv с libmpv, aiohttp, aiofiles, yarl, requests и
typing-extensions; для QR-кода — qrcode, для связки ключей — libsecret
(необязательно). Точные версии библиотек Python — в `requirements.txt`.

```
sh install.sh            # в /usr/local (нужен root)
sh install.sh /mnt/root  # в другой корень, например при сборке образа
```

`install.sh [ROOT] [PREFIX]` (PREFIX — `/usr/local`, если не указан) ставит
программу, `.desktop`-файл, значок и описание AppStream, скачивает обе
библиотеки Яндекса с PyPI и сверяет их sha256. Сборка пакетов: Alpine —
`packaging/alpine/APKBUILD`, Flatpak — `packaging/flatpak/`, Debian и
Ubuntu — `debian/`; выпуск по тегу — `haltia-de/ci`.

Лицензия — GPL-2.0.
