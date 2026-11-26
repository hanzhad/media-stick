"""SWEET.TV app: the words on the screen. Ready data in, strings out; nothing here touches Kodi.

The row of key hints, the status card (loading, empty, error), the steps for signing in on the phone, the account chip, and
the fixed labels of the skin. What is said about a channel is in sweettv_view. Every string goes through tr() (see the
end of this file): the language is the device's, set once when the window is made (set_language).
"""
from typing import NamedTuple

WAIT_LIMIT = 300                # s without a channel list after sign-in before it is called a failure
PHONE_TAB = "Аккаунты"          # the tab's name on the phone page (that page is in Russian)
ACCENT, RED, DIM = "FFFFC857", "FFFF6B5E", "99FFFFFF"      # the skin's amber, an error red, a muted white


def hint_line(numbered, archive=False) -> str:
    """The key hints at the top: each key in the accent colour, then what it does. The number keys are left out
    when no channel has a number (they would do nothing), the archive keys when no channel has an archive."""
    keys = [("OK", tr("Watch")), (tr("Menu"), tr("Favourite"))] + ([("0-9", tr("Channel number"))] if numbered else [])
    keys += [(tr("Up"), tr("Guide and continue"))] if archive else []
    return "        ".join(f"[COLOR {ACCENT}]{key}[/COLOR]  {what}" for key, what in keys)


def section_hint(kind) -> str:
    """The key hints while the row of cards holds something that is not channels: the shows ("shows"), the episodes of a
    show and the films ("episodes", "films"). Only the keys of a remote: OK and Back."""
    what = tr("Open") if kind == "shows" else tr("Watch")
    return "        ".join(f"[COLOR {ACCENT}]{key}[/COLOR]  {text}" for key, text in (("OK", what), (tr("Back"), tr("Go back"))))


SECTION_NAMES = {
    "search": "Search",
    "continue": "Continue",
    "favourites": "Favourites",
    "shows": "Shows",
    "series": "Series",
    "movies": "Movies",
    "channels": "TV Channels",
}



def page_search_label(section, query="") -> str:
    q = (query or "").strip()
    if q:
        return f"{q} [x]"
    if section == "search":
        return tr("Search everything")
    return f"{tr('Search')}: {section_title(section)}"


def page_search_prompt(section) -> str:
    if section == "search":
        return tr("Search programmes and channels")
    return tr("Search in {section}").format(section=section_title(section))

def section_title(section) -> str:
    return tr(SECTION_NAMES.get(section, "SWEET.TV"))


def chip(demo, signed) -> str:
    """The account chip top left. "Demo" only when the screen runs as the demo."""
    return tr("Demo") if demo else tr("Signed in") if signed else tr("Sign in")


def labels() -> dict:
    """The fixed labels of the skin, as window properties (the skin has no text of its own: it is in the device's language)."""
    return {"l_catchup": tr("Catch-up"), "l_favourite": tr("Favourite"),
            "l_play": tr("Watch"), "l_guide": tr("Programme guide"),
            "l_guide_help": tr("OK plays. Back closes."),
            "l_signin_title": tr("Sign in on your phone"), "l_signin_sub": tr("Live TV and the channel guide"),
            "l_scan": tr("Scan to open the phone page"), "l_code": tr("Or sign in here with a code"),
            "l_press_ok": tr("Press OK. Back returns to Home."), "l_retry": tr("Try again")}


def now_line(span) -> str:
    """"Now   22:10 – 23:00" over the title of a programme; "" when there is no time to say."""
    return f"{tr('Now')}   {span}" if span else ""


def next_line(span, title) -> str:
    """"Next   23:00 – 23:50   Title"; "" when nothing comes next."""
    return f"{tr('Next')}   {span}   {title}" if span else ""


# ---- signed out: sign in on the phone --------------------------------------------------------

def short_url(url) -> str:
    """The phone page's address as people type it: no scheme, no closing slash."""
    return url.split("://", 1)[-1].rstrip("/") if url else ""


def phone_steps(url) -> dict:
    """Window properties of the sign-in card: the three steps. `url` is the phone page ("" when offline)."""
    shown = short_url(url)
    return {"phone_step1": tr("1    On your phone, open") if shown else tr("1    Connect the stick to a network first"),
            "phone_url": shown,
            "phone_step2": tr("2    Tab  {tab}  >  SWEET.TV").format(tab=PHONE_TAB),     # ">", not an arrow: the skin's font has no glyph for it
            "phone_step3": tr("3    Sign in there: the channels appear here by themselves.")}


# ---- signed in, nothing to show --------------------------------------------------------------

class Status(NamedTuple):
    kind: str                   # loading | empty | error
    glyph: str                  # the badge's one character
    tint: str                   # the badge's colour
    title: str
    text: str
    note: str                   # the last line: what happens next


ERRORS = {                      # msgids: status() says them through tr()
    "service": "SWEET.TV answered with an error. Check the internet connection and that the account is signed in.",
    "format": "The channel list is not in the shape this screen knows. SWEET.TV may have changed it.",
    "unreadable": "The channel list cannot be read. SWEET.TV writes it again every 15 minutes.",
    "missing": "SWEET.TV has not delivered the channel list for a long while. Check the internet connection.",
}
TRYING = "Trying again every few seconds. Back returns to Home."


def status(error, has_file, unreadable, waited) -> Status:
    """What a signed-in screen without channels says. `error` is the parser's verdict on the file ("" when fine),
    `waited` the seconds this screen has been waiting for a first list."""
    if error or ((not has_file or unreadable) and waited > WAIT_LIMIT):
        key = error if error else "unreadable" if has_file else "missing"
        text = ERRORS.get(key, ERRORS["format"])
        return Status("error", "!", RED, tr("Cannot load the channels"), tr(text), tr(TRYING))
    if not has_file or unreadable:
        return Status("loading", "…", ACCENT, tr("Loading channels"),
                      tr("SWEET.TV is fetching the channel list. After signing in this takes a minute or two."),
                      tr("Checking again every few seconds. Back returns to Home."))
    return Status("empty", "0", DIM, tr("No channels yet"),
                  tr("The channel list is empty. SWEET.TV may still be loading it, or the account has none."),
                  tr("Back returns to Home."))


# ---- translations ----------------------------------------------------------------------------
# Every string a person sees goes through tr(msgid): the msgid is the English text as written in the code, the
# translations are here, in one place. The language is the device's (the phone's "Language", mediastick_lang): the window
# asks sweettv_files.language() when it is made and calls set_language(). Russian and Ukrainian are translated; any other
# language reads the English msgid.

DEFAULT_LANG = "ru"
LANG = DEFAULT_LANG


def set_language(code):
    """The language of every string from now on: "ru", "uk", or another code, which reads English."""
    global LANG
    LANG = code if isinstance(code, str) and code else DEFAULT_LANG


TEXT = {
    "Live": {"ru": "В эфире", "uk": "В ефірі"},
    "Back to live": {"ru": "К эфиру", "uk": "До ефіру"},
    "No archive for this channel": {"ru": "Архива у этого канала нет", "uk": "Архіву в цього каналу немає"},
    "SWEET.TV is not available on this device.": {"ru": "SWEET.TV недоступен на этом устройстве.",
                                                  "uk": "SWEET.TV недоступний на цьому пристрої."},
    "Wrong channel.": {"ru": "Неверный канал.", "uk": "Невірний канал."},
    "Wrong programme.": {"ru": "Неверная передача.", "uk": "Невірна передача."},
    "This programme is not in the channel's guide.": {"ru": "Такой передачи нет в программе канала.",
                                                      "uk": "Такої передачі немає в програмі каналу."},
    "This programme is not in the archive.": {"ru": "Этой передачи нет в архиве.",
                                              "uk": "Цієї передачі немає в архіві."},
    "Wrong start place.": {"ru": "Неверное место начала.", "uk": "Невірне місце початку."},
    "An archived programme is not playing.": {"ru": "Сейчас играет не архив.", "uk": "Зараз грає не архів."},
    "This channel is not in the list.": {"ru": "Такого канала нет в списке.", "uk": "Такого каналу немає у списку."},
    "Remember where I stopped, on the device": {"ru": "Помнить, где остановились, на приставке",
                                                 "uk": "Пам'ятати, де зупинилися, на приставці"},
    "Places to continue from are taken only from what this device saved while you watched. The history of YouTube, "
    "SWEET.TV and Kodi is not used.": {
        "ru": "Продолжать можно только с мест, которые приставка сама запомнила при просмотре. "
              "История YouTube, SWEET.TV и Kodi не используется.",
        "uk": "Продовжувати можна лише з місць, які приставка сама запам'ятала під час перегляду. "
              "Історія YouTube, SWEET.TV і Kodi не використовується."},
    "Wrong value.": {"ru": "Неверное значение.", "uk": "Невірне значення."},
    "Remembering places is not available on this device.": {"ru": "Запоминание мест недоступно на этом устройстве.",
                                                             "uk": "Запам'ятовування місць недоступне на цьому пристрої."},
    "The choice could not be saved.": {"ru": "Не удалось сохранить выбор.", "uk": "Не вдалося зберегти вибір."},
    "Channels": {"ru": "Каналы", "uk": "Канали"},
    "Shows and series": {"ru": "Шоу и сериалы", "uk": "Шоу та серіали"},
    "Films": {"ru": "Фильмы", "uk": "Фільми"},
    "Wrong show.": {"ru": "Неверное шоу.", "uk": "Невірне шоу."},
    "This show is not in the list.": {"ru": "Такого шоу нет в списке.", "uk": "Такого шоу немає у списку."},
    # the cards of the shows, their episodes and the films
    "Episodes: {n}": {"ru": "Серий: {n}", "uk": "Серій: {n}"},
    "Latest episode": {"ru": "Последняя серия", "uk": "Остання серія"},
    "Airings: {n}": {"ru": "Показов: {n}", "uk": "Показів: {n}"},
    "Season {n}": {"ru": "Сезон {n}", "uk": "Сезон {n}"},
    "Episode": {"ru": "Серия", "uk": "Серія"},
    "{n} min": {"ru": "{n} мин", "uk": "{n} хв"},
    "Soon": {"ru": "Скоро", "uk": "Незабаром"},
    "Not in the archive": {"ru": "Нет в архиве", "uk": "Немає в архіві"},
    "This programme has not aired yet.": {"ru": "Эта передача ещё не вышла в эфир.", "uk": "Ця передача ще не вийшла в ефір."},
    "This episode has not been released yet.": {"ru": "Эта серия ещё не вышла.", "uk": "Ця серія ще не вийшла."},
    "Loading…": {"ru": "Загрузка…", "uk": "Завантаження…"},
    "No shows with episodes in the archive yet.": {"ru": "Шоу и сериалов с архивом пока нет.",
                                                   "uk": "Шоу та серіалів з архівом поки немає."},
    "No films in the archive yet.": {"ru": "Фильмов в архиве пока нет.", "uk": "Фільмів в архіві поки немає."},
    "This show has no episodes to show.": {"ru": "У этого шоу нет серий для показа.",
                                           "uk": "У цього шоу немає серій для показу."},
    "The list could not be loaded. Try again in a minute.": {
        "ru": "Не удалось загрузить список. Попробуйте через минуту.", "uk": "Не вдалося завантажити список. Спробуйте за хвилину."},
    "Open": {"ru": "Открыть", "uk": "Відкрити"},
    "Watch": {"ru": "Смотреть", "uk": "Дивитися"},
    "Back": {"ru": "Назад", "uk": "Назад"},
    # the menu on the left, the line over the cards and the key hints
    "Continue": {"ru": "Продолжить", "uk": "Продовжити"},
    "Favourites": {"ru": "Избранное", "uk": "Обране"},
    "All": {"ru": "Все каналы", "uk": "Усі канали"},
    "Genres": {"ru": "Жанры", "uk": "Жанри"},
    "{n} channels": {"ru": "{n} канал|{n} канала|{n} каналов", "uk": "{n} канал|{n} канали|{n} каналів"},   # one|few|many
    "Menu": {"ru": "Меню", "uk": "Меню"},
    "Up": {"ru": "Вверх", "uk": "Вгору"},
    "Favourite": {"ru": "Избранное", "uk": "Обране"},
    "Channel number": {"ru": "Номер канала", "uk": "Номер каналу"},
    "Guide and continue": {"ru": "Программа и продолжение", "uk": "Програма й продовження"},
    "Go back": {"ru": "Вернуться", "uk": "Повернутися"},
    # a channel
    "Channel {n}": {"ru": "Канал {n}", "uk": "Канал {n}"},
    "No channel {n}": {"ru": "Нет канала {n}", "uk": "Немає каналу {n}"},
    "Now": {"ru": "Сейчас", "uk": "Зараз"},
    "Next": {"ru": "Далее", "uk": "Далі"},
    "Catch-up": {"ru": "Архив", "uk": "Архів"},
    "Programme guide": {"ru": "Программа передач", "uk": "Програма передач"},
    "Continue from {time}": {"ru": "Продолжить с {time}", "uk": "Продовжити з {time}"},
    "No programme information": {"ru": "Нет сведений о передаче", "uk": "Немає відомостей про передачу"},
    "Programme": {"ru": "Передача", "uk": "Передача"},
    "OK plays the programme. Back closes the guide.": {"ru": "OK смотреть передачу. Назад закрыть программу.",
                                                       "uk": "OK дивитися передачу. Назад закрити програму."},
    "No favourites yet. Press the menu key on a channel to add it.": {
        "ru": "Избранного пока нет. Нажмите кнопку меню на канале, чтобы добавить его.",
        "uk": "Обраного поки немає. Натисніть кнопку меню на каналі, щоб додати його."},
    "Nothing watched yet. The channels you play show up here.": {
        "ru": "Вы пока ничего не смотрели. Включённые каналы появятся здесь.",
        "uk": "Ви поки нічого не дивилися. Увімкнені канали з'являться тут."},
    "No channels here.": {"ru": "Здесь нет каналов.", "uk": "Тут немає каналів."},
    "The channel list is out of date. Refreshing…": {"ru": "Список каналов устарел. Обновляется…",
                                                      "uk": "Список каналів застарів. Оновлюється…"},
    "Demo: nothing is played.": {"ru": "Демо: ничего не воспроизводится.", "uk": "Демо: нічого не відтворюється."},
    # the account chip, signing in and the status card
    "Demo": {"ru": "Демо", "uk": "Демо"},
    "Signed in": {"ru": "Вход выполнен", "uk": "Вхід виконано"},
    "Sign in": {"ru": "Войти", "uk": "Увійти"},
    "Sign in on your phone": {"ru": "Войдите с телефона", "uk": "Увійдіть з телефона"},
    "Live TV and the channel guide": {"ru": "Прямой эфир и программа передач", "uk": "Прямий ефір і програма передач"},
    "Scan to open the phone page": {"ru": "Наведите камеру, чтобы открыть страницу", "uk": "Наведіть камеру, щоб відкрити сторінку"},
    "Or sign in here with a code": {"ru": "Или войдите здесь по коду", "uk": "Або увійдіть тут за кодом"},
    "Press OK. Back returns to Home.": {"ru": "Нажмите OK. Назад на главный экран.", "uk": "Натисніть OK. Назад на головний екран."},
    "Try again": {"ru": "Повторить", "uk": "Повторити"},
    "1    On your phone, open": {"ru": "1    На телефоне откройте", "uk": "1    На телефоні відкрийте"},
    "1    Connect the stick to a network first": {"ru": "1    Сначала подключите приставку к сети",
                                                  "uk": "1    Спочатку підключіть приставку до мережі"},
    "2    Tab  {tab}  >  SWEET.TV": {"ru": "2    Вкладка  {tab}  >  SWEET.TV", "uk": "2    Вкладка  {tab}  >  SWEET.TV"},
    "3    Sign in there: the channels appear here by themselves.": {
        "ru": "3    Войдите там: каналы появятся здесь сами.", "uk": "3    Увійдіть там: канали з'являться тут самі."},
    "Cannot load the channels": {"ru": "Не удалось загрузить каналы", "uk": "Не вдалося завантажити канали"},
    "SWEET.TV answered with an error. Check the internet connection and that the account is signed in.": {
        "ru": "SWEET.TV ответил ошибкой. Проверьте интернет и что вход в аккаунт выполнен.",
        "uk": "SWEET.TV відповів помилкою. Перевірте інтернет і чи виконано вхід в обліковий запис."},
    "The channel list is not in the shape this screen knows. SWEET.TV may have changed it.": {
        "ru": "Список каналов в неизвестном экрану виде. Возможно, SWEET.TV его изменил.",
        "uk": "Список каналів у невідомому екрану вигляді. Можливо, SWEET.TV його змінив."},
    "The channel list cannot be read. SWEET.TV writes it again every 15 minutes.": {
        "ru": "Список каналов не читается. SWEET.TV записывает его заново каждые 15 минут.",
        "uk": "Список каналів не читається. SWEET.TV записує його знову кожні 15 хвилин."},
    "SWEET.TV has not delivered the channel list for a long while. Check the internet connection.": {
        "ru": "SWEET.TV давно не присылал список каналов. Проверьте интернет.",
        "uk": "SWEET.TV давно не надсилав список каналів. Перевірте інтернет."},
    "Trying again every few seconds. Back returns to Home.": {
        "ru": "Пробуем снова каждые несколько секунд. Назад на главный экран.",
        "uk": "Пробуємо знову кожні кілька секунд. Назад на головний екран."},
    "Loading channels": {"ru": "Загрузка каналов", "uk": "Завантаження каналів"},
    "SWEET.TV is fetching the channel list. After signing in this takes a minute or two.": {
        "ru": "SWEET.TV получает список каналов. После входа это занимает минуту-две.",
        "uk": "SWEET.TV отримує список каналів. Після входу це займає хвилину-дві."},
    "Checking again every few seconds. Back returns to Home.": {
        "ru": "Проверяем снова каждые несколько секунд. Назад на главный экран.",
        "uk": "Перевіряємо знову кожні кілька секунд. Назад на головний екран."},
    "No channels yet": {"ru": "Каналов пока нет", "uk": "Каналів поки немає"},
    "The channel list is empty. SWEET.TV may still be loading it, or the account has none.": {
        "ru": "Список каналов пуст. Возможно, SWEET.TV ещё его загружает, или в аккаунте их нет.",
        "uk": "Список каналів порожній. Можливо, SWEET.TV ще його завантажує, або в обліковому записі їх немає."},
    "Back returns to Home.": {"ru": "Назад на главный экран.", "uk": "Назад на головний екран."},
    # the search (the API of SWEET.TV: what the phone page and the TV ask it)
    "Search": {"ru": "Поиск", "uk": "Пошук"},
    "Channel": {"ru": "Канал", "uk": "Канал"},
    "Not in the list": {"ru": "Нет в списке", "uk": "Немає у списку"},
    "Search programmes and channels": {"ru": "Поиск передач и каналов", "uk": "Пошук передач і каналів"},
    "Press OK to type what to look for.": {"ru": "Нажмите OK и введите, что искать.", "uk": "Натисніть OK і введіть, що шукати."},
    "Searching…": {"ru": "Поиск…", "uk": "Пошук…"},
    "Nothing found for \"{q}\".": {"ru": "По запросу \"{q}\" ничего не найдено.", "uk": "За запитом \"{q}\" нічого не знайдено."},
    "Type at least 2 letters.": {"ru": "Введите хотя бы 2 буквы.", "uk": "Введіть хоча б 2 літери."},
    "{n} more airing": {"ru": "ещё {n} показ", "uk": "ще {n} показ"},
    "{n} more airings": {"ru": "ещё {n} показ|ещё {n} показа|ещё {n} показов", "uk": "ще {n} показ|ще {n} покази|ще {n} показів"},
    "SWEET.TV does not accept the sign-in. Sign in again.": {"ru": "SWEET.TV не принимает вход. Войдите заново.",
                                                              "uk": "SWEET.TV не приймає вхід. Увійдіть знову."},
    "SWEET.TV did not answer. Check the internet connection.": {"ru": "SWEET.TV не ответил. Проверьте интернет.",
                                                                 "uk": "SWEET.TV не відповів. Перевірте інтернет."},
    "SWEET.TV answered with an error. Try again in a minute.": {"ru": "SWEET.TV ответил ошибкой. Попробуйте через минуту.",
                                                                 "uk": "SWEET.TV відповів помилкою. Спробуйте за хвилину."},
    "SWEET.TV answered in a way this device does not understand.": {"ru": "SWEET.TV ответил так, что приставка этого не понимает.",
                                                                     "uk": "SWEET.TV відповів так, що приставка цього не розуміє."},
    "Wrong date.": {"ru": "Неверная дата.", "uk": "Невірна дата."},
    "The archive of this channel does not go back that far.": {"ru": "Архив этого канала не уходит так далеко назад.",
                                                               "uk": "Архів цього каналу не сягає так далеко."},
    "The guide of this channel does not reach that far ahead.": {"ru": "Программа этого канала не доходит так далеко вперёд.",
                                                                  "uk": "Програма цього каналу не сягає так далеко вперед."},
    # the day and the month in "Fri 20 Nov 17:00"
    "Mon": {"ru": "Пн", "uk": "Пн"}, "Tue": {"ru": "Вт", "uk": "Вт"}, "Wed": {"ru": "Ср", "uk": "Ср"},
    "Thu": {"ru": "Чт", "uk": "Чт"}, "Fri": {"ru": "Пт", "uk": "Пт"}, "Sat": {"ru": "Сб", "uk": "Сб"}, "Sun": {"ru": "Вс", "uk": "Нд"},
    "Jan": {"ru": "янв", "uk": "січ"}, "Feb": {"ru": "фев", "uk": "лют"}, "Mar": {"ru": "мар", "uk": "бер"},
    "Apr": {"ru": "апр", "uk": "кві"}, "May": {"ru": "мая", "uk": "тра"}, "Jun": {"ru": "июн", "uk": "чер"},
    "Jul": {"ru": "июл", "uk": "лип"}, "Aug": {"ru": "авг", "uk": "сер"}, "Sep": {"ru": "сен", "uk": "вер"},
    "Oct": {"ru": "окт", "uk": "жов"}, "Nov": {"ru": "ноя", "uk": "лис"}, "Dec": {"ru": "дек", "uk": "гру"},
    # the name of an episode: S2 E7
    "S{n}": {"ru": "С{n}", "uk": "С{n}"},
    "E{n}": {"ru": "Э{n}", "uk": "Е{n}"},
    # Netflix-style rail, filter chips, hero actions and modals
    "Shows": {"ru": "Шоу", "uk": "Шоу"},
    "Series": {"ru": "Сериалы", "uk": "Серіали"},
    "Movies": {"ru": "Фильмы", "uk": "Фільми"},
    "TV Channels": {"ru": "ТВ-каналы", "uk": "ТБ-канали"},
    "All items": {"ru": "Все", "uk": "Усі"},
    "Live TV": {"ru": "Эфирные", "uk": "Ефірні"},
    "24/7": {"ru": "24/7", "uk": "24/7"},
    "From start": {"ru": "С начала", "uk": "Спочатку"},
    "From start (0:00)": {"ru": "С начала (0:00)", "uk": "Спочатку (0:00)"},
    "Watch live": {"ru": "Смотреть эфир", "uk": "Дивитись ефір"},
    "Today": {"ru": "Сегодня", "uk": "Сьогодні"},
    "Yesterday": {"ru": "Вчера", "uk": "Вчора"},
    "Tomorrow": {"ru": "Завтра", "uk": "Завтра"},
    "{n} season": {"ru": "{n} сезон", "uk": "{n} сезон"},
    "{n} episode": {"ru": "{n} серия", "uk": "{n} серія"},
    "Next episode in {n}s": {"ru": "Следующая серия через {n} с", "uk": "Наступна серія через {n} с"},
    "Seasons and episodes": {"ru": "Сезоны и серии", "uk": "Сезони та серії"},
    "Episodes": {"ru": "Выпуски", "uk": "Випуски"},
    "Add to favourites": {"ru": "В избранное", "uk": "В обране"},
    "In favourites": {"ru": "В избранном", "uk": "В обраному"},
    "Popular": {"ru": "Популярные", "uk": "Популярні"},
    "IMDb Rating": {"ru": "Рейтинг IMDb", "uk": "Рейтинг IMDb"},
    "Newest": {"ru": "Новинки", "uk": "Новинки"},
    "A-Z": {"ru": "А-Я", "uk": "А-Я"},
    "New search": {"ru": "Новый поиск", "uk": "Новий пошук"},
    "Archive": {"ru": "В архиве", "uk": "В архіві"},
    "Watched": {"ru": "Просмотрено", "uk": "Переглянуто"},
    "Nothing in Continue yet.": {"ru": "Пока нет начатых просмотров.", "uk": "Поки немає розпочатих переглядів."},
    "No favourites yet.": {"ru": "Избранного пока нет.", "uk": "Обраного поки немає."},
    "Search everything": {"ru": "Поиск по всему", "uk": "Пошук по всьому"},
    "Search in {section}": {"ru": "Поиск: {section}", "uk": "Пошук: {section}"},
    "Continue S{s} E{e} from {time}": {"ru": "Продолжить С{s} Э{e} с {time}", "uk": "Продовжити С{s} Е{e} з {time}"},
    "Watch S{s} E{e}": {"ru": "Смотреть С{s} Э{e}", "uk": "Дивитись С{s} Е{e}"},
    "OK plays. Back closes.": {"ru": "OK воспроизводит. Назад закрывает.", "uk": "OK відтворює. Назад закриває."},
}


def tr(msgid) -> str:
    """The text for a person: the translation in LANG, else the English msgid itself."""
    return TEXT.get(msgid, {}).get(LANG) or msgid


def _form(n) -> int:
    """Which of the three forms of a Russian or Ukrainian noun goes with `n`: 0 for 1, 21, ...; 1 for 2-4, 22-24, ...; 2 else."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return 0
    return 1 if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 2


def tr_n(n, one, other) -> str:
    """"1 channel" / "5 channels" in the language: `one` and `other` are English msgids with {n}. Russian and Ukrainian keep
    the three forms of `other` in TEXT, joined with "|" (one|few|many); the English language, and any without a translation,
    use `one` for 1 and `other` for the rest."""
    forms = TEXT.get(other, {}).get(LANG)
    if forms:
        return forms.split("|")[_form(n)].format(n=n)
    return (one if n == 1 else other).format(n=n)
