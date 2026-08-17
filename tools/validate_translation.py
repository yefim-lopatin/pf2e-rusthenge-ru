#!/usr/bin/env python3
"""Строгая офлайн-проверка Babele-перевода Rusthenge."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

TECH_RE = re.compile(r"@[A-Za-z][A-Za-z0-9]*\[(?:[^\[\]]|\[[^\[\]]*\])*\](?:\{[^{}]*\})?")
TECH_CORE_RE = re.compile(r"(@[A-Za-z][A-Za-z0-9]*\[(?:[^\[\]]|\[[^\[\]]*\])*\])(?:\{[^{}]*\})?")
INLINE_ROLL_RE = re.compile(r"\[\[/[a-z]+\s+(?:[^\[\]]|\[[^\[\]]*\])*\]\](?:\{[^{}]*\})?", re.I)
TAG_RE = re.compile(r"<[^>]+>")
VISIBLE_ATTRIBUTE_RE = re.compile(r'\b(alt|title)="([^"]*)"', re.I)
LATIN_RE = re.compile(r"\b[A-Za-z][A-Za-z'’-]{2,}\b")
ALLOWED_LATIN = {"foundry", "pathfinder", "babele", "pf2e", "vtt", "pdf"}
FORBIDDEN = ("pf2e-ts-adv", ".ldb", "leveldb", "%pdf", "data:image/")
SUSPICIOUS_HYPHEN_RE = re.compile(r"[А-Яа-яЁё]{2,}-\s+[а-яё]{2,}")
HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)
ANCHOR_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.I | re.S)
IMAGE_PATH_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', re.I)
LINK_PATH_RE = re.compile(r'<a\b[^>]*\bhref="([^"]+)"', re.I)
BALANCED_TAGS = ("div", "section", "aside", "h1", "h2", "h3", "p", "details")
CYRILLIC_CLASS_RE = re.compile(r'class="[^"]*[А-Яа-яЁё][^"]*"')
CYRILLIC_AREA_RE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])([АБВГДЕ])\d{1,2}[a-bA-Bа-бА-Б]?(?![A-Za-zА-Яа-яЁё0-9])"
)
INVALID_AREA_RE = re.compile(r"(?<![A-Za-z0-9])(?:D0|D15b|E13)(?![A-Za-z0-9])")
EMPTY_LIST_RE = re.compile(r"<(?:ul|ol)\b[^>]*>\s*(?:<li\b[^>]*>\s*</li>\s*)*</(?:ul|ol)>", re.I)
EMPTY_CONTAINER_RE = re.compile(r"<(section|div|aside|p|ul|ol|li)\b[^>]*>\s*</\1>", re.I)
BROKEN_PROSE_RE = re.compile(
    r"(?:провер\w*\s+(?:на\s+)?(?:[,.;)]|или\b|и\b)|"
    r"успешн\w*\s+на\s+|КС_|_КС|Твердость_|ПП_|"
    r"водки\s+с\s+травяным\s+поваром|конский\s+бочонок|проверок\s+на\s*[,.;)]|"
    r"обратите\s+Восприятие|Анлоргогог|небольшие\s+небольшие|"
    r"должн\w*\s+совершить\s+выполнить|ревностное\s+Восприятие|"
    r"привлека\w*\s+Восприятие|достойным\s+Восприятия|начальная\s+кладовка\s+встал|"
    r"долж\w*\s+сделать\s*,|отда[её]т\s+сво[йюи]\s*[,.;]|"
    r"становится\s+против\s+атак|из-за\s+взятие\s+в\s+тиски)",
    re.I,
)
BROKEN_INLINE_MARKUP_RE = re.compile(r"<strong>\s*</strong>|`[^`]+`")
BRACKETED_QUALITY_RE = re.compile(r"\[(?:Слабое|Малое|Малый|Слиток)\]", re.I)
EXPECTED_COUNTS = {
    "journals": 7,
    "pages": 191,
    "translatedTextPages": 116,
    "servicePagesOriginal": 4,
    "galleryPages": 71,
    "scenes": 19,
    "notes": 176,
    "translatedNoteLabels": 6,
    "translatedRegionNames": 20,
    "translatedRegionBehaviorNames": 13,
    "imageAttributes": 80,
    "translatedImageAttributes": 60,
    "preservedCreditAttributes": 18,
    "actors": 113,
    "tokens": 287,
    "customEmbeddedItems": 271,
    "macros": 13,
    "playlists": 3,
    "playlistSounds": 34,
    "actorPublicNotes": 43,
    "actorPrivateNotes": 4,
    "itemPublicDescriptions": 125,
    "itemGMDescriptions": 5,
    "actorBlurbs": 33,
    "actorLanguageDetails": 8,
    "actorSenseDetails": 2,
    "hazardDescriptions": 8,
    "hazardDisable": 8,
    "hazardReset": 8,
    "hazardRoutine": 1,
    "actorStealthDetails": 7,
    "actorHpDetails": 6,
    "actorAcDetails": 1,
    "actorAllSaveDetails": 5,
    "actorSpeedDetails": 6,
    "actorSaveDetails": 3,
    "actorSkillLabels": 7,
    "itemUnidentifiedNames": 42,
    "itemUnidentifiedDescriptions": 6,
    "itemRuleLabels": 5,
    "linkedItemNames": 393,
    "linkedItemOverrides": 393,
    "bestiaryActors": 25,
    "bestiaryEmbeddedItems": 218,
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def load_json(path: Path, check: Validation) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        check.errors.append(f"{path}: {error}")
        return {}


def technical_cores(value: str) -> list[str]:
    return [TECH_CORE_RE.fullmatch(token).group(1) for token in TECH_RE.findall(value)]


def technical_tokens(value: str) -> list[str]:
    return TECH_RE.findall(value)


def technical_label_words(value: str) -> set[str]:
    words: set[str] = set()
    for token in TECH_RE.findall(value):
        match = re.search(r"\{([^{}]*)\}$", token)
        if match:
            words.update(word.lower() for word in LATIN_RE.findall(match.group(1)))
    return words - ALLOWED_LATIN


def visible_words(value: str) -> list[str]:
    plain = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", value))))
    return re.findall(r"[A-Za-zА-Яа-яЁё'’-]+", plain)


def html_hash(value: str) -> str:
    return hashlib.sha256("\n".join(TAG_RE.findall(value)).encode()).hexdigest()


def inline_roll_cores(value: str) -> list[str]:
    return [re.sub(r"\{[^{}]*\}$", "", roll) for roll in INLINE_ROLL_RE.findall(value)]


def string_values(value: Any, path: str = "") -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    if isinstance(value, str):
        values.append((path, value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            values.extend(string_values(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            values.extend(string_values(item, f"{path}.{key}" if path else key))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translation", type=Path, default=Path("translations/pf2e-rusthenge.adventures.json"))
    parser.add_argument("--index", type=Path, default=Path("data/source-index.json"))
    parser.add_argument("--module", type=Path, default=Path("module.json"))
    parser.add_argument(
        "--bestiary-translation",
        type=Path,
        default=Path("translations/pf2e.rusthenge-bestiary.json"),
    )
    parser.add_argument("--source", type=Path, help="Официальный Adventure для локальной проверки команд макросов")
    args = parser.parse_args()
    check = Validation()
    translation = load_json(args.translation, check)
    index = load_json(args.index, check)
    manifest = load_json(args.module, check)
    bestiary_translation = load_json(args.bestiary_translation, check)
    if check.errors:
        print("\n".join(f"ОШИБК: {e}" for e in check.errors), file=sys.stderr)
        return 1

    for label, payload in (("Adventure", translation), ("бестиарий", bestiary_translation)):
        for path, value in string_values(payload):
            match = CYRILLIC_AREA_RE.search(value)
            check.require(
                match is None,
                f"{label} {path}: кириллический код области {match.group(0) if match else ''}",
            )
            invalid = INVALID_AREA_RE.search(value)
            check.require(
                invalid is None,
                f"{label} {path}: код области не совпадает с официальным модулем: {invalid.group(0) if invalid else ''}",
            )

    check.require(manifest.get("id") == "pf2e-rusthenge-ru", "неверный id модуля")
    check.require(
        manifest.get("manifest") == "https://github.com/yefim-lopatin/pf2e-rusthenge-ru/releases/latest/download/module.json",
        "неверная публичная manifest-ссылка",
    )
    expected_download = (
        "https://github.com/yefim-lopatin/pf2e-rusthenge-ru/releases/download/"
        f"v{manifest.get('version')}/pf2e-rusthenge-ru.zip"
    )
    check.require(manifest.get("download") == expected_download, "download-ссылка не совпадает с версией")
    required = {r.get("id") for r in manifest.get("relationships", {}).get("requires", [])}
    check.require(required == {"pf2e-rusthenge", "babele", "pf2e-ru", "ru-ru"}, "изменён набор обязательных модулей")
    register_path = args.module.parent / "scripts" / "register.js"
    try:
        register_source = register_path.read_text(encoding="utf-8")
    except OSError as error:
        register_source = ""
        check.errors.append(f"{register_path}: {error}")
    check.require(
        'description: "system.details.publicNotes"' in register_source,
        "Babele не сопоставляет публичные заметки PF2e",
    )
    check.require(
        all(needle in register_source for needle in ('converter: "document"', 'documentType: "Item"', 'cardinality: "many"')),
        "Babele не сопоставляет вложенные предметы актёров Adventure",
    )
    for needle in (
        'blurb: "system.details.blurb"',
        'descriptionHazard: "system.details.description"',
        'allSaves: "system.attributes.allSaves.value"',
        'unidentifiedName: "system.identification.unidentified.name"',
        'ruleLabel0: "system.rules.0.label"',
    ):
        check.require(needle in register_source, f"Babele mapping не содержит {needle}")
    check.require(index.get("source", {}).get("version") == "14.1.0", "индекс не от Rusthenge 14.1.0")
    for key, expected in EXPECTED_COUNTS.items():
        check.require(index.get("expected", {}).get(key) == expected, f"контрольное число {key} не равно {expected}")

    adventure_id = index.get("source", {}).get("adventureId")
    entries = translation.get("entries", {})
    check.require(set(entries) == {adventure_id}, "в entries должен быть ровно один официальный Adventure _id")
    adventure = entries.get(adventure_id, {})
    journals = adventure.get("journals", {})
    scenes = adventure.get("scenes", {})
    actors = adventure.get("actors", {})
    macros = adventure.get("macros", {})
    playlists = adventure.get("playlists", {})
    check.require(len(journals) == 7, "должно быть 7 журналов")
    check.require(len(scenes) == 19, "должно быть 19 сцен")
    check.require(len(actors) == 113, "должно быть 113 актёров")
    scene_text = index.get("sceneText", {})
    check.require(set(scene_text) == set(scenes), "индекс метаданных сцен не покрывает все 19 сцен")
    region_name_count = 0
    behavior_name_count = 0
    note_label_count = 0
    for scene_id, expected_scene in scene_text.items():
        scene = scenes.get(scene_id, {})
        expected_notes = expected_scene.get("notes", {})
        actual_notes = scene.get("notes", {})
        check.require(actual_notes == expected_notes, f"{scene_id}: неполный перевод подписей заметок")
        for value in actual_notes.values():
            check.require(not LATIN_RE.search(value), f"{scene_id}: в подписи заметки остался английский текст: {value!r}")
        note_label_count += len(actual_notes)
        expected_regions = expected_scene.get("regions", {})
        actual_regions = scene.get("regions", {})
        check.require(set(actual_regions) == set(expected_regions), f"{scene_id}: изменён набор регионов")
        for region_id, expected_region in expected_regions.items():
            actual_region = actual_regions.get(region_id, {})
            check.require(
                actual_region.get("name") == expected_region.get("name"),
                f"{scene_id}/{region_id}: не переведено имя региона",
            )
            check.require(
                not LATIN_RE.search(actual_region.get("name", "")),
                f"{scene_id}/{region_id}: в имени региона остался английский текст",
            )
            region_name_count += bool(expected_region.get("name"))
            expected_behaviors = expected_region.get("behaviors", {})
            actual_behaviors = actual_region.get("behaviors", {})
            check.require(
                set(actual_behaviors) == set(expected_behaviors),
                f"{scene_id}/{region_id}: изменён набор поведений региона",
            )
            for behavior_id, expected_behavior in expected_behaviors.items():
                check.require(
                    actual_behaviors.get(behavior_id, {}).get("name") == expected_behavior.get("name"),
                    f"{scene_id}/{region_id}/{behavior_id}: не переведено имя поведения региона",
                )
                check.require(
                    not LATIN_RE.search(actual_behaviors.get(behavior_id, {}).get("name", "")),
                    f"{scene_id}/{region_id}/{behavior_id}: в поведении региона остался английский текст",
                )
                behavior_name_count += bool(expected_behavior.get("name"))
    check.require(note_label_count == EXPECTED_COUNTS["translatedNoteLabels"], "должно быть 6 переводов подписей заметок")
    check.require(region_name_count == EXPECTED_COUNTS["translatedRegionNames"], "должно быть 20 переводов имён регионов")
    check.require(
        behavior_name_count == EXPECTED_COUNTS["translatedRegionBehaviorNames"],
        "должно быть 13 переводов поведений регионов",
    )
    for actor_id, actor in actors.items():
        check.require(
            not re.fullmatch(r"[A-F]\d{1,2}[ab]?", actor.get("name", "")),
            f"{actor_id}: название объекта ошибочно заменено кодом области",
        )
    check.require(len(macros) == 13, "должно быть 13 переводов названий макросов")
    check.require(set(macros) == set(index.get("macroCommandHashes", {})), "изменён набор _id макросов")
    for macro_id, macro in macros.items():
        check.require(set(macro) == {"name"}, f"{macro_id}: разрешён перевод только имени макроса")
    check.require(len(playlists) == 3, "должно быть 3 перевода плейлистов")
    check.require(set(playlists) == set(index.get("playlistSounds", {})), "изменён набор _id плейлистов")
    for playlist_id, sound_ids in index.get("playlistSounds", {}).items():
        sounds = playlists.get(playlist_id, {}).get("sounds", {})
        check.require(set(sounds) == set(sound_ids), f"{playlist_id}: изменён набор звуков")
        for sound_id, sound in sounds.items():
            check.require(set(sound) == {"name"}, f"{sound_id}: разрешён перевод только имени звука")
    folders = adventure.get("folders", {})
    check.require(len(folders) == 13, "должно быть 13 уникальных переводов папок")

    pages = {pid: page for journal in journals.values() for pid, page in journal.get("pages", {}).items()}
    check.require(len(pages) == 187, "должно быть 187 переводимых страниц (116 текстов + 71 галереи)")
    service = set(index.get("servicePageIds", []))
    check.require(not (service & set(pages)), "служебные Credits/OGL/Audio Credits/Changelog не должны переводиться")
    check.require(set(index.get("pages", {})) <= set(pages), "не все 116 текстовых page _id есть в переводе")
    vanda_text = pages.get("02speakingtova00", {}).get("text", "")
    check.require("двуручный меч +1" in vanda_text, "в разговоре с Вандой потерян предмет, который она отдаёт группе")
    rusthenge_text = pages.get("03rusthenge00000", {}).get("text", "")
    check.require(
        "@Check[fortitude|dc:15]{спасбросок Стойкости СЛ 15}" in rusthenge_text,
        "на странице Растхенджа спасбросок Стойкости отделён от правила",
    )

    visible_attribute_count = 0
    preserved_credit_attribute_count = 0
    for page_id, page_meta in index.get("pages", {}).items():
        text = pages.get(page_id, {}).get("text", "")
        for attribute, raw_value in VISIBLE_ATTRIBUTE_RE.findall(text):
            value = html.unescape(raw_value)
            visible_attribute_count += 1
            if value == "MetaMorphic Digital Studio":
                preserved_credit_attribute_count += 1
                continue
            words = {word.lower() for word in LATIN_RE.findall(value)} - ALLOWED_LATIN
            check.require(
                not words,
                f"{page_id}: в HTML-атрибуте {attribute} остался английский текст: {value!r}",
            )
        cores = technical_cores(text)
        source_cores = [TECH_CORE_RE.fullmatch(token).group(1) for token in page_meta.get("technicalTokens", [])]
        check.require(
            Counter(cores) == Counter(source_cores),
            f"{page_id}: потерян или добавлен технический @UUID/@Check/@Damage",
        )
        check.require(
            Counter(inline_roll_cores(text)) == Counter(inline_roll_cores(" ".join(page_meta.get("inlineRolls", [])))),
            f"{page_id}: потеряна или изменена встроенная формула броска",
        )
        image_paths = set(IMAGE_PATH_RE.findall(text))
        link_paths = set(LINK_PATH_RE.findall(text))
        check.require(set(page_meta.get("sourceImagePaths", [])) <= image_paths, f"{page_id}: потерян путь к изображению")
        check.require(set(page_meta.get("sourceLinkPaths", [])) <= link_paths, f"{page_id}: потеряна HTML-ссылка")
        check.require(not SUSPICIOUS_HYPHEN_RE.search(text), f"{page_id}: остался перенос слова из PDF")
        check.require("rusthenge-ru-controls" not in text, f"{page_id}: технические элементы вынесены в общий подвал")
        check.require(not CYRILLIC_CLASS_RE.search(text), f"{page_id}: остался класс старого PDF-конвертера")
        check.require(not EMPTY_LIST_RE.search(text), f"{page_id}: остался пустой список")
        check.require(not EMPTY_CONTAINER_RE.search(text), f"{page_id}: остался пустой HTML-контейнер")
        check.require(not re.search(r"\d+\s*ФТ\b|КБ_|Вспом\.Информ\.", text), f"{page_id}: осталась PDF-аббревиатура")
        visible_text = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", text))))
        check.require(not BROKEN_PROSE_RE.search(visible_text), f"{page_id}: осталась повреждённая фраза из PDF-конверсии")
        check.require(not BRACKETED_QUALITY_RE.search(visible_text), f"{page_id}: осталось машинное название предмета")
        for tag in BALANCED_TAGS:
            opened = len(re.findall(rf"<{tag}\b", text, flags=re.I))
            closed = len(re.findall(rf"</{tag}>", text, flags=re.I))
            check.require(opened == closed, f"{page_id}: несбалансированный HTML-тег {tag}")
        for _level, body in HEADING_RE.findall(text):
            words_in_heading = visible_words(body)
            check.require(bool(words_in_heading) or bool(TECH_RE.search(body)), f"{page_id}: пустой заголовок")
            check.require(len(words_in_heading) <= 24, f"{page_id}: в заголовок попал абзац ({len(words_in_heading)} слов)")
        for body in ANCHOR_RE.findall(text):
            check.require(len(visible_words(body)) <= 20, f"{page_id}: в HTML-ссылку попал абзац")
        plain = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", text))))
        words = {word.lower() for word in LATIN_RE.findall(plain)} - ALLOWED_LATIN
        if page_id not in {"01rusthenge00000", "01landing0000000"}:
            check.require(not words, f"{page_id}: остался английский текст: {', '.join(sorted(words)[:8])}")
            label_words = technical_label_words(text)
            check.require(
                not label_words,
                f"{page_id}: осталась английская подпись Foundry: {', '.join(sorted(label_words)[:8])}",
            )

    check.require(
        visible_attribute_count == EXPECTED_COUNTS["imageAttributes"],
        f"видимых alt/title должно быть {EXPECTED_COUNTS['imageAttributes']}, найдено {visible_attribute_count}",
    )
    check.require(
        preserved_credit_attribute_count == EXPECTED_COUNTS["preservedCreditAttributes"],
        "изменилось число оригинальных подписей студии в alt/title",
    )

    layout_forbidden = {
        "02sneakingonbo00": ("<h4>Отвлечь Экипаж</h4>", "<h4>Обыск Корабля</h4>", "75ФТ"),
        "02elderordwi0000": ("<h3>Старейшина Ордви</h3>",),
        "05sinsludge00000": ("<h2>Грехошлам</h2>",),
        "05thehornofrus00": (" / Предмет 5",),
    }
    for page_id, fragments in layout_forbidden.items():
        text = pages.get(page_id, {}).get("text", "")
        for fragment in fragments:
            check.require(fragment not in text, f"{page_id}: остался PDF-артефакт {fragment!r}")

    # Отдельный пак обязателен: официальный импортёр Rusthenge заменяет актёров Adventure
    # данными из pf2e.rusthenge-bestiary уже после перевода Adventure.
    bestiary_entries = bestiary_translation.get("entries", {})
    bestiary_meta = index.get("bestiary", {})
    check.require(bestiary_translation.get("label") == "Растхендж — бестиарий", "неверная метка перевода бестиария")
    bestiary_mapping = bestiary_translation.get("mapping", {})
    check.require(
        bestiary_mapping.get("description") == "system.details.publicNotes",
        "бестиарий не сопоставляет публичные заметки",
    )
    check.require(
        bestiary_mapping.get("items", {}).get("converter") == "document",
        "бестиарий не сопоставляет вложенные Item",
    )
    check.require(set(bestiary_entries) == set(bestiary_meta.get("actors", {})), "изменён набор ID актёров бестиария")
    check.require(len(bestiary_entries) == 25, "в бестиарии должно быть 25 актёров")
    bestiary_items: dict[str, dict[str, dict[str, Any]]] = {}
    for actor_id, actor_meta in bestiary_meta.get("actors", {}).items():
        actor = bestiary_entries.get(actor_id, {})
        items = {item.get("id"): item for item in actor.get("items", [])}
        bestiary_items[actor_id] = items
        check.require(set(items) == set(actor_meta.get("itemIds", [])), f"{actor_id}: изменён набор ID элементов бестиария")
        for value in [actor.get("name", ""), *[item.get("name", "") for item in items.values()]]:
            words = {word.lower() for word in LATIN_RE.findall(value)} - ALLOWED_LATIN
            check.require(not words, f"{actor_id}: не переведено имя бестиария {value!r}")
    check.require(sum(len(items) for items in bestiary_items.values()) == 218, "в бестиарии должно быть 218 вложенных элементов")
    check.require(
        sum("description" in item for items in bestiary_items.values() for item in items.values()) == 50,
        "в бестиарии должно быть 50 локальных описаний уникальных элементов",
    )
    actor_field_counts = bestiary_meta.get("actorFieldCounts", {})
    check.require(actor_field_counts.get("description") == 11, "в исходном бестиарии должно быть 11 описаний актёров")
    check.require(actor_field_counts.get("disable") == 7, "в исходном бестиарии должно быть 7 полей обезвреживания")
    for field, expected_count in actor_field_counts.items():
        actual_count = sum(field in actor for actor in bestiary_entries.values())
        check.require(
            actual_count == expected_count,
            f"неполный перевод поля бестиария {field}: {actual_count} вместо {expected_count}",
        )

    def bestiary_value(path: str) -> str:
        parts = path.split("/")
        if len(parts) == 2:
            return bestiary_entries.get(parts[0], {}).get(parts[1], "")
        return bestiary_items.get(parts[0], {}).get(parts[2], {}).get(parts[3], "")

    for path, expected_tokens in bestiary_meta.get("technical", {}).items():
        check.require(
            technical_cores(bestiary_value(path)) == technical_cores(" ".join(expected_tokens)),
            f"{path}: изменены технические токены бестиария",
        )
    for path, expected_rolls in bestiary_meta.get("inlineRolls", {}).items():
        check.require(
            inline_roll_cores(bestiary_value(path)) == inline_roll_cores(" ".join(expected_rolls)),
            f"{path}: изменены встроенные броски бестиария",
        )
    for path, expected_hash in bestiary_meta.get("html", {}).items():
        check.require(html_hash(bestiary_value(path)) == expected_hash, f"{path}: изменена HTML-структура бестиария")
        value = bestiary_value(path)
        plain = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", value))))
        words = {word.lower() for word in LATIN_RE.findall(plain)} - ALLOWED_LATIN
        check.require(not words, f"{path}: в описании бестиария остался английский текст")
        check.require(not BROKEN_PROSE_RE.search(plain), f"{path}: повреждена фраза в описании бестиария")
        check.require(not BROKEN_INLINE_MARKUP_RE.search(value), f"{path}: повреждена разметка описания бестиария")

    envy = bestiary_entries.get("FUxaVKVEV8eOuTVB", {})
    envy_items = {item.get("id"): item for item in envy.get("items", [])}
    for item_id, expected_name in {
        "HhUe0MpfzNrigkps": "Ощущение магии",
        "fJ34aqwTiZbTv92E": "Конфискация заклинания",
        "FDCXS4bVC2F1PdGz": "Вытягивание заклинания",
    }.items():
        item = envy_items.get(item_id, {})
        check.require(item.get("name") == expected_name, f"Первобытная зависть: неверное имя {item_id}")
        check.require(bool(item.get("description")), f"Первобытная зависть: нет описания {item_id}")

    linked_overrides = set(index.get("linkedItemOverrides", []))
    all_item_entries = [
        (actor_id, item)
        for actor_id, actor in actors.items()
        for item in actor.get("items", [])
    ]
    custom_items = [
        item for actor_id, item in all_item_entries
        if f"{actor_id}/{item.get('id')}" not in linked_overrides
    ]
    linked_items = [
        item for actor_id, item in all_item_entries
        if f"{actor_id}/{item.get('id')}" in linked_overrides
    ]
    check.require(len(custom_items) == 271, "должно быть 271 перевод встроенных несистемных элементов")
    actor_items = {
        actor_id: {item.get("id"): item for item in actor.get("items", [])}
        for actor_id, actor in actors.items()
    }
    gang_up = actor_items.get("2g8LSm8VMWFoOK8U", {}).get("CNpPqhgSIEamhwFL", {})
    check.require(
        "застигнут врасплох} для атак ближнего боя адепта Ржавчины" in gang_up.get("description", ""),
        "Сговориться: состояние отделено от правила или описание повреждено",
    )
    envy_items = actor_items.get("XCkK3Xrz8Yoi4SMG", {})
    check.require(
        envy_items.get("fJ34aqwTiZbTv92E", {}).get("name") == "Конфискация заклинания",
        "неверный перевод Confiscate Spell",
    )
    check.require(
        envy_items.get("FDCXS4bVC2F1PdGz", {}).get("name") == "Вытягивание заклинания",
        "неверный перевод Spell Drain",
    )
    for path, expected_tokens in index.get("actorTechnical", {}).items():
        parts = path.split("/")
        actor_id = parts[0]
        if len(parts) == 2:
            value = actors.get(actor_id, {}).get(parts[1], "")
        else:
            value = actor_items.get(actor_id, {}).get(parts[2], {}).get(parts[3], "")
        check.require(
            technical_cores(value) == technical_cores(" ".join(expected_tokens)),
            f"{path}: изменены технические токены актёра/элемента",
        )
    for path, expected_rolls in index.get("actorInlineRolls", {}).items():
        parts = path.split("/")
        actor_id = parts[0]
        if len(parts) == 2:
            value = actors.get(actor_id, {}).get(parts[1], "")
        else:
            value = actor_items.get(actor_id, {}).get(parts[2], {}).get(parts[3], "")
        check.require(
            inline_roll_cores(value) == inline_roll_cores(" ".join(expected_rolls)),
            f"{path}: изменены встроенные формулы актёра/элемента",
        )
    for path, expected_hash in index.get("actorHtml", {}).items():
        parts = path.split("/")
        actor_id = parts[0]
        if len(parts) == 2:
            value = actors.get(actor_id, {}).get(parts[1], "")
        else:
            value = actor_items.get(actor_id, {}).get(parts[2], {}).get(parts[3], "")
        check.require(html_hash(value) == expected_hash, f"{path}: изменена HTML-структура актёра/элемента")
    for label, values in (
        ("актёр", [a.get("name", "") for a in actors.values()]),
        ("встроенный элемент", [i.get("name", "") for i in custom_items]),
        ("системный элемент", [i.get("name", "") for i in linked_items]),
        ("страница", [p.get("name", "") for p in pages.values()]),
    ):
        for value in values:
            words = {w.lower() for w in LATIN_RE.findall(value)} - ALLOWED_LATIN
            check.require(not words, f"{label} не переведён: {value}")

    check.require(sum("description" in actor for actor in actors.values()) == 43, "неполный перевод публичных заметок актёров")
    check.require(sum("descriptionGM" in actor for actor in actors.values()) == 4, "неполный перевод приватных заметок актёров")
    check.require(sum("description" in item for item in custom_items) == 125, "неполный перевод описаний встроенных элементов")
    check.require(sum("gm" in item for item in custom_items) == 5, "неполный перевод GM-описаний встроенных элементов")
    field_counts = {
        "actorBlurbs": sum("blurb" in actor for actor in actors.values()),
        "actorLanguageDetails": sum("language" in actor for actor in actors.values()),
        "actorSenseDetails": sum("senses" in actor for actor in actors.values()),
        "hazardDescriptions": sum("descriptionHazard" in actor for actor in actors.values()),
        "hazardDisable": sum("disable" in actor for actor in actors.values()),
        "hazardReset": sum("reset" in actor for actor in actors.values()),
        "hazardRoutine": sum("routine" in actor for actor in actors.values()),
        "actorStealthDetails": sum("stealth" in actor for actor in actors.values()),
        "actorHpDetails": sum("hp" in actor for actor in actors.values()),
        "actorAcDetails": sum("ac" in actor for actor in actors.values()),
        "actorAllSaveDetails": sum("allSaves" in actor for actor in actors.values()),
        "actorSpeedDetails": sum("speed" in actor for actor in actors.values()),
        "actorSaveDetails": sum("willSave" in actor for actor in actors.values()),
        "actorSkillLabels": sum(
            key in actor
            for actor in actors.values()
            for key in ("skillAcrobatics", "skillAthletics", "skillCrafting", "skillStealth", "skillThievery")
        ),
        "itemUnidentifiedNames": sum("unidentifiedName" in item for _actor, item in all_item_entries),
        "itemUnidentifiedDescriptions": sum("unidentifiedDescription" in item for _actor, item in all_item_entries),
        "itemRuleLabels": sum("ruleLabel0" in item for _actor, item in all_item_entries),
        "linkedItemNames": sum("name" in item for item in linked_items),
        "linkedItemOverrides": len(linked_overrides),
    }
    for key, actual in field_counts.items():
        check.require(actual == EXPECTED_COUNTS[key], f"неполный перевод {key}: {actual} вместо {EXPECTED_COUNTS[key]}")
    for label, value in [
        *[(f"актёр {actor.get('name', '')}", actor.get("description", "")) for actor in actors.values()],
        *[(f"GM актёра {actor.get('name', '')}", actor.get("descriptionGM", "")) for actor in actors.values()],
        *[
            (f"поле {key} актёра {actor.get('name', '')}", actor.get(key, ""))
            for actor in actors.values()
            for key in (
                "blurb", "language", "senses", "descriptionHazard", "disable", "reset", "routine",
                "stealth", "hp", "ac", "allSaves", "speed", "willSave", "skillAcrobatics",
                "skillAthletics", "skillCrafting", "skillStealth", "skillThievery",
            )
        ],
        *[(f"элемент {item.get('name', '')}", item.get("description", "")) for item in custom_items],
        *[(f"GM элемента {item.get('name', '')}", item.get("gm", "")) for item in custom_items],
        *[
            (f"поле {key} элемента {item.get('name', item.get('id', ''))}", item.get(key, ""))
            for _actor, item in all_item_entries
            for key in ("unidentifiedName", "unidentifiedDescription", "ruleLabel0")
        ],
    ]:
        plain = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", value))))
        words = {word.lower() for word in LATIN_RE.findall(plain)} - ALLOWED_LATIN
        check.require(not words, f"{label}: остался английский текст: {', '.join(sorted(words)[:8])}")
        label_words = technical_label_words(value)
        check.require(
            not label_words,
            f"{label}: осталась английская подпись Foundry-ссылки: {', '.join(sorted(label_words)[:8])}",
        )
        check.require(not BROKEN_PROSE_RE.search(plain), f"{label}: повреждена фраза PDF-конверсии")
        check.require(not BROKEN_INLINE_MARKUP_RE.search(value), f"{label}: повреждена внутренняя разметка")
    for label, values in (
        ("папка", folders.values()),
        ("макрос", [macro.get("name", "") for macro in macros.values()]),
        ("плейлист", [playlist.get("name", "") for playlist in playlists.values()]),
        ("звук", [sound.get("name", "") for playlist in playlists.values() for sound in playlist.get("sounds", {}).values()]),
    ):
        for value in values:
            words = {word.lower() for word in LATIN_RE.findall(value)} - ALLOWED_LATIN
            check.require(not words, f"{label} не переведён: {value}")

    if args.source:
        source = load_json(args.source, check)
        if isinstance(source, list):
            source = source[0] if len(source) == 1 else {}
        source_macros = {macro.get("_id"): macro for macro in source.get("macros", [])}
        check.require(set(source_macros) == set(macros), "официальный источник содержит другой набор макросов")
        for macro_id, expected_hash in index.get("macroCommandHashes", {}).items():
            actual_hash = hashlib.sha256(source_macros.get(macro_id, {}).get("command", "").encode()).hexdigest()
            check.require(actual_hash == expected_hash, f"{macro_id}: команда официального макроса отличается от контрольной")
        source_items = {
            (actor.get("_id"), item.get("_id")): item.get("system", {}).get("description", {}).get("value", "")
            for actor in source.get("actors", [])
            for item in actor.get("items", [])
        }
        for actor_id, item in all_item_entries:
            translated_value = item.get("description")
            if not isinstance(translated_value, str) or not translated_value:
                continue
            source_value = source_items.get((actor_id, item.get("id")), "")
            check.require(bool(source_value), f"{actor_id}/{item.get('id')}: нет элемента в официальном источнике")
            check.require(
                Counter(technical_cores(translated_value)) == Counter(technical_cores(source_value)),
                f"{actor_id}/{item.get('id')}: изменены технические токены относительно Adventure",
            )
            check.require(
                Counter(inline_roll_cores(translated_value)) == Counter(inline_roll_cores(source_value)),
                f"{actor_id}/{item.get('id')}: изменены броски относительно Adventure",
            )
            check.require(
                html_hash(translated_value) == html_hash(source_value),
                f"{actor_id}/{item.get('id')}: изменена HTML-структура относительно Adventure",
            )

    raw = args.translation.read_text(encoding="utf-8").lower()
    for needle in FORBIDDEN:
        check.require(needle not in raw, f"запрещённая строка в переводе: {needle}")

    if check.errors:
        print("\n".join(f"ОШИБК: {error}" for error in check.errors), file=sys.stderr)
        print(f"\nПроверка не пройдена: {len(check.errors)} ошибок.", file=sys.stderr)
        return 1

    print("Проверка пройдена: 7 журналов, 116 текстовых страниц, 71 галерея, 19 сцен, 113 актёров, 271 встроенный элемент.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
