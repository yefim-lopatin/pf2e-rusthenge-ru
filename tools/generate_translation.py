#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

from translation_overrides import (
    ACTOR_BLURBS,
    ACTOR_DESCRIPTION_OVERRIDES,
    ACTOR_SHORT_FIELDS,
    CANONICAL_ACTOR_NAMES,
    CANONICAL_VISIBLE_REPLACEMENTS,
    HAZARD_FIELDS,
    LINK_LABELS,
    LINKED_ITEM_NAMES,
    RULE_LABELS,
    UNIDENTIFIED_DESCRIPTIONS,
    UNIDENTIFIED_NAMES,
)

SERVICE_PAGE_IDS = {
    "00credits0000000",
    "01opengamelice00",
    "01audiocredits00",
    "00changelog00000",
}

TECH_RE = re.compile(r"@[A-Za-z][A-Za-z0-9]*\[(?:[^\[\]]|\[[^\[\]]*\])*\](?:\{[^{}]*\})?")
TECH_CORE_RE = re.compile(r"(@[A-Za-z][A-Za-z0-9]*\[(?:[^\[\]]|\[[^\[\]]*\])*\])(?:\{[^{}]*\})?")
TAG_RE = re.compile(r"<[^>]+>")
INLINE_ROLL_RE = re.compile(r"\[\[/[a-z]+\s+(?:[^\[\]]|\[[^\[\]]*\])*\]\](?:\{[^{}]*\})?", re.I)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def inline_roll_cores(value: str) -> list[str]:
    return [re.sub(r"\{[^{}]*\}$", "", roll) for roll in INLINE_ROLL_RE.findall(value)]

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
    "02optionalstar00": "Вариант: начать раньше",
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
    ("Бухты Оспри", "Бухты Скопы"),
    ("Бухте Оспри", "Бухте Скопы"),
    ("Бухту Оспри", "Бухту Скопы"),
    ("Бухтой Оспри", "Бухтой Скопы"),
    ("Железная Гавань", "Айрон-Харбор"),
    ("Путь Родства", "Родственное Побережье"),
    ("Оспрей", "Скопы"),
    ("Cleanse Affliction", "Очищение недуга"),
    ("Violet Venom", "Фиолетовый яд"),
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

SIMPLE_NAMES.update({
    "Magic Sense": "Магическое чутьё",
    "Confiscate Spell": "Конфискация заклинания",
    "Spell Drain": "Вытягивание заклинания",
})

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

# Для приключенческих имён приоритет имеет официальный русский PDF. Системные
# названия правил по-прежнему берутся из pf2e-ru по UUID.
ACTOR_NAMES.update(CANONICAL_ACTOR_NAMES)
ACTOR_NAMES.update(LINK_LABELS)
ACTOR_NAMES.update({
    "Janis' Reward": "Награда Дженис",
    "First Mate Janis": "Первый помощник Дженис",
    "Petitioner (the Larvae)": "Петиционер (личинка)",
    "Haniver Gremlin": "Гремлин-ханивер",
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

    # UUID прежней конверсии невалидны в V14. Сохраняем русскую подпись как
    # часть предложения, а рабочую команду ниже возвращаем из официального
    # Adventure и только с официальным идентификатором.
    def old_token_label(match: re.Match[str]) -> str:
        label = re.search(r"\{([^{}]*)\}$", match.group(0))
        return label.group(1) if label else ""

    value = TECH_RE.sub(old_token_label, value)
    value = INLINE_ROLL_RE.sub(old_token_label, value)
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
    # Кириллические классы принадлежали старому PDF-конвертеру и ломают тему
    # официального V14. Смысловые выноски выше уже получили классы Foundry.
    value = re.sub(r'\sclass="[^"]*[А-Яа-яЁё][^"]*"', "", value)
    value = re.sub(r"<(p|li|h[1-6])\b[^>]*>\s*</\1>", "", value, flags=re.I)
    value = re.sub(r"<ul\b[^>]*>\s*</ul>", "", value, flags=re.I)
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

# Эти карточки содержат самостоятельный игровой текст. Его нельзя удалять как
# дублирующее английское описание: в старом русском Adventure соответствующие
# статблоки были вырезаны при очистке PDF-разметки.
MANUAL_ACTION_CARDS: dict[tuple[str, int], str] = {
    ("02optionalstar00", 0): '''<section class="action">
  <h2 class="split"><span>Бухта Скопы</span><span>Поселение 2</span></h2>
  <ul class="traits">
    <li class="trait alignment">ХД</li>
    <li class="trait size">Деревня</li>
  </ul>
  <p>Изолированная рыбацкая община</p>
  <p><strong>Правительство</strong> Старейшины (община)</p>
  <p><strong>Население</strong> 120 (85% людей, 15% прочих)</p>
  <p><strong>Языки</strong> Общий, Варисийский</p>
  <hr>
  <p><strong>Религии</strong> @UUID[Compendium.pf2e.deities.Item.JgqH3BhuEuA4Zyqs]{Десна}, @UUID[Compendium.pf2e.deities.Item.v67fHklTZ6LoU54q]{Кайден Кайлин}</p>
  <p><strong>Угрозы</strong> вражда с @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02ironharbor0000#iron-harborsettlement-2]{Айрон-Харбором}, вмешательство Нового Тассилона, сезонные штормы</p>
  <p><strong>Дружная община</strong> Хотя жители Бухты Скопы обращаются за советом к старейшинам, они управляют собой как единая община. Жители охотно помогают друг другу, ведь успех одного — это успех всех. Проверки Заработка ограничены заданиями не выше 2-го уровня, но любая попытка Заработать доход в Бухте Скопы получает ситуативный бонус +1 благодаря помощи соседей.</p>
  <hr>
  <p><strong>Старейшина Анлоргог</strong> (НД небинарная ундина-следопыт 2-го уровня) помогает руководить рыбной ловлей в деревне</p>
  <p><strong>Старейшина Бо-Мел</strong> (ХД женщина-дварф, фермер 3-го уровня) помогает руководить сельским хозяйством и строительством</p>
  <p><strong>Старейшина Йохейда</strong> (ХД женщина-полуэльф, оракул 3-го уровня) служит главной целительницей Бухты Скопы</p>
  <p><strong>Старейшина Ордви</strong> (ХД женщина-человек, жрица 2-го уровня) — самая молодая старейшина, ещё осваивающаяся в новой роли</p>
  <p><strong>Старейшина Вандус</strong> (ХН мужчина-человек, рыбак 3-го уровня) — старейший из деревенских старейшин, хранитель записей и историк</p>
</section>''',
    ("02elderordwi0000", 0): '''<section class="action">
  <h2 class="split no-toc"><span>@UUID[Actor.6AiPO2aKOFN6qipW]{Ордви}</span><span>Существо 2</span></h2>
  <p>Женщина-человек, жрица Кайдена Кайлина</p>
</section>''',
    ("02sneakingonbo00", 0): '''<section class="action">
  <h2>Отвлечь экипаж</h2>
  <ul class="traits">
    <li class="trait">Концентрация</li>
    <li class="trait">Исследование</li>
    <li class="trait">Ментальный</li>
  </ul>
  <p class="no-indent">Пытаясь завязать с экипажем «Рыбы-меч» сумбурный разговор с пирса, устроить отвлекающее происшествие, расспросить о причинах их пребывания или просто поболтать, существо в течение 10 минут старается отвлечь охрану на палубе и повысить шансы тех, кто пробирается на борт. Попросите персонажа описать свои действия и определите, какую проверку он должен пройти: @Check[deception|dc:15|trait:concentrate,exploration,mental,action:distract-crew|name:Distract Crew], @Check[diplomacy|dc:17|trait:concentrate,exploration,mental,action:distract-crew|name:Distract Crew], @Check[performance|dc:13|trait:concentrate,exploration,mental,action:distract-crew|name:Distract Crew] или @Check[xin-edasseril-lore|dc:13|trait:concentrate,exploration,mental,action:distract-crew|name:Distract Crew]. Одновременно можно предпринять только одну попытку Отвлечь экипаж, но другие персонажи могут Помочь ей.</p>
  <p><strong>Критический успех</strong> Экипаж отвлекается. Все попытки Обыскать корабль в течение этих 10 минут получают ситуативный бонус +1.</p>
  <p><strong>Успех</strong> Экипаж отвлекается.</p>
  <p><strong>Провал</strong> Экипаж не отвлекается.</p>
  <p><strong>Критический провал</strong> Экипаж настораживается, и все попытки Обыскать корабль в течение этих 10 минут получают ситуативный штраф –1.</p>
</section>''',
    ("02sneakingonbo00", 1): '''<section class="action">
  <h2>Обыскать корабль</h2>
  <ul class="traits">
    <li class="trait">Концентрация</li>
    <li class="trait">Исследование</li>
  </ul>
  <p class="no-indent">Персонаж пробирается на «Рыбу-меч» и в течение 10 минут крадётся по кораблю в поисках улик. Если экипаж не отвлечён, персонаж проходит @Check[stealth|dc:15|trait:concentrate,exploration,action:search-ship|name:Search Ship] или @Check[sailing-lore|dc:13|trait:concentrate,exploration,action:search-ship|name:Search Ship]. Если экипаж отвлечён, СЛ уменьшается на 5. Если экипаж насторожен, СЛ увеличивается на 5.</p>
  <p><strong>Критический успех</strong> Персонаж делает несколько открытий. Трижды бросьте по таблице находок «Рыбы-меч».</p>
  <p><strong>Успех</strong> Персонаж делает открытие! Один раз бросьте по таблице находок «Рыбы-меч».</p>
  <p><strong>Провал</strong> Персонаж ничего не находит, но экипаж его не замечает.</p>
  <p><strong>Критический провал</strong> Персонаж ничего не находит, и его замечает матрос! Он может начать переговоры (перейдите к разделу @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02speakingtoth00]{«Разговор с экипажем»}), атаковать (перейдите к разделу @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02gettinginafi00]{«Ввязаться в драку»}) или попытаться сбежать, пройдя ещё одну проверку Скрытности с той же СЛ. При успехе он избегает захвата, но экипаж «Рыбы-меч» остаётся настороженным и больше не может быть отвлечён. При провале персонажа загоняют в угол, и ему придётся сражаться, говорить или сдаться.</p>
</section>''',
    ("02ironharbor0000", 0): '''<section class="action">
  <h2 class="split"><span>Айрон-Харбор</span><span>Поселение 2</span></h2>
  <ul class="traits">
    <li class="trait alignment">ХН</li>
    <li class="trait size">Деревня</li>
  </ul>
  <p>Отдалённое поселение горумитов</p>
  <p><strong>Правительство</strong> Верховный жрец (духовенство)</p>
  <p><strong>Население</strong> 80 (90% людей, 10% прочих)</p>
  <p><strong>Языки</strong> Общий, Варисийский</p>
  <hr>
  <p><strong>Религии</strong> @UUID[Compendium.pf2e.deities.Item.88vRw2ZVPax4hhga]{Горум}</p>
  <p><strong>Угрозы</strong> культ Ксар-Азмака, сезонные штормы</p>
  <p><strong>Деревня горумитов</strong> Как и следовало ожидать от деревни, возглавляемой поклонниками Горума, оружие и доспехи здесь достать проще. Для покупки оружия, доспехов, боеприпасов и сопутствующих предметов считайте Айрон-Харбор поселением 3-го уровня.</p>
  <hr>
  <p><strong>Кнурр Рагнульф</strong> (ХН мужчина-дварф, бывший жрец Горума 2-го уровня) — лидер Айрон-Харбора, недавно обращённый культом Ксар-Азмака</p>
  <p><strong>Элси</strong> (ХН женщина-полурослик, алхимик 3-го уровня) — местная алхимик, пекарь и возможная союзница</p>
</section>''',
    ("02rustcreep00000", 0): '''<section class="action">
  <h2 class="no-toc split"><span>Ползучая ржавчина</span><span>Болезнь 2</span></h2>
  <ul class="traits">
    <li class="trait rare">Редкий</li>
    <li class="trait">Болезнь</li>
    <li class="trait">Сакральный</li>
    <li class="trait">Трансмутация</li>
  </ul>
  <p class="no-indent">У заражённых ползучей ржавчиной на теле появляются болезненные ржаво-коричневые синяки, а всё тело болит, как после долгой тренировки. По мере развития болезни тело, одежда и переносимые предметы всё сильнее разрушаются, пока не наступает мучительная смерть. Персонаж, успешно сопротивлявшийся заражению или излечившийся от ползучей ржавчины, получает временный иммунитет к новым заражениям на 24 часа.</p>
  <p>
    <strong>Спасбросок</strong> @Check[fortitude|dc:15|trait:rare,disease,divine,transmutation];<br>
    <strong>Стадия 1</strong> штраф состояния –1 к проверкам Атлетики (1 день);<br>
    <strong>Стадия 2</strong> как стадия 1 (1 день);<br>
    <strong>Стадия 3</strong> @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{Ослаблен 1} (1 день);<br>
    <strong>Стадия 4</strong> @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{Ослаблен 1} и @UUID[Compendium.pf2e.conditionitems.Item.e1XGnhKNSQIm5IXg]{Одурманен 1}; кроме того, все переносимые доспехи, одежда и предметы, чей уровень не выше уровня болезни, получают состояние @UUID[Compendium.pf2e.conditionitems.Item.6dNUvdb1dhToNDj3]{Сломан} из-за распространяющегося разрушения (1 день; предметы остаются сломанными);<br>
    <strong>Стадия 5</strong> @UUID[Compendium.pf2e.conditionitems.Item.fBnFDH2MTzgFijKf]{Без сознания} (1 день);<br>
    <strong>Стадия 6</strong> @UUID[Compendium.pf2e.conditionitems.Item.fBnFDH2MTzgFijKf]{Без сознания} (1 день);<br>
    <strong>Стадия 7</strong> смерть
  </p>
</section>''',
    ("02securestorag00", 0): '''<section class="action">
  <h2 class="split no-toc"><span>@UUID[Actor.Q3ciH3AHZlb1Dc3E]{Аколиты Горума (3)}</span><span>Существо 1</span></h2>
  <p>Вариант аколита Нэфиса</p>
</section>''',
    ("02stables0000000", 0): '''<section class="action">
  <h2 class="split no-toc"><span>@UUID[Actor.lCNsglj9xoQfBl3p]{Ида}</span><span>Существо 1</span></h2>
  <p>Ослабленный баран «Розовый шип»</p>
</section>''',
    ("04bedroompriso00", 0): '''<section class="action">
  <h2 class="split no-toc"><span>@UUID[Actor.zb2LebobKQWXeVQ1]{Ордви}</span><span>Существо 2</span></h2>
  <p>Женщина-человек, жрица Кайдена Кайлина</p>
</section>''',
}

EXISTING_PAGE_TEXT_REPAIRS = {
    "02sneakingonbo00": (
        (
            'исследования "Обыск Корабля"',
            'исследования @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02sneakingonbo00#search-ship]{«Обыскать корабль»}',
        ),
        (
            'активность "Отвлечь Экипаж"',
            'активность @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02sneakingonbo00#distract-crew]{«Отвлечь экипаж»}',
        ),
    ),
}

FOLDER_NAMES = {
    "Rusthenge": "Растхендж",
    "Original Maps": "Оригинальные карты",
    "Chapter 1: Message in the Night": "Глава 1: Послание в ночи",
    "Bonus Flip Mats": "Дополнительные двусторонние карты",
    "Chapter 2: The Rusted Ruin": "Глава 2: Ржавые руины",
    "Chapter 3: Resurrection of Rust": "Глава 3: Воскрешение ржавчины",
    "Kindred Crossing": "Родственное Побережье",
    "The Swordfish": "«Рыба-меч»",
    "Stonehome": "Стоунхоум",
    "Temple of Xar-Azmak": "Храм Ксар-Азмака",
    "Despoiler’s Deep": "Глубины Опустошителя",
    "Treasure": "Сокровища",
    "Summon Fiend": "Призыв демона",
}

MACRO_NAMES = {
    "Esipil Transformation": "Превращение Эсипила",
    "Bring Down Wall of Force": "Разрушить силовую стену",
    "Weakened": "Ослаблен",
    "Stable": "Стабилен",
    "Drop Rusted Cage": "Сбросить ржавую клетку",
    "Reveal Spiky Pit": "Показать шипованную яму",
    "Toggle Rusthenge Chanting": "Переключить песнопения Растхенджа",
    "Landing Scene Picker": "Выбор стартовой сцены",
    "Summon Fiend": "Призвать демона",
    "Reset": "Сброс",
    "Stop Chanting": "Остановить песнопения",
    "Unstable": "Нестабилен",
    "Disrupted": "Нарушен",
}

PLAYLIST_NAMES = {"Ambience": "Атмосфера", "Loop": "Зацикленные звуки", "SFX": "Звуковые эффекты"}
SOUND_NAMES = {
    "Basement": "Подвал", "Coastal Waves": "Прибрежные волны", "Docks": "Доки", "Ship": "Корабль",
    "Small Village Indoors": "Малая деревня — внутри", "Small Village Outdoors": "Малая деревня — снаружи",
    "Strong Winds": "Сильный ветер", "Underground Caverns": "Подземные пещеры",
    "Underground Facility": "Подземный комплекс", "Windy Coast": "Ветреное побережье", "Temple": "Храм",
    "Campfire": "Костёр", "Chanting": "Песнопения", "Dripping": "Капли",
    "Electrical Machinery": "Электрические механизмы", "Light Wall": "Световая стена",
    "Mechanical Clockwork 1": "Заводной механизм 1", "Mechanical Clockwork 2": "Заводной механизм 2",
    "Mechanical Gear 1": "Механическая передача 1", "Mechanical Gear 2": "Механическая передача 2",
    "Mechanical Gear 3": "Механическая передача 3", "Mechanical Gear 4": "Механическая передача 4",
    "Mechanical Gear 5": "Механическая передача 5", "Metalwork Forge": "Металлообрабатывающая кузница",
    "Ritual Circle Energy Large": "Энергия большого ритуального круга",
    "Ritual Circle Energy Small": "Энергия малого ритуального круга",
    "Underground Lake Shore": "Берег подземного озера", "Underground Ravine": "Подземное ущелье",
    "Magic Surge": "Всплеск магии", "Mechanical Spike Trap": "Механическая ловушка с шипами",
    "Metal Cage Drop": "Падение металлической клетки", "Pit Trap": "Ловушка-яма",
    "Rushing Water": "Бурный поток", "Summoned Fiend": "Призванный демон",
}

MANUAL_ITEM_DESCRIPTIONS = {
    "Navigational Logs": {"description": "Навигационные журналы и записи показывают, что «Рыба-меч» — наёмное судно, которое обычно нанимает тассилонская знать, а не торговый корабль."},
    "Unopened Pony Keg of Akvavit": {"description": "Водка, настоянная на травах."},
    "Fine Captain's Hat": {
        "description": "Добротная треуголка.",
        "gm": "Янис позволяет героям оставить перьевой жетон, если они вернут эту шляпу как доказательство судьбы капитана.",
    },
    "Chart a Course": {"description": "Потратив 10 минут на работу и успешно пройдя @Check[type:sailing-lore|dc:22]{проверку Знаний о мореплавании}, штурман прокладывает оптимальный курс.\n\nСерьёзность погодных условий, кроме температуры, снижается на одну ступень на 24 часа (на две ступени при критическом успехе). Средний урон становится малым, ветер, создающий особо трудную местность, создаёт только трудную местность, и так далее."},
    "Navigator's Edge": {"description": "Находясь на корабле, штурман наносит оружием дополнительно [[/r {1d6}]]{1d6 урона}."},
    "Heft Crate": {"description": "**Требования** Матрос находится рядом с ящиком.\n\n**Эффект** Матрос поднимает ящик и бросает его на расстояние до 15 футов. При падении ящик разбивается в @Template[type:burst|distance:5]. Каждое существо в области получает @Damage[2d6[bludgeoning]] дробящего урона (@Check[type:reflex|dc:13|basic:true]{простой спасбросок Рефлекса}); область становится трудной местностью, пока её не расчистят."},
    "Swig": {"description": "Матрос Взаимодействует, чтобы достать бутылку @UUID[Compendium.pf2e.equipment-srd.Item.UMAXLDpI6YLSfYX1]{алкоголя} либо подобрать стоящую рядом ничейную бутылку алкоголя и выпить её целиком.\n\nНа 1 минуту матрос получает предметный бонус +2 к броскам урона в ближнем бою и спасброскам против страха, но становится @UUID[Compendium.pf2e.conditionitems.Item.i3OJZU2nk64Df3xm]{неуклюжим 1}.\n\n@UUID[Compendium.pf2e.bestiary-effects.Item.HArljmKc2IR7rtfc]{Эффект: глоток}"},
    "Swordfish’s Log": {"description": "Журнал «Рыбы-меч», написанный на тассилонском.", "gm": "@UUID[JournalEntry.pf2sa06406handou.JournalEntryPage.06handout0100000]{Раздаточный материал №1}"},
    "Meitremar's Journal": {"description": "Журнал Мейтремара, написанный на тассилонском, открыт на последней записи без даты. Этот древний журнал некогда принадлежал его деду; прежние записи рассказывают об истории мастерской небесного металла, Влорийских шпилей и плане Тейлтемара воскресить Ксар-Азмака. Упоминается и пребывание Тейлтемара в Дисе во время неудачного нападения Ксар-Азмака: бежав обратно к Влорийским шпилям, он сумел унести один из отломленных рогов повелителя демонов. В середине журнала записаны два ритуала: @UUID[Compendium.pf2e.spells-srd.Item.c3b6LdLlQDPngNIb]{Создание нежити} и @UUID[Compendium.pf2e.spells-srd.Item.5pwK2FZX6QwgtfqX]{Обольщение}.\n\nМейтремар продолжил записи после того, как через год после возвращения Ксин-Эдассерила в современную эпоху нашёл журнал в доме деда. Его увлекла мысль, что Рог Ржавчины скрыт глубоко под Растхенджем, и он задумал отправиться туда с последователями. Записи после прибытия в Айрон-Харбор кратки. В одной он ликует, что нашёл Рог Ржавчины в «великом храме», и упоминает тайную дверь за огромной статуей Ксар-Азмака. Последняя, более длинная запись воспроизведена в @UUID[JournalEntry.pf2sa06406handou.JournalEntryPage.06handout0200000]{раздаточном материале №2}."},
    "Key to E3": {"description": "Ключ от спальни-тюрьмы."},
    "Tiny Brass Key set with Small Gemstones": {"gm": "По вашему усмотрению этот ключ может сыграть важную роль в будущем приключении. В частности, если группа продолжит приключения в «Семи погибелях Сэндпойнта», он может оказаться ключом к таинственной заводной певчей птице, которую герои будут постепенно восстанавливать."},
    "Magic Sense": {"description": "Первородная зависть обнаруживает магические ауры, предметы и заклинателей в пределах 30 футов."},
    "Confiscate Spell": {"description": "Триггер: Существо в пределах 30 футов, которое чувствует Первородная Зависть, Сотворяет заклинание. Эффект: Поверхность Первородной Зависти переливается калейдоскопом цветов, озаряющим спровоцировавшее существо. Первородная Зависть пытается противодействовать заклинанию с модификатором +12. При успехе заклинанию удаётся противодействовать, а Первородная Зависть получает 2d6 временных ОЗ."},
    "Spell Drain": {"description": "Первородная Зависть пытается вытянуть магию из заклинателя, которого она Схватила или Сдерживает. Заклинатель должен совершить спасбросок Воли КС 20. Критический успех: Существо не подвергается эффекту и получает временный иммунитет к Вытягиванию заклинания на 24 часа. Успех: Существо получает 1d6 ментального урона. Провал: Существо получает 2d6 ментального урона и становится Одурманено 1 на 1 час. Критический провал: Как провал, но одно из несотворённых заклинаний или неиспользованных слотов заклинаний существа теряется, как если бы существо его сотворило. Теряется одно из заклинаний наивысшего ранга, которое существо может сотворить; если подготовлено несколько таких заклинаний, выберите случайное. Если вытянуты чары, заклинатель теряет доступ к ним на 10 минут. Первородная Зависть становится Ускорена на 1 раунд и может потратить дополнительное действие только на Перемещение или Удар."},
}

MANUAL_ACTOR_NOTES = {
    "Starving Werebat": {"description": "Вернетопыри образуют организованные колонии охотников-приспособленцев. Они охотно обращают других существ, пополняя колонию, а посвящение сопровождают сложными обрядами и кровавыми испытаниями. Проклятие вернетопыря пробуждает сильное желание охотиться на слабых и одиноких. Истинные вернетопыри часто необычно высоки и худы, с угловатыми чертами. В бою они предпочитают безоружные атаки, поскольку не могут летать с оружием в крыльях.\n\nВерсущества — гуманоиды, которые под светом полной луны превращаются в животных и гибридов. Их судьба связана с древним природным проклятием, передающимся через укусы. Параметры представлены для гибридного облика."},
    "Janis": {"description": "Штурман определяет маршрут по небесным телам и морским путям. Для небоевых задач, связанных с навигацией или мореплаванием, штурман представляет испытание 4-го уровня.\n\nИскателям приключений может понадобиться переход на быстром судне, либо им придётся столкнуться с морскими разбойниками и опасностями прибрежных поселений."},
    "Deck Hand": {"description": "Матросы грузят и разгружают суда. Их считают неуправляемыми, но многие сосредоточенно и упорно трудятся до конца работы, а уже затем шумно празднуют завершение дня.\n\nКаждый день рабочие выполняют изнурительный физический труд."},
    "Elder Vandous": {"descriptionGM": "Старейший из деревенских старейшин, хранитель записей и историк.\n@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}"},
    "Elder Anlorgog": {"descriptionGM": "Помогает руководить рыболовством деревни.\n@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}"},
    "Elder Johedia": {"descriptionGM": "Главная целительница Бухты Скопы.\n@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}"},
    "Elder Bo-Mel": {"descriptionGM": "Помогает руководить земледелием и строительством деревни.\n@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}"},
}

# Для отсутствовавших в старой конверсии полей задаём готовый HTML с той же
# последовательностью тегов, что в официальном документе. Это сохраняет
# команды в середине предложений и не создаёт пробелов на их прежнем месте.
MANUAL_ITEM_HTML = {
    "Navigational Logs": {"description": "<p>Навигационные журналы и записи показывают, что «Рыба-меч» — наёмное судно, которое обычно нанимает тассилонская знать, а не торговый корабль.</p>"},
    "Unopened Pony Keg of Akvavit": {"description": "<p>Водка, настоянная на травах.</p>"},
    "Fine Captain's Hat": {
        "description": "<p>Добротная треуголка.</p>",
        "gm": "<p>Янис позволяет героям оставить перьевой жетон, если они вернут эту шляпу как доказательство судьбы капитана.</p>",
    },
    "Chart a Course": {"description": "<p>Потратив 10 минут на работу и успешно пройдя @Check[type:sailing-lore|dc:22]{проверку Знаний о мореплавании}, штурман прокладывает оптимальный курс.</p>\n<p>Серьёзность погодных условий, кроме температуры, снижается на одну ступень на 24 часа (на две ступени при критическом успехе). Средний урон становится малым, ветер, создающий особо трудную местность, создаёт только трудную местность, и так далее.</p>"},
    "Navigator's Edge": {"description": "<p>Находясь на корабле, штурман наносит оружием дополнительно [[/r {1d6}]]{1d6 урона}.</p>"},
    "Heft Crate": {"description": "<p><strong>Требования</strong> Матрос находится рядом с ящиком.</p>\n<hr />\n<p><strong>Эффект</strong> Матрос поднимает ящик и бросает его на расстояние до 15 футов. При падении ящик разбивается в @Template[type:burst|distance:5]. Каждое существо в области получает @Damage[2d6[bludgeoning]] дробящего урона (@Check[type:reflex|dc:13|basic:true]{простой спасбросок Рефлекса}); область становится трудной местностью, пока её не расчистят.</p>"},
    "Swig": {"description": "<p>Матрос Взаимодействует, чтобы достать бутылку @UUID[Compendium.pf2e.equipment-srd.Item.UMAXLDpI6YLSfYX1]{алкоголя} либо подобрать стоящую рядом ничейную бутылку @UUID[Compendium.pf2e.equipment-srd.Item.UMAXLDpI6YLSfYX1]{алкоголя} и выпить её целиком.</p>\n<p>На 1 минуту матрос получает предметный бонус +2 к броскам урона в ближнем бою и спасброскам против страха, но становится @UUID[Compendium.pf2e.conditionitems.Item.i3OJZU2nk64Df3xm]{неуклюжим 1}.</p>\n<p>@UUID[Compendium.pf2e.bestiary-effects.Item.HArljmKc2IR7rtfc]{Эффект: глоток}</p>"},
    "Swordfish’s Log": {
        "description": "<p>Журнал «Рыбы-меч», написанный на тассилонском.</p>",
        "gm": "<p>@UUID[JournalEntry.pf2sa06406handou.JournalEntryPage.06handout0100000]{Раздаточный материал №1}</p>",
    },
    "Meitremar's Journal": {"description": "<p>Журнал Мейтремара, написанный на тассилонском, открыт на последней записи без даты. Этот древний журнал некогда принадлежал его деду; прежние записи рассказывают об истории мастерской небесного металла, Влорийских шпилей и плане Тейлтемара воскресить Ксар-Азмака. Упоминается и пребывание Тейлтемара в Дисе во время неудачного нападения Ксар-Азмака: бежав обратно к Влорийским шпилям, он сумел унести один из отломленных рогов повелителя демонов. В середине журнала записаны два ритуала: @UUID[Compendium.pf2e.spells-srd.Item.c3b6LdLlQDPngNIb]{Создание нежити} и @UUID[Compendium.pf2e.spells-srd.Item.5pwK2FZX6QwgtfqX]{Обольщение}.</p>\n<p>Мейтремар продолжил записи после того, как через год после возвращения Ксин-Эдассерила в современную эпоху нашёл журнал в доме деда. Его увлекла мысль, что Рог Ржавчины скрыт глубоко под Растхенджем, и он задумал отправиться туда с последователями. Записи после прибытия в Айрон-Харбор кратки. В одной он ликует, что нашёл Рог Ржавчины в «великом храме», и упоминает тайную дверь за огромной статуей Ксар-Азмака. Последняя, более длинная запись воспроизведена в @UUID[JournalEntry.pf2sa06406handou.JournalEntryPage.06handout0200000]{раздаточном материале №2}.</p>"},
    "Key to E3": {"description": "<p>Ключ от спальни-тюрьмы.</p>"},
    "Tiny Brass Key set with Small Gemstones": {"gm": "<p>По вашему усмотрению этот ключ может сыграть важную роль в будущем приключении. В частности, если группа продолжит приключения в «Семи погибелях Сэндпойнта», он может оказаться ключом к таинственной заводной певчей птице, которую герои будут постепенно восстанавливать.</p>"},
    "Magic Sense": {"description": "<p>Первородная зависть обнаруживает магические ауры, предметы и заклинателей в пределах 30 футов.</p>"},
    "Confiscate Spell": {"description": "<p><strong>Триггер</strong> Существо в пределах 30 футов, которое чувствует Первородная Зависть, Сотворяет заклинание</p>\n<hr />\n<p><strong>Эффект</strong> Поверхность Первородной Зависти переливается калейдоскопом цветов, озаряющим спровоцировавшее существо. Первородная Зависть пытается противодействовать заклинанию с модификатором [[/r 1d20+12 #Counteract]]{+12}. При успехе заклинанию удаётся противодействовать, а Первородная Зависть получает [[/br 2d6 #Temp HP]] временных ОЗ.</p>"},
    "Spell Drain": {"description": "<p>Первородная Зависть пытается вытянуть магию из заклинателя, которого она @UUID[Compendium.pf2e.conditionitems.Item.kWc1fhmv9LBiTuei]{Схватила} или @UUID[Compendium.pf2e.conditionitems.Item.VcDeM8A5oI6VqhbM]{Сдерживает}. Заклинатель должен совершить @Check[type:will|dc:20] спасбросок.</p>\n<hr />\n<p><strong>Критический успех</strong> Существо не подвергается эффекту и получает временный иммунитет к Вытягиванию заклинания на 24 часа.</p>\n<p><strong>Успех</strong> Существо получает @Damage[1d6[mental]] ментального урона.</p>\n<p><strong>Провал</strong> Существо получает @Damage[2d6[mental]] ментального урона и становится @UUID[Compendium.pf2e.conditionitems.Item.e1XGnhKNSQIm5IXg]{Одурманено 1} на 1 час.</p>\n<p><strong>Критический провал</strong> Как провал, но одно из несотворённых заклинаний или неиспользованных слотов заклинаний существа теряется, как если бы существо его сотворило. Теряется одно из заклинаний наивысшего ранга, которое существо может сотворить; если подготовлено несколько таких заклинаний, выберите случайное. Если вытянуты чары, заклинатель теряет доступ к ним на 10 минут. Первородная Зависть становится @UUID[Compendium.pf2e.conditionitems.Item.nlCjDvLMf2EkV2dl]{Ускорена} на 1 раунд и может потратить дополнительное действие только на Перемещение или Удар.</p>"},
    "Rusting Death": {"description": "<p>Когда Тейлтемар уничтожен, некромантическая энергия, удерживающая его кости, высвобождается и заставляет их взорваться. Ржавая кольчуга разлетается вместе с ними, разбрасывая во все стороны зазубренные металлические осколки. Существа рядом получают @Damage[2d6[piercing]] колющего урона (@Check[type:reflex|dc:21|basic:true]{простой спасбросок Рефлекса}) и подвергаются воздействию ползучей ржавчины. Когда останки оседают на пол, силовая стена, преграждающая путь в область <strong>F14</strong>, мерцает и исчезает.</p>"},
    "Destructive Croak": {"description": "<p>Болотный мудрец издаёт могучее кваканье, которое наносит @Damage[4d6[sonic]] урона звуком всем не-боггардам в @Template[type:emanation|distance:15] (@Check[type:fortitude|dc:19|basic:true]{простой спасбросок Стойкости}).</p>\n<p>Любое существо в состоянии @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испуга} получает дополнительный урон звуком, равный удвоенному значению этого состояния.</p>\n<p>Боггард не может снова использовать «Разрушительное кваканье» в течение [[/br 1d4 #Recharge Destructive Croak]]{1d4 раундов}.</p>"},
    "Hibernation": {"description": "<p>Проведя без пищи 3 дня или больше, аката может выделить смолу, заключающую её в кокон из ноквала. Кокон имеет Твёрдость 9, 40 ОЗ и Предел Поломки 18, а также сопротивление 5 урону от магических источников. Пока кокон цел, акате нельзя навредить и ей не требуется есть или пить.</p>\n<p>Внутри кокона аката получает @UUID[Compendium.pf2e.bestiary-ability-glossary-srd.Item.sebk9XseMCRkDqRg]{чувство жизни} на 30 футов.</p>\n<p>Аката остаётся в спячке, пока не подвергнется воздействию чрезвычайно высокой температуры или не почувствует живое существо; после этого она может вырваться из кокона за [[/br 1d4 #minutes]]{1d4 минуты}.</p>"},
    "Void Death": {"description": "<p>Аката внедряет паразитических личинок в укушенное существо, но подходящими носителями служат только гуманоиды Среднего или Маленького размера; все остальные существа невосприимчивы к этой болезни.</p>\n<p><strong>Спасбросок</strong> @Check[type:fortitude|dc:17]{Стойкость}</p>\n<p><strong>Стадия 1</strong> носитель без негативного эффекта (1 день)</p>\n<p><strong>Стадия 2</strong> @UUID[Compendium.pf2e.conditionitems.Item.4D2KBtexWXa6oUMR]{истощён 1} (1 день)</p>\n<p><strong>Стадия 3</strong> как стадия 2 (1 день)</p>\n<p><strong>Стадия 4</strong> истощён 2 и @UUID[Compendium.pf2e.conditionitems.Item.HL2l2VRSaQHu9lUw]{утомлён} (1 день)</p>\n<p><strong>Стадия 5</strong> как стадия 4 (1 день)</p>\n<p><strong>Стадия 6</strong> смерть; труп восстаёт как пустотный зомби через [[/br 2d4 #hours]]{2d4 часа}</p>"},
    "Spew Rusted Shards": {"description": "<p>Влориак извергает @Template[type:cone|distance:15]{15-футовый конус} кислоты и ржавого металла. Существа в области получают 3d6 урона кислотой и @Damage[3d6[piercing]] колющего урона (@Check[type:reflex|dc:22|basic:true]{простой спасбросок Рефлекса}). Существо, получившее колющий урон, подвергается воздействию столбняка. Влориак не может снова извергать ржавые осколки в течение [[/br 1d4 #rounds]]{1d4 раундов}.</p>"},
    "Bay": {"description": "<p>Гончая йета издаёт потусторонний вой, слышимый на расстоянии до 300 футов. Любое существо, не являющееся бесом, которое слышит вой, должно успешно пройти @Check[type:will|dc:20]{спасбросок Воли}, иначе становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испуганным 1}. При критическом провале существо в пределах 60 футов от гончей вместо этого становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испуганным 3} и @UUID[Compendium.pf2e.conditionitems.Item.sDPxOjQ9kx2RZE8D]{бегущим} на [[/br 1d4 #rounds]]{1d4 раунда} (или пока не избавится от состояния испуга).</p>\n<p>Независимо от результата спасброска существо после этого получает временную невосприимчивость к Вою на 24 часа.</p>"},
    "Sinister Bite": {"description": "<p>Доброе существо, укушенное гончей йета, должно пройти @Check[type:will|dc:20]{спасбросок Воли}. При критическом успехе существо получает временную невосприимчивость к зловещему укусу на 1 минуту. При провале существо становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испуганным 1}; если оно уже испугано, значение этого состояния увеличивается на 1.</p>"},
}

MANUAL_ITEM_HTML_BY_ID = {
    "oHYtarmUC2qQjUtU": {"gm": "<p>Ключ от сундука в области <strong>E2</strong>.</p>"},
    "0tDhCne8RVvfJHxv": {"gm": "<p>Ключ от защищённого хранилища.</p>"},
}

MANUAL_ACTOR_HTML = {
    "Starving Werebat": {"description": "<p>Вернетопыри образуют организованные колонии охотников-приспособленцев. Они охотно обращают других существ, пополняя колонию, а посвящение сопровождают сложными обрядами и кровавыми испытаниями. Проклятие вернетопыря пробуждает сильное желание охотиться на слабых и одиноких. Истинные вернетопыри часто необычно высоки и худы, с угловатыми чертами. В бою они предпочитают безоружные атаки, поскольку не могут летать с оружием в крыльях.</p>\n<hr>\n<p>Версущества — гуманоиды, которые под светом полной луны превращаются в животных и гибридов. Их судьба связана с древним природным проклятием, передающимся через укусы. Параметры представлены для гибридного облика.</p>"},
    "Janis": {"description": "<p>Штурман определяет маршрут по небесным телам и морским путям. Для небоевых задач, связанных с навигацией или мореплаванием, штурман представляет испытание 4-го уровня.</p>\n<hr>\n<p>Искателям приключений может понадобиться переход на быстром судне, либо им придётся столкнуться с морскими разбойниками и опасностями прибрежных поселений.</p>"},
    "Deck Hand": {"description": "<p>Матросы грузят и разгружают суда. Их считают неуправляемыми, но многие сосредоточенно и упорно трудятся до конца работы, а уже затем шумно празднуют завершение дня.</p>\n<hr>\n<p>Каждый день рабочие выполняют изнурительный физический труд.</p>"},
    "Elder Vandous": {"descriptionGM": "<p>Старейший из деревенских старейшин, хранитель записей и историк.<br>@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}</p>"},
    "Elder Anlorgog": {"descriptionGM": "<p>Помогает руководить рыболовством деревни.<br>@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}</p>"},
    "Elder Johedia": {"descriptionGM": "<p>Главная целительница Бухты Скопы.<br>@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}</p>"},
    "Elder Bo-Mel": {"descriptionGM": "<p>Помогает руководить земледелием и строительством деревни.<br>@UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы}</p>"},
}

PF2E_RU_ACTOR_DONORS = {
    "Envyspawn": ("pf2e.pathfinder-monster-core.json", "Envyspawn"),
    "Azomi": ("pf2e.pathfinder-monster-core.json", "Envyspawn"),
    "Severed Head": ("pf2e.pathfinder-monster-core-2.json", "Severed Head"),
    "Theiltemar": ("pf2e.pathfinder-monster-core.json", "Skeleton Guard"),
    "Vlorian Cythnigot": ("pf2e.pathfinder-monster-core.json", "Cythnigot"),
    "Glutu": ("pf2e.pathfinder-monster-core.json", "Boggard Swampseer"),
    "Rust Zombie": ("pf2e.pathfinder-monster-core.json", "Plague Zombie"),
    "Reefclaw": ("pf2e.pathfinder-monster-core.json", "Reefclaw"),
    "Zaiox": ("pf2e.pathfinder-monster-core.json", "Dero Magister"),
    "Ida": ("pf2e.pathfinder-bestiary-3.json", "Rosethorn Ram"),
}

PF2E_LABEL_OVERRIDES = {
    "30 feet": "30 футов",
    "25 feet": "25 футов",
    "5-foot radius": "радиус 5 футов",
    "Magic Wand": "Магическая палочка",
    "Effect: Fanatical Frenzy": "Эффект: фанатичное безумие",
    "Effect: Mutilating Bite": "Эффект: увечащий укус",
}


def load_pf2e_ru_actor_lore(root: Path) -> dict[str, str]:
    lore: dict[str, str] = {}
    for actor_name, (filename, entry_name) in PF2E_RU_ACTOR_DONORS.items():
        path = root / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        description = data.get("entries", {}).get(entry_name, {}).get("description", "")
        if not description:
            raise ValueError(f"В pf2e-ru не найден перевод {entry_name} ({path})")
        lore[actor_name] = description
    return lore


def load_pf2e_ru_names(root: Path) -> dict[str, str]:
    """Собирает русские имена документов по английским ключам Babele."""
    names: dict[str, str] = {}
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for original, entry in data.get("entries", {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                names.setdefault(original, entry["name"].replace("(*)", "").strip())
    return names


def localize_pf2e_markup_labels(value: str, names: dict[str, str]) -> str:
    """Переводит видимую подпись Foundry, не изменяя техническое ядро."""
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        core_match = TECH_CORE_RE.fullmatch(token)
        label_match = re.search(r"\{([^{}]*)\}$", token)
        if not core_match or not label_match:
            return token
        core = core_match.group(1)
        label = label_match.group(1)
        translated = PF2E_LABEL_OVERRIDES.get(label)
        if translated is None and core.startswith("@UUID[Compendium.pf2e."):
            translated = names.get(label)
        if translated is None:
            numbered = re.fullmatch(r"(.+?)\s+(\d+)", label)
            if numbered and numbered.group(1) in names:
                translated = f"{names[numbered.group(1)]} {numbered.group(2)}"
        return f"{core}{{{translated}}}" if translated else token

    return TECH_RE.sub(replace, value)


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
            label = MACRO_NAMES.get(label, "Макрос Foundry")
        else:
            label = translated_name(label)
    elif label:
        label = translated_name(label)
    return core + ("{" + label + "}" if label else "")


def translate_card(
    block: str,
    page_id: str,
    card_index: int,
    source_name: str,
    translated_page_name: str,
    page_names: dict[str, str],
    journal_names: dict[str, str],
    actor_names: dict[str, str],
) -> str:
    opening = block.lstrip().lower().split(">", 1)[0]
    manual = MANUAL_ACTION_CARDS.get((page_id, card_index)) if 'class="action' in opening else None
    if manual is not None:
        return manual
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
    page_id: str,
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
            card_index = sum(1 for existing in cards if existing.lstrip().lower().startswith('<section class="action'))
            cards.append(
                translate_card(
                    block,
                    page_id,
                    card_index,
                    source_name,
                    translated_page_name,
                    page_names,
                    journal_names,
                    actor_names,
                )
            )
    return "".join(cards)


def _markup_key(value: str) -> str:
    if value.startswith("@"):
        return technical_cores(value)[0]
    return re.sub(r"\{[^{}]*\}$", "", value)


def _foundry_markup(value: str) -> list[str]:
    matches = [(match.start(), match.group(0)) for match in TECH_RE.finditer(value)]
    matches.extend((match.start(), match.group(0)) for match in INLINE_ROLL_RE.finditer(value))
    return [token for _position, token in sorted(matches)]


def _append_inline_markup(block: str, markup: str) -> str:
    closing = block.rfind("</")
    if closing < 0:
        return block + " " + markup
    return block[:closing].rstrip() + " " + markup + block[closing:]


def restore_missing_markup(
    source_html: str,
    current_html: str,
    page_names: dict[str, str],
    journal_names: dict[str, str],
    actor_names: dict[str, str],
) -> str:
    """Возвращает отсутствующие команды в ближайший смысловой HTML-блок."""
    current = Counter(_markup_key(token) for token in _foundry_markup(current_html))
    source_blocks = top_level_blocks(source_html)
    missing: list[tuple[int, str]] = []
    for source_index, block in enumerate(source_blocks):
        for token in _foundry_markup(block):
            key = _markup_key(token)
            if current[key]:
                current[key] -= 1
                continue
            translated = translate_token_label(token, page_names, journal_names, actor_names) if token.startswith("@") else token
            missing.append((source_index, translated))
    if not missing:
        return current_html
    blocks = top_level_blocks(current_html)
    candidates = [
        index for index, block in enumerate(blocks)
        if block_plain_text(block)
        and not block.lstrip().lower().startswith(("<h1", "<h2", "<h3", "<h4", "<h5", "<h6", "<img", "<hr"))
    ]
    if not candidates:
        return current_html + " ".join(markup for _index, markup in missing)
    source_denominator = max(1, len(source_blocks) - 1)
    for source_index, markup in missing:
        fraction = source_index / source_denominator
        target = candidates[round(fraction * (len(candidates) - 1))]
        blocks[target] = _append_inline_markup(blocks[target], markup)
    return "".join(blocks)
    # Старый общий подвал ниже намеренно недостижим и будет удалён после
    # миграции существующих переводов.
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
    # Команды и формулы всегда берутся из официального исходника. Переводной
    # текст может содержать их копии лишь как ориентиры для переводчика.
    translated_markup = _foundry_markup(translated_text)
    markup_cursor = 0
    translated_text = INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", translated_text))
    parts = re.split(r"(<[^>]+>)", source_html)
    weighted: list[tuple[int, int]] = []
    for index in range(0, len(parts), 2):
        source_text = INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", html.unescape(parts[index])))
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
        original_tokens = _foundry_markup(parts[index])
        localized_tokens: list[str] = []
        for source_token in original_tokens:
            candidate = translated_markup[markup_cursor] if markup_cursor < len(translated_markup) else None
            markup_cursor += 1
            if candidate and source_token.startswith("@") and candidate.startswith(source_token.split("[", 1)[0] + "["):
                label = re.search(r"\{([^{}]*)\}$", candidate)
                source_token = _markup_key(source_token) + ("{" + label.group(1) + "}" if label else "")
            elif candidate and source_token.startswith("[[/r") and candidate.startswith("[[/r"):
                label = re.search(r"\{([^{}]*)\}$", candidate)
                source_token = _markup_key(source_token) + ("{" + label.group(1) + "}" if label else "")
            localized_tokens.append(source_token)
        if localized_tokens:
            chunk = (chunk + " " if chunk else "") + " ".join(localized_tokens)
        parts[index] = chunk
        cursor = end
    # Технические токены из нулевых по весу узлов тоже должны остаться на месте.
    weighted_indexes = {index for index, _ in weighted}
    for index in range(0, len(parts), 2):
        if index not in weighted_indexes:
            parts[index] = " ".join(_foundry_markup(parts[index]))
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
    return SIMPLE_NAMES.get(
        name,
        ACTOR_NAMES.get(
            name,
            LINK_LABELS.get(name, SOUND_NAMES.get(name, MACRO_NAMES.get(name, clean_ru(name)))),
        ),
    )


def item_source(item: dict[str, Any]) -> str | None:
    return (
        item.get("_stats", {}).get("compendiumSource")
        or item.get("flags", {}).get("pf2e", {}).get("compendiumSource")
        or item.get("flags", {}).get("core", {}).get("sourceId")
    )


def make_translation(
    source: dict[str, Any],
    reference: dict[str, Any],
    pdf_pages: list[str],
    pf2e_ru_actor_lore: dict[str, str],
    pf2e_ru_names: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ref_pages = {p["name"]: p for j in reference["journal"] for p in j.get("pages", [])}
    ref_areas = {reference_area_code(p["name"]): p for p in ref_pages.values() if reference_area_code(p["name"])}
    source_pages = {p["_id"]: p for j in source["journal"] for p in j.get("pages", [])}
    translated_page_names: dict[str, str] = {}
    for page_id, page in source_pages.items():
        source_name = page.get("name", "")
        translated = PAGE_NAMES.get(page_id) or translated_name(source_name)
        if translated == source_name and page.get("type") != "image":
            reference_page = None
            if page_id in REFERENCE_SLICES:
                reference_page = ref_pages.get(REFERENCE_SLICES[page_id][0])
            else:
                area_code = first_area_code(page.get("text", {}).get("content", ""))
                if area_code:
                    reference_page = ref_areas.get(AREA_PREFIX[area_code[0]] + area_code[1:])
                if reference_page is None:
                    reference_page = ref_pages.get(NARRATIVE_REFERENCE.get(page_id, ""))
            if reference_page:
                translated = clean_ru(reference_page["name"])
        translated_page_names[page_id] = translated
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

            name = translated_page_names[pid]
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
                    pid,
                    page["name"],
                    name,
                    translated_page_names,
                    translated_journal_names,
                    translated_actor_names,
                )
                body = translated_heading(pid, name) + ref_html
                if pid.startswith("06handout"):
                    body = f'<div class="handout-wrapper"><section class="handout">{body}</section></div>'
                body = restore_missing_markup(
                    source_html,
                    body + cards,
                    translated_page_names,
                    translated_journal_names,
                    translated_actor_names,
                )
                russian_html = f'<div class="rusthenge-ru-content">{media}{body}</div>'
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
                "inlineRolls": INLINE_ROLL_RE.findall(source_html),
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
    actor_inline_rolls: dict[str, list[str]] = {}
    actor_html: dict[str, str] = {}
    custom_items = 0
    custom_items_translated = 0
    for actor in source.get("actors", []):
        ref_actor = ref_actors_by_source.get(item_source(actor)) or ref_actors_by_id.get(actor["_id"])
        actor_name = ACTOR_NAMES.get(actor["name"])
        if actor_name is None:
            actor_name = clean_ru(ref_actor["name"]) if ref_actor else translated_name(actor["name"])
        entry: dict[str, Any] = {"name": actor_name, "tokenName": actor_name}
        source_details = actor.get("system", {}).get("details", {})
        ref_details = ref_actor.get("system", {}).get("details", {}) if ref_actor else {}
        manual_notes = MANUAL_ACTOR_NOTES.get(actor["name"], {})
        manual_html = MANUAL_ACTOR_HTML.get(actor["name"], {})
        for source_key, output_key, manual_key in (
            ("publicNotes", "description", "description"),
            ("privateNotes", "descriptionGM", "descriptionGM"),
        ):
            source_value = source_details.get(source_key, "")
            reference_value = ref_details.get(source_key, "")
            translated_value = manual_notes.get(manual_key)
            if output_key == "description" and actor["name"] in pf2e_ru_actor_lore:
                translated_value = html.unescape(
                    TAG_RE.sub(" ", TECH_RE.sub(" ", pf2e_ru_actor_lore[actor["name"]]))
                )
            if translated_value is None and reference_value:
                translated_value = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", clean_ru(reference_value))))
            if source_value and translated_value:
                rendered = manual_html.get(output_key) or reflow_preserving_html(source_value, translated_value)
                if html_tags(rendered) != html_tags(source_value):
                    raise ValueError(f"{actor['name']}/{output_key}: ручной HTML не совпадает со структурой источника")
                entry[output_key] = rendered
                actor_technical[f"{actor['_id']}/{output_key}"] = TECH_RE.findall(source_value)
                actor_inline_rolls[f"{actor['_id']}/{output_key}"] = INLINE_ROLL_RE.findall(source_value)
                actor_html[f"{actor['_id']}/{output_key}"] = hashlib.sha256(
                    "\n".join(html_tags(source_value)).encode()
                ).hexdigest()

        item_entries = []
        for item in actor.get("items", []):
            if item_source(item):
                continue  # pf2e-ru переводит системный Compendium UUID.
            custom_items += 1
            ref_item = ref_items_by_id.get(item["_id"])
            manual_item_name = translated_name(item["name"])
            item_entry = {
                "id": item["_id"],
                "name": (
                    manual_item_name
                    if manual_item_name != item["name"]
                    else translated_name(clean_ru(ref_item["name"])) if ref_item else manual_item_name
                ),
            }
            source_desc = item.get("system", {}).get("description", {})
            ref_desc = ref_item.get("system", {}).get("description", {}) if ref_item else {}
            manual_desc = MANUAL_ITEM_DESCRIPTIONS.get(item["name"], {})
            manual_html = {
                **MANUAL_ITEM_HTML.get(item["name"], {}),
                **MANUAL_ITEM_HTML_BY_ID.get(item["_id"], {}),
            }
            for source_key, output_key in (("value", "description"), ("gm", "gm")):
                source_value = source_desc.get(source_key, "")
                reference_value = ref_desc.get(source_key, "")
                translated_value = manual_desc.get(output_key)
                if translated_value is None and reference_value:
                    translated_value = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", clean_ru(reference_value))))
                if source_value and translated_value:
                    rendered = manual_html.get(output_key) or reflow_preserving_html(source_value, translated_value)
                    rendered = localize_pf2e_markup_labels(rendered, pf2e_ru_names)
                    if html_tags(rendered) != html_tags(source_value):
                        raise ValueError(f"{item['name']}/{output_key}: ручной HTML не совпадает со структурой источника")
                    item_entry[output_key] = rendered
                    key = f"{actor['_id']}/items/{item['_id']}/{output_key}"
                    actor_technical[key] = TECH_RE.findall(source_value)
                    actor_inline_rolls[key] = INLINE_ROLL_RE.findall(source_value)
                    actor_html[key] = hashlib.sha256("\n".join(html_tags(source_value)).encode()).hexdigest()
            if ref_item or manual_desc:
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

    folder_names = {f["name"]: FOLDER_NAMES.get(f["name"], translated_name(f["name"])) for f in source.get("folders", [])}
    macros = {
        macro["_id"]: {"name": MACRO_NAMES[macro["name"]]}
        for macro in source.get("macros", [])
    }
    playlists = {
        playlist["_id"]: {
            "name": PLAYLIST_NAMES[playlist["name"]],
            "sounds": {
                sound["_id"]: {"name": SOUND_NAMES[sound["name"]]}
                for sound in playlist.get("sounds", [])
            },
        }
        for playlist in source.get("playlists", [])
    }
    translation = {
        "label": "Pathfinder Adventure: Растхендж",
        "entries": {
            source["_id"]: {
                "name": "Pathfinder Adventure: Растхендж",
                "description": "<p>Русский перевод приключения «Растхендж».</p>",
                "folders": folder_names,
                "journals": translated_journals,
                "scenes": scenes,
                "macros": macros,
                "playlists": playlists,
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
            "macros": len(source.get("macros", [])), "playlists": len(source.get("playlists", [])),
            "playlistSounds": sum(len(p.get("sounds", [])) for p in source.get("playlists", [])),
            "actorPublicNotes": sum(bool(a.get("system", {}).get("details", {}).get("publicNotes")) for a in source.get("actors", [])),
            "actorPrivateNotes": sum(bool(a.get("system", {}).get("details", {}).get("privateNotes")) for a in source.get("actors", [])),
            "itemPublicDescriptions": sum(
                bool(i.get("system", {}).get("description", {}).get("value"))
                for a in source.get("actors", []) for i in a.get("items", []) if not item_source(i)
            ),
            "itemGMDescriptions": sum(
                bool(i.get("system", {}).get("description", {}).get("gm"))
                for a in source.get("actors", []) for i in a.get("items", []) if not item_source(i)
            ),
        },
        "servicePageIds": sorted(SERVICE_PAGE_IDS),
        "pages": page_index,
        "actorTechnical": actor_technical,
        "actorInlineRolls": actor_inline_rolls,
        "actorHtml": actor_html,
        "macroCommandHashes": {
            macro["_id"]: hashlib.sha256(macro.get("command", "").encode()).hexdigest()
            for macro in source.get("macros", [])
        },
        "playlistSounds": {
            playlist["_id"]: [sound["_id"] for sound in playlist.get("sounds", [])]
            for playlist in source.get("playlists", [])
        },
    }
    complete_existing_translation(source, translation, index, pf2e_ru_names)
    return translation, index


ACTION_SECTION_RE = re.compile(
    r'<section\b[^>]*class="[^"]*action[^"]*"[^>]*>.*?</section>',
    flags=re.I | re.S,
)

EMPTY_CONTAINER_RE = re.compile(
    r"<(section|div|aside|p|ul|ol|li)\b[^>]*>\s*</\1>",
    flags=re.I,
)

# Точечные артефакты старой PDF-конверсии. Они не содержатся в
# официальном HTML и дублируют заголовки/карточки в цифровом журнале.
DIGITAL_LAYOUT_REPAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "02sneakingonbo00": (
        ('<h4>Отвлечь Экипаж</h4><h4>Обыск Корабля</h4>', ""),
        ('Меч-Рыба" - это корабль длиной 75ФТ', '«Рыба-меч» — это корабль длиной 75 футов'),
        ('#search-ship]{Б2. Меч-Рыба}', '#search-ship]{Обыскать корабль}'),
        ('#distract-crew]{Б2. Меч-Рыба}', '#distract-crew]{Отвлечь экипаж}'),
    ),
    "02elderordwi0000": (("<h3>Старейшина Ордви</h3>", ""),),
    "05sinsludge00000": (("<h2>Грехошлам</h2>", ""),),
    "05demonvloriak00": (
        ('<span class="keepme">Бестиарий: Влориак</span>', '<span class="keepme">Влорианское влияние</span>'),
    ),
    "05thehornofrus00": (("<h4><span> / Предмет 5</span></h4>", ""),),
}


def cleanup_digital_layout(translation: dict[str, Any]) -> int:
    """Удаляет печатные артефакты, не меняя технические токены."""
    changed = 0
    for adventure in translation.get("entries", {}).values():
        pages = {
            page_id: page
            for journal in adventure.get("journals", {}).values()
            for page_id, page in journal.get("pages", {}).items()
        }
        for page_id, page in pages.items():
            text = page.get("text")
            if not isinstance(text, str):
                continue
            before_cores = Counter(technical_cores(text))
            for old, new in DIGITAL_LAYOUT_REPAIRS.get(page_id, ()):
                text = text.replace(old, new)
            text = EMPTY_CONTAINER_RE.sub("", text)
            text = re.sub(r"(\d+)\s*ФТ\b", r"\1 футов", text)
            text = text.replace("КБ_", "КБ ").replace("Вспом.Информ.", "Вспомнить информацию")

            # Карточка аколитов была добавлена в конец страницы вместо пустого
            # места из PDF. Возвращаем её к абзацу о существах, как в официальном HTML.
            if page_id == "02securestorag00":
                cards = list(ACTION_SECTION_RE.finditer(text))
                creature = next((m for m in cards if "Actor.Q3ciH3AHZlb1Dc3E" in m.group(0)), None)
                marker = "</p><p>Трое выживших пленников"
                if creature and marker in text and creature.start() > text.index(marker):
                    card = creature.group(0)
                    text = text[:creature.start()] + text[creature.end():]
                    text = text.replace(marker, f"</p>{card}<p>Трое выживших пленников", 1)

            if Counter(technical_cores(text)) != before_cores:
                raise ValueError(f"{page_id}: очистка вёрстки изменила технические токены")
            if text != page["text"]:
                page["text"] = text
                changed += 1
    return changed


ACTOR_EXTRA_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blurb", ("system", "details", "blurb")),
    ("language", ("system", "details", "languages", "details")),
    ("senses", ("system", "perception", "details")),
    ("descriptionHazard", ("system", "details", "description")),
    ("disable", ("system", "details", "disable")),
    ("reset", ("system", "details", "reset")),
    ("routine", ("system", "details", "routine")),
    ("stealth", ("system", "attributes", "stealth", "details")),
    ("hp", ("system", "attributes", "hp", "details")),
    ("ac", ("system", "attributes", "ac", "details")),
    ("allSaves", ("system", "attributes", "allSaves", "value")),
    ("speed", ("system", "attributes", "speed", "details")),
    ("willSave", ("system", "saves", "will", "saveDetail")),
    ("skillAcrobatics", ("system", "skills", "acrobatics", "special", "0", "label")),
    ("skillAthletics", ("system", "skills", "athletics", "special", "0", "label")),
    ("skillCrafting", ("system", "skills", "crafting", "special", "0", "label")),
    ("skillStealth", ("system", "skills", "stealth", "special", "0", "label")),
    ("skillThievery", ("system", "skills", "thievery", "special", "0", "label")),
)


def nested_value(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for part in path:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return ""
        elif isinstance(current, dict):
            current = current.get(part, "")
        else:
            return ""
    return current


def normalize_visible_text(value: str) -> str:
    for old, new in CANONICAL_VISIBLE_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def normalize_translation_tree(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_visible_text(value)
    if isinstance(value, list):
        return [normalize_translation_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_translation_tree(item) for key, item in value.items()}
    return value


def translate_actor_extra(value: str, field: str) -> str:
    if field == "blurb":
        translated = ACTOR_BLURBS.get(value)
    elif field in {"descriptionHazard", "disable", "reset", "routine"}:
        translated = HAZARD_FIELDS.get(value)
    else:
        translated = ACTOR_SHORT_FIELDS.get(value)
    if translated is None:
        raise ValueError(f"Нет проверенного перевода Actor.{field}: {value!r}")
    return translated


def complete_existing_translation(
    source: dict[str, Any],
    translation: dict[str, Any],
    index: dict[str, Any],
    pf2e_ru_names: dict[str, str],
) -> dict[str, int]:
    """Дозаполняет все видимые текстовые поля актёров и их предметов по ID."""
    adventure = translation["entries"][source["_id"]]
    normalized = normalize_translation_tree(adventure)
    adventure.clear()
    adventure.update(normalized)
    actors = adventure["actors"]
    actor_technical = index.setdefault("actorTechnical", {})
    actor_inline_rolls = index.setdefault("actorInlineRolls", {})
    actor_html = index.setdefault("actorHtml", {})
    counts: Counter[str] = Counter()

    canonical_actor_names = {
        actor["_id"]: ACTOR_NAMES.get(actor["name"], actors[actor["_id"]].get("name", actor["name"]))
        for actor in source.get("actors", [])
    }
    for actor in source.get("actors", []):
        actor_id = actor["_id"]
        entry = actors[actor_id]
        entry["name"] = canonical_actor_names[actor_id]
        entry["tokenName"] = canonical_actor_names[actor_id]
        if actor["name"] in ACTOR_DESCRIPTION_OVERRIDES:
            value = ACTOR_DESCRIPTION_OVERRIDES[actor["name"]]
            source_value = nested_value(actor, ("system", "details", "publicNotes"))
            if html_tags(value) != html_tags(source_value):
                raise ValueError(f"{actor['name']}/description: изменена HTML-структура")
            entry["description"] = value
            key = f"{actor_id}/description"
            actor_technical[key] = TECH_RE.findall(source_value)
            actor_inline_rolls[key] = INLINE_ROLL_RE.findall(source_value)
            actor_html[key] = hashlib.sha256("\n".join(html_tags(source_value)).encode()).hexdigest()

        for output_key, path in ACTOR_EXTRA_FIELDS:
            source_value = nested_value(actor, path)
            if not isinstance(source_value, str) or not source_value:
                continue
            translated = translate_actor_extra(source_value, output_key)
            entry[output_key] = translated
            counts[output_key] += 1
            key = f"{actor_id}/{output_key}"
            actor_technical[key] = TECH_RE.findall(source_value)
            actor_inline_rolls[key] = INLINE_ROLL_RE.findall(source_value)
            actor_html[key] = hashlib.sha256("\n".join(html_tags(source_value)).encode()).hexdigest()

        item_entries = entry.setdefault("items", [])
        translated_items = {item.get("id"): item for item in item_entries}
        for item in actor.get("items", []):
            item_entry = translated_items.get(item["_id"])
            linked = bool(item_source(item))
            unidentified = nested_value(item, ("system", "identification", "unidentified"))
            rules = nested_value(item, ("system", "rules"))
            original_unidentified_name = unidentified.get("name", "") if isinstance(unidentified, dict) else ""
            original_unidentified_description = (
                nested_value(unidentified, ("data", "description", "value"))
                if isinstance(unidentified, dict)
                else ""
            )
            original_rule_label = (
                rules[0].get("label", "")
                if isinstance(rules, list) and rules and isinstance(rules[0], dict)
                else ""
            )
            needs_local_override = bool(
                linked
                or original_unidentified_name
                or original_unidentified_description
                or original_rule_label in RULE_LABELS
            )
            if item_entry is None and needs_local_override:
                item_entry = {"id": item["_id"]}
                item_entries.append(item_entry)
                translated_items[item["_id"]] = item_entry
                if linked:
                    index.setdefault("linkedItemOverrides", []).append(f"{actor_id}/{item['_id']}")
                    counts["linkedItemOverrides"] += 1
            if item_entry is None:
                continue
            canonical_item_name = (
                LINKED_ITEM_NAMES.get(item["name"])
                or pf2e_ru_names.get(item["name"])
                or translated_name(item["name"])
            )
            if linked and canonical_item_name == item["name"]:
                raise ValueError(f"Нет перевода имени системного элемента: {item['name']!r}")
            if canonical_item_name != item["name"]:
                item_entry["name"] = canonical_item_name
                if linked:
                    counts["linkedItemNames"] += 1
            if isinstance(unidentified, dict):
                original_name = original_unidentified_name
                if original_name:
                    if original_name not in UNIDENTIFIED_NAMES:
                        raise ValueError(f"Нет перевода неопознанного имени: {original_name!r}")
                    item_entry["unidentifiedName"] = UNIDENTIFIED_NAMES[original_name]
                    counts["itemUnidentifiedNames"] += 1
                original_description = original_unidentified_description
                if original_description:
                    if original_description not in UNIDENTIFIED_DESCRIPTIONS:
                        raise ValueError(f"Нет перевода неопознанного описания: {original_description!r}")
                    item_entry["unidentifiedDescription"] = UNIDENTIFIED_DESCRIPTIONS[original_description]
                    counts["itemUnidentifiedDescriptions"] += 1
                    key = f"{actor_id}/items/{item['_id']}/unidentifiedDescription"
                    actor_technical[key] = TECH_RE.findall(original_description)
                    actor_inline_rolls[key] = INLINE_ROLL_RE.findall(original_description)
                    actor_html[key] = hashlib.sha256("\n".join(html_tags(original_description)).encode()).hexdigest()
            if isinstance(rules, list) and rules:
                original_label = original_rule_label
                if original_label in RULE_LABELS:
                    item_entry["ruleLabel0"] = RULE_LABELS[original_label]
                    counts["itemRuleLabels"] += 1

    page_names = {
        page_id: page.get("name", "")
        for journal in adventure.get("journals", {}).values()
        for page_id, page in journal.get("pages", {}).items()
    }
    journal_names = {journal_id: journal.get("name", "") for journal_id, journal in adventure.get("journals", {}).items()}
    for journal in adventure.get("journals", {}).values():
        for page in journal.get("pages", {}).values():
            if "text" in page:
                page["text"] = TECH_RE.sub(
                    lambda match: translate_token_label(
                        match.group(0), page_names, journal_names, canonical_actor_names
                    ),
                    normalize_visible_text(page["text"]),
                )

    expected = index.setdefault("expected", {})
    expected.update({
        "actorBlurbs": counts["blurb"],
        "actorLanguageDetails": counts["language"],
        "actorSenseDetails": counts["senses"],
        "hazardDescriptions": counts["descriptionHazard"],
        "hazardDisable": counts["disable"],
        "hazardReset": counts["reset"],
        "hazardRoutine": counts["routine"],
        "actorStealthDetails": counts["stealth"],
        "actorHpDetails": counts["hp"],
        "actorAcDetails": counts["ac"],
        "actorAllSaveDetails": counts["allSaves"],
        "actorSpeedDetails": counts["speed"],
        "actorSaveDetails": counts["willSave"],
        "actorSkillLabels": sum(counts[key] for key in counts if key.startswith("skill")),
        "itemUnidentifiedNames": counts["itemUnidentifiedNames"],
        "itemUnidentifiedDescriptions": counts["itemUnidentifiedDescriptions"],
        "itemRuleLabels": counts["itemRuleLabels"],
        "linkedItemNames": counts["linkedItemNames"],
        "linkedItemOverrides": len(set(index.get("linkedItemOverrides", []))),
    })
    index["linkedItemOverrides"] = sorted(set(index.get("linkedItemOverrides", [])))
    return dict(counts)


def repair_existing_action_cards(source: dict[str, Any], translation: dict[str, Any]) -> int:
    """Заменяет пустые хвостовые action-карточки проверенными русскими версиями."""
    entries = translation.get("entries", {})
    adventure = entries.get(source.get("_id"), {})
    journals = adventure.get("journals", {})
    translated_pages = {
        page_id: page
        for journal in journals.values()
        for page_id, page in journal.get("pages", {}).items()
    }
    source_pages = {
        page["_id"]: page
        for journal in source.get("journal", [])
        for page in journal.get("pages", [])
    }
    repaired = 0
    page_ids = sorted({page_id for page_id, _index in MANUAL_ACTION_CARDS})
    for page_id in page_ids:
        source_page = source_pages.get(page_id)
        translated_page = translated_pages.get(page_id)
        if not source_page or not translated_page:
            raise ValueError(f"Не найдена страница для ремонта: {page_id}")
        source_html = source_page.get("text", {}).get("content", "")
        source_actions = ACTION_SECTION_RE.findall(source_html)
        current_html = translated_page.get("text", "")
        current_matches = list(ACTION_SECTION_RE.finditer(current_html))
        if len(current_matches) < len(source_actions):
            raise ValueError(f"{page_id}: action-карточек меньше, чем в официальном источнике")
        offset = len(current_matches) - len(source_actions)
        replacements: list[tuple[int, int, str]] = []
        for card_index, source_action in enumerate(source_actions):
            manual = MANUAL_ACTION_CARDS.get((page_id, card_index))
            if manual is None:
                continue
            if Counter(technical_cores(manual)) != Counter(technical_cores(source_action)):
                raise ValueError(f"{page_id}/{card_index}: изменены технические токены")
            if Counter(INLINE_ROLL_RE.findall(manual)) != Counter(INLINE_ROLL_RE.findall(source_action)):
                raise ValueError(f"{page_id}/{card_index}: изменены встроенные броски")
            match = current_matches[offset + card_index]
            replacements.append((match.start(), match.end(), manual))
        for start, end, manual in reversed(replacements):
            current_html = current_html[:start] + manual + current_html[end:]
            repaired += 1
        for old, new in EXISTING_PAGE_TEXT_REPAIRS.get(page_id, ()):
            current_html = current_html.replace(old, new, 1)
        desired_cores = Counter(technical_cores(source_html))
        extra_cores = Counter(technical_cores(current_html)) - desired_cores
        protected: dict[str, str] = {}
        for index, (_start, _end, manual) in enumerate(replacements):
            placeholder = f"@@RUSTHENGE_ACTION_CARD_{index}@@"
            current_html = current_html.replace(manual, placeholder, 1)
            protected[placeholder] = manual

        def remove_old_duplicate(match: re.Match[str]) -> str:
            token = match.group(0)
            core_match = TECH_CORE_RE.fullmatch(token)
            core = core_match.group(1) if core_match else token
            if extra_cores[core]:
                extra_cores[core] -= 1
                return ""
            return token

        current_html = TECH_RE.sub(remove_old_duplicate, current_html)
        for placeholder, manual in protected.items():
            current_html = current_html.replace(placeholder, manual, 1)
        if Counter(technical_cores(current_html)) != desired_cores:
            raise ValueError(f"{page_id}: после ремонта изменён набор технических токенов")
        translated_page["text"] = current_html
    return repaired


BESTIARY_MAPPING = {
    "description": "system.details.publicNotes",
    "descriptionGM": "system.details.privateNotes",
    "blurb": "system.details.blurb",
    "language": "system.details.languages.details",
    "senses": "system.perception.details",
    "descriptionHazard": "system.details.description",
    "disable": "system.details.disable",
    "reset": "system.details.reset",
    "routine": "system.details.routine",
    "stealth": "system.attributes.stealth.details",
    "hp": "system.attributes.hp.details",
    "ac": "system.attributes.ac.details",
    "allSaves": "system.attributes.allSaves.value",
    "speed": "system.attributes.speed.details",
    "willSave": "system.saves.will.saveDetail",
    "skillAcrobatics": "system.skills.acrobatics.special.0.label",
    "skillAthletics": "system.skills.athletics.special.0.label",
    "skillCrafting": "system.skills.crafting.special.0.label",
    "skillStealth": "system.skills.stealth.special.0.label",
    "skillThievery": "system.skills.thievery.special.0.label",
    "items": {
        "path": "items",
        "converter": "document",
        "documentType": "Item",
        "cardinality": "many",
    },
}

BESTIARY_ACTOR_FIELD_PATHS = {
    "description": ("system", "details", "publicNotes"),
    "descriptionGM": ("system", "details", "privateNotes"),
    **{field: path for field, path in ACTOR_EXTRA_FIELDS},
}

BESTIARY_DESCRIPTION_OVERRIDES = {
    "PFa0h9BekFPB4Eoh": '<p><strong>Триггер</strong> Существо проходит под клеткой и наступает на нажимную плиту</p><hr /><p><strong>Эффект</strong> Клетка падает с потолка, пытаясь поймать спровоцировавшее существо; оно должно совершить спасбросок @Check[reflex|dc:17|traits:damaging-effect].</p><hr /><p><strong>Критический успех</strong> Существо избегает ловушки и возвращается в пространство, которое только что покинуло, вместо того чтобы войти в пространство ловушки.</p><p><strong>Успех</strong> Как критический успех, но падающая ловушка задевает существо и наносит ему @Damage[(1d6+3)[bludgeoning]] дробящего урона, когда оно отшатывается.</p><p><strong>Провал</strong> Падающая ловушка накрывает спровоцировавшее существо. Существо среднего размера или меньше оказывается заперто в клетке ([[/act escape dc=20]]{Вырваться, СЛ 20}). Существо большого размера или больше получает @Damage[(2d6+5)[bludgeoning]] дробящего урона и падает @UUID[Compendium.pf2e.conditionitems.Item.j91X7x0XSomq8d60]{ничком}, а клетка отскакивает от его тела и разрушается.</p><p><strong>Критический провал</strong> Как провал, но существо среднего размера или меньше также получает удар клеткой, падает ничком, получает @Damage[(2d6+5)[bludgeoning]] дробящего урона и становится @UUID[Compendium.pf2e.conditionitems.Item.eIcWbB5o3pP6OIMe]{обездвижено}, поскольку клетка придавливает его конечность.</p>',
    "lL49wJa4ig4V0ag1": '<p>Заводной шпион записывает все звуки в @Template[emanation|distance:25]{25-футовой эманации} на маленький самоцвет стоимостью 1 зм, встроенный в его тело. На один самоцвет можно записать до 1 часа звука. Начав запись, шпион не может остановить её досрочно или записать что-либо на самоцвет, где уже есть запись.</p><p>Некоторые заводные шпионы содержат несколько самоцветов и могут сделать серию записей. Поскольку они неразумны, им нужно дать простые указания, когда начинать запись. Заводной шпион различает виды существ, но не отдельных личностей.</p><p>Шпион может одним действием начать или остановить воспроизведение записи. Чтобы извлечь или установить самоцвет, нужно успешно пройти проверку [[/act disable-device dc=14]]{Воровства СЛ 14} для действия @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключить устройство}. При провале самоцвет не повреждается, но запись стирается, и самоцвет по-прежнему нельзя использовать для новой записи.</p>',
    "zdb8RR0jcIIol6on": '<p>24 часа, [[/act disable-device dc=17]]{Воровство СЛ 17}, режим ожидания</p><hr /><p>Чтобы заводной механизм мог действовать, другое существо должно завести его уникальным ключом; это занимает 1 минуту. После завода механизм работает указанное время, обычно 24 часа, затем перестаёт воспринимать окружение и не может действовать, пока его не заведут снова. Некоторые способности расходуют оставшееся рабочее время. Механизм не может потратить больше времени, чем у него есть, и немедленно отключается, когда время заканчивается. Если неизвестно, когда его заводили в последний раз, считается, что смотритель заводит механизмы в установленное время, обычно в 8 утра.</p><p>Механизм с режимом ожидания может перейти в него активностью за 3 действия. В этом режиме рабочее время не уменьшается, механизм воспринимает окружение со штрафом –2 к Восприятию и не может действовать, кроме одного случая: заметив существо, он может реакцией выйти из режима ожидания и при необходимости бросить инициативу.</p><p>Существо может попытаться выполнить @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключение устройства} с указанной СЛ, чтобы постепенно остановить механизм. При каждом успехе механизм теряет 1 час рабочего времени. Это можно делать и в режиме ожидания.</p>',
    "QXmns8bw5DBlNJ9D": '<p>Мейтремар может свободно усиливать заклинания @UUID[Compendium.pf2e.spells-srd.Item.rfZpqmj0AIIdkVIs]{Исцеление}.</p>',
    "0rwXFzCG58mrENRi": '<p><strong>Триггер</strong> Не поклоняющееся Ксар-Азмаку существо пытается открыть дверь или наносит ей урон Ударом ближнего боя</p><hr /><p><strong>Эффект</strong> Спровоцировавшее существо подвергается воздействию ползучей ржавчины: из ржавых пятен на двери выползают усики ржаво-красной энергии и странно нежно скребут открытую кожу.</p>',
    "edVyMro5viX5rgD9": '<p>24 часа, [[/act disable-device dc=21]]{Воровство СЛ 21}, режим ожидания</p><hr /><p>Чтобы заводной механизм мог действовать, другое существо должно завести его уникальным ключом; это занимает 1 минуту. После завода механизм работает указанное время, обычно 24 часа, затем перестаёт воспринимать окружение и не может действовать, пока его не заведут снова. Некоторые способности расходуют оставшееся рабочее время. Механизм не может потратить больше времени, чем у него есть, и немедленно отключается, когда время заканчивается. Если неизвестно, когда его заводили в последний раз, считается, что смотритель заводит механизмы в установленное время, обычно в 8 утра.</p><p>Механизм с режимом ожидания может перейти в него активностью за 3 действия. В этом режиме рабочее время не уменьшается, механизм воспринимает окружение со штрафом –2 к Восприятию и не может действовать, кроме одного случая: заметив существо, он может реакцией выйти из режима ожидания и при необходимости бросить инициативу.</p><p>Существо может попытаться выполнить @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключение устройства} с указанной СЛ, чтобы постепенно остановить механизм. При каждом успехе механизм теряет 1 час рабочего времени. Это можно делать и в режиме ожидания.</p>',
    "fH4zN6EufktPqbW4": '<p>Заводной маг использует механическую палочку как фокус для направления магической энергии. Палочка встроена в грудь мага, наружу выступает только кристалл на её конце. Маг может Взаимодействовать, чтобы извлечь палочку; другое существо может сделать это, успешно пройдя проверку @Check[thievery|dc:25|traits:action:disable-a-device] для действия @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключить устройство}. Без палочки заводной маг может сотворять только чары.</p><p>После извлечения заводная палочка становится <em>@UUID[Compendium.pf2e.equipment-srd.Item.vJZ49cgi8szuQXAD]{магической палочкой}</em>, содержащей последнее сотворённое заводным магом врождённое заклинание 1-го ранга (@UUID[Compendium.pf2e.spells-srd.Item.4koZzrnMXhhosn0D]{Страх}, если заводной Белимариус ещё не сотворял в этом приключении заклинаний 1-го ранга). Заклинания закладываются в палочку при создании мага; создатель может заменить их другими арканными заклинаниями соответствующего ранга.</p>',
    "qtsF75k2Zterahrt": '<p>Деро-магистр получает @Damage[10[untyped]] урона за каждый час пребывания под солнечным светом.</p>',
    "htliQ05jVKwfE22v": '<p>@UUID[Compendium.pf2e.spells-srd.Item.rfZpqmj0AIIdkVIs]{Исцеление}</p>',
    "UDhWMhJzdEJtykvO": '<p>Когда Ордви сотворяет @UUID[Compendium.pf2e.spells-srd.Item.rfZpqmj0AIIdkVIs]{Исцеление}, она бросает d10 вместо d8.</p>',
}

BESTIARY_ACTOR_FIELD_OVERRIDES = {
    ("Tvz5JKAE8rrCF5qW", "reset"): "<p>Существа всё ещё могут упасть в яму, но закрывающую её шкуру нужно натянуть вручную (10-минутная активность), чтобы ловушка снова стала скрытой.</p>",
}

DISEASE_TEXT_REPLACEMENTS = (
    ("These undead inflict rust creep with their jaws Strikes. A creature damaged by a jaws Strike or a Gnash from one of these severed heads must succeed at a DC 15 Fortitude save or contract rust creep.",
     "Эти неживые существа заражают ползучей ржавчиной ударами челюстей. Существо, получившее урон от Удара челюстями или Скрежета одной из этих отрубленных голов, должно успешно пройти спасбросок Стойкости СЛ 15, иначе оно заражается ползучей ржавчиной."),
    ("A creature bitten by the Vlorian cythnigot becomes afflicted by rust creep, but with a DC 20 Fortitude save.",
     "Существо, укушенное влорианским цитниготом, заражается ползучей ржавчиной, но проходит спасбросок Стойкости СЛ 20."),
    ("Those afflicted by rust creep develop uncomfortable rust-colored bruises on their flesh and endure full-body aches like those one might experience after a long workout. As the affliction progresses, their bodies—as well as the clothing and items they wear or carry—increasingly break down until a painful death occurs. If a character successfully resists contracting rust creep, or recovers from a case of rust creep, they are temporarily immune to future rust creep infections for 24 hours.",
     "У заражённых ползучей ржавчиной на теле появляются болезненные ржаво-коричневые синяки, а всё тело болит, словно после долгой тренировки. По мере развития болезни тело, одежда и переносимые предметы всё сильнее разрушаются, пока не наступает мучительная смерть. Персонаж, успешно сопротивлявшийся заражению или излечившийся от ползучей ржавчины, получает временный иммунитет к новым заражениям на 24 часа."),
    ("An infection introduced through open wounds, tetanus can produce stiffness, muscle spasms strong enough to break bones, and ultimately death.",
     "Столбняк — инфекция, попадающая в организм через открытые раны и вызывающая скованность, мышечные спазмы, способные ломать кости, и в конечном счёте смерть."),
    ("Rustcreep", "Ползучая ржавчина"),
    ("Saving Throw", "Спасбросок"),
    ("Onset", "Начало действия"),
    ("Stage 1", "Стадия 1"),
    ("Stage 2", "Стадия 2"),
    ("Stage 3", "Стадия 3"),
    ("Stage 4", "Стадия 4"),
    ("Stage 5", "Стадия 5"),
    ("Stage 6", "Стадия 6"),
    ("Stage 7", "Стадия 7"),
    ("–1 status penalty to Athletics checks (1 day)", "штраф состояния –1 к проверкам Атлетики (1 день)"),
    ("as stage 1 (1 day)", "как стадия 1 (1 день)"),
    ("enfeebled 1 and ", "ослаблен 1 и "),
    (", plus any armor, clothing and items you carry and that are of a level equal to or less than the disease become broken as the decay spreads to them (1 day; broken items remain broken)",
     ", а все переносимые доспехи, одежда и предметы с уровнем не выше уровня болезни получают состояние сломан из-за распространяющегося разрушения (1 день; предметы остаются сломанными)"),
    ("unconscious (1 day)", "без сознания (1 день)"),
    ("death", "смерть"),
    ("10 days", "10 дней"),
    (" and can't speak (1 day)", " и не может говорить (1 день)"),
    (" with spasms (1 day)", " со спазмами (1 день)"),
    (" (1 week)", " (1 неделя)"),
    ("(1 day)", "(1 день)"),
)


def translated_disease_description(item: dict[str, Any], pf2e_ru_names: dict[str, str]) -> str | None:
    if item.get("name") not in {"Rust Creep", "Tetanus"}:
        return None
    source_value = nested_value(item, ("system", "description", "value"))
    if not isinstance(source_value, str) or not source_value:
        return None
    value = source_value
    for old, new in DISEASE_TEXT_REPLACEMENTS:
        value = value.replace(old, new)
    value = localize_pf2e_markup_labels(value, pf2e_ru_names)
    if html_tags(value) != html_tags(source_value) or technical_cores(value) != technical_cores(source_value):
        raise ValueError(f"{item.get('name')}: перевод болезни изменил HTML или технические токены")
    return value


def rebase_technical_markup(translated: str, current_source: str) -> str | None:
    """Переносит русские подписи на актуальные команды PF2e 8.4 по их порядку."""
    if html_tags(translated) != html_tags(current_source):
        return None
    source_tokens = TECH_RE.findall(current_source)
    translated_tokens = TECH_RE.findall(translated)
    source_rolls = INLINE_ROLL_RE.findall(current_source)
    translated_rolls = INLINE_ROLL_RE.findall(translated)
    if len(source_tokens) != len(translated_tokens) or len(source_rolls) != len(translated_rolls):
        return None

    token_index = 0
    def replace_token(match: re.Match[str]) -> str:
        nonlocal token_index
        source_token = source_tokens[token_index]
        token_index += 1
        source_core = TECH_CORE_RE.fullmatch(source_token).group(1)
        translated_label = re.search(r"\{([^{}]*)\}$", match.group(0))
        return source_core + (f"{{{translated_label.group(1)}}}" if translated_label else "")

    roll_index = 0
    def replace_roll(match: re.Match[str]) -> str:
        nonlocal roll_index
        source_roll = source_rolls[roll_index]
        roll_index += 1
        source_core = re.sub(r"\{[^{}]*\}$", "", source_roll)
        translated_label = re.search(r"\{([^{}]*)\}$", match.group(0))
        return source_core + (f"{{{translated_label.group(1)}}}" if translated_label else "")

    return INLINE_ROLL_RE.sub(replace_roll, TECH_RE.sub(replace_token, translated))


def build_bestiary_translation(
    source: dict[str, Any],
    adventure_translation: dict[str, Any],
    bestiary_actors: list[dict[str, Any]],
    pf2e_ru_names: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Создаёт перевод исходного пака, которым импортёр Rusthenge заменяет актёров."""
    source_actors = source.get("actors", [])
    translated_actors = adventure_translation["entries"][source["_id"]]["actors"]
    source_by_pack_id: dict[str, dict[str, Any]] = {}
    for actor in source_actors:
        actor_source = item_source(actor) or ""
        if actor_source.startswith("Compendium.pf2e.rusthenge-bestiary.Actor."):
            source_by_pack_id.setdefault(actor_source.rsplit(".", 1)[-1], actor)

    # Резервный поиск по английскому имени нужен только для элементов, чей ID
    # изменился при миграции PF2e. Актёры всегда сопоставляются по UUID/ID.
    item_candidates_by_name: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for actor in source_actors:
        tr_items = {item.get("id"): item for item in translated_actors.get(actor["_id"], {}).get("items", [])}
        for item in actor.get("items", []):
            translated = tr_items.get(item["_id"])
            if translated:
                item_candidates_by_name.setdefault(item.get("name", ""), []).append((item, translated))

    entries: dict[str, Any] = {}
    metadata: dict[str, Any] = {"actors": {}, "technical": {}, "inlineRolls": {}, "html": {}}
    for actor in bestiary_actors:
        actor_id = actor["_id"]
        representative = source_by_pack_id.get(actor_id)
        if representative is None:
            raise ValueError(f"В Adventure нет актёра из pf2e.rusthenge-bestiary: {actor_id}")
        representative_translation = translated_actors[representative["_id"]]
        entry: dict[str, Any] = {
            "name": representative_translation.get("name", translated_name(actor.get("name", "")))
        }
        for field, path in BESTIARY_ACTOR_FIELD_PATHS.items():
            source_value = nested_value(actor, path)
            translated_value = representative_translation.get(field)
            if isinstance(source_value, str) and source_value and isinstance(translated_value, str) and translated_value:
                current_override = BESTIARY_ACTOR_FIELD_OVERRIDES.get((actor_id, field))
                if current_override is not None:
                    if html_tags(current_override) != html_tags(source_value):
                        raise ValueError(f"{actor_id}/{field}: ручной перевод изменил HTML-структуру")
                    rebased = current_override
                else:
                    rebased = rebase_technical_markup(translated_value, source_value)
                if rebased is None:
                    continue
                entry[field] = rebased
                key = f"{actor_id}/{field}"
                metadata["technical"][key] = TECH_RE.findall(source_value)
                metadata["inlineRolls"][key] = INLINE_ROLL_RE.findall(source_value)
                metadata["html"][key] = hashlib.sha256("\n".join(html_tags(source_value)).encode()).hexdigest()

        representative_items = {item["_id"]: item for item in representative.get("items", [])}
        representative_item_translations = {
            item.get("id"): item for item in representative_translation.get("items", [])
        }
        item_entries: list[dict[str, Any]] = []
        for item in actor.get("items", []):
            source_candidate = representative_items.get(item["_id"])
            translated_candidate = representative_item_translations.get(item["_id"])
            if translated_candidate is None:
                for candidate_source, candidate_translation in item_candidates_by_name.get(item.get("name", ""), []):
                    source_candidate, translated_candidate = candidate_source, candidate_translation
                    break
            item_entry: dict[str, Any] = {"id": item["_id"]}
            canonical_name = (
                (translated_candidate or {}).get("name")
                or LINKED_ITEM_NAMES.get(item.get("name", ""))
                or pf2e_ru_names.get(item.get("name", ""))
                or translated_name(item.get("name", ""))
            )
            if canonical_name == item.get("name") and re.search(r"[A-Za-z]", canonical_name):
                raise ValueError(f"Нет перевода имени элемента бестиария: {canonical_name!r}")
            item_entry["name"] = canonical_name

            current_description = nested_value(item, ("system", "description", "value"))
            special_description = translated_disease_description(item, pf2e_ru_names)
            current_override = BESTIARY_DESCRIPTION_OVERRIDES.get(item["_id"])
            if current_override:
                if html_tags(current_override) != html_tags(current_description):
                    raise ValueError(f"{actor_id}/{item['_id']}: ручной перевод изменил HTML-структуру")
                if technical_cores(current_override) != technical_cores(current_description):
                    raise ValueError(f"{actor_id}/{item['_id']}: ручной перевод изменил технические токены")
                if inline_roll_cores(current_override) != inline_roll_cores(current_description):
                    raise ValueError(f"{actor_id}/{item['_id']}: ручной перевод изменил встроенные броски")
                item_entry["description"] = current_override
            elif special_description:
                item_entry["description"] = special_description
            elif translated_candidate and source_candidate:
                candidate_source_description = nested_value(source_candidate, ("system", "description", "value"))
                candidate_translation = translated_candidate.get("description")
                if (
                    isinstance(current_description, str) and current_description
                    and isinstance(candidate_translation, str) and candidate_translation
                ):
                    rebased = rebase_technical_markup(candidate_translation, current_description)
                    if rebased is not None:
                        item_entry["description"] = rebased

            for field, source_key in (("description", "value"), ("gm", "gm")):
                source_value = nested_value(item, ("system", "description", source_key))
                translated_value = item_entry.get(field)
                if not isinstance(source_value, str) or not source_value or not isinstance(translated_value, str):
                    continue
                if html_tags(source_value) != html_tags(translated_value):
                    raise ValueError(f"{actor_id}/{item['_id']}/{field}: изменена HTML-структура")
                key = f"{actor_id}/items/{item['_id']}/{field}"
                metadata["technical"][key] = TECH_RE.findall(source_value)
                metadata["inlineRolls"][key] = INLINE_ROLL_RE.findall(source_value)
                metadata["html"][key] = hashlib.sha256("\n".join(html_tags(source_value)).encode()).hexdigest()
            item_entries.append(item_entry)
        entry["items"] = item_entries
        entries[actor_id] = entry
        metadata["actors"][actor_id] = {
            "sourceName": actor.get("name", ""),
            "itemIds": [item["_id"] for item in actor.get("items", [])],
        }

    metadata["actorCount"] = len(entries)
    metadata["itemCount"] = sum(len(entry["items"]) for entry in entries.values())
    return {
        "label": "Растхендж — бестиарий",
        "mapping": BESTIARY_MAPPING,
        "entries": entries,
    }, metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--pdf", type=Path, help="Локальный PDF для проверки источника; не копируется")
    parser.add_argument("--pf2e-ru", type=Path, help="Каталог data/community/pf2e/packs модуля pf2e-ru")
    parser.add_argument("--output", type=Path, default=Path("translations/pf2e-rusthenge.adventures.json"))
    parser.add_argument("--index", type=Path, default=Path("data/source-index.json"))
    parser.add_argument("--bestiary", type=Path, help="JSON-массив актёров пака pf2e.rusthenge-bestiary")
    parser.add_argument(
        "--bestiary-output",
        type=Path,
        default=Path("translations/pf2e.rusthenge-bestiary.json"),
    )
    parser.add_argument("--repair-existing", action="store_true", help="Восстановить только известные пустые action-карточки")
    parser.add_argument("--cleanup-layout", action="store_true", help="Удалить печатные артефакты из журналов")
    parser.add_argument("--build-bestiary", action="store_true", help="Собрать перевод исходного бестиария PF2e")
    parser.add_argument(
        "--complete-existing",
        action="store_true",
        help="Дозаполнить актёров, опасности и предметы в существующем переводе",
    )
    args = parser.parse_args()
    source = load_adventure(args.source)
    if args.cleanup_layout:
        translation = json.loads(args.output.read_text(encoding="utf-8"))
        changed = cleanup_digital_layout(translation)
        args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Очищено страниц: {changed}")
        return
    if args.build_bestiary:
        if args.pf2e_ru is None or args.bestiary is None:
            parser.error("для --build-bestiary нужны --pf2e-ru и --bestiary")
        translation = json.loads(args.output.read_text(encoding="utf-8"))
        index = json.loads(args.index.read_text(encoding="utf-8"))
        bestiary_source = json.loads(args.bestiary.read_text(encoding="utf-8"))
        if not isinstance(bestiary_source, list):
            raise ValueError("--bestiary должен содержать JSON-массив актёров")
        bestiary_translation, metadata = build_bestiary_translation(
            source, translation, bestiary_source, load_pf2e_ru_names(args.pf2e_ru)
        )
        index["bestiary"] = metadata
        index.setdefault("expected", {}).update({
            "bestiaryActors": metadata["actorCount"],
            "bestiaryEmbeddedItems": metadata["itemCount"],
        })
        args.bestiary_output.parent.mkdir(parents=True, exist_ok=True)
        args.bestiary_output.write_text(
            json.dumps(bestiary_translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Собран бестиарий: {metadata['actorCount']} актёров, {metadata['itemCount']} элементов")
        return
    if args.repair_existing:
        translation = json.loads(args.output.read_text(encoding="utf-8"))
        repaired = repair_existing_action_cards(source, translation)
        args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Восстановлено action-карточек: {repaired}")
        return
    if args.complete_existing:
        if args.pf2e_ru is None:
            parser.error("для --complete-existing нужен --pf2e-ru")
        translation = json.loads(args.output.read_text(encoding="utf-8"))
        index = json.loads(args.index.read_text(encoding="utf-8"))
        counts = complete_existing_translation(source, translation, index, load_pf2e_ru_names(args.pf2e_ru))
        cleanup_digital_layout(translation)
        args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        return
    if args.reference is None or args.pdf is None or args.pf2e_ru is None:
        parser.error("для полной генерации нужны --reference, --pdf и --pf2e-ru")
    if not args.pdf.is_file() or args.pdf.read_bytes()[:4] != b"%PDF":
        raise SystemExit(f"Не найден корректный PDF: {args.pdf}")
    translation, index = make_translation(
        source,
        load_adventure(args.reference),
        extract_pdf_pages(args.pdf),
        load_pf2e_ru_actor_lore(args.pf2e_ru),
        load_pf2e_ru_names(args.pf2e_ru),
    )
    cleanup_digital_layout(translation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(index["expected"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
