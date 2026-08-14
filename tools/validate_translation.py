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
EMPTY_LIST_RE = re.compile(r"<(?:ul|ol)\b[^>]*>\s*(?:<li\b[^>]*>\s*</li>\s*)*</(?:ul|ol)>", re.I)
EXPECTED_COUNTS = {
    "journals": 7,
    "pages": 191,
    "translatedTextPages": 116,
    "servicePagesOriginal": 4,
    "galleryPages": 71,
    "scenes": 19,
    "notes": 176,
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


def visible_words(value: str) -> list[str]:
    plain = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", value))))
    return re.findall(r"[A-Za-zА-Яа-яЁё'’-]+", plain)


def html_hash(value: str) -> str:
    return hashlib.sha256("\n".join(TAG_RE.findall(value)).encode()).hexdigest()


def inline_roll_cores(value: str) -> list[str]:
    return [re.sub(r"\{[^{}]*\}$", "", roll) for roll in INLINE_ROLL_RE.findall(value)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translation", type=Path, default=Path("translations/pf2e-rusthenge.adventures.json"))
    parser.add_argument("--index", type=Path, default=Path("data/source-index.json"))
    parser.add_argument("--module", type=Path, default=Path("module.json"))
    parser.add_argument("--source", type=Path, help="Официальный Adventure для локальной проверки команд макросов")
    args = parser.parse_args()
    check = Validation()
    translation = load_json(args.translation, check)
    index = load_json(args.index, check)
    manifest = load_json(args.module, check)
    if check.errors:
        print("\n".join(f"ОШИБК: {e}" for e in check.errors), file=sys.stderr)
        return 1

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

    for page_id, page_meta in index.get("pages", {}).items():
        text = pages.get(page_id, {}).get("text", "")
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

    custom_items = [item for actor in actors.values() for item in actor.get("items", [])]
    check.require(len(custom_items) == 271, "должно быть 271 перевод встроенных несистемных элементов")
    actor_items = {
        actor_id: {item.get("id"): item for item in actor.get("items", [])}
        for actor_id, actor in actors.items()
    }
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
        ("страница", [p.get("name", "") for p in pages.values()]),
    ):
        for value in values:
            words = {w.lower() for w in LATIN_RE.findall(value)} - ALLOWED_LATIN
            check.require(not words, f"{label} не переведён: {value}")

    check.require(sum("description" in actor for actor in actors.values()) == 43, "неполный перевод публичных заметок актёров")
    check.require(sum("descriptionGM" in actor for actor in actors.values()) == 4, "неполный перевод приватных заметок актёров")
    check.require(sum("description" in item for item in custom_items) == 125, "неполный перевод описаний встроенных элементов")
    check.require(sum("gm" in item for item in custom_items) == 5, "неполный перевод GM-описаний встроенных элементов")
    for label, value in [
        *[(f"актёр {actor.get('name', '')}", actor.get("description", "")) for actor in actors.values()],
        *[(f"GM актёра {actor.get('name', '')}", actor.get("descriptionGM", "")) for actor in actors.values()],
        *[(f"элемент {item.get('name', '')}", item.get("description", "")) for item in custom_items],
        *[(f"GM элемента {item.get('name', '')}", item.get("gm", "")) for item in custom_items],
    ]:
        plain = html.unescape(TAG_RE.sub(" ", INLINE_ROLL_RE.sub(" ", TECH_RE.sub(" ", value))))
        words = {word.lower() for word in LATIN_RE.findall(plain)} - ALLOWED_LATIN
        check.require(not words, f"{label}: остался английский текст: {', '.join(sorted(words)[:8])}")
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
