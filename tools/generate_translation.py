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
    IMAGE_ATTRIBUTE_TRANSLATIONS,
    LINK_LABELS,
    LINKED_ITEM_NAMES,
    RULE_LABELS,
    SCENE_TEXT_TRANSLATIONS,
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
VISIBLE_ATTRIBUTE_RE = re.compile(r'\b(alt|title)="([^"]*)"', re.I)
INLINE_ROLL_RE = re.compile(r"\[\[/[a-z]+\s+(?:[^\[\]]|\[[^\[\]]*\])*\]\](?:\{[^{}]*\})?", re.I)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def inline_roll_cores(value: str) -> list[str]:
    return [re.sub(r"\{[^{}]*\}$", "", roll) for roll in INLINE_ROLL_RE.findall(value)]


def document_values(value: Any) -> list[dict[str, Any]]:
    """Нормализует коллекцию документов Foundry из массива или объекта по ID."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []

# Коды локаций в старом структурированном тексте имели кириллический сдвиг.
# Эта таблица нужна только для поиска фрагментов в старом русском источнике.
# В готовом цифровом модуле обозначения всегда возвращаются к латинским A–F,
# как на картах и в официальном Adventure.
AREA_PREFIX = {"A": "А", "B": "Б", "C": "В", "D": "Г", "E": "Д", "F": "Е"}
CYRILLIC_AREA_RE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])([АБВГДЕ])(\d{1,2})([a-bA-Bа-бА-Б]?)(?![A-Za-zА-Яа-яЁё0-9])"
)
LATIN_AREA_PREFIX = {"А": "A", "Б": "B", "В": "C", "Г": "D", "Д": "E", "Е": "F"}
LATIN_AREA_SUFFIX = {"а": "a", "б": "b", "А": "a", "Б": "b", "A": "a", "B": "b", "a": "a", "b": "b"}


def restore_latin_area_codes(value: str) -> str:
    """Возвращает печатные кириллические коды областей к обозначениям карт A–F."""

    def replacement(match: re.Match[str]) -> str:
        prefix, number, suffix = match.groups()
        normalized_suffix = LATIN_AREA_SUFFIX.get(suffix, "")
        return f"{LATIN_AREA_PREFIX[prefix]}{int(number)}{normalized_suffix}"

    return CYRILLIC_AREA_RE.sub(replacement, value)


def normalize_area_codes_tree(value: Any) -> Any:
    if isinstance(value, str):
        return restore_latin_area_codes(value)
    if isinstance(value, list):
        return [normalize_area_codes_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_area_codes_tree(item) for key, item in value.items()}
    return value

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
    "07elderanlorgo00": "Старейшина Анлоргог",
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
    "East Weapon Racks": "Восточные стойки с оружием", "West Arrows": "Стрелы на западе",
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

# Полные описания для элементов, в которых старая PDF-конверсия отделила
# Foundry-команды от слов, к которым они относятся. HTML и команды повторяют
# официальный документ; формулировки правил сверены с pf2e-ru.
ITEM_DESCRIPTION_REPAIRS = {
    "CNpPqhgSIEamhwFL": '<p>Любой враг @UUID[Compendium.pf2e.conditionitems.Item.AJh5ex99aV6VTggg]{застигнут врасплох} для атак ближнего боя адепта Ржавчины, как при взятии в тиски, пока он находится в пределах досягаемости адепта и одного из его союзников.</p>',
    "T8jQXV4jxIhvfS14": '<p><strong>Требования</strong> Деро-сталкер не @UUID[Compendium.pf2e.conditionitems.Item.D5mg6Tc7Jzrj6ro7]{перегружен}.</p>\n<p><strong>Триггер</strong> Существо выбирает деро целью атаки, и деро видит атакующего.</p>\n<hr />\n<p><strong>Эффект</strong> Деро ловко уклоняется и получает бонус обстоятельства +2 к КБ против спровоцировавшей атаки.</p>',
    "zMkrKhyfRWFrFfuv": '<p><strong>Требования</strong> Культист получил урон, не @UUID[Compendium.pf2e.conditionitems.Item.HL2l2VRSaQHu9lUw]{утомлён} и ещё не находится в безумии</p>\n<hr />\n<p><strong>Эффект</strong> Культист впадает в безумие на 1 минуту. В безумии он получает бонус состояния +1 к броскам атак и +2 к броскам урона, а также штраф состояния –2 к КБ. Культист не может добровольно прекратить безумие. После его окончания культист становится @UUID[Compendium.pf2e.conditionitems.Item.HL2l2VRSaQHu9lUw]{утомлён}.</p>\n<p>@UUID[Compendium.pf2e.bestiary-effects.Item.3Wtzyb0ZgkaC7vHY]{Эффект: фанатичное безумие}</p>',
    "MpNlJrdPvv9bECNE": '<p>Существо, по которому порождение греха попало челюстями, должно совершить @Check[type:will|dc:18]{спасбросок Воли СЛ 18}, поскольку его одолевают греховные мысли.</p>\n<hr />\n<p><strong>Критический успех</strong> Существо не получает эффекта.</p>\n<p><strong>Успех</strong> Существо становится @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 1}.</p>\n<p><strong>Провал</strong> Существо становится @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 2}.</p>\n<p><strong>Критический провал</strong> Существо становится тошнота 2 и @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{ослаблено 2} на 1 минуту.</p>',
    "KjLaF8NJBaPjsRAz": '<p><strong>Требования</strong> Предыдущим действием отрубленной головы был Удар челюстями, нанёсший цели урон.</p>\n<hr />\n<p><strong>Эффект</strong> Отрубленная голова наносит второй Удар челюстями, яростно трясясь и пытаясь вырвать кусок плоти. При успехе цель получает дополнительно 1d4 рубящего урона и 1 продолжительного урона кровотечением, а также подвергается воздействию ползучей ржавчины.</p>',
    "xcV4iG9yR2uKSGdL": '<p><strong>Триггер</strong> Существо открывает дверь, не произнеся перед этим молитву Ксар-Азмаку</p>\n<hr />\n<p><strong>Эффект</strong> В открытом дверном проёме возникает множество ржавых шипов, которые устремляются в область <strong>Д1</strong>. Шипы изгибаются в воздухе, преследуя цели: все существа в области <strong>Д1</strong> должны совершить @Check[type:reflex|dc:20|traits:damaging-effect]{спасбросок Реакции СЛ 20}.</p>\n<hr />\n<p><strong>Критический успех</strong> Существо уклоняется от шипов и не получает урона.</p>\n<p><strong>Успех</strong> Шип задевает существо, нанося @Damage[2d10[piercing]] колющего урона.</p>\n<p><strong>Провал</strong> Шип пронзает существо, нанося @Damage[(2d10+13)[piercing]] колющего урона.</p>\n<p><strong>Критический провал</strong> Как провал, но существо также подвергается воздействию столбняка.</p>',
    "a5X5gNKg3MIEGsZ9": '<p><strong>Триггер</strong> Существо наступает на нажимную плиту</p>\n<hr />\n<p><strong>Эффект</strong> Шипы выскакивают из пола и наносят Удар всем существам в коридоре. Пол становится особо трудной местностью.</p>',
    "80CuEcGtDQ6fUIyY": '<p><strong>Триггер</strong> Болотный мудрец или один из его союзников в пределах 60 футов совершает спасбросок против слухового или звукового эффекта.</p>\n<hr />\n<p><strong>Эффект</strong> Болотный мудрец издаёт кваканье, заглушающее другие звуки, и совершает @Check[type:performance]{проверку Выступления}. Он и союзные боггарды в области могут использовать против слухового или звукового эффекта более высокий результат: свой спасбросок или проверку Выступления мудреца.</p>',
    "xBIoPO0Yl00JwtXW": '<p>Болотный мудрец игнорирует трудную местность, созданную особенностями болот.</p>',
    "Kv1pkf5Ma30A8n58": '<p>Цитнигот полностью раскрывает свой ужасающий облик. Существа в @Template[type:emanation|distance:10]{10-футовой эманации} должны совершить @Check[type:will|dc:20]{спасбросок Воли СЛ 20}. После этого существо получает временный иммунитет к «Мерзкому зрелищу» на 1 минуту.</p>\n<hr />\n<p><strong>Критический успех</strong> Существо не получает эффекта.</p>\n<p><strong>Успех</strong> Существо @UUID[Compendium.pf2e.conditionitems.Item.AJh5ex99aV6VTggg]{застигнуто врасплох} до начала своего следующего хода.</p>\n<p><strong>Провал</strong> Существо становится @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 1} и застигнуто врасплох, пока испытывает тошноту.</p>\n<p><strong>Критический провал</strong> Существо становится @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 2} и застигнуто врасплох, пока испытывает тошноту.</p>',
    "5gY8gk28J2srHl1t": '<p>Эсипил перемещается с Материального плана на Эфирный или наоборот, получая эффекты <em>@UUID[Compendium.pf2e.spells-srd.Item.D2nPKbIS67m9199U]{Эфирной прогулки}</em>, но с неограниченной продолжительностью и возможностью Отклонить эффект.</p>\n<p>Призванный эсипил не может использовать «Переход между планами».</p>',
    "y7VNs5A41UH94zX1": '<p><strong>Триггер</strong> Древний аппарат получает урон или проваливается попытка Отключить его</p>\n<hr />\n<p><strong>Эффект</strong> Древний аппарат начинает быстрее скрежетать и вращаться. Тихое тиканье перерастает в диссонансное жужжание, а вся конструкция озаряется тревожным светом цвета ржавчины. Все живые существа в области <strong>Г3</strong> ощущают во рту привкус ржавчины и должны успешно пройти @Check[type:fortitude|dc:18]{спасбросок Стойкости СЛ 18}, иначе становятся @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 1}. Затем древний аппарат совершает проверку инициативы.</p>',
    "3wLOdV2RXEY5pnF5": '<p>Когда абрикандил попадает по существу Ударом челюстями, цель должна успешно пройти @Check[type:fortitude|dc:21]{спасбросок Стойкости СЛ 21}, иначе получает уродующие раны.</p>\n<p>Существо получает штраф состояния –1 к проверкам на основе Харизмы. Этот штраф складывается до –3 и сохраняется даже после исцеления ран.</p>\n<p>Штраф уменьшается на 1 каждые 24 часа, пока не достигнет 0.</p>\n<p>@UUID[Compendium.pf2e.bestiary-effects.Item.LgZx5xotO08JzhVc]{Эффект: увечащий укус}</p>',
    "D2ezhwANZLcMNbz9": '<p><strong>Триггер</strong> ОЗ рифокогтя снижаются до 0.</p>\n<hr />\n<p><strong>Эффект</strong> Перед смертью рифокоготь наносит Удар клешнёй.</p>',
    "K8HY6MgNzIvDLuDT": '<p>Остовиты строят и населяют подвижные оболочки из костей. Базовые параметры остовита, особенно его иммунитеты, предполагают, что он находится внутри костяной колесницы. Она разрушается, когда у остовита остаётся меньше половины ОЗ, или сразу после получения урона от критического попадания. Урон, способный воздействовать непосредственно на управляющего колесницей остовита (например, заклинание <em>взрыв духа</em>), не разрушает колесницу и обходит его иммунитеты.</p>\n<p>Без костяной колесницы остовит теряет иммунитеты и Удар костяным шипом и становится Крошечного размера. Он также получает слабость 5 к ментальному и физическому урону, а также к урону с признаком «святой». Для создания новой колесницы нужен скелет существа Маленького или большего размера и 10 минут. Обычно остовит в колеснице имеет Маленький размер, но возможны и более крупные конструкции, особенно если несколько остовитов работают вместе.</p>',
    "uMNXrK8Is6PAzNEB": '<p><strong>Триггер</strong> Костяная колесница остовита уничтожена</p>\n<hr />\n<p><strong>Эффект</strong> Остовит внутри неё выполняет Шаг или Перемещение.</p>',
}

ITEM_DESCRIPTION_REPAIRS.update({
    "0rwXFzCG58mrENRi": '<p><strong>Триггер</strong> Существо, не поклоняющееся Ксар-Азмаку, пытается открыть дверь или наносит ей урон Ударом ближнего боя</p>\n<hr />\n<p><strong>Эффект</strong> Спровоцировавшее существо подвергается воздействию ползучей ржавчины: из ржавых пятен на двери выползают усики ржаво-красной энергии и странно нежно скребут открытую кожу.</p>\n<hr />\n<p>У заражённых ползучей ржавчиной на теле появляются болезненные ржаво-коричневые синяки, а всё тело болит, словно после долгой тренировки. По мере развития болезни тело, одежда и переносимые предметы всё сильнее разрушаются, пока не наступает мучительная смерть. Персонаж, успешно сопротивлявшийся заражению или излечившийся от ползучей ржавчины, получает временный иммунитет к новым заражениям на 24 часа.</p>\n<p><strong>Спасбросок</strong> @Check[type:fortitude|dc:15|traits:disease,divine,transmutation]{Стойкость СЛ 15}</p>\n<p><strong>Стадия 1</strong> штраф состояния –1 к проверкам Атлетики (1 день)</p>\n<p><strong>Стадия 2</strong> как стадия 1 (1 день)</p>\n<p><strong>Стадия 3</strong> @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{ослаблен 1} (1 день)</p>\n<p><strong>Стадия 4</strong> ослаблен 1 и @UUID[Compendium.pf2e.conditionitems.Item.e1XGnhKNSQIm5IXg]{одурманен 1}; все переносимые доспехи, одежда и предметы с уровнем не выше уровня болезни получают состояние «сломано» (1 день; предметы остаются сломанными)</p>\n<p><strong>Стадия 5</strong> @UUID[Compendium.pf2e.conditionitems.Item.fBnFDH2MTzgFijKf]{без сознания} (1 день)</p>\n<p><strong>Стадия 6</strong> без сознания (1 день)</p>\n<p><strong>Стадия 7</strong> смерть</p>',
    "rsf1q6ooMNJFjdfh": '<p>У акаты нет слуха. Она невосприимчива к слуховым эффектам, автоматически получает критический провал проверок Внимания, требующих слуха, и штраф состояния –2 к проверкам Внимания, которые связаны со звуком, но также опираются на другие чувства. На броски инициативы этот штраф не действует.</p>',
    "D13sjvjuSrxFEe35": '<p>Аката не дышит и невосприимчива к эффектам, для которых требуется дыхание, например к вдыхаемым ядам.</p>',
    "9yu44cM7W0Xg2Q36": '<p>Все просители формируются из природы плана, на котором воплощаются, и олицетворяют её; их параметры изменяются, как указано ниже. Они также получают все признаки существ своего плана.</p>\n<p><strong>Бездна</strong> Личинки выглядят как червеобразные существа с лицами, которые просители имели при жизни.</p>\n<ul>\n<li><strong>Мировоззрение</strong> ХЗ;</li>\n<li><strong>Язык</strong> Бездны;</li>\n<li><strong>Дополнительная способность</strong> иммунитет к болезням и ядам;</li>\n<li><strong>Ближний бой</strong> челюсти +7, <strong>Урон</strong> 1d8+2 колющего урона</li>\n</ul>',
    "ZDJkjnIor7qxsiSU": '<p><strong>Требования</strong> У деро две свободные руки либо аклис и одна свободная рука</p>\n<hr />\n<p><strong>Эффект</strong> Деро совершает @Check[type:athletics|traits:action:grapple,action:strangle]{проверку Атлетики}, чтобы @UUID[Compendium.pf2e.actionspf2e.Item.PMbdMWc2QroouFGD]{Схватить} существо, с бонусом обстоятельства +2. При успехе цель также получает @Damage[(1d6+6)[bludgeoning]] дробящего урона, а при критическом успехе — вдвое больше.</p>',
    "PFa0h9BekFPB4Eoh": '<p><strong>Триггер</strong> Существо проходит под клеткой и наступает на нажимную плиту</p>\n<hr />\n<p><strong>Эффект</strong> Клетка падает с потолка, пытаясь поймать спровоцировавшее существо; оно должно совершить @Check[type:reflex|dc:17|traits:damaging-effect]{спасбросок Реакции СЛ 17}.</p>\n<hr />\n<p><strong>Критический успех</strong> Существо избегает ловушки и возвращается в пространство, которое только что покинуло, вместо того чтобы войти в пространство ловушки.</p>\n<p><strong>Успех</strong> Как критический успех, но падающая ловушка задевает существо и наносит ему @Damage[(1d6+3)[bludgeoning]] дробящего урона, когда оно отшатывается.</p>\n<p><strong>Провал</strong> Падающая клетка накрывает спровоцировавшее существо. Существо среднего размера или меньше оказывается заперто внутри (@UUID[Compendium.pf2e.actionspf2e.Item.SkZAQRkLLkmBQNB9]{Вырваться}, СЛ 20). Существо большого размера или больше получает @Damage[(2d6+5)[bludgeoning]] дробящего урона и падает @UUID[Compendium.pf2e.conditionitems.Item.j91X7x0XSomq8d60]{ничком}, а клетка отскакивает от его тела и разрушается.</p>\n<p><strong>Критический провал</strong> Как провал, но существо среднего размера или меньше также получает удар клеткой, падает ничком, получает @Damage[(2d6+5)[bludgeoning]] дробящего урона и становится @UUID[Compendium.pf2e.conditionitems.Item.eIcWbB5o3pP6OIMe]{обездвижено}, поскольку клетка придавливает его конечность.</p>',
    "v90WRjELLiKF57vr": '<p><strong>Требования</strong> У зомби есть @UUID[Compendium.pf2e.conditionitems.Item.kWc1fhmv9LBiTuei]{схваченное} или @UUID[Compendium.pf2e.conditionitems.Item.VcDeM8A5oI6VqhbM]{сдерживаемое} существо.</p>',
    "MuiyXm8KyQF57NaW": '<p><strong>Требования</strong> У зомби есть @UUID[Compendium.pf2e.conditionitems.Item.kWc1fhmv9LBiTuei]{схваченное} или @UUID[Compendium.pf2e.conditionitems.Item.VcDeM8A5oI6VqhbM]{сдерживаемое} существо.</p>',
    "8LvVStEHJB30KVCE": '<p>Боггард-разведчик издаёт ужасающее кваканье. Любое существо в @Template[type:emanation|distance:30]{30-футовой эманации}, не являющееся боггардом, становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испугано 1}, если не преуспеет в @Check[type:will|dc:17]{спасброске Воли СЛ 17}.</p>\n<p>При критическом успехе существо получает временный иммунитет на 1 минуту.</p>',
    "z8bl09rqF4yCJDy4": '<p>Болотный мудрец издаёт ужасающее кваканье. Любое существо в @Template[type:emanation|distance:30]{30-футовой эманации}, не являющееся боггардом, становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испугано 1}, если не преуспеет в @Check[type:will|dc:19]{спасброске Воли СЛ 19}.</p>\n<p>При критическом успехе существо получает временный иммунитет на 1 минуту.</p>',
    "up8Xcig2FrwgbFfb": '<p>Боггард-воин издаёт ужасающее кваканье. Любое существо в @Template[type:emanation|distance:30]{30-футовой эманации}, не являющееся боггардом, становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испугано 1}, если не преуспеет в @Check[type:will|dc:18]{спасброске Воли СЛ 18}.</p>\n<p>При критическом успехе существо получает временный иммунитет на 1 минуту.</p>',
    "kGQg9F0ZgW7fp4DB": '<p>Если боггард-разведчик попадает по существу языком, цель становится @UUID[Compendium.pf2e.conditionitems.Item.kWc1fhmv9LBiTuei]{схвачена} боггардом. В отличие от обычного захвата, существо не @UUID[Compendium.pf2e.conditionitems.Item.eIcWbB5o3pP6OIMe]{обездвижено}, но не может выйти за пределы досягаемости языка.</p>\n<p>Язык можно отсечь, попав по КБ 13 и нанеся не менее 2 рубящего урона. Боггард не получает этот урон, но теряет возможность наносить Удары языком, пока тот не отрастёт через неделю.</p>',
    "A33mGw1DCgRJRDSe": '<p>Если болотный мудрец попадает по существу языком, цель становится @UUID[Compendium.pf2e.conditionitems.Item.kWc1fhmv9LBiTuei]{схвачена} боггардом. В отличие от обычного захвата, существо не @UUID[Compendium.pf2e.conditionitems.Item.eIcWbB5o3pP6OIMe]{обездвижено}, но не может выйти за пределы досягаемости языка.</p>\n<p>Язык можно отсечь, попав по КБ 15 и нанеся не менее 4 рубящего урона. Боггард не получает этот урон, но теряет возможность наносить Удары языком, пока тот не отрастёт через неделю.</p>',
    "MEAPfylvHHHbTqOf": '<p>Если боггард-воин попадает по существу языком, цель становится @UUID[Compendium.pf2e.conditionitems.Item.kWc1fhmv9LBiTuei]{схвачена} боггардом. В отличие от обычного захвата, существо не @UUID[Compendium.pf2e.conditionitems.Item.eIcWbB5o3pP6OIMe]{обездвижено}, но не может выйти за пределы досягаемости языка.</p>\n<p>Язык можно отсечь, попав по КБ 15 и нанеся не менее 3 рубящего урона. Боггард не получает этот урон, но теряет возможность наносить Удары языком, пока тот не отрастёт через неделю.</p>',
    "mdEZdShzE63nlTQK": '<p>Солёная вода действует на личинку акаты внутри пустотного зомби как чрезвычайно сильная кислота. Полное погружение в солёную воду наносит @Damage[4d6[acid]] урона за раунд. В любой раунд, когда зомби получает урон из-за слабости к солёной воде, личинка отступает в глубины его тела, из-за чего зомби становится @UUID[Compendium.pf2e.conditionitems.Item.xYTAsEpcJE1Ccni3]{замедлен 1} до конца своего следующего хода.</p>',
    "PIjZTZsbQlriq5X3": '<p><strong>Спасбросок</strong> @Check[type:fortitude|dc:14]{Стойкость СЛ 14}</p>\n<hr />\n<p><strong>Максимальная продолжительность</strong> 6 раундов</p>\n<p><strong>Стадия 1</strong> @Damage[1d6[poison]] урона ядом (1 раунд)</p>\n<p><strong>Стадия 2</strong> @Damage[1d8[poison]] урона ядом и @UUID[Compendium.pf2e.conditionitems.Item.AJh5ex99aV6VTggg]{застигнут врасплох} (1 раунд)</p>\n<p><strong>Стадия 3</strong> @Damage[1d12[poison]] урона ядом, @UUID[Compendium.pf2e.conditionitems.Item.i3OJZU2nk64Df3xm]{неуклюжесть 1} и застигнут врасплох (1 раунд)</p>',
    "We6LladGR4C687q0": '<p><strong>Спасбросок</strong> @Check[type:fortitude|dc:17]{Стойкость СЛ 17}</p>\n<hr />\n<p><strong>Максимальная продолжительность</strong> 4 раунда</p>\n<p><strong>Стадия 1</strong> @Damage[1d6[poison]] урона ядом и @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{ослаблен 1} (1 раунд)</p>\n<p><strong>Стадия 2</strong> @Damage[1d6[poison]] урона ядом и @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{ослаблен 2} (1 раунд)</p>',
    "fzTUnlrMpxSgmSAy": '<p><strong>Требования</strong> В этом ходу влориак проржавил языком металлический предмет</p>\n<hr />\n<p><strong>Эффект</strong> Влориак наносит Удар языком по той же цели. При попадании он не наносит урона, а слизывает ржавчину и восстанавливает [[/r 2d6[healing]]]{2d6 ОЗ} (или [[/r 4d6[healing]]]{4d6 ОЗ} при критическом попадании). В следующем ходу он не может снова Слизать ржавчину.</p>',
    "TZig28UcpE4GS2P0": '<p>Слюна влориака заставляет металл стремительно ржаветь. При успешном Ударе языком или попытке @UUID[Compendium.pf2e.actionspf2e.Item.Dt6B1slsBy8ipJu9]{Разоружить} влориак наносит @Damage[2d6[untyped]] урона металлическому предмету, который цель носит или держит (вдвое больше при критическом попадании), игнорируя его Твёрдость. Бесхозный металлический предмет получает этот урон автоматически. Если существо применяет реакцию Блок щитом с металлическим щитом против атаки языком, щит автоматически ломается, но другие предметы от этой атаки не ржавеют.</p>',
    "hAK9kJGhzP6DASJX": '<p>При критическом попадании Ударом заточенной шестернёй заводная змея-шпион также наносит @Damage[1d4[persistent,bleed]] продолжительного урона кровотечением; успешный @Check[type:fortitude|dc:17]{спасбросок Стойкости СЛ 17} отменяет дополнительное кровотечение.</p>',
    "36QKwrAooz1cygR4": '<p><strong>Частота</strong> раз в раунд</p>\n<hr />\n<p><strong>Эффект</strong> Заокс пристально смотрит на существо, которое видит в пределах 30 футов. Цель становится @UUID[Compendium.pf2e.conditionitems.Item.TkIyaNPgTZFBCCuh]{ослеплена} на 1 раунд и должна успешно пройти @Check[type:will|dc:21]{спасбросок Воли СЛ 21}, иначе становится @UUID[Compendium.pf2e.conditionitems.Item.e1XGnhKNSQIm5IXg]{одурманена 1} на 1 раунд.</p>',
    "rmbTeX3cdnck9oQ2": '<p>Кнурр наносит Удар ближнего боя, выкрикивая имя Ксар-Азмака. Если он попадает и наносит урон, цель становится @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испугана 1}, а при критическом попадании — @UUID[Compendium.pf2e.conditionitems.Item.TBSHQspnbcqxsmjL]{испугана 2}.</p>',
    "lL49wJa4ig4V0ag1": '<p>Заводная змея-шпион записывает все звуки в @Template[type:emanation|distance:25]{25-футовой эманации} на маленький самоцвет стоимостью 1 зм, встроенный в её тело. На один самоцвет можно записать до 1 часа звука. Начав запись, шпион не может остановить её досрочно или записать что-либо на самоцвет, где уже есть запись.</p>\n<p>Некоторые заводные шпионы содержат несколько самоцветов и могут сделать серию записей. Поскольку они неразумны, им нужно дать простые указания, когда начинать запись. Заводной шпион различает виды существ, но не отдельных личностей.</p>\n<p>Шпион может одним действием начать или остановить воспроизведение записи. Чтобы извлечь или установить самоцвет, нужно успешно пройти @Check[type:thievery|dc:14|traits:action:disable-a-device]{проверку Воровства СЛ 14} для действия @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключить устройство}. При провале самоцвет не повреждается, но запись стирается, и самоцвет по-прежнему нельзя использовать для новой записи.</p>',
    "zdb8RR0jcIIol6on": '<p>24 часа, @Check[type:thievery|dc:17|traits:action:disable-a-device]{Воровство СЛ 17}, режим ожидания</p>\n<hr />\n<p>Чтобы заводной механизм мог действовать, другое существо должно завести его уникальным ключом; это занимает 1 минуту. После завода механизм работает указанное время, обычно 24 часа, затем перестаёт воспринимать окружение и не может действовать, пока его не заведут снова. Некоторые способности расходуют оставшееся рабочее время. Механизм не может потратить больше времени, чем у него есть, и немедленно отключается, когда время заканчивается. Если неизвестно, когда его заводили в последний раз, считается, что смотритель заводит механизмы в установленное время, обычно в 8 утра.</p>\n<p>Механизм с режимом ожидания может перейти в него активностью за 3 действия. В этом режиме рабочее время не уменьшается, механизм воспринимает окружение со штрафом –2 к Восприятию и не может действовать, кроме одного случая: заметив существо, он может реакцией выйти из режима ожидания и при необходимости бросить инициативу.</p>\n<p>Существо может попытаться выполнить @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключение устройства}, чтобы постепенно остановить механизм. При каждом успехе механизм теряет 1 час рабочего времени. Это можно делать и в режиме ожидания.</p>',
    "edVyMro5viX5rgD9": '<p>24 часа, @Check[type:thievery|dc:21|traits:action:disable-a-device]{Воровство СЛ 21}, режим ожидания</p>\n<hr />\n<p>Чтобы заводной механизм мог действовать, другое существо должно завести его уникальным ключом; это занимает 1 минуту. После завода механизм работает указанное время, обычно 24 часа, затем перестаёт воспринимать окружение и не может действовать, пока его не заведут снова. Некоторые способности расходуют оставшееся рабочее время. Механизм не может потратить больше времени, чем у него есть, и немедленно отключается, когда время заканчивается. Если неизвестно, когда его заводили в последний раз, считается, что смотритель заводит механизмы в установленное время, обычно в 8 утра.</p>\n<p>Механизм с режимом ожидания может перейти в него активностью за 3 действия. В этом режиме рабочее время не уменьшается, механизм воспринимает окружение со штрафом –2 к Восприятию и не может действовать, кроме одного случая: заметив существо, он может реакцией выйти из режима ожидания и при необходимости бросить инициативу.</p>\n<p>Существо может попытаться выполнить @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключение устройства}, чтобы постепенно остановить механизм. При каждом успехе механизм теряет 1 час рабочего времени. Это можно делать и в режиме ожидания.</p>',
    "fH4zN6EufktPqbW4": '<p>Заводной маг использует механическую палочку как фокус для направления магической энергии. Палочка встроена в грудь мага, наружу выступает только кристалл на её конце. Маг может Взаимодействовать, чтобы извлечь палочку; другое существо может сделать это, успешно пройдя @Check[type:thievery|dc:25|traits:action:disable-a-device]{проверку Воровства СЛ 25} для действия @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключить устройство}. Без палочки заводной маг может сотворять только чары.</p>\n<p>После извлечения заводная палочка становится <em>@UUID[Compendium.pf2e.equipment-srd.Item.vJZ49cgi8szuQXAD]{магической палочкой}</em>, содержащей последнее сотворённое заводным магом врождённое заклинание 1-го ранга (<em>@UUID[Compendium.pf2e.spells-srd.Item.4koZzrnMXhhosn0D]{Страх}</em>, если заводной Белимариус ещё не сотворял в этом приключении заклинаний 1-го ранга). Заклинания закладываются в палочку при создании мага; создатель может заменить их другими арканными заклинаниями соответствующего ранга.</p>',
    "UK9gsjbHYgmKZze9": '<p>Заводная змея-шпион должна использовать эту реакцию, если создатель не запрограммировал её иначе.</p>\n<p><strong>Триггер</strong> ОЗ заводной змеи-шпиона снижаются до 0.</p>\n<hr />\n<p><strong>Эффект</strong> Шпион мечется и издаёт металлический визг, за которым следует размеренное тиканье. В начале своего следующего предполагаемого хода он взрывается, нанося @Damage[1d12[piercing]] колющего урона в @Template[type:emanation|distance:5]{5-футовой эманации}; применяется @Check[type:reflex|dc:17|basic:true]{простой спасбросок Реакции СЛ 17}. Самоцвет и записанная на нём информация уничтожаются.</p>\n<p>Соседнее существо может остановить самоуничтожение, успешно выполнив @Check[type:thievery|dc:17|traits:action:disable-a-device]{проверку Воровства СЛ 17} для действия @UUID[Compendium.pf2e.actionspf2e.Item.cYdz2grcOcRt4jk6]{Отключить устройство}.</p>',
    "yf2VZtO2S4eV7fKZ": '<p><strong>Триггер</strong> Существо или другой тяжёлый объект, например поток воды из предыдущей ловушки, перемещается на покрытую гравием шкуру</p>\n<hr />\n<p><strong>Эффект</strong> Спровоцировавшее существо или объект падает в яму, получает урон от падения (@Damage[10[bludgeoning]] дробящего урона) и становится целью Удара шипа. Падающее существо может попытаться @UUID[Compendium.pf2e.actionspf2e.Item.3yoajuKjwHZ9ApUY]{Схватиться за уступ} с @Check[type:reflex|dc:20]{проверкой Реакции СЛ 20}; если в яму льётся бурлящая вода, СЛ повышается до @Check[type:reflex|dc:22]{22}.</p>',
    "8tVnSA2uTOLAmycM": '<p><strong>Триггер</strong> Существо входит в область к югу от отмеченного на карте кольца камней</p>\n<hr />\n<p><strong>Эффект</strong> Из кольца камней вырывается поток воды, с силой несётся по проходу и стекает в яму в области <strong>Е1б</strong>. Все существа Большого или меньшего размера на пути воды должны совершить @Check[type:fortitude|dc:20|traits:damaging-effect]{спасбросок Стойкости СЛ 20}. Достигнув дна ямы, вода мгновенно исчезает, но всё вокруг остаётся промокшим.</p>\n<hr />\n<p><strong>Критический успех</strong> Существо выдерживает напор и не получает эффекта.</p>\n<p><strong>Успех</strong> Поток ударяет существо о стену пещеры, нанося @Damage[1d10[bludgeoning]] дробящего урона.</p>\n<p><strong>Провал</strong> Поток сбивает существо @UUID[Compendium.pf2e.conditionitems.Item.j91X7x0XSomq8d60]{ничком}, наносит @Damage[(1d10+6)[bludgeoning]] дробящего урона и толкает к шипастой яме, активируя ловушку.</p>\n<p><strong>Критический провал</strong> Как провал, но при падении в шипастую яму существо не может попытаться @UUID[Compendium.pf2e.actionspf2e.Item.3yoajuKjwHZ9ApUY]{Схватиться за уступ}.</p>',
    "Y2DikEsO4R95MHFo": '<p>Когда грибной леший умирает, его тело взрывается первобытной энергией и восстанавливает [[/r 2d8[healing]]]{2d8 ОЗ} каждому грибковому существу в @Template[type:emanation|distance:30]{30-футовой эманации}. Область зарастает грибами и становится трудной местностью. Если окружение не подходит для этих грибов, они увядают через 24 часа.</p>',
    "LCFMKpxw0iDxWGXu": '<p>Грибной леший выпускает облако спор в @Template[type:emanation|distance:15]{15-футовой эманации}, раздражающее глаза и горло существ, не являющихся грибковыми. Каждое такое существо должно успешно пройти @Check[type:fortitude|dc:16|traits:damaging-effect]{спасбросок Стойкости СЛ 16}, иначе получает @Damage[1[persistent,poison]] продолжительного урона ядом. Пока продолжается этот урон, существо видит не дальше 20 футов, а при критическом провале — не дальше 10 футов.</p>',
})

ITEM_DESCRIPTION_REPAIRS.update({
    "UDhWMhJzdEJtykvO": '<p>Когда Ордви сотворяет исцеление, она бросает d10 вместо d8.</p>',
    "983mBG3qwmzQKGS2": '<p>Абрикандил ненавидит собственное отражение. Когда существо Взаимодействует с зеркалом в поле зрения демона-разрушителя, демон получает штраф –2 к спасброскам Воли против проверок Запугивания.</p>\n<p>Если абрикандил заканчивает ход рядом с зеркалом или его атакует существо с зеркалом, он получает @Damage[1d6[mental]] ментального урона; обычно после этого демон сосредоточивается на уничтожении ближайшего зеркала способностью «Крушить».</p>',
    "4cx1d9efogHuWe26": '<p>Абрикандил наносит два Удара когтями по бесхозному объекту или удерживаемому зеркалу. Удерживаемое зеркало использует КБ держащего его персонажа.</p>\n<p>Если оба Удара попадают, объедините их урон для преодоления Твёрдости или сопротивления.</p>\n<p>Эти Удары не учитываются при расчёте штрафа множественной атаки абрикандила, и штраф к ним не применяется.</p>',
    "p6uToNU7wgFDgDDH": '<p>В начале каждого хода дретча бросьте [[/br 1d4 #Actions Regained]]{1d4}. Результат равен числу действий, которые он восстанавливает в этот ход (максимум 3).</p>\n<p>Такие эффекты, как состояние @UUID[Compendium.pf2e.conditionitems.Item.xYTAsEpcJE1Ccni3]{замедлен}, могут дополнительно уменьшить число его действий.</p>',
    "h8caQJMnKj4F22zZ": '<p>Дретч наносит три Удара когтями по одному существу, каждый со штрафом –2. Штраф множественной атаки дретча не увеличивается, пока он не завершит все три атаки.</p>\n<p>До начала своего следующего хода дретч получает состояние @UUID[Compendium.pf2e.conditionitems.Item.i3OJZU2nk64Df3xm]{неуклюжесть 2}.</p>',
})

ACTOR_DESCRIPTION_REPAIRS = {
    "oeM8EcS1F5NIkd30": '<p>Самые распространённые скелеты-прислужники — простые стражи.</p>\n<hr>\n<p>Скелеты, созданные из костей, скреплённых нечестивой некромантией, относятся к самым распространённым видам нежити. Они обитают в старых подземельях и на забытых кладбищах.</p>',
    "viyUBIwO7gFRqwVG": '<p>Когда смертный умирает, его душа отправляется на Могильник во Внешних планах, где её судит Фаразма, богиня мёртвых. После суда душа получает окончательную награду или наказание и превращается в просителя. Она обретает новое тело, облик которого определяется господствующими философскими силами плана назначения. Воспоминания о прежней жизни почти полностью стираются, оставляя лишь туманные обрывки, похожие на полузабытые сны. Независимо от прежнего размера, силы и природы, в загробной жизни проситель становится существом Среднего размера.</p>\n<p>Проситель может существовать целые эоны, но это состояние не обязательно вечно. Божества, могущественные обитатели Великого Запределья и сами Внешние планы могут превратить его в чистую квинтэссенцию, расширяющую физическое воплощение плана, или в новую форму сверхъестественной жизни — небожителя, наблюдателя либо беса. После смерти тело просителя распадается, а его сущность возвращается к квинтэссенции или стихиям родного плана. Так завершается путь души: жизненная сущность возвращается в сердце Великого Запределья, чтобы вновь участвовать в создании новых душ.</p>\n<p>Личинки похожи на огромных червей с лицами, которые просители имели при жизни.</p>',
    "zj4VyFf9wYB6xO6S": '<p>Грибные лешие охраняют пещеры, болота и другие сырые тёмные места. Их грибные сады причудливы по обычным меркам, но сами лешие чрезвычайно гордятся своей работой.</p>\n<hr>\n<p>Лешие — разумные растительные существа, охраняющие уголки первозданной природы или земной силы. Первоначально их создавали могущественные феи; теперь леший появляется, когда искусный заклинатель первобытной магии, обычно друид, соединяет природного духа с тщательно выращенным телом из местной растительности. Обряды и материалы зависят от вида лешего. Обычно жизнь им дают в местах большой природной значимости: в роще древодрева, друидическом круге, кольце фей или возле великого чуда природы.</p>',
}

ACTOR_NAME_REPAIRS_BY_ID = {
    "CQ4xqipQ5pUpZcp7": "Восточные стойки с оружием",
    "a8mnFF6O9hewd4CH": "Стрелы на западе",
}


def repair_translated_item_descriptions(
    translation: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> int:
    """Возвращает команды Foundry в смысловые позиции внутри карточек."""
    roots = list(translation.get("entries", {}).values())
    actor_groups: list[dict[str, Any]] = []
    for root in roots:
        if isinstance(root, dict) and isinstance(root.get("actors"), dict):
            actor_groups.append(root["actors"])
        elif isinstance(root, dict) and "items" in root:
            actor_groups.append(translation["entries"])
            break

    source_item_docs = {
        (actor.get("_id"), item.get("_id")): item
        for actor in (source or {}).get("actors", [])
        for item in actor.get("items", [])
    }
    changed = 0
    for actors in actor_groups:
        for actor_id, actor in actors.items():
            for item in actor.get("items", []):
                current = item.get("description")
                if not isinstance(current, str) or not current:
                    continue
                source_item = source_item_docs.get((actor_id, item.get("id")))
                structural_source = (
                    source_item.get("system", {}).get("description", {}).get("value", "")
                    if source_item else current
                )
                disease_translation = (
                    translated_disease_description(source_item, {
                        "Enfeebled 1": "Ослаблен 1",
                        "Stupefied 1": "Одурманен 1",
                        "Unconscious": "Без сознания",
                        "Clumsy 1": "Неуклюжесть 1",
                        "Clumsy 2": "Неуклюжесть 2",
                        "Paralyzed": "Парализован",
                    })
                    if source_item and source_item.get("name") in {"Rust Creep", "Tetanus"}
                    else None
                )
                candidates = (
                    ITEM_DESCRIPTION_REPAIRS.get(item.get("id")),
                    MANUAL_ITEM_HTML_BY_ID.get(item.get("id"), {}).get("description"),
                    MANUAL_ITEM_HTML.get(item.get("name", ""), {}).get("description"),
                    globals().get("BESTIARY_DESCRIPTION_OVERRIDES", {}).get(item.get("id")),
                    disease_translation,
                )
                desired = next((candidate for candidate in candidates if (
                    isinstance(candidate, str)
                    and candidate
                    and html_tags(candidate) == html_tags(structural_source)
                    and Counter(technical_cores(candidate)) == Counter(technical_cores(structural_source))
                    and Counter(inline_roll_cores(candidate)) == Counter(inline_roll_cores(structural_source))
                )), None)
                if isinstance(desired, str):
                    desired = restore_latin_area_codes(desired)
                if desired is None or desired == current:
                    continue
                item["description"] = desired
                changed += 1
        for actor_id, actor in actors.items():
            repaired_name = ACTOR_NAME_REPAIRS_BY_ID.get(actor_id)
            if repaired_name and (actor.get("name") != repaired_name or actor.get("tokenName") != repaired_name):
                actor["name"] = repaired_name
                if "tokenName" in actor:
                    actor["tokenName"] = repaired_name
                changed += 1
            current = actor.get("description")
            desired = ACTOR_DESCRIPTION_REPAIRS.get(actor_id)
            source_actor = next(
                (candidate for candidate in (source or {}).get("actors", []) if candidate.get("_id") == actor_id),
                None,
            )
            structural_source = source_actor.get("system", {}).get("details", {}).get("publicNotes", "") if source_actor else current
            if not isinstance(current, str) or not current or not isinstance(desired, str):
                continue
            if (
                html_tags(desired) == html_tags(structural_source)
                and Counter(technical_cores(desired)) == Counter(technical_cores(structural_source))
                and Counter(inline_roll_cores(desired)) == Counter(inline_roll_cores(structural_source))
                and desired != current
            ):
                actor["description"] = desired
                changed += 1
    normalized = normalize_area_codes_tree(translation)
    if normalized != translation:
        translation.clear()
        translation.update(normalized)
        changed += 1
    return changed

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


def translated_scene_text(value: str) -> str:
    translated = SCENE_TEXT_TRANSLATIONS.get(value)
    if translated is not None:
        return translated
    region = re.fullmatch(r"Region( \(\d+\))", value)
    if region:
        return f"Область{region.group(1)}"
    if re.search(r"[A-Za-z]{3,}", value):
        raise ValueError(f"Нет перевода метаданных сцены: {value!r}")
    return value


def translate_visible_attributes(value: str) -> str:
    """Переводит доступный пользователю alt/title, не меняя прочие HTML-атрибуты."""

    def replacement(match: re.Match[str]) -> str:
        attribute, original = match.groups()
        original = html.unescape(original)
        translated = IMAGE_ATTRIBUTE_TRANSLATIONS.get(original)
        if translated is None:
            if original == "MetaMorphic Digital Studio" or not re.search(r"[A-Za-z]{3,}", original):
                return match.group(0)
            raise ValueError(f"Нет перевода HTML-атрибута {attribute}: {original!r}")
        return f'{attribute}="{html.escape(translated, quote=True)}"'

    return VISIBLE_ATTRIBUTE_RE.sub(replacement, value)


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
            russian_html = translate_visible_attributes(russian_html)
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
        for item in document_values(actor.get("items", [])):
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
                notes[original] = translated_scene_text(original)
                translated_note_labels += 1
        regions = {}
        for region in scene.get("regions", []):
            region_entry = {"name": translated_scene_text(region.get("name", ""))}
            behaviors = {
                behavior["_id"]: {"name": translated_scene_text(behavior.get("name", ""))}
                for behavior in region.get("behaviors", [])
                if behavior.get("name")
            }
            if behaviors:
                region_entry["behaviors"] = behaviors
            regions[region["_id"]] = region_entry
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
    "02securestorag00": (
        ("небольшие небольшие бочки и бочонки", "небольшие бочонки и кеги"),
        ("пивные горшки", "бочонки и кеги"),
        ("небольшие ящики с мягкой набивкой с хрупкими стеклянными бутылками", "ящики с мягкой набивкой, в которых лежат хрупкие стеклянные бутылки"),
        ("небольшие мягкие ящики", "ящики с мягкой набивкой"),
        ("грязи и отходов", "грязи и нечистот"),
    ),
    "02basement000000": (
        ("бязевых кошек", "трёхцветных кошек"),
        ("(ТС: Эффект их превращения в безобидных крошечных животных в предметах &gt; эффекты - )", "Туннель ведёт к"),
    ),
    "02speakingwith00": (("они видят славят Бога Ржавчины", "они славят Бога Ржавчины"),),
    "02courtyard00000": (
        ("С внутренней стороны стены встает деревянная дорожка для лучников", "С внутренней стороны стены устроен деревянный помост для лучников"),
        ("у западной стены долины встает небольшая конюшня", "у западной стены стоит небольшая конюшня"),
    ),
    "02optionalstar00": (("Старейшина Анлоргогогогогогогогог", "Старейшина Анлорг"),),
    "02kitchen0000000": (("Начальная кладовка встала", "Кладовая распахнута"),),
    "02acryforhelp000": (("дорога встает в расщелину", "дорога выходит к расщелине"),),
    "03secretlab00000": (
        ("встает широкий ржавый металлический цилиндр", "стоит широкий ржавый металлический цилиндр"),
        ("на ржавой железной подставке встал медный котел", "на ржавой железной подставке стоит медный котёл"),
        ("у стены за лестницей, уходящей в темноту, встает пустой книжный шкаф", "у стены за лестницей, уходящей в темноту, стоит пустой книжный шкаф"),
        ("терпеливо встали на стражу здесь на протяжении многих веков", "терпеливо несли здесь стражу на протяжении многих веков"),
    ),
    "03metalrodstor00": (("К восточной и южной стенам этой камеры встает пара широких стеллажей", "У восточной и южной стен этой камеры стоят два широких стеллажа"),),
    "03ritualroom0000": (("над почерневшим кострищем встал огромный медный котел", "над почерневшим кострищем стоит огромный медный котёл"),),
    "03grandaltar0000": (("привлекающему Восприятие кровавому каменному алтарю", "притягивающему взгляд окровавленному каменному алтарю"),),
    "03therusteddoo00": (("В северной стене этой камеры встает ржавая железная дверь", "В северной стене этой камеры стоит ржавая железная дверь"),),
    "04whatifthepcs00": (("привлекает Восприятие Рунного Лорда Белимариуса", "привлекает внимание рунной владычицы Белимариус"),),
    "04grandgallery00": (
        ("ржавый воин встает на фиолетовой каменной горе", "ржавый воин стоит на фиолетовой каменной горе"),
        ("Одинокая фигура в черном одеянии встает на передний план", "На переднем плане стоит одинокая фигура в чёрном одеянии"),
    ),
    "02worshiphall000": (("не обращают на него Восприятия", "не обращают на него внимания"),),
    "04deroencampme00": (("В центре пещеры встает большой костер", "В центре пещеры горит большой костёр"),),
    "04summoningcha00": (
        ("Обратите Восприятие, что", "Обратите внимание: "),
        ("встал каменный помост", "возвышается каменный помост"),
        ("алтарь, укрытие которого залито свежей кровью", "алтарь, поверхность которого залита свежей кровью"),
        ("Перед алтарем встает фигура", "Перед алтарём стоит фигура"),
        ("фигуры, вставшей на помост", "фигуры, стоящей на помосте"),
        ("когда ПИ поступят в эту область", "когда ПИ войдут в эту область"),
        ("ревностное Восприятие Мейтремара к деталям", "внимание Мейтремара к каждой детали"),
        ("когда привлекают Восприятие культистов", "когда привлекают внимание культистов"),
        ("достойным Восприятия мертвого демона", "достойным внимания мёртвого демона"),
    ),
    "02shelteredled00": (
        ("Обратите Восприятие", "Обратите внимание"),
        ("обратите Восприятие", "обратите внимание"),
        ("для опытов, что понять как он может противостоять солнечному свету", "для опытов и выяснить, как он способен выдерживать солнечный свет"),
    ),
    "02findingsonth00": (("обратите Восприятие", "обратите внимание"),),
    "02swordfishdis00": (("обратите Восприятие", "обратите внимание"),),
    "03workshop000000": (
        ("Сокровища Г15 Г15б", "Сокровища D15"),
        ("Сокровища D15 D15b", "Сокровища D15"),
    ),
    "04worshipchamb00": (("Обратите Восприятие, что дверь", "Обратите внимание: дверь"),),
    "04meitremarsqu00": (
        ("У северной стены встает старинная кровать", "У северной стены стоит старинная кровать"),
        ("Рядом с кроватью встали древний письменный стол и стул", "Рядом с кроватью стоят древний письменный стол и стул"),
        ("Свет от одинокого мерцающего факела, рассеянно лежащего на столе", "Комнату освещает одинокий мерцающий факел, лежащий на столе"),
        ("Ключ от спальня-тюрьма", "Ключ от спальни-тюрьмы"),
        ("в \"великом храме\" В этой записи", "в «великом храме». В этой записи"),
    ),
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


# Литературные исправления сверены с русским PDF. Каждая замена
# переносит технические токены из конца абзаца в смысловую позицию.
LITERARY_PARAGRAPH_REPAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "02tunneltorust00": ((
        "Этот длинный туннель",
        '<p>Этот длинный туннель уходит под уклон на юго-запад, проходя под Железной Гаванью к @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03therusteddoo00]{D1} под @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03rusthenge00000]{Растхенджем}. Через несколько сотен футов от подвала кровавый след становится незаметным, но успешная @Check[survival|dc:15|traits:secret,concentrate,exploration,move,skill,action:track|name:Track]{проверка Выживания СЛ 15} при Выслеживании подтверждает, что путь продолжается. В самой низкой точке, под гаванью, со стен капает солёная вода и на полу собираются лужи глубиной до фута, но туннель прочен и ему не грозит затопление.</p>',
    ),),
    "02securestorag00": (
        (
            "Если ПИ успешно выполнит проверку",
            '<p>Трое выживших пленников истощены, обезвожены, заражены ползучей ржавчиной (все на 4-й стадии) и отчаянно ждут спасения, но по-прежнему отказываются подчиниться культистам. У них нет ни снаряжения, ни религиозных символов, ни подготовленных заклинаний. Если ПИ их спасут, пленники с радостью вернутся в Железную Гавань. Они могут рассказать о падении Стоунхоума и о том, что культисты поклоняются демону по имени Ксар-Азмак. Успешная @Check[religion|dc:25|traits:concentrate,secret,skill,action:recall-knowledge|name:Recall Knowledge]{проверка Религии СЛ 25} при Вспоминании информации позволяет опознать в Ксар-Азмаке давно погибшего повелителя демонов ржавчины, разложения и смерти. Пленники также слышали, как Мейтремар говорил о планах «исследовать и вернуть труды моего деда под Растхенджем», но больше ничего не знают.</p>',
        ),
        (
            "конский бочонок аквавита",
            '<p>Среди пустых бочек и обломков в комнате персонажи могут найти нераспечатанный пони-кег аквавита — травяной настойки на основе водки стоимостью 10 зм. Ящик со слабыми зельями исцеления был взломан и использован заключёнными, но они не утолили ими голод. Осталось только пять слабых зелий исцеления.</p>',
        ),
    ),
    "02basement000000": ((
        "Вино, медовуха и эль более высокого качества",
        '<p>Лестница ведёт в @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02clinic00000000]{В5}. Горумиты использовали этот подвал для хранения припасов и продуктов. Вино, медовуха и эль более высокого качества хранятся в @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02securestorag00]{защищённом хранилище В21} за железной дверью, запертой на замок среднего качества. Замок можно взломать четырьмя успешными @Check[thievery|dc:25|traits:manipulate,skill,action:pick-a-lock|name:Pick a Lock]{проверками Воровства СЛ 25} или открыть ключом из @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02smithy00000000]{В6}.</p>',
    ),),
    "02rooftoprange00": ((
        "Одиночным действием можно открыть каждую бочку",
        '<p>Каждый бочонок можно открыть одним действием и обнаружить внутри композитный длинный лук и 50 стрел. На голове капитана Перриоса всё ещё красуется его отличная капитанская шляпа — хорошо сделанная треуголка, украшенная талисманом «веер из перьев». Дженис разрешит ПИ оставить талисман, если они вернут шляпу как доказательство судьбы капитана.</p>',
    ),),
    "02duelingbalco00": ((
        "В песке, помимо засохшей крови",
        '<p>Помимо засохшей крови в песке спрятано сокровище. ПИ, успешно прошедший @Check[perception|dc:14|traits:concentrate,exploration,secret,action:search|name:Search]{проверку Внимания СЛ 14} при Поиске в этой области, обнаруживает зарытый в песок талисман «кристалл мощи».</p>',
    ),),
    "02courtyard00000": ((
        "Крытый колодец опускается",
        '<p>Крытый колодец опускается на 15 футов к небольшому водоёму, соединённому с @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02streamoutlet00]{Б8} проходимым подземным ручьём. Чтобы подняться или спуститься по стенам колодца, нужна @Check[athletics|dc:15]{проверка Атлетики СЛ 15}.</p>',
    ),),
    "02smithy00000000": ((
        "У ПИ есть единственный шанс уговорить его",
        '<p>Ночью Трюгве беспокойно спит на небольшой раскладушке, но быстро просыпается, если кто-то входит. Не узнав ПИ, он принимает их за отряд убийц и решает защищаться, надеясь погибнуть смертью воина в глазах @UUID[Compendium.pf2e.deities.Item.88vRw2ZVPax4hhga]{Горума}. У ПИ есть один шанс его отговорить: нужна успешная @Check[diplomacy|dc:15]{проверка Дипломатии СЛ 15}, @Check[gorum-lore|dc:15]{проверка Знаний о Горуме СЛ 15} или @Check[religion|dc:15]{проверка Религии СЛ 15}. Иначе он пускает в ход молот и сражается насмерть, надеясь пасть в бою. Чтобы дать ПИ шанс спасти его и поговорить с ним, можно позволить ему получить состояние «при смерти» вместо мгновенной гибели при 0 ОЗ.</p>',
    ),),
    "02speakingwith00": (
        (
            "Большего Трюгве не знает",
            '<p>Большего Трюгве не знает и не догадывается об истинных намерениях Мейтремара, но понимает, что последовавшие за ним отреклись от @UUID[Compendium.pf2e.deities.Item.88vRw2ZVPax4hhga]{Горума} и его пути. Он также опасается, что болен (<strong>неправда</strong>), и боится, что большинство его товарищей-горумитов либо мертвы, либо примкнули к новому «культу ржавчины» (<strong>правда</strong>).</p>',
        ),
        (
            "Дальнейшее описание \"монстра с раздвоенным лицом\"",
            '<p>После разговора с ПИ Трюгве согласен покинуть Стоунхоум, если ему обеспечат безопасный выход; он говорит, что найдёт убежище у Элси. Перед уходом он может набросать план Стоунхоума, но не знает, какие опасности ждут ПИ. Подробное описание «монстра с раздвоенным лицом» позволяет опознать порождение греха при успешной @Check[occultism|dc:16|traits:concentrate,secret,skill,action:recall-knowledge|name:Recall Knowledge]{проверке Оккультизма СЛ 16} при Вспоминании информации. Уходя, Трюгве дарит ПИ свой двуручный меч из холодного железа, прося по возможности использовать его только для убийства Мейтремара, а также ключ от @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02securestorag00]{защищённого хранилища В21}.</p>',
        ),
    ),
    "02speakingtova00": (
        (
            "Если Ванда попала в плен",
            '<p>Если Ванда попала в плен, она может сообщить почти те же сведения, что и @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02speakingwith00]{Трюгве (C6)}, но также предупреждает ПИ о судьбе капитана Перриоса и его команды. Когда речь заходит о старейшине Ордви, Ванда краснеет от стыда и рассказывает о случившемся. Прибыв в Стоунхоум, она и другие павшие послушники взяли Ордви в плен, а затем передали её самому опасному агенту Мейтремара в здании — исчадию греха Азоми. Ванда знает, что Азоми утащил Ордви в подвал, но не знает, что с ней стало впоследствии.</p>',
        ),
        (
            "В обмен на милосердие Ванда",
            '<p>В обмен на милосердие Ванда будет сопровождать ПИ и помогать им в оставшихся делах в Стоунхоуме, особенно если это связано с убийством Азоми. Однако её храбрость пропадает, когда речь заходит об исследовании самого @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03rusthenge00000]{Растхенджа}. Вместо этого она отдаёт группе свой двуручный меч +1, чтобы помочь в дальнейших приключениях.</p>',
        ),
    ),
    "02streamoutlet00": ((
        "Здесь в Железную Гавань впадает подземный ручей",
        '<p>Здесь в Железную Гавань впадает подземный ручей шириной 3 фута, но его выход трудно заметить издалека. ПИ, обследующий эту область, может обнаружить выход с помощью @Check[scouting-lore|dc:15]{проверки Знаний разведчика СЛ 15} или @Check[perception|dc:20]{проверки Внимания СЛ 20}; о нём также можно узнать от Элси в разделе @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02enteringston00]{«Вход в Стоунхоум»}. Хотя туннель тесен, существо среднего или меньшего размера может пробраться по нему к небольшому водоёму под колодцем в @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02courtyard00000]{В1} @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02stonehome00001]{Стоунхоума}.</p>',
    ),),
}

LITERARY_PARAGRAPH_REPAIRS.update({
    "02enteringston00": (
        (
            "Для вскрытия замка на входных воротах",
            '<p>К храму горумитов в Стоунхоуме трудно подойти по земле: парадные ворота наглухо заперты, а острые железные шипы мешают перелезть через ограду. Чтобы взломать замок на воротах, нужно успешно выполнить пять @Check[thievery|dc:25|traits:manipulate,skill,action:pick-a-lock|name:Pick a Lock]{проверок Воровства СЛ 25}. Чтобы открыть прочные ворота силой, нужна @Check[athletics|dc:30|traits:attack,skill,action:force-open|name:Force Open]{проверка Атлетики СЛ 30}. Стена с шипами имеет высоту 20 футов; чтобы подняться по ней, нужна @Check[athletics|dc:20|traits:move,skill,action:climb|name:Climb]{проверка Атлетики СЛ 20}. Шипы считаются трудной и опасной местностью: при каждой попытке пробраться сквозь них существо получает [[/r 4d6[piercing]]]{4d6 колющего урона} с базовым @Check[reflex|dc:20|basic:true]{спасброском Реакции СЛ 20}.</p>',
        ),
        (
            "Будучи архитектором, Деррол",
            '<p><strong>Деррол:</strong> Как архитектор, Деррол знает особенности здания. Он объясняет, что Стоунхоум хорошо защищён с земли, но уязвим сверху. Деррол может указать безопасный путь по скалам к узкому уступу на 20 футов выше @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02rooftoprange00]{крыши В19}. Без его помощи этот путь можно обнаружить за 4 часа исследований при успешной @Check[architecture-lore|dc:15]{проверке Знаний архитектуры СЛ 15} или @Check[perception|dc:20]{проверке Внимания СЛ 20}. Лишь на последних 20 футах потребуется @Check[athletics|dc:15|traits:move,skill,action:climb|name:Climb]{проверка Атлетики СЛ 15}, чтобы спуститься к крыше. Если ПИ не будут красться, их могут заметить обитатели @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02rooftoprange00]{крыши В19} и @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02duelingbalco00]{балкона В14}.</p>',
        ),
        (
            "С помощью формы и набора инструментов ремесленника",
            '<p><strong>Дженис:</strong> Беспокоясь о капитане, Дженис просит ПИ проникнуть в Стоунхоум и спасти его или хотя бы принести весть о его судьбе и шляпу как доказательство. Она предостерегает от попытки перелезть через стены с шипами и отдаёт восковой слепок украденного ключа. Имея форму и @UUID[Compendium.pf2e.equipment-srd.Item.y34yjumCFakrbtdw]{набор инструментов ремесленника}, можно за час изготовить ключ, способный отпереть ворота, при успешной @Check[crafting|dc:15]{проверке Ремесла СЛ 15}.</p>',
        ),
    ),
    "02speakingtoth00": (
        (
            "Во время разговора каждый ПИ",
            '<p>Во время разговора каждый ПИ может попытаться выполнить @Check[deception|dc:15]{проверку Обмана СЛ 15}, @Check[diplomacy|dc:15]{проверку Дипломатии СЛ 15} или @Check[intimidation|dc:15]{проверку Запугивания СЛ 15}. Каждый успех приносит 1 очко влияния на Дженис; критический успех приносит 2 очка, а критический провал отнимает 1 очко. Общее число очков определяет её реакцию.</p>',
        ),
        (
            "Она согласится отпустить захваченного ПИ",
            '<p>Если кто-то из ПИ попадает в плен во время обыска корабля, Дженис особенно раздражена группой, и все проверки навыков в разговоре с ней получают штраф обстоятельства –3. Она отпустит пленника, только если группа вернёт всё украденное, успешно выполнит @Check[intimidation|dc:22|traits:auditory,concentrate,emotion,exploration,linguistic,mental,skill,action:coerce|name:Coerce]{проверку Запугивания СЛ 22} при Принуждении или пообещает попытаться спасти её капитана. В последнем случае наградой станет свобода пленника, а не талисманы и золото.</p>',
        ),
    ),
    "02approachingt00": ((
        "Любой ПИ, успешно выполнивший проверку Знания",
            '<p>Старейшина Ордви кивает и просит поговорить с ПИ наедине. Сестра Ванда нетерпеливо хмыкает, но затем отходит. Любой ПИ, успешно выполнивший @Check[gorum-lore|dc:15]{проверку Знаний о Горуме СЛ 15} или @Check[perception|dc:20|traits:concentrate,secret,action:sense-motive|name:Sense Motive]{проверку Внимания СЛ 20} при Понимании намерений, понимает, что что-то случилось. Критический успех показывает, что новость о Блэнтоне застала её врасплох. Ордви тоже это замечает и тихо обращается к ПИ.</p>',
        ),
    ),
    "02shelteredled00": (
        (
            "ПИ, который занимается разведкой или поиском",
            '<p>Когда ПИ идут по этому участку дороги, они могут заметить труднодоступный уступ наверху. ПИ, выполняющий Разведку или Поиск, может совершить тайную @Check[perception|dc:15|traits:concentrate,exploration,secret,action:search|name:Search]{проверку Внимания СЛ 15} или @Check[scouting-lore|dc:13|traits:concentrate,exploration,secret,action:scout|name:Scout]{проверку Знаний разведчика СЛ 13}, чтобы заметить уступ снизу. К нему можно подняться по склону, считая его трудной местностью; проверка Атлетики не требуется.</p>',
        ),
        (
            "Каждый раз, когда она промахивается",
            '<p>Если ПИ не заметят уступ и пройдут мимо, наблюдающая сверху деро выстрелит из ручного арбалета в замыкающего строй ПИ, надеясь застать его врасплох. После каждого промаха дайте ПИ @Check[perception|dc:5]{проверку Внимания СЛ 5}, чтобы услышать звук болта, ударившегося обо что-то поблизости. Критический успех позволяет понять, что стреляли с уступа наверху.</p>',
        ),
        (
            "Если все ПИ в партии используют Активность",
            '<p>Если все ПИ в группе Избегают обнаружения, позвольте каждому из них и Ордви совершить тайную @Check[stealth|dc:16|traits:move,skill,secret,exploration,action:avoid-notice|name:Avoid Notice]{проверку Скрытности СЛ 16}. Если все преуспеют, группа полностью избежит столкновения.</p>',
        ),
    ),
})

LITERARY_PARAGRAPH_REPAIRS.update({
    "02optionalstar00": ((
        "ПИ, осматривающий его тело",
        '<p><em>Растхендж</em> предполагает, что игра начинается, когда ПИ приближаются к первому бою в @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02acryforhelp000]{А1}, но при желании можно начать накануне вечером. Дайте ПИ время представиться. Они могут присутствовать при обнаружении Блэнтона и услышать его предсмертные слова. ПИ, осматривающий тело, может совершить @Check[medicine|dc:15]{проверку Медицины СЛ 15}. Успех подтверждает, что раны от арбалетных болтов отравлены ядом гигантской сороконожки; критический успех также показывает, что странная болезнь вызвала атрофию кожи и мышц.</p>',
    ),),
    "03workshop000000": (
        (
            "Колесо и запорный механизм",
            '<p>Когда боггарды Чёрного озера исследовали мастерскую, они забрали многие полуфабрикаты и припасы, но оставили инструменты. Культисты поддерживают здесь снаряжение в рабочем состоянии, не счищая священную ржавчину. Колесо и запорный механизм на северной стене управляют клеткой-ловушкой в @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03metalrodstor00]{Г16}. ПИ может разобраться в назначении устройства за 1 минуту и при успешной @Check[perception|dc:15]{проверке Внимания СЛ 15}.</p>',
        ),
        (
            "Если ПИ ищет в комнате",
            '<p>@UUID[Actor.WLRDPeJjHCqJGYAw]{Мастерская} @UUID[Actor.fFMhZSnaETOHdzPj]{Южные шкафы} При Поиске в комнате ПИ находит набор серебряных инструментов ремесленника, предназначенных для тонкой работы по созданию талисманов. Успешная @Check[perception|dc:18|traits:concentrate,exploration,secret,action:search|name:Search]{проверка Внимания СЛ 18} также позволяет обнаружить под южными шкафами наполовину готовый окуляр ремесленника. Для завершения работы нужны 4 дня и компоненты на 30 зм; формула не требуется.</p>',
        ),
    ),
    "03magicalstora00": ((
        "Грязные отпечатки подсказывают",
        '<p>Когда-то здесь хранилось множество магических предметов и компонентов, но теперь комната почти пуста. Грязные следы оставили боггарды, которые вошли через потайную дверь в западной стене и погибли, пытаясь вернуться через @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03secretlab00000]{тайную лабораторию Г21}. Следы указывают, где искать, поэтому совершающий Поиск ПИ находит дверь при успешной @Check[perception|dc:15|traits:concentrate,exploration,secret,action:search|name:Search]{проверке Внимания СЛ 15}.</p>',
    ),),
    "03dininghall0000": (
        (
            "Южная дверь в этот зал",
            '<p>Южная дверь в зал забаррикадирована каменной скамьёй. Её можно Открыть силой с @Check[athletics|dc:20|traits:attack,skill,action:force-open|name:Force Open]{проверкой Атлетики СЛ 20}.</p>',
        ),
        (
            "В этой комнате осталось только два боггарда",
            '<p>В комнате остались два разведчика боггардов @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04theblacklake00]{Чёрного озера}, Болгус и Дургон. Они сортируют предметы из мастерской и враждебно относятся ко всем небоггардам. Успешная @Check[diplomacy|dc:18|traits:action:make-an-impression|name:Make an Impression]{проверка Дипломатии СЛ 18} при Произведении впечатления убеждает их, что ПИ не желают зла. Став безразличными, боггарды зовут свою начальницу Гургу из @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03drippingroom00]{Г10}. Чтобы заслужить её доверие, ПИ должен успешно выполнить @Check[diplomacy|dc:20|traits:action:make-an-impression|name:Make an Impression]{проверку Дипломатии СЛ 20} при Произведении впечатления. Провал заставит Гургу приказать Болгусу и Дургону атаковать ПИ, обвинив их в том, что они «лживые лжецы».</p>',
        ),
    ),
    "04theblacklake00": (
        (
            "Глуту часто сидит на пирсе",
            '<p>Глуту часто сидит на пирсе возле хижины и смотрит на воду, размышляя о культистах и о судьбе Гурги. Его телохранитель Гнорк всегда рядом. Пока ПИ не угрожают, Глуту не атакует. Значок друга боггардов заставит его расспросить о Гурге и остальных. Враждебные действия, включая хвастовство убийством боггардов, провоцируют бой насмерть. Если Глуту захватят живым, он с горечью попытается обманом направить ПИ на поиски сокровищ в @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04boggardcompo00]{Е11}, надеясь, что ловушка хотя бы навредит им.</p>',
        ),
        (
            "Потайная дверь, соединяющая эти пещеры",
            '<p>Потайная дверь, соединяющая пещеры с @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04ritualprepar00]{Ж13}, ещё не обнаружена культистами, но боггарды знают о ней и могут рассказать союзникам. Иначе совершающий Поиск ПИ может обнаружить дверь с @Check[perception|dc:25|traits:concentrate,exploration,secret,action:search|name:Search]{проверкой Внимания СЛ 25}.</p>',
        ),
        (
            "ПИ не нужно делать Глуту дружественным",
            '<p>ПИ не нужно добиваться дружелюбия Глуту: достаточно убедить его, что они хотят победить культистов. Поскольку ПИ не боггарды, Глуту считает, что культисты не заподозрят его народ в помощи. Если планы ПИ впечатлят Глуту, он откроет потайную дверь в западной стене при успешной @Check[deception|dc:18]{проверке Обмана СЛ 18}, @Check[diplomacy|dc:18]{Дипломатии СЛ 18} или @Check[intimidation|dc:18]{Запугивания СЛ 18} — в зависимости от тона речи. Значок друга боггардов даёт бонус обстоятельств +4. При критическом успехе Глуту вдохновляется и предлагает помощь телохранителя Гнорка.</p>',
        ),
    ),
    "04darklandslan00": ((
        "ПИ, исследующий здесь пол",
        '<p>ПИ, исследующий пол и успешно выполнивший @Check[survival|dc:20|traits:secret,concentrate,exploration,move,skill,action:track|name:Track]{проверку Выживания СЛ 20} при Выслеживании, замечает следы интенсивного движения. Южный проход к @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04werebatcamp000]{Ж7} использовали реже всего.</p>',
    ),),
    "04deroencampme00": ((
        "Туннель на юге уходит все глубже",
        '<p>Южный туннель уходит всё глубже в Тёмные земли; именно оттуда деро впервые пришли в эти пещеры. На протяжении почти 10 миль здесь нет значимых пещер. Если ПИ продолжат спуск, позвольте им совершить @Check[survival|dc:15|traits:secret,exploration,skill,action:sense-direction|name:Sense Direction]{проверку Выживания СЛ 15}, чтобы понять, что путь ведёт далеко за пределы этой области.</p>',
    ),),
    "04worshipchamb00": (
        (
            "Тейлтемар построил этот зал",
            '<p>Тейлтемар построил этот зал как символ обещания помочь своему повелителю отомстить Диспатеру после возвращения Ксар-Азмака. Огромная статуя изображает Ксар-Азмака с отрубленной головой Диспатера. ПИ автоматически узнают в ней демона с фресок в @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04grandgallery00]{Большой галерее}. Успешная @Check[religion|dc:20|traits:concentrate,secret,skill,action:recall-knowledge|name:Recall Knowledge]{проверка Религии СЛ 20} при Вспоминании информации позволяет опознать голову Диспатера. На колоннах изображены известные демоны и по одному влориаку. Вторая @Check[religion|dc:20|traits:concentrate,secret,skill,action:recall-knowledge|name:Recall Knowledge]{проверка Религии СЛ 20} позволяет узнать абрикандила, бабау, врока и марилита; лишь критический успех позволяет опознать влориака и понять его значение для Ксар-Азмака.</p>',
        ),
        (
            "Зазубренный пень на голове статуи",
            '<p>Зазубренный обрубок на голове статуи — это место, где @UUID[JournalEntry.pf2sa06405advent.JournalEntryPage.05thehornofrus00]{Рог Ржавчины} пролежал тысячи лет, пока Мейтремар не завладел им.</p>',
        ),
        (
            "Потайную дверь за статуей",
            '<p>Потайную дверь за статуей Ксар-Азмака можно обнаружить при успешной @Check[perception|dc:25|traits:concentrate,exploration,secret,action:search|name:Search]{проверке Внимания СЛ 25}. ПИ, который узнал о ней из дневника Мейтремара, находит дверь автоматически после 1 минуты Поиска. За дверью лестница спускается на 50 футов к @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04darklandslan00]{Ж1} в Глубинах Опустошителя.</p>',
        ),
        (
            "ПИ может карабкаться по передней части статуи",
            '<p>@UUID[Actor.HqpzxgEhWWsgPszX]{Статуя} ПИ может взобраться по передней части статуи и выковырять светящиеся глаза-самоцветы при успешной @Check[athletics|dc:15|traits:move,skill,action:climb|name:Climb]{проверке Атлетики СЛ 15}. После извлечения самоцветы перестают светить, а красные факелы гаснут, возможно погружая зал во тьму. Это два обычных граната стоимостью 50 зм каждый. Их снятие также безвредно рассеивает накопленную за века божественную энергию и мешает ритуалу Мейтремара.</p>',
        ),
    ),
})

LITERARY_PARAGRAPH_REPAIRS.update({
    "02stables0000000": (
        (
            "Успешная проверка",
            '<p>Потайную дверь в северной стене можно обнаружить при успешной @Check[perception|dc:17]{проверке Внимания СЛ 17}. Сейчас за ней нет ничего особенно интересного, но она позволяет попасть в подсобное помещение персонажам, спустившимся с крыши.</p>',
        ),
        (
            "Ида находится здесь и по сей день",
            '<p>Ида по-прежнему находится здесь, но из-за болезни и пренебрежения со стороны захватившего храм культа она сильно ослабла и истощена. Сейчас баран не может ходить, но ПИ способен на время вернуть ей подвижность: для этого нужно 10 минут кормить Иду и ухаживать за ней, а затем успешно выполнить @Check[medicine|dc:15]{проверку Медицины СЛ 15}. Если у ПИ есть лечебное печенье от Элси, достаточно просто скормить его Иде.</p>',
        ),
    ),
    "03prison00000000": ((
        "Пока комната пуста",
        '<p>Кнурр Рагнульф переоборудовал эту тренировочную комнату в импровизированную тюрьму для пленников, доставленных в подземелье. Сейчас комната пуста, но ПИ, который проведёт здесь Поиск и успешно выполнит @Check[perception|dc:20|traits:concentrate,exploration,secret,action:search|name:Search]{проверку Внимания СЛ 20}, обнаружит спрятанную в одной из кроватей записку. Её оставила @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02elderordwi0000]{старейшина Ордви}, написав собственной кровью: «Кнурр примкнул к культу. Предупредите Бухту Скопы! Боюсь, скоро они заберут меня вниз». Подпись нацарапана дрожащей рукой.</p>',
    ),),
    "03cultistquart00": ((
        "В этих комнатах живут Ржавые Посвященные",
        '<p>Эти комнаты занимают адепты Ржавчины — тассилонские культисты, сопровождавшие Мейтремара в Железную Гавань. Когда ПИ впервые входят в комплекс, адепты распределены между поверхностью Растхенджа, @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03grandaltar0000]{D3} и @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03ritualroom0000]{D13}.</p>',
    ),),
    "04summoningcha00": (
        (
            "Вход в эту комнату из F13",
            '<p>Вход в эту комнату из @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04ritualprepar00]{F13} перекрыт @UUID[Compendium.pf2e.spells-srd.Item.7Iela4GgVeO3LfAo]{силовой стеной}. Маловероятно, что у ПИ есть способ её обойти, но после уничтожения Тейлтемара стена рассеивается. Обратите внимание: во втором абзаце приведённого ниже текста для чтения вслух описывается продолжающийся ритуал Мейтремара — при необходимости измените текст.</p>',
        ),
        (
            "Для проведения ритуала Мейтремар использует шесть источников",
            '<p>Для проведения ритуала Мейтремар использует шесть источников внешней энергии: взаимодействие Влорианских шпилей с влорианским цитниготом на поверхности (@UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03sacrificekee00]{Жертвенные хранители}); демоническую энергию, собранную древним аппаратом на @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03grandaltar0000]{большом алтаре (D3)}; мучения просителя Бездны в @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03ritualroom0000]{ритуальной комнате (D13)}; зловещую энергию из @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03researchlab000]{исследовательской лаборатории (D20)} и @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03secretlab00000]{тайной лаборатории (D21)}; а также фокусирующие самоцветы в глазах статуи Ксар-Азмака в @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04worshipchamb00]{зале поклонения (E5)}. В этих местах ПИ могут получить до 6 очков прерывания, но даже если нарушить работу всех источников, ритуал Мейтремара продолжится.</p>',
        ),
        (
            "Если ход Мейтремара происходит до демона",
            '<p>Если ход Мейтремара происходит раньше хода демона, он сначала пытается Деморализовать его, для чего нужна @Check[intimidation|dc:23|traits:auditory,concentrate,emotion,fear,mental,action:demoralize|name:Demoralize]{проверка Запугивания СЛ 23}, а затем активирует @UUID[JournalEntry.pf2sa06405advent.JournalEntryPage.05thehornofrus00]{Рог Ржавчины}. Если демон уже атаковал, Мейтремар осознаёт свою ошибку и вскрикивает от ужаса: он становится Испуган 1 и тратит первое действие на Перемещение как можно дальше от демона, прежде чем активировать рог. В конце раунда напряжённая магия вынуждает влориака вернуться в Бездну. Оставшаяся часть боя — это сражение с зомби и, вероятно, раненым Мейтремаром. Это умеренное столкновение 3-го уровня. Для драматического эффекта после гибели Мейтремар может сразу превратиться в Ржавого зомби, когда остаточная энергия Бездны наполнит его останки.</p>',
        ),
    ),
    "04rusteddoor0000": ((
        "Большая ржавая дверь в этой стене",
        '<p><strong>Опасность:</strong> Большая ржавая дверь в этой стене выглядит так же, как дверь к @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04worshipchamb00]{Д5} в храме выше, но она заперта. Чтобы взломать замок, нужно успешно выполнить три @Check[thievery|dc:20|traits:manipulate,skill,action:pick-a-lock|name:Pick a Lock]{проверки Воровства СЛ 20}. Кроме того, дверь защищает ржавый шипомёт.</p>',
    ),),
    "04derobarracks00": ((
        "Деро выращивают здесь грибы цитиллеш",
        '<p>@UUID[Actor.dUxUDTLcUnDxvvA2]{Грибы} Деро выращивают здесь грибы цитиллеш, надеясь пополнить запасы необычного наркотика, который помогает им похищать жителей поверхности. Успешная @Check[nature|dc:20|traits:concentrate,secret,skill,action:recall-knowledge|name:Recall Knowledge]{проверка Природы СЛ 20} при Вспоминании информации позволяет опознать грибы. Съевший их ПИ должен совершить @Check[type:fortitude|dc:20]{спасбросок Стойкости СЛ 20}, иначе станет @UUID[Compendium.pf2e.conditionitems.Item.e1XGnhKNSQIm5IXg]{Одурманен 1} на 1 час, а при критическом провале — @UUID[Compendium.pf2e.conditionitems.Item.e1XGnhKNSQIm5IXg]{Одурманен 2}. Безопасно собрать грибы можно при успешной @Check[medicine|dc:20]{проверке Медицины СЛ 20} или @Check[survival|dc:20]{проверке Выживания СЛ 20}. При успехе персонаж собирает сырьё на 35 зм для создания @UUID[Compendium.pf2e.equipment-srd.Item.rjUJEY424jyG9dGn]{цитиллеша} или @UUID[Compendium.pf2e.equipment-srd.Item.aZm1x9tpvBAT8YCd]{масла цитиллеша}, а при критическом успехе — на 70 зм. При критическом провале персонаж подвергается действию токсина, как если бы съел грибы.</p>',
    ),),
    "04thedespoiled00": ((
        "Эта огромная пропасть простирается",
        '<p>Эта огромная пропасть тянется на сотни футов к востоку и западу и уходит в глубины Нар-Вота. Падающий в неё ПИ может Схватиться за уступ с @Check[type:reflex|dc:18|trait:action:grab-an-edge|name:Grab an Edge]{проверкой Реакции СЛ 18}. При провале он падает на [[/r 1d6*10]]{1d6×10 футов}, ударяется об узкий уступ и получает соответствующий урон. Стены пропасти очень неровные, поэтому для Карабкания нужна @Check[athletics|dc:15|traits:move,skill,action:climb|name:Climb]{проверка Атлетики СЛ 15}. Ниже 60 футов стены становятся глаже, и СЛ проверки повышается до @Check[athletics|dc:25|traits:move,skill,action:climb|name:Climb]{25}; далее пропасть падает ещё на 200 футов в большую пещеру. То, что лежит ниже, выходит за рамки этого приключения, но может стать местом для дальнейших приключений высокого уровня.</p>',
    ),),
    "04bedroompriso00": ((
        "Дверь в эту комнату закрыта",
        '<p>Дверь в эту комнату заперта на замок среднего качества. Ключ находится в @UUID[JournalEntry.pf2sa06404ressur.JournalEntryPage.04meitremarsqu00]{Д2}. Без ключа замок можно взломать четырьмя успешными @Check[thievery|dc:25|traits:manipulate,skill,action:pick-a-lock|name:Pick a Lock]{проверками Воровства СЛ 25}. Дверь также можно Открыть силой при успешной @Check[athletics|dc:25|traits:attack,skill,action:force-open|name:Force Open]{проверке Атлетики СЛ 25}. Любой подошедший к двери персонаж может совершить тайную @Check[perception|dc:20|traits:secret]{проверку Внимания СЛ 20}, чтобы услышать тихую молитву по ту сторону. При критическом успехе ПИ узнаёт голос старейшины Ордви.</p>',
    ),),
    "04meitremarsqu00": ((
        "Окованный железом сундук принадлежит",
        '<p>Окованный железом сундук принадлежит Мейтремару. Он заперт на замок среднего качества; чтобы взломать его, нужны четыре успешные @Check[thievery|dc:25|traits:manipulate,skill,action:pick-a-lock|name:Pick a Lock]{проверки Воровства СЛ 25}. Ключ от сундука Мейтремар носит при себе. Внутри лежат кожаные мешочки с 14 зм и 66 см, а также малое зелье исцеления, малый эликсир понимания, три малые микстуры и шесть питательных тоников.</p>',
    ),),
})


SWORDFISH_DISCOVERIES_TABLE = '''<table class="pf2-table"><thead><tr><th>[[/r 1d20]]{d20}</th><th>Находка</th></tr></thead><tbody><tr><td>1–6</td><td>Кошель с [[/r 3d6 #sp]]{3d6 см}.</td></tr><tr><td>7–10</td><td>@UUID[Actor.vzfjiN90hY4BKqTC]{Бутылка «Карпендена»} — талданского игристого вина среднего качества стоимостью 10 зм.</td></tr><tr><td>11–14</td><td>@UUID[Actor.E4nAqM6ioupOiCO8]{Судовая платёжная ведомость} — деревянная шкатулка с 230 см и 100 зм.</td></tr><tr><td>15–17</td><td>@UUID[Actor.DT8LYKyMTa0BzUgx]{Навигационные журналы} и записи, из которых следует, что «Рыба-меч» — наёмное судно, которое обычно нанимает тассилонская знать, а не торговый корабль.</td></tr><tr><td>18–19</td><td>@UUID[Actor.mkpyy4bVJi16lOhD]{Малая шкатулка} с четырьмя талисманами «кристалл мощи».</td></tr><tr><td>20</td><td>@UUID[Actor.rWV6SIL5lXsJufgs]{Журнал «Рыбы-меч»} (см. @UUID[JournalEntry.pf2sa06406handou.JournalEntryPage.06handout0100000]{раздаточный материал №1}); журнал написан на тассилонском.</td></tr></tbody></table>'''

LITERARY_PARAGRAPH_REPAIRS.update({
    "02theoldbridge00": (
        (
            "В течение многих лет жители Бухты Скопы",
            '<p>Многие годы @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02optionalstar00#osprey-covesettlement-2]{Бухта Скопы} старалась поддерживать мост, но в последнее десятилетие город почти не уделял ему внимания. Деревянную замену давно растащили жители @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02ironharbor0000#iron-harborsettlement-2]{Железной Гавани} на крыши и корабли. Когда Блэнтон добрался сюда по пути в Бухту Скопы, его преследовала пара деро. Он бросился в море с южной стороны и переплыл прибой к северному пролому. Это случилось на рассвете, поэтому деро пришлось отступить к @UUID[JournalEntry.pf2sa06402messag.JournalEntryPage.02shelteredled00]{А3}. Измотанному болезнью, двумя отравленными болтами и тяжёлым заплывом Блэнтону потребовался остаток дня, чтобы добраться до Бухты Скопы.</p>',
        ),
        (
            "Эта область служит испытанием",
            '<p>Эта область служит испытанием изобретательности ПИ. Наиболее вероятные решения описаны ниже. Обычно для преодоления разлома нужна проверка СЛ 15, если только способ не особенно опасен — как, например, хождение по канату.</p>',
        ),
        (
            "ПИ может Карабкаться на 15 футов",
            '<p><strong>Карабкание и плавание:</strong> ПИ может спуститься на 15 футов к воде, переплыть приливную лужу шириной 5 футов и глубиной 10 футов, а затем подняться на 15 футов с другой стороны. Можно также обойти воду по северо-восточному краю, но это займёт больше времени. Вода достаточно глубока, чтобы падение с 15 футов не нанесло урона; падающий может Схватиться за уступ с @Check[reflex|dc:15|traits:manipulate,action:grab-an-edge|name:Grab an Edge]{проверкой Реакции СЛ 15}. Проверки: @Check[athletics|dc:15|traits:move,skill,action:climb|name:Climb]{Атлетика СЛ 15 для Карабкания}, @Check[athletics|dc:15|traits:move,skill,action:swim|name:Swim]{Атлетика СЛ 15 для Плавания}.</p>',
        ),
        (
            "ПИ может попытаться совершить Прыжок в Длину",
            '<p><strong>Прыжок:</strong> ПИ может перепрыгнуть разлом в его самом узком месте у крутого северного гребня. Для этого нужно преодолеть 15 футов с @Check[athletics|dc:15|traits:move,skill,action:long-jump|name:Long Jump]{проверкой Атлетики СЛ 15} при Прыжке в длину, предварительно разбежавшись не менее чем на 10 футов. ПИ со Скоростью не менее 30 футов автоматически преодолевает разлом одним Прыжком.</p>',
        ),
        (
            "ПИ может перекинуть лассо",
            '<p><strong>Верёвка:</strong> ПИ могут перебросить лассо или абордажную кошку через дальнюю статую, натянуть верёвку и закрепить ближний конец на соседней статуе. Закрепление верёвки — тайный бросок дальней атаки с наивысшим мастерством ПИ против КБ 20. При критическом провале крепление кажется надёжным, но срывается на полпути. Перебраться можно с @Check[athletics|dc:15|traits:move,skill,action:climb|name:Climb]{проверкой Атлетики СЛ 15} для Карабкания по верёвке или с @Check[acrobatics|dc:30|traits:move,skill,action:balance|name:Balance]{проверкой Акробатики СЛ 30} для Удержания равновесия на канате.</p>',
        ),
        (
            "На восточной стороне моста",
            '<p>@UUID[Actor.tO46DP0MnaEzL54l]{Деревянный столб} На восточной стороне моста в деревянный столб вбит болт ручного арбалета. Он соответствует ране на теле Блэнтона. Если извлечь и исследовать болт, следы яда гигантской сороконожки можно опознать при успешной @Check[crafting|dc:15|traits:concentrate,exploration,secret,skill,action:identify-alchemy|name:Identify Alchemy]{проверке Ремесла СЛ 15} для Идентификации алхимии.</p>',
        ),
    ),
    "03secretlab00000": ((
        "Как и в исследовательской лаборатории",
            '<p>Как и в @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03researchlab000]{исследовательской лаборатории Г20}, здесь находится основание Влорианского шпиля. Присоединённое к нему устройство больше и сложнее аппаратов в основной лаборатории, будто те были лишь прототипами. В отличие от устройств в @UUID[JournalEntry.pf2sa06403therus.JournalEntryPage.03researchlab000]{Г20}, этот шпиль не собирает энергию, а перенаправляет её в комплекс ниже. Это подтверждает успешная проверка Идентификации магии СЛ 20 с помощью @Check[arcana|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Арканы}, @Check[nature|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Природы}, @Check[occultism|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Оккультизма} или @Check[religion|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Религии}.</p>',
        ),
    ),
    "03researchlab000": (
        (
            "ПИ, изучивший аппараты",
            '<p>ПИ, побывавший в наземных руинах Растхенджа, сразу узнаёт две ржавые колонны: это основания юго-восточных шпилей на поверхности. Провода и арматура соединяют шпили с магическими верстаками. Успешная @Check[arcana|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{проверка Арканы СЛ 20} при Идентификации магии показывает, что шпили служат магическими «батареями», а верстаки фокусируют энергию; этот успех также позволяет деактивировать верстак действием Взаимодействие. Верстак имеет КБ 18, Твёрдость 9 и 36 ОЗ (ПП 18).</p>',
        ),
        (
            "Если раньше каменная плита была гораздо прочнее",
            '<p>За тысячи лет воздействия энергии веры Ксар-Азмака каменная плита ослабла. Она имеет КБ 15, Твёрдость 7 и 28 ОЗ (ПП 14). Если плита получает состояние @UUID[Compendium.pf2e.conditionitems.Item.6dNUvdb1dhToNDj3]{Сломан}, трещины становятся достаточно большими, чтобы выпустить запечатанную в колодце первобытную зависть. Колодец также можно открыть, сдвинув каменную крышку при успешной @Check[athletics|dc:20|traits:attack,skill,action:force-open|name:Force Open]{проверке Атлетики СЛ 20}.</p>',
        ),
        (
            "Выцветший красный фолиант",
            '<p>Выцветший красный фолиант на северных полках сделан из дерева и переплетён кожей. Когда библиотека была полна, он не бросался в глаза, но теперь его легко заметить. Если потянуть книгу, срабатывает рычаг и открывает потайную дверь за шкафом. Ищущий ПИ также может обнаружить дверь при успешной @Check[perception|dc:20|traits:concentrate,exploration,secret,action:search|name:Search]{проверке Внимания СЛ 20}.</p>',
        ),
    ),
    "03ingotstorage00": ((
        "Единственный слиток без ржавчины",
            '<p>Железные слитки здесь ничего не стоят: они давно поддались влиянию Ксар-Азмака. Единственный нетронутый ржавчиной слиток серебра стоит 100 зм. ПИ, искавший среди ржавых слитков не менее минуты, находит под ними лёгкий молот из холодного железа.</p>',
        ),
    ),
    "03drippingroom00": ((
        "ПИ, осмотревший душ",
            '<p>ПИ, осматривающий душ, может понять, что им управляют руны на стене, и научиться включать, выключать и регулировать температуру воды при успешной проверке Идентификации магии СЛ 20 с помощью @Check[arcana|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Арканы}, @Check[nature|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Природы}, @Check[occultism|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Оккультизма} или @Check[religion|dc:20|traits:concentrate,exploration,secret,action:identify-magic|name:Identify Magic]{Религии}. Вода создаётся магией, как от заклинания @UUID[Compendium.pf2e.spells-srd.Item.WzLKjSw6hsBhuklC]{«Создать воду»}, но быстро испаряется и не затапливает комнату.</p>',
        ),
    ),
    "03storeroom00000": ((
        "В ящиках и бочках находится еда и питье",
            '<p>@UUID[Actor.MwHZ9llX4RCpTqzc]{Полки} В ящиках и бочках хранятся еда и питьё для культистов. На полках ПИ находит истлевший кожаный мешочек с 45 мм и 1 см, десятки пустых флаконов из-под зелий и эликсиров, одно малое зелье исцеления с тассилонской этикеткой «яд», покрытый грязью оккультный кулон и покрытый пылью талисман «кулон плачущего ангела».</p>',
        ),
    ),
    "03rusthenge00000": (
        (
            "Семь разрушенных",
            '<p>Семь разрушенных скальных образований в кольце железных шпилей когда-то были скульптурами семи рун греха, которыми пользовались тассилонские маги. ПИ, потративший несколько минут на изучение этого места, может распознать их при успешной @Check[arcana|dc:20]{проверке Арканы СЛ 20} или подходящей @Check[xin-edasseril-lore|dc:20]{проверке Знаний о Ксин-Эдассериле СЛ 20}.</p>',
        ),
        (
            "Наконец, сами Влорианские Шпили",
            '<p>Наконец, сами Влорианские шпили излучают слабую тревожную ауру, от которой становится не по себе каждому, кто входит в кольцо шпилей. Как только ПИ ступает внутрь кольца, он должен успешно пройти @Check[fortitude|dc:15]{спасбросок Стойкости СЛ 15}, чтобы не получить состояние @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 1} (или @UUID[Compendium.pf2e.conditionitems.Item.MIRkyAjyBeXivMa7]{ослаблен 1} на 24 часа при критическом провале). После попытки спасброска ПИ получает иммунитет к этому эффекту независимо от результата.</p>',
        ),
    ),
    "03startingthis00": ((
        "подготовить для Деррола пригодную",
            '<p>Если ПИ полностью исследуют Стоунхоум, они смогут за 2 часа подготовить для Деррола пригодную карту внутренних помещений при успешной @Check[crafting|dc:15]{проверке Ремесла СЛ 15}. За доставку карты бывшему архитектору ПИ получают 40 ОО.</p>',
        ),
    ),
})


PARAGRAPH_RE = re.compile(r"<p\b[^>]*>.*?</p>", flags=re.I | re.S)


def replace_literary_paragraph(text: str, page_id: str, anchor: str, replacement: str) -> str:
    """Заменяет один абзац и переносит в него те же макросы Foundry."""
    replacement = restore_latin_area_codes(replacement)
    current = next((match for match in PARAGRAPH_RE.finditer(text) if anchor in match.group(0)), None)
    if current is None:
        if replacement in text:
            return text
        raise ValueError(f"{page_id}: не найден абзац для литературной правки: {anchor!r}")

    for desired in TECH_RE.findall(replacement):
        desired_core = TECH_CORE_RE.fullmatch(desired).group(1)
        current = next((match for match in PARAGRAPH_RE.finditer(text) if anchor in match.group(0)), None)
        local_tokens = TECH_RE.findall(current.group(0)) if current else []
        source = next(
            (token for token in local_tokens if TECH_CORE_RE.fullmatch(token).group(1) == desired_core),
            None,
        )
        if source is None:
            source = next(
                (token for token in TECH_RE.findall(text) if TECH_CORE_RE.fullmatch(token).group(1) == desired_core),
                None,
            )
        if source is None:
            raise ValueError(f"{page_id}: не найден токен {desired_core}")
        if source in local_tokens and current is not None:
            offset = current.start() + current.group(0).index(source)
            text = text[:offset] + text[offset + len(source):]
        else:
            text = text.replace(source, "", 1)

    for desired in INLINE_ROLL_RE.findall(replacement):
        desired_core = re.sub(r"\{[^{}]*\}$", "", desired)
        current = next((match for match in PARAGRAPH_RE.finditer(text) if anchor in match.group(0)), None)
        local_rolls = INLINE_ROLL_RE.findall(current.group(0)) if current else []
        source = next(
            (roll for roll in local_rolls if re.sub(r"\{[^{}]*\}$", "", roll) == desired_core),
            None,
        )
        if source is None:
            source = next(
                (roll for roll in INLINE_ROLL_RE.findall(text) if re.sub(r"\{[^{}]*\}$", "", roll) == desired_core),
                None,
            )
        if source is None:
            raise ValueError(f"{page_id}: не найден встроенный бросок {desired_core}")
        if source in local_rolls and current is not None:
            offset = current.start() + current.group(0).index(source)
            text = text[:offset] + text[offset + len(source):]
        else:
            text = text.replace(source, "", 1)

    current = next((match for match in PARAGRAPH_RE.finditer(text) if anchor in match.group(0)), None)
    if current is None:
        raise ValueError(f"{page_id}: абзац исчез при переносе токенов")
    return text[:current.start()] + replacement + text[current.end():]


def cleanup_digital_layout(
    translation: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> int:
    """Удаляет печатные артефакты, не меняя технические токены."""
    changed = 0
    for adventure in translation.get("entries", {}).values():
        pages = {
            page_id: page
            for journal in adventure.get("journals", {}).values()
            for page_id, page in journal.get("pages", {}).items()
        }
        if "07elderanlorgo00" in pages:
            pages["07elderanlorgo00"]["name"] = "Старейшина Анлоргог"
        for page_id, page in pages.items():
            text = page.get("text")
            if not isinstance(text, str):
                continue
            before_cores = Counter(technical_cores(text))
            before_rolls = Counter(inline_roll_cores(text))
            for old, new in DIGITAL_LAYOUT_REPAIRS.get(page_id, ()):
                text = text.replace(old, new)
            for anchor, replacement in LITERARY_PARAGRAPH_REPAIRS.get(page_id, ()):
                text = replace_literary_paragraph(text, page_id, anchor, replacement)
            if page_id == "02swordfishdis00":
                table_match = re.search(r"<table\b[^>]*>.*?</table>", text, flags=re.I | re.S)
                if table_match is None:
                    raise ValueError(f"{page_id}: не найдена таблица находок")
                text = text[:table_match.start()] + SWORDFISH_DISCOVERIES_TABLE + text[table_match.end():]
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
            if Counter(inline_roll_cores(text)) != before_rolls:
                raise ValueError(f"{page_id}: очистка вёрстки изменила встроенные броски")
            if text != page["text"]:
                page["text"] = text
                changed += 1
    changed += repair_translated_item_descriptions(translation, source)
    normalized = normalize_area_codes_tree(translation)
    if normalized != translation:
        translation.clear()
        translation.update(normalized)
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
    value = re.sub(r"Старейшина Анлорг(?!ог)", "Старейшина Анлоргог", value)
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

    scene_index: dict[str, Any] = {}
    translated_scenes = adventure["scenes"]
    for scene in source.get("scenes", []):
        scene_entry = translated_scenes[scene["_id"]]
        notes = {
            note["text"]: translated_scene_text(note["text"])
            for note in scene.get("notes", [])
            if note.get("text")
        }
        regions: dict[str, Any] = {}
        for region in scene.get("regions", []):
            region_entry: dict[str, Any] = {"name": translated_scene_text(region.get("name", ""))}
            behaviors = {
                behavior["_id"]: {"name": translated_scene_text(behavior.get("name", ""))}
                for behavior in region.get("behaviors", [])
                if behavior.get("name")
            }
            if behaviors:
                region_entry["behaviors"] = behaviors
            regions[region["_id"]] = region_entry
            counts["translatedRegionNames"] += bool(region.get("name"))
            counts["translatedRegionBehaviorNames"] += len(behaviors)
        if notes:
            scene_entry["notes"] = notes
        else:
            scene_entry.pop("notes", None)
        if regions:
            scene_entry["regions"] = regions
        else:
            scene_entry.pop("regions", None)
        counts["translatedNoteLabels"] += len(notes)
        scene_index[scene["_id"]] = {"notes": notes, "regions": regions}
    index["sceneText"] = scene_index

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
        for item in document_values(actor.get("items", [])):
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
                    translate_visible_attributes(normalize_visible_text(page["text"])),
                )

    translated_attribute_values = set(IMAGE_ATTRIBUTE_TRANSLATIONS.values())
    for journal in adventure.get("journals", {}).values():
        for page in journal.get("pages", {}).values():
            for _attribute, translated in VISIBLE_ATTRIBUTE_RE.findall(page.get("text", "")):
                counts["imageAttributes"] += 1
                value = html.unescape(translated)
                if value == "MetaMorphic Digital Studio":
                    counts["preservedCreditAttributes"] += 1
                elif value in translated_attribute_values:
                    counts["translatedImageAttributes"] += 1

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
        "translatedNoteLabels": counts["translatedNoteLabels"],
        "translatedRegionNames": counts["translatedRegionNames"],
        "translatedRegionBehaviorNames": counts["translatedRegionBehaviorNames"],
        "imageAttributes": counts["imageAttributes"],
        "translatedImageAttributes": counts["translatedImageAttributes"],
        "preservedCreditAttributes": counts["preservedCreditAttributes"],
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

BESTIARY_DESCRIPTION_OVERRIDES.update({
    "p6uToNU7wgFDgDDH": '<p>В начале каждого хода дретча бросьте [[/gmr 1d4 #Actions Regained]]{1d4}. Результат равен числу действий, которые он восстанавливает в этот ход (максимум 3).</p>\n<p>Такие эффекты, как состояние @UUID[Compendium.pf2e.conditionitems.Item.xYTAsEpcJE1Ccni3]{замедлен}, могут дополнительно уменьшить число его действий.</p>',
    "h8caQJMnKj4F22zZ": ITEM_DESCRIPTION_REPAIRS["h8caQJMnKj4F22zZ"],
    "8tVnSA2uTOLAmycM": '<p><strong>Триггер</strong> Существо входит в область к югу от отмеченного на карте кольца камней</p><hr /><p><strong>Эффект</strong> Из кольца камней вырывается поток воды, с силой несётся по проходу и стекает в яму в области <strong>Е1б</strong>. Все существа Большого или меньшего размера на пути воды должны совершить @Check[fortitude|dc:20|options:area-effect,damaging-effect,forced-movement,inflicts:prone]{спасбросок Стойкости СЛ 20}. Достигнув дна ямы, вода мгновенно исчезает, но всё вокруг остаётся промокшим.</p><hr /><p><strong>Критический успех</strong> Существо выдерживает напор и не получает эффекта.</p><p><strong>Успех</strong> Поток ударяет существо о стену пещеры, нанося @Damage[1d10[bludgeoning]|options:area-damage] дробящего урона.</p><p><strong>Провал</strong> Поток сбивает существо @UUID[Compendium.pf2e.conditionitems.Item.j91X7x0XSomq8d60]{ничком}, наносит @Damage[(1d10+6)[bludgeoning]|options:area-damage] дробящего урона и толкает к шипастой яме, активируя ловушку.</p><p><strong>Критический провал</strong> Как провал, но при падении в шипастую яму существо не может попытаться @UUID[Compendium.pf2e.actionspf2e.Item.3yoajuKjwHZ9ApUY]{Схватиться за уступ}.</p>',
    "y7VNs5A41UH94zX1": '<p><strong>Триггер</strong> Древний аппарат получает урон или проваливается попытка Отключить его</p><hr /><p><strong>Эффект</strong> Древний аппарат начинает быстрее скрежетать и вращаться. Тихое тиканье перерастает в диссонансное жужжание, а вся конструкция озаряется тревожным светом цвета ржавчины. Все живые существа в области <strong>Г3</strong> ощущают во рту привкус ржавчины и должны успешно пройти @Check[fortitude|dc:18]{спасбросок Стойкости СЛ 18}, иначе становятся @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 1}. Затем древний аппарат совершает проверку инициативы.</p>',
    "80CuEcGtDQ6fUIyY": '<p><strong>Триггер</strong> Болотный мудрец или один из его союзников в пределах 60 футов совершает спасбросок против слухового или звукового эффекта.</p><hr /><p><strong>Эффект</strong> Болотный мудрец издаёт кваканье, заглушающее другие звуки, и совершает @Check[performance]{проверку Выступления}. Он и союзные боггарды в области могут использовать против слухового или звукового эффекта более высокий результат: свой спасбросок или проверку Выступления мудреца.</p>',
    "xcV4iG9yR2uKSGdL": '<p><strong>Триггер</strong> Существо открывает дверь, не произнеся перед этим молитву Ксар-Азмаку</p><hr /><p><strong>Эффект</strong> В открытом дверном проёме возникает множество ржавых шипов, которые устремляются в область <strong>Д1</strong>. Шипы изгибаются в воздухе, преследуя цели: все существа в области <strong>Д1</strong> должны совершить @Check[reflex|dc:20|traits:damaging-effect]{спасбросок Реакции СЛ 20}.</p><hr /><p><strong>Критический успех</strong> Существо уклоняется от шипов и не получает урона.</p><p><strong>Успех</strong> Шип задевает существо, нанося @Damage[2d10[piercing]] колющего урона.</p><p><strong>Провал</strong> Шип пронзает существо, нанося @Damage[(2d10+13)[piercing]] колющего урона.</p><p><strong>Критический провал</strong> Как провал, но существо также подвергается воздействию столбняка.</p>',
    "Kv1pkf5Ma30A8n58": '<p>Цитнигот полностью раскрывает свой ужасающий облик. Существа в @Template[emanation|distance:10]{10-футовой эманации} должны совершить @Check[will|dc:20]{спасбросок Воли СЛ 20}. После этого существо получает временный иммунитет к «Мерзкому зрелищу» на 1 минуту.</p><hr /><p><strong>Критический успех</strong> Существо не получает эффекта.</p><p><strong>Успех</strong> Существо @UUID[Compendium.pf2e.conditionitems.Item.AJh5ex99aV6VTggg]{застигнуто врасплох} до начала своего следующего хода.</p><p><strong>Провал</strong> Существо становится @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 1} и застигнуто врасплох, пока испытывает тошноту.</p><p><strong>Критический провал</strong> Существо становится @UUID[Compendium.pf2e.conditionitems.Item.fesd1n5eVhpCSS18]{тошнота 2} и застигнуто врасплох, пока испытывает тошноту.</p>',
})

BESTIARY_ACTOR_FIELD_OVERRIDES = {
    ("33irjDlbW0pXhxiS", "disable"): '<p>@Check[thievery|dc:20] (эксперт), чтобы стереть скрытые руны на потолке, или @UUID[Compendium.pf2e.spells-srd.Item.9HpwDN4MYQJnW0LG]{Рассеивание магии} (2-й ранг; КС противодействия 18), чтобы противодействовать ловушке</p>',
    ("LGcNyvqAKnhwEzuf", "disable"): '<p>@Check[thievery|dc:20], чтобы отсоединить пусковые стержни, выдвигающие шипы, или @UUID[Compendium.pf2e.spells-srd.Item.9HpwDN4MYQJnW0LG]{Рассеивание магии} (2-й ранг; КС противодействия 18), чтобы противодействовать ловушке</p>',
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
    translated_tags = html_tags(translated)
    source_tags = html_tags(current_source)
    normalized_translated_tags = [re.sub(r"\s*/>$", ">", tag) for tag in translated_tags]
    normalized_source_tags = [re.sub(r"\s*/>$", ">", tag) for tag in source_tags]
    if normalized_translated_tags != normalized_source_tags:
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

    rebased = INLINE_ROLL_RE.sub(replace_roll, TECH_RE.sub(replace_token, translated))
    source_tag_iterator = iter(source_tags)
    return TAG_RE.sub(lambda _match: next(source_tag_iterator), rebased)


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
        for item in document_values(actor.get("items", [])):
            translated = tr_items.get(item["_id"])
            if translated:
                item_candidates_by_name.setdefault(item.get("name", ""), []).append((item, translated))

    entries: dict[str, Any] = {}
    metadata: dict[str, Any] = {
        "actors": {},
        "technical": {},
        "inlineRolls": {},
        "html": {},
        "actorFieldCounts": {
            field: sum(bool(nested_value(actor, path)) for actor in bestiary_actors)
            for field, path in BESTIARY_ACTOR_FIELD_PATHS.items()
        },
    }
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
            if not isinstance(source_value, str) or not source_value:
                continue
            translated_value = representative_translation.get(field)
            current_override = BESTIARY_ACTOR_FIELD_OVERRIDES.get((actor_id, field))
            if current_override is not None:
                if html_tags(current_override) != html_tags(source_value):
                    raise ValueError(f"{actor_id}/{field}: ручной перевод изменил HTML-структуру")
                if Counter(technical_cores(current_override)) != Counter(technical_cores(source_value)):
                    raise ValueError(f"{actor_id}/{field}: ручной перевод изменил технические токены")
                if Counter(inline_roll_cores(current_override)) != Counter(inline_roll_cores(source_value)):
                    raise ValueError(f"{actor_id}/{field}: ручной перевод изменил встроенные броски")
                rebased = current_override
            elif isinstance(translated_value, str) and translated_value:
                rebased = rebase_technical_markup(translated_value, source_value)
            else:
                rebased = None
            if rebased is None:
                raise ValueError(f"{actor_id}/{field}: нет полного перевода видимого поля бестиария")
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
        for item in document_values(actor.get("items", [])):
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
            "itemIds": [item["_id"] for item in document_values(actor.get("items", []))],
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
        changed = cleanup_digital_layout(translation, source)
        args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bestiary_changed = 0
        if args.bestiary_output.is_file():
            bestiary_translation = json.loads(args.bestiary_output.read_text(encoding="utf-8"))
            bestiary_changed = repair_translated_item_descriptions(bestiary_translation)
            args.bestiary_output.write_text(
                json.dumps(bestiary_translation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(f"Очищено страниц и карточек: {changed}; карточек бестиария: {bestiary_changed}")
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
        repair_translated_item_descriptions(bestiary_translation)
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
        repair_translated_item_descriptions(translation, source)
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
    cleanup_digital_layout(translation, source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(translation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(index["expected"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
