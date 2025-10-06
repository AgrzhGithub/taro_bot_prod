# -*- coding: utf-8 -*-
import os
from pathlib import Path
import pytest

# ВАЖНО: запускать pytest из КОРНЯ проекта или добавить PYTHONPATH=.
from handlers.daily_card import (
    _ALLOWED_CARD_NAMES,
    find_card_image_path,
    _CARD_IMAGE_DIRS,
    _IMG_EXTS,
)

def _human_readable_dirs():
    return ", ".join(str(p) for p in _CARD_IMAGE_DIRS)

@pytest.mark.integration
def test_all_allowed_cards_have_images_on_real_fs():
    """
    Интеграционный тест: проверяет, что КАЖДАЯ карта из _ALLOWED_CARD_NAMES
    реально имеет файл изображения в одном из каталогов _CARD_IMAGE_DIRS
    (расширения: _IMG_EXTS). Использует find_card_image_path ровно как в боевом коде.
    """
    missing = []
    wrong_ext = []

    for name in _ALLOWED_CARD_NAMES:
        hit = find_card_image_path(name)
        if not hit:
            missing.append(name)
            continue

        # Доп. контроль: найденный файл действительно с допустимым расширением
        ext_ok = Path(hit).suffix.lower() in _IMG_EXTS
        if not ext_ok:
            wrong_ext.append((name, hit))

    msg = []
    if missing:
        msg.append(
            "❌ Не найдены изображения для карт:\n- " + "\n- ".join(missing)
        )
        # Подсказка, куда класть:
        msg.append(
            f"\nПроверь директории: {_human_readable_dirs()}\n"
            f"Разрешённые расширения: {', '.join(_IMG_EXTS)}\n"
            "Имена файлов должны совпадать с названием карты (пробелы -> _), например:\n"
            "  data/cards/Иерофант.jpg\n  data/cards/Справедливость.jpg"
        )

    if wrong_ext:
        msg.append(
            "⚠️ Найдены файлы с недопустимым расширением:\n" +
            "\n".join(f"- {n}: {p}" for n, p in wrong_ext) +
            f"\nРазрешённые расширения: {', '.join(_IMG_EXTS)}"
        )

    if msg:
        pytest.fail("\n\n".join(msg))


@pytest.mark.integration
def test_specific_major_arcana_examples_present():
    """
    Точечный контроль самых частых проблем: у этих двух карт часто забывают картинки.
    Тест сразу подсветит, если они отсутствуют.
    """
    majors_to_check = ["Иерофант", "Справедливость"]
    missing = [n for n in majors_to_check if not find_card_image_path(n)]
    if missing:
        pytest.fail(
            "❌ Нет изображений у ключевых старших арканов:\n- " +
            "\n- ".join(missing) +
            f"\nПоложи файлы в одну из директорий: {_human_readable_dirs()}\n"
            "Например:\n"
            "  data/cards/Иерофант.jpg\n  data/cards/Справедливость.jpg"
        )
