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

TECH_RE = re.compile(r"@[A-Za-z][A-Za-z0-9]*\[[^\]]+\](?:\{[^{}]*\})?")
TECH_CORE_RE = re.compile(r"(@[A-Za-z][A-Za-z0-9]*\[[^\]]+\])(?:\{[^{}]*\})?")
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
    plain = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", value)))
    return re.findall(r"[A-Za-zА-Яа-яЁё'’-]+", plain)


def html_hash(value: str) -> str:
    return hashlib.sha256("\n".join(TAG_RE.findall(value)).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translation", type=Path, default=Path("translations/pf2e-rusthenge.adventures.json"))
    parser.add_argument("--index", type=Path, default=Path("data/source-index.json"))
    parser.add_argument("--module", type=Path, default=Path("module.json"))
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
    check.require(len(journals) == 7, "должно быть 7 журналов")
    check.require(len(scenes) == 19, "должно быть 19 сцен")
    check.require(len(actors) == 113, "должно быть 113 актёров")
    check.require("macros" not in adventure, "макросы не должны переопределяться")
    check.require("playlists" not in adventure, "плейлисты не должны переопределяться")

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
        image_paths = set(IMAGE_PATH_RE.findall(text))
        link_paths = set(LINK_PATH_RE.findall(text))
        check.require(set(page_meta.get("sourceImagePaths", [])) <= image_paths, f"{page_id}: потерян путь к изображению")
        check.require(set(page_meta.get("sourceLinkPaths", [])) <= link_paths, f"{page_id}: потеряна HTML-ссылка")
        check.require(not SUSPICIOUS_HYPHEN_RE.search(text), f"{page_id}: остался перенос слова из PDF")
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
        plain = html.unescape(TAG_RE.sub(" ", TECH_RE.sub(" ", text)))
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
            technical_tokens(value) == expected_tokens,
            f"{path}: изменены технические токены актёра/элемента",
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
