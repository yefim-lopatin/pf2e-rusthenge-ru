#!/usr/bin/env python3
"""Собирает Babele-перевод Rusthenge 14.1.0 из локальных источников.

Исходные файлы Paizo и PDF никогда не копируются в модуль. В репозиторий
попадают только сопоставленные по _id строки Babele и контрольные хэши.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SERVICE_PAGE_IDS = {
    "00credits0000000",
    "01opengamelice00",
    "01audiocredits00",
    "00changelog00000",
}

TECH_RE = re.compile(r"@[A-Za-z][A-Za-z0-9]*\[[^\]]+\](?:\{[^{}]*\})?")
TECH_CORE_RE = re.compile(r"(@[A-Za-z][A-Za-z0-9]*\[[^\]]+\])(?:\{[^{}]*\})?")
TAG_RE = re.compile(r"<[^>]+>")

# Коды локаций в старом структурированном тексте имели кириллический сдвиг.
AREA_PREFIX = {"A": "А", "B": "Б", "C": "В", "D": "Г", "E": "Д", "F": "Е"}

JOURNAL_NAMES = {
    "pf2sa06401frontm": "Вводная часть",
    "pf2sa06402messag": "Глава 1: Послание в ночи",
    "pf2sa06403therus": "Глава 2: Ржавые руины",
    "pf2sa06404ressur": "Глава 3: Воскрешение ржавчины",
    "pf2sa06405advent": "Инструментарий приключения",
    "pf2sa06406handou": "Раздаточные материалы",
    "pf2sa06407artgal": "Галерея",
}

SCENE_NAMES = {
    "Temple Of Xar-Azmak": "Храм Ксар-Азмака",
    "The Skymetal Workshop": "Мастерская небесного металла",
    "Rusthenge": "Растхендж",
    "Stonehome Ground Floor": "Стоунхоум: первый этаж",
    "Stonehome Roof": "Стоунхоум: крыша",
    "Stonehome Second Floor": "Стоунхоум: второй этаж",
    "Stonehome Basement": "Стоунхоум: подвал",
    "Landing": "Стартовая сцена",
    "Iron Harbor": "Айрон-Харбор",
    "Osprey Cove": "Бухта Скопы",
    "Despoiler's Deep": "Глубины Опустошителя",
    "Kindred Crossing": "Родственное Побережье",
}

PAGE_NAMES = {
    "01adventures0000": "Краткое содержание",
    "01rusthenge00000": "Растхендж",
    "01landing0000000": "Стартовая страница",
    "02chapter1000000": "Глава 1: Послание в ночи",
    "03chapter2000000": "Глава 2: Ржавые руины",
    "04chapter3000000": "Глава 3: Воскрешение ржавчины",
    "05adventuretoo00": "Инструментарий приключения",
    "06handout0100000": "Раздаточный материал №1",
    "06handout0200000": "Раздаточный материал №2",
}

# Одна страница старого макета может соответствовать нескольким атомарным
# страницам V14. Технические токены всегда берутся из соответствующей V14-страницы.
NARRATIVE_REFERENCE = {
    "01adventures0000": "Краткое Содержание",
    "01rusthenge00000": "Предыстория Местности",
    "01landing0000000": "Краткое Содержание",
    "02chapter1000000": "Предыстория Местности",
    "02adeeperhisto00": "Углубленная Предыстория",
    "02startingrust00": "Начало Приключения",
    "02optionalstar00": "Начало Приключения",
    "02elderordwi0000": "Начало Приключения",
    "02kindredcross00": "Путь Родства",
    "02ironharbor0000": "Железная Гавань",
    "02approachingt00": "Приближение к Деревне",
    "02askingaround00": "Расспросы",
    "02elsies00000000": "Б1. У Элси",
    "02elsiesconcer00": "Б1. У Элси",
    "02theswordfish00": "Б2. Меч-Рыба",
    "02sneakingonbo00": "Б2. Меч-Рыба",
    "02swordfishdis00": "Б2. Меч-Рыба",
    "02gettinginafi00": "Б2. Меч-Рыба",
    "02speakingtoth00": "Б2. Меч-Рыба",
    "02finalreward000": "Б2. Меч-Рыба",
    "02stonehome00001": "Каменный Дом",
    "02rustcreep00000": "Каменный Дом",
    "02templefeatur00": "Каменный Дом",
    "02enteringston00": "Вход в Каменный Дом",
    "02speakingwith00": "В5. Клиника",
    "02speakingtova00": "В15. Старшая Казарма / Сурово 1",
    "03chapter2000000": "Начало 2 Главы",
    "03startingthis00": "Начало 2 Главы",
    "03rusthenge00000": "Растхендж",
    "03sacrificekee00": "Жертвенные Хранители / Серьезно 2",
    "03encounteradj00": "Жертвенные Хранители / Серьезно 2",
    "03theskymetalw00": "Мастерская Небесного Металла",
    "04chapter3000000": "Храм Ксар-Азмак",
    "04thetempleofx00": "Храм Ксар-Азмак",
    "04despoilersde00": "Глубины Опустошителя",
    "04concludingth00": "Завершение Приключения",
    "04whatifthepcs00": "Завершение Приключения",
    "05adventuretoo00": "Краткое Содержание",
    "05shoppinginir00": "Покупки в Железной Гавани",
    "05thehornofrus00": "Рог Ржавчины",
    "05rusthengebac00": "Предыстории РастХендж",
    "05demonvloriak00": "Бестиарий: Влориак",
    "05sinsludge00000": "Бестиарий: Первородная Зависть",
    "06handout0100000": "Журнал Рыбы-Меч",
    "06handout0200000": "Последняя Запись Мейтримара",
}

GLOSSARY = (
    ("РастХендж", "Растхендж"),
    ("Каменный Дом", "Стоунхоум"),
    ("Каменный дом", "Стоунхоум"),
    ("Мейтреймар", "Мейтремар"),
    ("Мейтримар", "Мейтремар"),
    ("Бухта Оспри", "Бухта Скопы"),
    ("Железная Гавань", "Айрон-Харбор"),
    ("Путь Родства", "Родственное Побережье"),
    ("ПИ", "герои"),
)

SIMPLE_NAMES = {
    "A Cry for Help": "Крик о помощи", "The Old Bridge": "Старый мост",
    "Sheltered Ledge": "Укрытый уступ", "Drydock": "Сухой док", "Gold’s Ruin": "Руины Голда",
    "Fisher’s Point": "Рыбацкий мыс", "Thunderhead Isle": "Остров Громовой Головы", "Stream Outlet": "Сток ручья",
    "Stonehome": "Стоунхоум", "Courtyard": "Внутренний двор", "Stables": "Конюшни", "Main Entrance": "Главный вход",
    "Worship Hall": "Зал поклонений", "Clinic": "Лечебница", "Smithy": "Кузница", "Outer Guard Stations": "Внешние посты стражи",
    "Inner Guard Stations": "Внутренние посты стражи", "Kitchen": "Кухня", "Stairwell": "Лестница", "Duel Preparation": "Подготовка к дуэли",
    "Storage": "Склад", "Upstairs Hall": "Верхний холл", "Dueling Balcony": "Балкон для дуэлей", "Senior Barracks": "Старшая казарма",
    "Junior Barracks": "Младшая казарма", "Defensive Battery": "Оборонительная батарея", "Ramparts": "Боевая галерея", "Rooftop Range": "Стрельбище на крыше",
    "Basement": "Подвал", "Secure Storage": "Защищённое хранилище", "Tunnel to Rusthenge": "Туннель в Растхендж",
    "The Rusted Door": "Ржавая дверь", "Grand Entrance": "Большой вход", "Grand Altar": "Большой алтарь", "Storeroom": "Кладовая",
    "Priest’s Quarters": "Покои жреца", "Cultist Quarters": "Покои культистов", "Prison": "Тюрьма", "Dining Hall": "Столовая",
    "Dripping Room": "Капающая комната", "Toilets": "Уборные", "Magical Storage": "Магическое хранилище", "Ritual Room": "Ритуальная комната",
    "Refuse Pile": "Куча мусора", "Workshop": "Мастерская", "Metal Rod Storage": "Хранилище металлических стержней", "Akata Husbandry": "Питомник акат",
    "Ingot Storage": "Склад слитков", "Research Lab": "Исследовательская лаборатория", "Secret Lab": "Тайная лаборатория",
    "Grand Gallery": "Большая галерея", "Meitremar’s Quarters": "Покои Мейтремара", "Bedroom Prison": "Спальня-тюрьма", "Wreckage Room": "Комната обломков",
    "Worship Chamber": "Зал поклонения", "Darklands Landing": "Преддверие Тёмных земель", "The Despoiled Rift": "Осквернённый разлом", "Watchpost": "Наблюдательный пост",
    "Dero Encampment": "Лагерь деро", "Dero Barracks": "Казармы деро", "Zaiox’s Nook": "Уголок Заокса", "Werebat Camp": "Лагерь вернетопырей",
    "Mold Farm": "Грибная ферма", "Boggard Bridge": "Мост боггардов", "The Black Lake": "Чёрное озеро", "Boggard Compost": "Компост боггардов",
    "Rusted Door": "Ржавая дверь", "Ritual Preparation Chamber": "Зал подготовки ритуала", "Summoning Chamber": "Зал призыва",
}

ACTOR_NAMES = {
    "Sydri": "Сидри", "Rustsworn Cultist": "Культист Ржавой Клятвы", "Zombie Shambler": "Шаркающий зомби",
    "Rustsworn Initiate": "Посвящённый Ржавой Клятвы", "Haniver": "Хэнивер", "Vanda": "Ванда", "Envyspawn": "Порождение Зависти",
    "Rusted Door": "Ржавая дверь", "Severed Head": "Отрубленная голова", "Azomi": "Азоми", "Dero Stalker": "Деро-сталкер",
    "Boggard Scout": "Боггард-разведчик", "Elder Ordwi": "Старейшина Ордви", "Theiltemar": "Тейлтемар", "Gurga": "Гурга",
    "Vlorian Cythnigot": "Влорианский цитнигот", "Esipil": "Эсипил", "Starving Werebat": "Голодный вернетопырь", "Akata": "Аката",
    "Glutu": "Глуту", "Meitremar": "Мейтремар", "Void Zombie": "Пустотный зомби", "Giant Centipede": "Гигантская многоножка",
    "Rust Zombie": "Ржавый зомби", "Trygve": "Трюгве", "Primordial Envy": "Первородная Зависть", "Reefclaw": "Рифокоготь",
    "Vloriak": "Влориак", "Ostovite": "Остовит", "Fallen Acolyte": "Падший аколит", "Clockwork Serpent Spy": "Заводная змея-шпион",
    "Zaiox": "Заокс", "Knurr Ragnulf": "Кнурр Рагнульф", "Dretch": "Дретч", "Janis": "Янис", "Gnork": "Гнорк",
    "Dero Strangler": "Деро-душитель", "Skeleton Guard": "Скелет-страж", "Yeth Hound": "Гончая йета", "Larva": "Лярва", "Deadly Fungus Leshy": "Смертоносный грибной леший",
}

ACTOR_NAMES.update({
    "South Roof Barrel": "Бочка на южной крыше", "North Roof Barrel": "Бочка на северной крыше", "Wall": "Стена",
    "Janis' Reward": "Награда Янис", "Fishing Hut": "Рыбацкая хижина", "Quarters": "Покои",
    "East Guard Station": "Восточный пост стражи", "West Guard Station": "Западный пост стражи", "Anvil": "Наковальня",
    "Navigational Logs": "Навигационные журналы", "Ship’s Payroll": "Судовая платёжная ведомость", "Iron-Bound Chest": "Окованный железом сундук",
    "Statue": "Статуя", "Waterproof Leather Bag": "Водонепроницаемая кожаная сумка", "Shelves": "Полки", "Rusty Ingots": "Ржавые слитки",
    "Skeletal Remains": "Скелетированные останки", "Captain Perrios’s Head": "Голова капитана Перриоса", "Rusty Mannequin": "Ржавый манекен",
    "Beacon Shot Barrel": "Бочка с сигнальными зарядами", "Mushrooms": "Грибы", "Crystals": "Кристаллы", "Desk": "Письменный стол",
    "Corpses": "Трупы", "Treasure Pile": "Куча сокровищ", "Small Coffer": "Малая шкатулка", "Barrel": "Бочка", "Deck Hand": "Матрос",
    "Swordfish’s Log": "Журнал «Рыбы-меч»", "Small Bedroom": "Малая спальня", "Derrol's Gift": "Подарок Деррола", "Mannequin": "Манекен",
    "Wooden Post": "Деревянный столб", "Footlockers": "Рундуки", "Bottle of “Carpenden”": "Бутылка «Карпендена»",
    "Warfare Lore": "Знания о войне", "Divine Prepared Spells": "Подготовленные сакральные заклинания", "Divine Focus Spells": "Сакральные фокусные заклинания",
    "Divine Spontaneous Spells": "Спонтанные сакральные заклинания", "Divine Innate Spells": "Врождённые сакральные заклинания", "Occult Innate Spells": "Врождённые оккультные заклинания",
    "Occult Spontaneous Spells": "Спонтанные оккультные заклинания", "Arcane Innate Spells": "Врождённые арканные заклинания", "Demonic Bloodline Spells": "Заклинания демонической линии крови",
    "Ancient Coins and Curiosities": "Древние монеты и диковинки", "Eye Garnets": "Гранаты-глаза", "Unopened Pony Keg of Akvavit": "Неоткрытый бочонок аквавита",
    "Fine Captain's Hat": "Отличная капитанская шляпа", "Smithing Lore": "Знания о кузнечном деле", "Raw Materials for Crafting Cytillesh Drug Doses or Cytillesh Oil": "Сырьё для изготовления цитиллеша или цитиллешевого масла",
    "Noqual Crystals": "Кристаллы ноквала", "Scroll Case with Ship's Charts": "Тубус с морскими картами", "Dagger": "Кинжал", "Chart a Course": "Проложить курс",
    "Navigator's Edge": "Преимущество штурмана", "Sailing Lore": "Знания о мореплавании", "Key To C21": "Ключ от C21", "Key to D7": "Ключ от D7", "Key to E3": "Ключ от E3",
    "Empty Bottle": "Пустая бутылка", "Fist": "Кулак", "Bottle": "Бутылка", "Heft Crate": "Поднять ящик", "Swig": "Глоток", "Labor Lore": "Знания о физическом труде",
    "Bay": "Бухта", "Sinister Bite": "Зловещий укус", "Meitremar's Journal": "Журнал Мейтремара", "Tiny Brass Key set with Small Gemstones": "Крошечный латунный ключ с мелкими самоцветами", "Azomi’s Porcelain Mask": "Фарфоровая маска Азоми",
    "Vloriak Demon": "Демон Влориак", "Sister Vanda": "Сестра Ванда", "Smith Trygve": "Кузнец Трюгве", "Sinsludge": "Грехошлам",
    "Sanitizing Pin": "Очищающая булавка", "High Priest Knurr Ragnulf": "Верховный жрец Кнурр Рагнульф", "First Mate Janis": "Старпом Янис", "Horn of Rust": "Рог Ржавчины",
    "Elsie": "Элси", "Derrol Finnick": "Деррол Финник", "Clockwork Serpent": "Заводная змея", "Clockwork Belimarius": "Заводной Белимариус",
    "Void Zombie Boggard": "Пустотный зомби-боггард", "Deep Gnome (Svirfneblin)": "Глубинный гном (свирфнеблин)", "Sailor": "Матрос", "Prisoner": "Пленник",
    "Petitioner (the Larvae)": "Петиционер (лярва)", "Ida (Rosethorn Ram)": "Ида (баран Розовый Шип)", "Haniver Gremlin": "Гремлин-хэнивер", "Elder Vandous": "Старейшина Вандус",
    "Elder Johedia": "Старейшина Йохейда", "Elder Bo-Mel": "Старейшина Бо-Мел", "Elder Anlorgog": "Старейшина Анлоргог", "Durgon": "Дургон",
    "Esipil (Calico Cat Form)": "Эсипил (облик трёхцветной кошки)", "Captain Perrio's Head": "Голова капитана Перрио", "Bolgus": "Болгус", "Birger Frodeson": "Биргер Фродесон",
    "Azmakian Animated Armor": "Азмакианский оживлённый доспех", "Abrikandilu": "Абрикандилу",
})


def load_adventure(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        if len(data) != 1:
            raise ValueError(f"Ожидался один Adventure в {path}")
        data = data[0]
    return data


def clean_ru(value: str) -> str:
    value = re.sub(r"<img\b[^>]*>", "", value, flags=re.I)
    value = re.sub(r"<a\b[^>]*>", "", value, flags=re.I)
    value = re.sub(r"</a\s*>", "", value, flags=re.I)
    value = re.sub(r"modules/pf2e-ts-adv/[^\"' )<]+", "", value, flags=re.I)
    for old, new in GLOSSARY:
        value = value.replace(old, new)
    return value


def technical_cores(value: str) -> list[str]:
    return [TECH_CORE_RE.fullmatch(token).group(1) for token in TECH_RE.findall(value)]


def extract_pdf_pages(path: Path) -> list[str]:
    try:
        import pdfplumber  # type: ignore
    except ImportError as error:
        raise SystemExit(
            "Для сборки из PDF нужен pdfplumber (pip install pdfplumber). "
            "В релизный ZIP PDF не включается."
        ) from error
    with pdfplumber.open(path) as document:
        pages = [page.extract_text() or "" for page in document.pages]
    if len(pages) != 68:
        raise ValueError(f"Ожидалось 68 страниц PDF, получено {len(pages)}")
    return pages


PDF_STOPWORDS = set(
    "этот эта это эти которые который которая чтобы когда если или как его её их для при что все они она однако".split()
)


def russian_words(value: str) -> Counter[str]:
    value = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", value))).lower()
    return Counter(word for word in re.findall(r"[а-яё]{4,}", value) if word not in PDF_STOPWORDS)


def best_pdf_page(reference_html: str, pdf_pages: list[str]) -> tuple[int, float]:
    reference = russian_words(reference_html)
    total = max(1, sum(reference.values()))
    best_index = -1
    best_score = -1.0
    for index, page in enumerate(pdf_pages):
        # Служебные/OGL и обложки не участвуют в поиске игрового текста.
        if index < 4 or index >= 65:
            continue
        candidate = russian_words(page)
        score = sum(min(count, candidate[word]) for word, count in reference.items()) / total
        if score > best_score:
            best_index, best_score = index, score
    if best_index < 0 or best_score < 0.08:
        raise ValueError(f"Не удалось надёжно сопоставить русский текст с PDF (лучший балл {best_score:.2f})")
    return best_index, best_score


def pdf_page_text(page_text: str, page_number: int) -> str:
    ignored = {
        "Глава 1:", "Глава 2:", "Глава 3:", "Ночное", "послание", "Ржавые", "руины",
        "Воскрешение", "Ржавчины", "Инструменты", "приключения",
    }
    lines = []
    for raw in page_text.splitlines():
        line = " ".join(raw.split()).strip()
        if not line or line in ignored or line == str(page_number):
            continue
        lines.append(line)
    joined = ""
    for line in lines:
        if joined.endswith("-") and line and line[0].islower():
            joined = joined[:-1] + line
        else:
            joined += (" " if joined else "") + line
    return joined


def reflow_preserving_html(source_html: str, translated_text: str) -> str:
    """Заменяет только текстовые узлы, оставляя каждый HTML-тег и атрибут без изменений."""
    parts = re.split(r"(<[^>]+>)", source_html)
    weighted: list[tuple[int, int]] = []
    for index in range(0, len(parts), 2):
        source_text = TECH_RE.sub(" ", html.unescape(parts[index]))
        weight = len(re.findall(r"[A-Za-zА-яЁё]{2,}", source_text))
        if weight:
            weighted.append((index, weight))
    if not weighted:
        return source_html

    words = translated_text.split()
    total_weight = sum(weight for _, weight in weighted)
    consumed_weight = 0
    cursor = 0
    for position, (index, weight) in enumerate(weighted):
        consumed_weight += weight
        end = len(words) if position == len(weighted) - 1 else round(len(words) * consumed_weight / total_weight)
        chunk = html.escape(" ".join(words[cursor:end]), quote=False)
        original_tokens = TECH_RE.findall(parts[index])
        if original_tokens:
            chunk = (chunk + " " if chunk else "") + " ".join(original_tokens)
        parts[index] = chunk
        cursor = end
    # Технические токены из нулевых по весу узлов тоже должны остаться на месте.
    weighted_indexes = {index for index, _ in weighted}
    for index in range(0, len(parts), 2):
        if index not in weighted_indexes:
            parts[index] = " ".join(TECH_RE.findall(parts[index]))
    return "".join(parts)


def html_tags(value: str) -> list[str]:
    return TAG_RE.findall(value)


def pdf_area_section(pdf_pages: list[str], page_index: int, code: str) -> tuple[str, bool, int]:
    """Вырезает из PDF текст одной локации; продолжение может находиться на следующей странице."""
    prefix_pattern = {"A": "[AА]", "B": "[BВ]", "C": "[CС]", "D": "D", "E": "E", "F": "F"}[code[0]]
    heading = re.compile(rf"(?<![A-ZАВС0-9]){prefix_pattern}{re.escape(code[1:])}\.\s+")
    next_heading = re.compile(r"(?<![A-ZАВС0-9])[A-FАВС]\d{1,2}\.\s+")
    nearby = sorted(
        range(max(0, page_index - 2), min(len(pdf_pages), page_index + 3)),
        key=lambda candidate: abs(candidate - page_index),
    )
    for candidate in nearby:
        combined = pdf_pages[candidate]
        if candidate + 1 < len(pdf_pages):
            combined += "\n" + pdf_pages[candidate + 1]
        start_match = heading.search(combined)
        if not start_match:
            continue
        end_match = next_heading.search(combined, start_match.end())
        end = end_match.start() if end_match else len(combined)
        return combined[start_match.start():end], True, candidate
    return pdf_pages[page_index], False, page_index


def sync_technical_tokens(russian_html: str, source_html: str) -> str:
    """Сохраняет русские подписи, но все команды/цели берёт только из официальной V14."""
    source_tokens = TECH_RE.findall(source_html)
    cursor = 0

    def replacement(match: re.Match[str]) -> str:
        nonlocal cursor
        if cursor >= len(source_tokens):
            return ""
        source = source_tokens[cursor]
        cursor += 1
        ru_label = re.search(r"\{([^{}]*)\}$", match.group(0))
        if ru_label:
            source = re.sub(r"\{[^{}]*\}$", "", source) + "{" + ru_label.group(1) + "}"
        return source

    result = TECH_RE.sub(replacement, russian_html)
    if cursor < len(source_tokens):
        controls = " ".join(source_tokens[cursor:])
        result += (
            '<details class="rusthenge-ru-controls"><summary>Ссылки и проверки Foundry</summary>'
            f"<p>{controls}</p></details>"
        )
    return result


def first_area_code(content: str) -> str | None:
    text = html.unescape(TAG_RE.sub(" ", content))
    match = re.search(r"\b([A-F])(\d{1,2})\.", text)
    return match.group(1) + str(int(match.group(2))) if match else None


def reference_area_code(name: str) -> str | None:
    match = re.match(r"\s*([AАБВГДЕЕ])\s*(\d{1,2})\.", name, flags=re.I)
    if not match:
        return None
    prefix = match.group(1).upper()
    if prefix == "A":
        prefix = "А"
    return prefix + str(int(match.group(2)))


def translated_name(name: str) -> str:
    return SIMPLE_NAMES.get(name, ACTOR_NAMES.get(name, clean_ru(name)))


def item_source(item: dict[str, Any]) -> str | None:
    return (
        item.get("_stats", {}).get("compendiumSource")
        or item.get("flags", {}).get("pf2e", {}).get("compendiumSource")
        or item.get("flags", {}).get("core", {}).get("sourceId")
    )


def make_translation(source: dict[str, Any], reference: dict[str, Any], pdf_pages: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    ref_pages = {p["name"]: p for j in reference["journal"] for p in j.get("pages", [])}
    ref_areas = {reference_area_code(p["name"]): p for p in ref_pages.values() if reference_area_code(p["name"])}

    # Сопоставление актёров по источному UUID надёжнее имён и внутренних id.
    ref_actors_by_source: dict[str, dict[str, Any]] = {}
    ref_actors_by_id = {actor["_id"]: actor for actor in reference.get("actors", [])}
    ref_items_by_id = {
        item["_id"]: item
        for actor in reference.get("actors", [])
        for item in actor.get("items", [])
    }
    for actor in reference.get("actors", []):
        src = item_source(actor)
        if src:
            ref_actors_by_source.setdefault(src, actor)

    translated_journals: dict[str, Any] = {}
    page_index: dict[str, Any] = {}
    covered_text_pages = 0
    gallery_pages = 0
    pdf_alignment: dict[str, Any] = {}
    for journal in source["journal"]:
        pages: dict[str, Any] = {}
        for page in journal.get("pages", []):
            pid = page["_id"]
            if pid in SERVICE_PAGE_IDS:
                continue
            if page.get("type") == "image":
                pages[pid] = {"name": translated_name(page["name"])}
                gallery_pages += 1
                continue

            source_html = page.get("text", {}).get("content", "")
            code = first_area_code(source_html)
            ref_page = None
            if code:
                ref_code = AREA_PREFIX[code[0]] + code[1:]
                ref_page = ref_areas.get(ref_code)
            if ref_page is None:
                ref_page = ref_pages.get(NARRATIVE_REFERENCE.get(pid, ""))
            if ref_page is None:
                raise ValueError(f"Не найден русский текст для страницы {pid} ({page['name']})")

            ref_html = clean_ru(ref_page.get("text", {}).get("content", ""))
            pdf_index, alignment_score = best_pdf_page(ref_html, pdf_pages)
            pdf_text = pdf_pages[pdf_index]
            area_section_used = False
            content_pdf_index = pdf_index
            if code:
                pdf_text, area_section_used, content_pdf_index = pdf_area_section(pdf_pages, pdf_index, code)
            russian_plain = pdf_page_text(pdf_text, content_pdf_index + 1)
            russian_html = reflow_preserving_html(source_html, russian_plain)
            name = PAGE_NAMES.get(pid) or translated_name(page["name"])
            if name == page["name"]:
                name = clean_ru(ref_page["name"])
            pages[pid] = {"name": name, "text": russian_html}
            page_index[pid] = {
                "journalId": journal["_id"],
                "sourceName": page["name"],
                "translatedName": name,
                "technicalTokens": TECH_RE.findall(source_html),
                "technicalHash": hashlib.sha256("\n".join(TECH_RE.findall(source_html)).encode()).hexdigest(),
                "htmlHash": hashlib.sha256("\n".join(html_tags(source_html)).encode()).hexdigest(),
                "pdfPage": content_pdf_index + 1,
                "alignmentPage": pdf_index + 1,
                "alignmentScore": round(alignment_score, 4),
                "areaSection": area_section_used,
                "areaCode": code,
            }
            covered_text_pages += 1

        translated_journals[journal["_id"]] = {
            "name": JOURNAL_NAMES[journal["_id"]],
            "pages": pages,
        }

    actors: dict[str, Any] = {}
    actor_technical: dict[str, list[str]] = {}
    actor_html: dict[str, str] = {}
    custom_items = 0
    custom_items_translated = 0
    for actor in source.get("actors", []):
        ref_actor = ref_actors_by_source.get(item_source(actor)) or ref_actors_by_id.get(actor["_id"])
        actor_name = clean_ru(ref_actor["name"]) if ref_actor else ACTOR_NAMES.get(actor["name"], translated_name(actor["name"]))
        entry: dict[str, Any] = {"name": actor_name, "tokenName": actor_name}
        if ref_actor:
            public = ref_actor.get("system", {}).get("details", {}).get("publicNotes", "")
            private = ref_actor.get("system", {}).get("details", {}).get("privateNotes", "")
            if public:
                source_public = actor.get("system", {}).get("details", {}).get("publicNotes", "")
                public_plain = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", clean_ru(public))))
                entry["description"] = reflow_preserving_html(source_public, public_plain)
                actor_technical[f"{actor['_id']}/description"] = TECH_RE.findall(source_public)
                actor_html[f"{actor['_id']}/description"] = hashlib.sha256(
                    "\n".join(html_tags(source_public)).encode()
                ).hexdigest()
            if private:
                source_private = actor.get("system", {}).get("details", {}).get("privateNotes", "")
                private_plain = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", clean_ru(private))))
                entry["descriptionGM"] = reflow_preserving_html(source_private, private_plain)
                actor_technical[f"{actor['_id']}/descriptionGM"] = TECH_RE.findall(source_private)
                actor_html[f"{actor['_id']}/descriptionGM"] = hashlib.sha256(
                    "\n".join(html_tags(source_private)).encode()
                ).hexdigest()

        item_entries = []
        for item in actor.get("items", []):
            if item_source(item):
                continue  # pf2e-ru переводит системный Compendium UUID.
            custom_items += 1
            ref_item = ref_items_by_id.get(item["_id"])
            item_entry = {
                "id": item["_id"],
                "name": translated_name(clean_ru(ref_item["name"])) if ref_item else translated_name(item["name"]),
            }
            if ref_item:
                source_desc = item.get("system", {}).get("description", {})
                ref_desc = ref_item.get("system", {}).get("description", {})
                if ref_desc.get("value"):
                    source_value = source_desc.get("value", "")
                    ref_plain = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", clean_ru(ref_desc["value"]))))
                    item_entry["description"] = reflow_preserving_html(source_value, ref_plain)
                    key = f"{actor['_id']}/items/{item['_id']}/description"
                    actor_technical[key] = TECH_RE.findall(source_value)
                    actor_html[key] = hashlib.sha256("\n".join(html_tags(source_value)).encode()).hexdigest()
                if ref_desc.get("gm"):
                    source_gm = source_desc.get("gm", "")
                    ref_plain = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", clean_ru(ref_desc["gm"]))))
                    item_entry["gm"] = reflow_preserving_html(source_gm, ref_plain)
                    key = f"{actor['_id']}/items/{item['_id']}/gm"
                    actor_technical[key] = TECH_RE.findall(source_gm)
                    actor_html[key] = hashlib.sha256("\n".join(html_tags(source_gm)).encode()).hexdigest()
                custom_items_translated += 1
            item_entries.append(item_entry)
        if item_entries:
            entry["items"] = item_entries
        actors[actor["_id"]] = entry

    scenes: dict[str, Any] = {}
    translated_note_labels = 0
    notes_count = sum(len(scene.get("notes", [])) for scene in source.get("scenes", []))
    for scene in source.get("scenes", []):
        notes = {}
        for note in scene.get("notes", []):
            original = note.get("text", "")
            if original:
                notes[original] = translated_name(original)
                translated_note_labels += 1
        regions = {r["_id"]: {"name": translated_name(r.get("name", ""))} for r in scene.get("regions", [])}
        entry = {"name": SCENE_NAMES.get(scene["name"], translated_name(scene["name"]))}
        if notes:
            entry["notes"] = notes
        if regions:
            entry["regions"] = regions
        scenes[scene["_id"]] = entry

    folder_names = {f["name"]: translated_name(f["name"]) for f in source.get("folders", [])}
    translation = {
        "label": "Pathfinder Adventure: Растхендж",
        "entries": {
            source["_id"]: {
                "name": "Pathfinder Adventure: Растхендж",
                "description": "<p>Русский перевод приключения «Растхендж».</p>",
                "folders": folder_names,
                "journals": translated_journals,
                "scenes": scenes,
                "actors": actors,
            }
        },
    }
    index = {
        "source": {"module": "pf2e-rusthenge", "version": "14.1.0", "adventureId": source["_id"]},
        "expected": {
            "journals": len(source["journal"]), "pages": sum(len(j.get("pages", [])) for j in source["journal"]),
            "translatedTextPages": covered_text_pages, "servicePagesOriginal": len(SERVICE_PAGE_IDS),
            "galleryPages": gallery_pages, "scenes": len(source.get("scenes", [])), "notes": notes_count,
            "translatedNoteLabels": translated_note_labels,
            "actors": len(source.get("actors", [])), "tokens": sum(len(s.get("tokens", [])) for s in source.get("scenes", [])),
            "customEmbeddedItems": custom_items, "referenceMatchedCustomItems": custom_items_translated,
        },
        "servicePageIds": sorted(SERVICE_PAGE_IDS),
        "pages": page_index,
        "actorTechnical": actor_technical,
        "actorHtml": actor_html,
    }
    return translation, index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--pdf", required=True, type=Path, help="Локальный PDF для проверки источника; не копируется")
    parser.add_argument("--output", type=Path, default=Path("translations/pf2e-rusthenge.adventures.json"))
    parser.add_argument("--index", type=Path, default=Path("data/source-index.json"))
    args = parser.parse_args()
    if not args.pdf.is_file() or args.pdf.read_bytes()[:4] != b"%PDF":
        raise SystemExit(f"Не найден корректный PDF: {args.pdf}")
    translation, index = make_translation(
        load_adventure(args.source),
        load_adventure(args.reference),
        extract_pdf_pages(args.pdf),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(index["expected"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
