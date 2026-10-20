# Музыка (haltia-music)

Музыка (`haltia-music`, `io.github.haltia_de.Music`): Яндекс Музыка и
собственный сервер [Music Assistant](https://music-assistant.io) плитками и
списком, с игрой в фоне. Часть рабочего стола Haltia, сделана
для планшета Lenovo YOGA Tablet 10 (B8000-H)
([device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h)),
но работает как обычная GTK-программа и в GNOME, KDE и других средах.
До 2.0 называлась `b8k-music` (`io.github.trudenboy.Music`); с 3.0 старых
имён нет.

Неофициальный клиент Яндекс Музыки, не связан с Яндексом; без подписки
Плюс часть треков может не играть.

- Вход — в карточке сервиса в настройках: QR-кодом (навести камеру
  телефона) или кодом устройства: открыть `ya.ru/device` и ввести код с
  экрана; токен обновления продлевает вход сам. Пока вход не выполнен,
  главная показывает «Войти».
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
  Ответы сервиса хранятся в `~/.cache/haltia-music/data-yandex.json` (у каждого сервиса свой файл) и показываются
  сразу, а обновляются, если им больше четверти часа.
- Сердечко у трека ставит или снимает «Мне нравится».
- Шестерёнка — настройки: «Источники» — карточка на каждый сервис с
  переключателем, аккаунтом, «Войти» и «Выйти»; качество звука каждого
  (у Яндекса экономное ~64 кбит/с — по умолчанию, обычное ~192, высокое до
  320 с подпиской); хранится в `~/.config/haltia/music.conf`. Если включено
  больше одного сервиса, кнопка в шапке называет показанный и переключает
  на следующий.
- Внизу — обложка, трек, сердечко, назад / пауза / дальше и полоса перемотки.
- Музыка играет, пока открыты другие программы; закрытие окна
  останавливает её. Вне оболочки Haltia у окна обычные кнопки рабочего
  стола, и среди них «Закрыть» (в Haltia её ставит сама оболочка). Пока играет музыка (не на паузе), компьютер не засыпает
  (запрет сна через logind), экран гаснуть может.

Сервисы — модули в `sources/` (описание — в `sources/__init__.py`):
Яндекс Музыка через [yandex-music](https://github.com/MarshalX/yandex-music-api)
и [ya-passport-auth](https://github.com/trudenboy/ya-passport-auth), и Music
Assistant. Источники включаются и выключаются в настройках; если включены
оба, кнопка в шапке переключает между ними.

**Music Assistant** — экспериментальный источник: он выключен, пока его
не включить в настройках. В карточке «Music Assistant» — адрес
сервера (найденные в сети предлагаются сами), имя и пароль (из них
делается токен на год, пароль не хранится) или готовый токен из настроек
сервера. Музыка становится одним из проигрывателей сервера по протоколу
Sendspin: играет его очередь этого устройства, а радио, продолжение после
списка и отметки для сервисов делает сервер. Главная — ряды самого сервера,
«Обзор» — его папки с «Избранным» первым, сердечко — избранное сервера.
Нужны aiohttp, cryptography, orjson и zeroconf (на Ubuntu 24.04 нет
python3-orjson — там Music Assistant есть во Flatpak). План и решения —
`docs/plan-music-assistant.md`, `docs/adr/`.

Вход хранится в связке ключей рабочего стола (Secret Service), а где её нет — в
`~/.local/share/haltia-music/yandex.json` и `music_assistant.json` (права 600). Обложки —
в `~/.cache/haltia-music/`.

## Установка

**Ubuntu 24.04 и 26.04, Debian 13** (и elementary OS 8, Linux Mint 22) — из
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
(необязательно), для Music Assistant — cryptography, orjson и zeroconf.
Точные версии библиотек Python — в `requirements.txt`.

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
