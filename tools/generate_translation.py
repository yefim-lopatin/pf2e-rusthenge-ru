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
from html.parser import HTMLParser
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
INLINE_ROLL_RE = re.compile(r"\[\[/r\s+[^\]]+\]\](?:\{[^{}]*\})?", re.I)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

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
    "02speakingwith00": "В6. Кузница / Низко 1",
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
    "05shoppinginir00": "Покупки в Железной Гавани",
    "05thehornofrus00": "Рог Ржавчины",
    "05rusthengebac00": "Предыстории РастХендж",
    "05demonvloriak00": "Бестиарий: Влориак",
    "05sinsludge00000": "Бестиарий: Первородная Зависть",
    "06handout0100000": "Журнал Рыбы-Меч",
    "06handout0200000": "Последняя Запись Мейтримара",
}

# Страницы старой русской конверсии нередко объединяли несколько разделов,
# которые в официальном модуле V14 стали отдельными JournalEntryPage.
# Индексы относятся к верхнеуровневым HTML-блокам структурированного источника.
REFERENCE_SLICES: dict[str, tuple[str, tuple[int, ...]]] = {
    "02startingrust00": ("Начало Приключения", tuple(range(0, 6))),
    "02optionalstar00": ("Начало Приключения", (6, 7)),
    "02elderordwi0000": ("Начало Приключения", tuple(range(8, 14))),
    "02elsies00000000": ("Б1. У Элси", tuple(range(0, 16))),
    "02elsiesconcer00": ("Б1. У Элси", tuple(range(16, 21))),
    "02theswordfish00": ("Б2. Меч-Рыба", (0, 1)),
    "02sneakingonbo00": ("Б2. Меч-Рыба", tuple(range(2, 6))),
    "02swordfishdis00": ("Б2. Меч-Рыба", tuple(range(6, 9))),
    "02gettinginafi00": ("Б2. Меч-Рыба", (9,)),
    "02speakingtoth00": ("Б2. Меч-Рыба", tuple(range(10, 20))),
    "02finalreward000": ("Б2. Меч-Рыба", (20,)),
    "02stonehome00001": ("Каменный Дом", tuple(range(0, 5))),
    "02rustcreep00000": ("Каменный Дом", tuple(range(5, 8))),
    "02templefeatur00": ("Каменный Дом", tuple(range(8, 11))),
    "02smithy00000000": ("В6. Кузница / Низко 1", tuple(range(0, 7))),
    "02speakingwith00": ("В6. Кузница / Низко 1", tuple(range(7, 13))),
    "02seniorbarrac00": ("В15. Старшая Казарма / Сурово 1", tuple(range(0, 8)) + (11,)),
    "02speakingtova00": ("В15. Старшая Казарма / Сурово 1", (8, 9, 10, 12)),
    "03chapter2000000": ("Начало 2 Главы", (0,)),
    "03startingthis00": ("Начало 2 Главы", tuple(range(1, 5))),
    "03sacrificekee00": ("Жертвенные Хранители / Серьезно 2", tuple(range(0, 9))),
    "03encounteradj00": ("Жертвенные Хранители / Серьезно 2", (9,)),
    "04chapter3000000": ("Храм Ксар-Азмак", (0,)),
    "04thetempleofx00": ("Храм Ксар-Азмак", (2, 3, 4)),
    "04concludingth00": ("Завершение Приключения", (0, 1, 2, 3)),
    "04whatifthepcs00": ("Завершение Приключения", (4,)),
}

SPECIAL_AREA_SLICES: dict[str, tuple[int, ...]] = {
    "02theswordfish00": (0, 1),
    "02smithy00000000": tuple(range(0, 7)),
    "02seniorbarrac00": tuple(range(0, 8)) + (11,),
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


class TopLevelHTMLBlocks(HTMLParser):
    """Разбивает HTML-фрагмент на верхнеуровневые элементы без сторонних библиотек."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._buffer: list[str] = []
        self._depth = 0

    def _append(self, value: str) -> None:
        if self._depth or self._buffer:
            self._buffer.append(value)
        elif value.strip():
            self.blocks.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth == 0:
            self._buffer = []
        self._buffer.append(self.get_starttag_text())
        if tag.lower() not in VOID_TAGS:
            self._depth += 1
        elif self._depth == 0:
            self.blocks.append("".join(self._buffer))
            self._buffer = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth == 0:
            self.blocks.append(self.get_starttag_text())
        else:
            self._buffer.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        self._append(f"</{tag}>")
        if self._depth:
            self._depth -= 1
        if self._depth == 0 and self._buffer:
            self.blocks.append("".join(self._buffer))
            self._buffer = []

    def handle_data(self, data: str) -> None:
        self._append(data)

    def handle_entityref(self, name: str) -> None:
        self._append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._append(f"<!--{data}-->")


def top_level_blocks(value: str) -> list[str]:
    parser = TopLevelHTMLBlocks()
    parser.feed(value)
    parser.close()
    return parser.blocks


def block_plain_text(value: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", value)).split())


def selected_reference_html(page: dict[str, Any], indexes: tuple[int, ...] | None = None) -> str:
    blocks = top_level_blocks(page.get("text", {}).get("content", ""))
    if indexes is None:
        return "".join(blocks)
    missing = [index for index in indexes if index >= len(blocks)]
    if missing:
        raise ValueError(f"В странице {page.get('name')} отсутствуют HTML-блоки {missing}")
    return "".join(blocks[index] for index in indexes)


def clean_reference_html(value: str) -> str:
    """Очищает структурированный русский текст от старых UUID, статблоков и ресурсов."""
    value = clean_ru(value)
    value = re.sub(r"<figure\b[^>]*>.*?</figure>", "", value, flags=re.I | re.S)
    value = TECH_RE.sub("", value)
    value = INLINE_ROLL_RE.sub("", value)
    value = re.sub(r"`[^`]*`", "", value)

    def stat_block(match: re.Match[str]) -> str:
        body = match.group(1)
        plain = block_plain_text(body).lower()
        if plain.startswith(("сокровищ", "опыт", "награ", "повышенная готовность")):
            return f'<section class="action rusthenge-ru-note">{body}</section>'
        return ""

    value = re.sub(r'<section\b[^>]*class="[^"]*БлокСтат[^"]*"[^>]*>(.*?)</section>', stat_block, value, flags=re.I | re.S)
    value = re.sub(r'<section\b[^>]*class="[^"]*ЦЕНТР[^"]*"[^>]*>.*?</section>', "", value, flags=re.I | re.S)
    value = re.sub(r'<section\b[^>]*class="[^"]*insite[^"]*"[^>]*>', '<aside class="sidebar rusthenge-ru-sidebar">', value, flags=re.I)
    # Меняем закрывающий тег только у преобразованных выносок.
    value = re.sub(
        r'<aside class="sidebar rusthenge-ru-sidebar">(.*?)</section>',
        r'<aside class="sidebar rusthenge-ru-sidebar">\1</aside>',
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<blockquote\b[^>]*>", '<div class="read-aloud">', value, flags=re.I)
    value = re.sub(r"</blockquote>", "</div>", value, flags=re.I)
    value = re.sub(r'<h[1-6]\b[^>]*>\s*(?:/\s*)?(?:Существо|Предмет|Болезнь)?\s*\d*\s*</h[1-6]>', "", value, flags=re.I)
    value = re.sub(r"([А-Яа-яЁё]{2,})-\s+([а-яё]{2,})", r"\1\2", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r">\s+<", "><", value)
    return value.strip()


def source_media(value: str) -> str:
    media: list[str] = []
    for block in top_level_blocks(value):
        opening = block.lstrip().lower()
        if opening.startswith("<img") or (
            opening.startswith("<div") and "chapter-image-container" in opening.split(">", 1)[0]
        ):
            media.append(block)
    return "".join(media)


CARD_REPLACEMENTS = {
    "Scene Notes": "Заметки сцены",
    "Audio": "Аудио",
    "Ambiance": "Атмосфера",
    "Macro": "Макрос",
    "Contact": "Контакты",
    "Creature": "Существо",
    "Item": "Предмет",
    "Disease": "Болезнь",
    "Background": "Предыстория",
    "Other": "Прочее",
    "Beyond": "Сверх",
    "SFX": "Звуковой эффект",
    "Distract Crew": "Отвлечь команду",
    "Search Ship": "Обыскать корабль",
    "Osprey Cove": "Бухта Скопы",
    "Settlement": "Поселение",
    "Trivial": "Тривиальная",
    "Low": "Низкая",
    "Moderate": "Умеренная",
    "Severe": "Тяжёлая",
    "Extreme": "Экстремальная",
    "Varies": "Разная",
}


def translate_token_label(
    token: str,
    page_names: dict[str, str],
    journal_names: dict[str, str],
    actor_names: dict[str, str],
) -> str:
    core_match = TECH_CORE_RE.fullmatch(token)
    if not core_match:
        return token
    core = core_match.group(1)
    label_match = re.search(r"\{([^{}]*)\}$", token)
    label = label_match.group(1) if label_match else ""
    if core.startswith("@UUID["):
        target = core[6:-1]
        page_match = re.search(r"JournalEntryPage\.([A-Za-z0-9]+)", target)
        journal_match = re.search(r"JournalEntry\.([A-Za-z0-9]+)", target)
        actor_match = re.search(r"(?:^|\.)Actor\.([A-Za-z0-9]+)", target)
        if page_match and page_match.group(1) in page_names:
            label = page_names[page_match.group(1)]
        elif journal_match and journal_match.group(1) in journal_names:
            label = journal_names[journal_match.group(1)]
        elif actor_match and actor_match.group(1) in actor_names:
            label = actor_names[actor_match.group(1)]
        elif target.startswith("Compendium.pf2e."):
            label = ""  # Babele/pf2e-ru подставят локализованное имя документа.
        elif target.startswith("Macro."):
            label = "Макрос Foundry"
        else:
            label = translated_name(label)
    elif label:
        label = translated_name(label)
    return core + ("{" + label + "}" if label else "")


def translate_card(
    block: str,
    source_name: str,
    translated_page_name: str,
    page_names: dict[str, str],
    journal_names: dict[str, str],
    actor_names: dict[str, str],
) -> str:
    # Оставляем интерактивную шапку карточки; английское описание заменяет русский основной текст.
    block = re.sub(r"<p\b[^>]*>.*?</p>", "", block, flags=re.I | re.S)
    block = re.sub(r'<ul\b[^>]*class="[^"]*traits[^"]*"[^>]*>.*?</ul>', "", block, flags=re.I | re.S)
    original_tokens = TECH_RE.findall(block)
    token_index = 0

    def protect_token(match: re.Match[str]) -> str:
        nonlocal token_index
        placeholder = f"@@RUSTHENGE_TECH_{token_index}@@"
        token_index += 1
        return placeholder

    block = TECH_RE.sub(protect_token, block)
    block = block.replace(source_name, translated_page_name)
    for original, translated in CARD_REPLACEMENTS.items():
        block = re.sub(rf"\b{re.escape(original)}\b", translated, block, flags=re.I)
    keepme_index = 0

    def keepme(match: re.Match[str]) -> str:
        nonlocal keepme_index
        body = match.group(1)
        plain = block_plain_text(body)
        replacement = body
        if "@@RUSTHENGE_TECH_" not in body:
            if plain.lower() == "scene notes":
                replacement = "Заметки сцены"
            elif not any(word.lower() in plain.lower() for word in CARD_REPLACEMENTS.values()):
                replacement = translated_page_name if keepme_index == 0 else body
        keepme_index += 1
        return f'<span class="keepme">{replacement}</span>'

    block = re.sub(r'<span\b[^>]*class="keepme"[^>]*>(.*?)</span>', keepme, block, flags=re.I | re.S)
    for index, token in enumerate(original_tokens):
        translated = translate_token_label(token, page_names, journal_names, actor_names)
        block = block.replace(f"@@RUSTHENGE_TECH_{index}@@", translated, 1)
    return block


def source_functional_cards(
    value: str,
    source_name: str,
    translated_page_name: str,
    page_names: dict[str, str],
    journal_names: dict[str, str],
    actor_names: dict[str, str],
) -> str:
    cards = []
    for block in top_level_blocks(value):
        opening = block.lstrip().lower().split(">", 1)[0]
        if opening.startswith("<section") and ('class="encounter' in opening or 'class="action' in opening):
            cards.append(
                translate_card(
                    block,
                    source_name,
                    translated_page_name,
                    page_names,
                    journal_names,
                    actor_names,
                )
            )
    return "".join(cards)


def translated_controls(
    source_html: str,
    current_html: str,
    page_names: dict[str, str],
    journal_names: dict[str, str],
    actor_names: dict[str, str],
) -> str:
    source_tokens = TECH_RE.findall(source_html)
    current = Counter(technical_cores(current_html))
    missing: list[str] = []
    for token in source_tokens:
        core = technical_cores(token)[0]
        if current[core]:
            current[core] -= 1
        else:
            missing.append(translate_token_label(token, page_names, journal_names, actor_names))
    if not missing:
        return ""
    return (
        '<details class="rusthenge-ru-controls"><summary>Игровые элементы Foundry</summary>'
        f'<div class="rusthenge-ru-control-list">{" ".join(missing)}</div></details>'
    )


def translated_heading(page_id: str, page_name: str) -> str:
    chapter = {
        "02chapter1000000": ("Глава 1:", "Послание в ночи"),
        "03chapter2000000": ("Глава 2:", "Ржавые руины"),
        "04chapter3000000": ("Глава 3:", "Воскрешение ржавчины"),
    }.get(page_id)
    if chapter:
        return (
            '<h1 class="chapter-heading no-toc">'
            f'<span class="chapter-num">{chapter[0]}</span><span>{chapter[1]}</span></h1>'
        )
    return f'<h1 class="rusthenge-ru-page-title no-toc">{html.escape(page_name)}</h1>'


def manual_page(page_id: str, source_html: str) -> str | None:
    media = source_media(source_html)
    if page_id == "01adventures0000":
        return f'''<div class="rusthenge-ru-content">{media}<h1 class="chapter-heading no-toc"><span>Растхендж</span></h1>
<aside class="float-right rusthenge-ru-summary-aside"><h2 class="no-toc">Устранение дискомфорта</h2><p>В «Растхендже» присутствуют элементы, связанные со сверхъестественной болезнью под названием ползучая ржавчина: она ослабляет тело и портит предметы, которые носят персонажи. Однако болезнь не является ключевой частью сюжета. Если вашей группе некомфортна эта тема, ползучую ржавчину можно представить как проклятие, медленно действующий яд или зловещий эффект трансмутации, рождённый в одном из регионов Бездны.</p><h2 class="no-toc">Двусторонний коврик</h2><p>В приключении используется специальный двусторонний коврик с двумя важными локациями. Все карты также представлены в книге, поэтому при желании их можно использовать без отдельного коврика.</p></aside>
<h2 class="no-toc">Глава 1: Послание в ночи</h2><p>Деревня Бухта Скопы десятилетиями вела тихую и мирную жизнь. Всё меняется в ночь, когда буря приносит умирающего гонца с жутким предупреждением. Герои отправляются в Айрон-Харбор и вскоре обнаруживают, что местный храм Горума захвачен зловещим культом.</p>
<h2 class="no-toc">Глава 2: Ржавые руины</h2><p>Разоблачив злодеяния культа в храме Горума, герои исследуют подземный комплекс под древними ржавыми монолитами Растхенджа и узнают главную цель культистов: воскресить мёртвого повелителя демонов.</p>
<h2 class="no-toc">Глава 3: Воскрешение ржавчины</h2><p>Приближаясь к лидеру культа, герои узнают о сложном ритуале воскрешения Ксар-Азмака, повелителя демонов ржавчины и разложения. Им предстоит ослабить магию ритуала и встретиться с культистом на границе Тёмных земель.</p>
<section class="advancement-track"><h1 class="no-toc">Направление развития</h1><p><span class="level">1</span>Персонажи начинают приключение с 1-го уровня.</p><p><span class="level">2</span>Персонажи должны достичь 2-го уровня перед исследованием Растхенджа и первого подземного этажа.</p><p><span class="level">3</span>Перед спуском в храм Ксар-Азмака персонажи должны достичь 3-го уровня. К завершению приключения они должны получить 4-й уровень.</p></section></div>'''
    if page_id == "01rusthenge00000":
        return f'''<div class="rusthenge-ru-content rusthenge-ru-credits">{media}<aside class="float-left"><p><strong>Автор</strong></p><p>Vanessa Hoskins</p><p><strong>Разработка</strong></p><p>James Jacobs</p><p><strong>Ведущий редактор</strong></p><p>Patrick Hurley</p><p><strong>Редакторы</strong></p><p>Felix Dritz, Avi Kool, Patrick Hurley, Lynne M. Meyer, Zac Moran и Simone D. Sallé</p><p><strong>Обложка</strong></p><p>Rodrigo Gonzalez Toledo</p><p><strong>Иллюстрации</strong></p><p>Rael Dionisio, Robert Lazzaretti, Luis Salas Lastra и Firat Solhan</p><p><strong>Арт-дирекция и графический дизайн</strong></p><p>Sonja Morris</p><p><strong>Издатель</strong></p><p>Erik Mona</p></aside><h2 class="no-toc">Растхендж</h2><p>Автор: Vanessa Hoskins</p><p><strong>Глава 1:</strong> @UUID[JournalEntry.pf2sa06402messag]{{Послание в ночи}}</p><p><strong>Глава 2:</strong> @UUID[JournalEntry.pf2sa06403therus]{{Ржавые руины}}</p><p><strong>Глава 3:</strong> @UUID[JournalEntry.pf2sa06404ressur]{{Воскрешение ржавчины}}</p><h2 class="no-toc">@UUID[JournalEntry.pf2sa06405advent]{{Инструментарий приключения}}</h2><p>Автор: Vanessa Hoskins</p><hr><h2 class="no-toc black">Картография VTT</h2><p>Jason Juta и Andrew Gordon</p><h2 class="no-toc black">Конверсия для VTT</h2><p>Модуль подготовлен командой <a href="https://metamorphic-digital.com/">MetaMorphic Digital</a> под руководством Dr. Amy Bliss Marshall.</p></div>'''
    if page_id == "01landing0000000":
        return f'''<div class="rusthenge-ru-content"><section class="encounter"><div class="header"><div class="encounter-image-wrapper"><img style="transform:scale(1.5)" src="modules/pf2e-rusthenge/assets/mini/Elder Johedia-MINI.webp"></div><h2 class="split no-toc"><span class="keepme">Смена стартовой сцены</span><span class="keepme">Макрос</span></h2><span class="link">@UUID[Macro.OgpGrBEI2nchZQUC]{{Выбор стартовой сцены}}</span></div><p><strong>Этот макрос меняет фоновую сцену приключения.</strong></p></section><section class="encounter"><div class="header"><div class="encounter-image-wrapper"><img style="transform:scale(2)" src="modules/pf2e-rusthenge/assets/mini/Azmakian Animated Armor-MINI.webp"></div><h2 class="split no-toc"><span class="keepme">Поддержка модуля</span><span class="keepme">Контакты</span></h2><span class="link"><a href="https://support.metamorphic-digital.com/">Служба поддержки MetaMorphic Digital</a></span></div><p><strong>Для сообщения об ошибке заполните заявку в службе поддержки.</strong></p></section><section class="encounter"><div class="header"><div class="encounter-image-wrapper"><img style="transform:scale(1)" src="modules/pf2e-rusthenge/assets/token/CombinedToken.webp"></div><h2 class="split no-toc"><span class="keepme">Рамка токена</span><span class="keepme">Ресурсы</span></h2><span class="link"><a href="modules/pf2e-rusthenge/assets/token/TokenBorder.webp">Пустая рамка</a> <a href="modules/pf2e-rusthenge/assets/token/TokenBackground.webp">Фон токена</a></span></div><p><strong>Эти ресурсы позволяют создавать собственные токены в стиле модуля.</strong></p></section></div>'''
    if page_id == "05adventuretoo00":
        return f'''<div class="rusthenge-ru-content">{media}<h1 class="chapter-heading no-toc"><span>Инструментарий приключения</span></h1></div>'''
    return None


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
    source_pages = {p["_id"]: p for j in source["journal"] for p in j.get("pages", [])}
    translated_page_names = {
        page_id: PAGE_NAMES.get(page_id) or translated_name(page.get("name", ""))
        for page_id, page in source_pages.items()
    }
    translated_journal_names = {
        journal["_id"]: JOURNAL_NAMES.get(journal["_id"], translated_name(journal.get("name", "")))
        for journal in source["journal"]
    }
    translated_actor_names = {
        actor["_id"]: ACTOR_NAMES.get(actor.get("name", ""), translated_name(actor.get("name", "")))
        for actor in source.get("actors", [])
    }

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
            manual_html = manual_page(pid, source_html)
            ref_page = None
            ref_indexes: tuple[int, ...] | None = None
            if pid in REFERENCE_SLICES:
                reference_name, ref_indexes = REFERENCE_SLICES[pid]
                ref_page = ref_pages.get(reference_name)
            elif code:
                ref_code = AREA_PREFIX[code[0]] + code[1:]
                ref_page = ref_areas.get(ref_code)
                ref_indexes = SPECIAL_AREA_SLICES.get(pid)
            if ref_page is None:
                ref_page = ref_pages.get(NARRATIVE_REFERENCE.get(pid, ""))
            if manual_html is None and ref_page is None:
                raise ValueError(f"Не найден русский текст для страницы {pid} ({page['name']})")

            name = PAGE_NAMES.get(pid) or translated_name(page["name"])
            if name == page["name"]:
                name = clean_ru(ref_page["name"]) if ref_page else name
            if manual_html is not None:
                russian_html = manual_html
                alignment_reference = block_plain_text(manual_html)
            else:
                ref_html = selected_reference_html(ref_page, ref_indexes)
                if pid == "04summoningcha00":
                    ref_html += selected_reference_html(ref_pages["Стабильность Ритуала"])
                ref_html = clean_reference_html(ref_html)
                if pid == "03encounteradj00":
                    ref_html += (
                        '<aside class="sidebar rusthenge-ru-sidebar"><h1 class="no-toc">Очки прерывания</h1>'
                        '<p>Даже получив доступ к наследию своего деда, Мейтремар пока не способен воскресить '
                        'Ксар-Азмака. Однако незавершённый ритуал позволит ему призвать подавляющее демоническое '
                        'подкрепление и станет первым шагом к возвращению повелителя демонов. Чтобы остановить его, '
                        'персонажи должны нарушать работу подземного комплекса и накапливать очки прерывания. Их '
                        'итоговое количество изменит сложность финального столкновения.</p></aside>'
                    )
                media = source_media(source_html)
                cards = source_functional_cards(
                    source_html,
                    page["name"],
                    name,
                    translated_page_names,
                    translated_journal_names,
                    translated_actor_names,
                )
                body = translated_heading(pid, name) + ref_html
                if pid.startswith("06handout"):
                    body = f'<div class="handout-wrapper"><section class="handout">{body}</section></div>'
                russian_html = f'<div class="rusthenge-ru-content">{media}{body}{cards}</div>'
                controls = translated_controls(
                    source_html,
                    russian_html,
                    translated_page_names,
                    translated_journal_names,
                    translated_actor_names,
                )
                if controls:
                    russian_html = russian_html.removesuffix("</div>") + controls + "</div>"
                alignment_reference = ref_html

            try:
                pdf_index, alignment_score = best_pdf_page(alignment_reference, pdf_pages)
            except ValueError:
                # Служебные стартовые/титульные страницы не имеют прямого текстового аналога в PDF.
                pdf_index, alignment_score = 0, 0.0
            area_section_used = bool(code)
            content_pdf_index = pdf_index
            pages[pid] = {"name": name, "text": russian_html}
            page_index[pid] = {
                "journalId": journal["_id"],
                "sourceName": page["name"],
                "translatedName": name,
                "technicalTokens": TECH_RE.findall(source_html),
                "technicalCoreHash": hashlib.sha256("\n".join(technical_cores(source_html)).encode()).hexdigest(),
                "sourceImagePaths": re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', source_html, flags=re.I),
                "sourceLinkPaths": re.findall(r'<a\b[^>]*\bhref="([^"]+)"', source_html, flags=re.I),
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
