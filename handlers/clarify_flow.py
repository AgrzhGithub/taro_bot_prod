# handlers/clarify_flow.py
from __future__ import annotations

"""
Экран выбора направлений/сценариев раскладов с полноценной индикацией «печатает…»
во время всех долгих операций LLM. Без гифок в ходе советов/раскладов.
Интро-медиа (если есть) — только как вступление (data/spreads/*.mp4|.gif|.webm).
"""

from typing import Any, Dict, List, Tuple
import os
import re
import random
import asyncio
import contextlib

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatAction

from services.tarot_ai import draw_cards, gpt_make_prediction
from services.billing import ensure_user, spend_one_or_pass
from keyboards_inline import advice_inline_limits
from db import SessionLocal, models


router = Router()

# =========================
# НАПРАВЛЕНИЯ (подтемы)
# =========================
DIRECTIONS: List[Tuple[str, str]] = [
    ("Гадания на отношения", "love"),
    ("Гадания о будущем", "future"),
    ("Гадания для самопознания и познания другого человека", "self"),
    ("Гадания на работу", "work"),
]

# =========================
# Сценарии по направлениям
# =========================

# --- 1) Отношения ---
SCENARIOS_LOVE: List[Dict[str, Any]] = [
    {"title": "На отношение к вам другого человека",
     "points": ["мысли", "чувства", "подсознание"]},
    {"title": "Гадание на прояснение отношений",
     "points": [
         "как вы относитесь к человеку",
         "как человек относится к вам",
         "что мешает вам быть вместе",
         "что мешает человеку быть вместе с вами",
         "будущее, ответ на ваш вопрос",
         "пояснение к будущему",
     ]},
    {"title": "На любимого человека",
     "points": [
         "о чём человек думает",
         "что на сердце",
         "чего желает",
         "что у человека в жизни сейчас",
         "ближайшее будущее",
         "непредвиденные обстоятельства в ближайшем будущем",
     ]},
    {"title": "Сила любви по шкале 100%",
     "points": ["насколько сильно любит загаданная персона (в процентах)"]},
    {"title": "На чувства любимого человека",
     "points": [
         "любит ли человек вас",
         "что хочет получить от ваших отношений",
         "есть ли для вас угроза в отношениях",
     ]},
    {"title": "Скрытая информация",
     "points": [
         "отношение к вам в прошлом",
         "была ли у вас причина беспокоиться в прошлом",
         "отношение к вам в настоящем",
         "есть ли у вас причина беспокоиться сейчас",
         "отношение к вам в будущем",
         "будет ли для вас в будущем причина беспокоиться",
         "ближайшее будущее",
         "отдалённое будущее",
     ]},
    {"title": "Помиримся ли мы",
     "points": [
         "есть ли сейчас причина для ссоры",
         "любит ли ещё вас человек",
         "хватает ли вам обоим всего, или вы чем-то обделены",
         "не являются ли деньги источником проблем",
         "совместимость",
         "хочет ли партнёр всё бросить или хочет всё исправить",
         "есть ли проблемы с зависимостями",
         "давите ли вы друг на друга негативом",
         "ситуация на ближайшее будущее",
         "итог",
     ]},
    {"title": "Расклад мистерия любви",
     "points": [
         "потенциал пары как союза",
         "зрелость и готовность партнёра А к семье",
         "зрелость и готовность партнёра Б к семье",
         "совместимость ценностей и целей",
         "готовность к ответственности и быту",
         "прогноз: способна ли пара создать семью",
     ]},
    {"title": "Расклад партнёр",
     "points": [
         "сходство, чем похож(а) на вас",
         "какие ваши качества усиливает",
         "в чём человек противоположен вам",
         "риски и возможные потери",
         "куда он(а) вас ведёт, каких вершин помогает достичь",
         "тайна, что от вас скрывается",
     ]},
    {"title": "События настоящего",
     "points": [
         "причина интереса к вам со стороны человека",
         "что вы получаете от ваших отношений",
         "что человек получает от ваших отношений",
         "проблемы на данный момент",
     ]},
    {"title": "Расклад по прошлому ваших отношений",
     "points": [
         "почему человек начал встречаться со мной",
         "оправдались ли эти ожидания",
         "что наносило вред отношениям",
         "что помогало отношениям",
         "будет ли сейчас человек проявлять инициативу",
         "перспективы отношений",
     ]},
]

# --- 2) Будущее ---
SCENARIOS_FUTURE: List[Dict[str, Any]] = [
    {
        "title": "Краткий прогноз на будущее",
        "points": [
            "есть ли помеха в настоящем",
            "будет ли помеха в будущем",
            "результат, будущее, ответ на ваш вопрос",
        ],
    },
    {
        "title": "Общий прогноз на будущее",
        "points": [
            "общий прогноз на загаданный период времени",
            "что вас ждёт в личной жизни в этот период",
            "что вас ждёт в материальном плане",
        ],
    },
    {
        "title": "Анализ будущей ситуации",
        "points": [
            "на что обратить внимание",
            "в чём вы ошибаетесь",
            "настоящее",
            "как будут развиваться события",
            "будущее, итог",
        ],
    },
    {
        "title": "Гадание на прошлое",
        "points": [
            "общая характеристика прошлого",
            "кармическое влияние на прошлое человека",
            "влияние окружения на прошлые события",
            "в чём была главная проблема",
            "что в большей степени влияло на ситуацию",
            "настоящее",
            "вероятное будущее",
        ],
    },
    {
        "title": "Судьба и будущие события",
        "points": [
            "текущая ситуация",
            "ближайшее будущее",
            "более отдалённое будущее",
            "судьба",
        ],
    },
    {
        "title": "Семь домов — подробный расклад на будущее",
        "points": [
            "общее состояние человека в этот период времени (чувства, здоровье)",
            "семья, родственники, близкие",
            "эмоции: надежды и желания",
            "сомнения и опасения",
            "планы и цели",
            "то, что скрыто, но в ближайшее время станет явным",
            "ближайшее будущее",
            "более отдалённое будущее",
        ],
    },
]

# --- 3) Самопознание и познание другого человека ---
SCENARIOS_SELF: List[Dict[str, Any]] = [
    {
        "title": "Прояснение различных сторон жизни человека",
        "points": [
            "что волнует человека",
            "дела и работа",
            "финансовые вопросы и материальное благосостояние",
            "неожиданные события",
        ],
    },
    {
        "title": "Расклад на личность человека",
        "points": [
            "общее описание личности, характер",
            "описание прошлого, в какой среде человек жил",
            "будущее человека",
            "в чём видит проблему, которая лежит перед ним",
            "идеалы человека, в чём видит моральную силу",
            "материальное положение человека",
            "дальнейшая судьба",
        ],
    },
    {
        "title": "Психологический портрет человека",
        "points": [
            "в чём наше мнение о нас самих совпадает с мнением окружающих",
            "неизвестные силы внутри нас",
            "скрытое в тени",
            "белое пятно",
        ],
    },
    {
        "title": "Расклад на личность",
        "points": [
            "это вы сейчас",
            "вызов, который бросает вам судьба",
            "на что вы должны ориентироваться",
        ],
    },
]

# --- 4) Работа ---
SCENARIOS_WORK: List[Dict[str, Any]] = [
    {
        "title": "Гадание на исход дела",
        "points": [
            "прошлое",
            "настоящее",
            "будущее",
        ],
    },
    {
        "title": "Оптимальное решение",
        "points": [
            "уместно ли положительное решение",
            "уместно ли отрицательное решение",
            "последствия положительного решения",
            "последствия отрицательного решения",
            "факторы, не принятые во внимание",
            "факторы, значимость которых была преувеличена",
            "результат претворения решения в жизнь (три карты)",
        ],
    },
    {
        "title": "Расклад на здоровье и эмоциональное состояние",
        "points": [
            "здоровье и настроение в настоящем",
            "что способствует укреплению здоровья",
            "чем наносится вред",
            "общий прогноз на будущее",
            "особенности здоровья, которые проявятся в будущем",
        ],
    },
    {
        "title": "Расклад на отпуск",
        "points": [
            "общий характер поездки",
            "характер условий пребывания",
            "особенности места отдыха",
            "вероятность новых знакомств",
            "развлечения",
            "возможные проблемы",
            "качество отдыха",
            "возможность продолжения завязанных знакомств",
        ],
    },
    {
        "title": "Расклад на путешествие",
        "points": [
            "цель путешествия",
            "характер взаимоотношений с официальными лицами",
            "общий характер путешествия",
            "личные ожидания человека от путешествия",
            "насколько оправдаются ожидания",
            "новые знакомства",
            "обстановка в том месте, куда планируется поездка",
            "материальная выгода от путешествия",
        ],
    },
    {
        "title": "Расклад на новый бизнес или новую работу",
        "points": [
            "возможна ли удача в новом деле",
            "возможные проблемы в настоящем и ближайшем будущем",
            "ваша предрасположенность к занятию этой работой",
            "перспективы",
            "общий характер ситуации: прибыли, потери",
            "коллеги, служащие",
            "прогноз на отдалённое будущее",
        ],
    },
]

SCENARIOS_BY_KEY = {
    "love": SCENARIOS_LOVE,
    "future": SCENARIOS_FUTURE,
    "self": SCENARIOS_SELF,
    "work": SCENARIOS_WORK,
}

THEME_BY_KEY = {
    "love": "Отношения",
    "future": "Будущее",
    "self": "Самопознание",
    "work": "Работа",
}

# ------------------ FSM ------------------
class ClarifyFSM(StatesGroup):
    picking_direction = State()
    waiting_choice = State()
    processing = State()

# ------------------ Эмодзи для низа итога ------------------
MAGIC_FOOTER = "🔮✨🌙✨🔮"

# ------------------ Утилиты форматирования/очистки ------------------
EMOJI_RX = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002500-\U00002BEF\U00002600-\U000026FF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF\ufe0f\ufe0e]",
    flags=re.UNICODE,
)
_SENT_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
_ITOG_HEADER_RE = re.compile(r"(?im)^\s*(?:🌙\s*)?Итог\s*:?\s*")

ADVICE_HINTS = [
    "совет", "советую", "рекоменд", "стоит", "следует", "лучше",
    "нужно", "необходимо", "постарайтесь", "попробуйте", "сделайте",
    "возьмите", "должны", "вам стоит", "вам следует", "рекомендую",
    "избегайте", "продолжайте", "планируйте", "подума", "уделите",
    "сконцентрируйтесь", "сосредоточьтесь", "начните", "перестаньте"
]

def _collapse_spaces(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"(?m)^[ \t]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def strip_emojis(text: str) -> str:
    return EMOJI_RX.sub("", text or "")

def strip_bullets(text: str) -> str:
    t = re.sub(r"(?m)^\s*[•\-\*\u2022\u25CF>\u27A1\u279C\u25B6]+\s*", "", text or "")
    return re.sub(r"\n{3,}", "\n\n", t).strip()

LINE_DROP_RX = re.compile(r"(?im)^\s*(итог|вывод|совет|рекомендац\w*)\s*:\s*.*$", re.UNICODE | re.MULTILINE)
INLINE_ITOG_RX = re.compile(r"(?im)\b(итог|вывод|совет)\s*:\s*[^.\n]*[^\n]*")

def remove_itog_advice_lines(text: str) -> str:
    t = LINE_DROP_RX.sub("", text or "")
    t = INLINE_ITOG_RX.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t

def collapse_card_named_lines_to_paragraph(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    rhs_parts, other = [], []
    pattern = re.compile(r'^[\-\*\•\u25CF\s]*[A-Za-zА-Яа-яЁё0-9 ]{1,30}\s*[—\-:]\s*(.+)$')
    for l in lines:
        m = pattern.match(l)
        if m:
            rhs_parts.append(m.group(1).strip())
        else:
            other.append(l)
    if len(rhs_parts) >= 2:
        paragraph = " ".join(rhs_parts)
        text = ("\n\n".join(other + [paragraph])).strip() if other else paragraph
    return text

def sanitize_answer(text: str) -> str:
    t = remove_itog_advice_lines(text)
    t = strip_emojis(t)
    t = strip_bullets(t)
    return _collapse_spaces(t)

def sanitize_summary(text: str) -> str:
    t = remove_itog_advice_lines(text)
    t = strip_emojis(t)
    t = strip_bullets(t)
    t = re.sub(r"(?m)^\s*(\d+[\).\:]|\-|\•)\s+.*$", "", t)
    t = collapse_card_named_lines_to_paragraph(t)
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # убрать возможные упоминания карт из итога
    t = re.sub(r"(?i)\b(туз|двойка|тройка|четвёрка|пятёрка|шестёрка|семёрка|восьмёрка|девятка|десятка|паж|рыцарь|королева|король|шут|маг|жрица|императрица|император|жрец|влюблённые|колесница|сила|отшельник|колесо фортуны|справедливость|повешенный|смерть|умеренность|дьявол|башня|звезда|луна|солнце|суд|мир)\b.*?(жезл|чаш|кубк|меч|пентакл)", "", t)
    t = re.sub(r"\(\s*перев[ёе]рнут[аяы].*?\)", "", t)
    return t.strip()

def starify_card_header_block(text: str) -> str:
    """Гарантируем '🃏 Карта:' в начале сообщения по карте (заменили ⭐️ на 🃏)."""
    if not isinstance(text, str):
        return text
    text = _collapse_spaces(text)
    # заменяем любую 'Карта:' в начале на вариант с эмодзи карты
    text = re.sub(r"(?m)^\s*(?:⭐️\s*)?Карта:", "🃏 Карта:", text, count=1)
    return text

def itog_three_sentences_no_advice(text: str) -> str:
    """
    Приводит блок 'Итог' к одному абзацу, ровно 3 предложения, без советов.
    Принимает ТОЛЬКО сам текст итога (без заголовка).
    """
    t = _collapse_spaces(text)
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()

    # фильтруем предложения с советными словами
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(t) if s.strip()]
    clean = [s for s in sentences if not any(h in s.lower() for h in ADVICE_HINTS)]

    # доводим до ровно трёх
    clean = clean[:3]
    while len(clean) < 3:
        filler = "Ситуация развивается последовательно."
        if clean and filler.lower() == clean[-1].lower():
            filler = "Динамика остаётся устойчивой."
        clean.append(filler)

    joined = " ".join(s if s.endswith(('.', '!', '?')) else s + '.' for s in clean)
    joined = re.sub(r"\s{2,}", " ", joined).strip()

    # ограничение длины (≈ 350 символов)
    if len(joined) > 350:
        words, acc, total = joined.split(), [], 0
        for w in words:
            add = len(w) + (1 if acc else 0)
            if total + add > 350:
                break
            acc.append(w)
            total += add
        joined = " ".join(acc).rstrip(" ,;:") + "."

    return joined

# ---------- НОВОЕ: «умные» варианты имён карт для удаления дублей ----------
def _card_name_variants_regex(card_name: str) -> str:
    """
    Строит regex, совпадающий с именем карты и частыми падежными вариантами мастей,
    чтобы убирать дубли вида «Туз Жезлов (перевёрнутая)» после «Карта: Туз Жезлы (перевёрнутая)».
    """
    if not isinstance(card_name, str) or not card_name.strip():
        return re.escape(card_name or "")

    words = card_name.strip().split()
    suit_map = {
        "жезлы": r"Жезл(?:ы|ов)",
        "кубки": r"Кубк(?:и|ов)",
        "чаши": r"Чаш(?:и|)",
        "мечи": r"Меч(?:и|ей)",
        "пентакли": r"Пентакл(?:и|ей)",
    }

    def suit_pattern(token: str) -> str:
        low = token.lower().replace("ё", "е")
        return suit_map.get(low, re.escape(token))

    if len(words) >= 2:
        head = r"\s+".join(re.escape(w) for w in words[:-1])
        tail_pat = suit_pattern(words[-1])
        return rf"{head}\s+{tail_pat}"
    else:
        return re.escape(words[0])

def drop_leading_card_header(text: str, card_name: str) -> str:
    """
    Убирает в начале толкования:
    • строки вида "Карта: …"
    • повтор имени карты (в т.ч. падежные варианты мастей) с/без "(перевёрнутая)" и тире/двоеточия
    • лишний перенос после удаления
    """
    if not isinstance(text, str):
        return text
    t = text.strip()

    # 1) Любая шапка "Карта: …" (с эмодзи или без)
    t = re.sub(r'^(?:[⭐️🃏]\s*)?Карта:\s*[^\n]*\n+', '', t, flags=re.IGNORECASE)

    # 2) Повтор имени карты (включая падежные варианты мастей)
    name_pat = _card_name_variants_regex(card_name)
    repeat_rx = rf'^(?:{name_pat})(?:\s*\((?:перев[ёе]рнут\w*|reversed)[^)]*\))?\s*(?:[—\-:]\s*)?(?:\n+|$)'
    t = re.sub(repeat_rx, '', t, flags=re.IGNORECASE)

    # 3) Если осталась пустая первая строка/двойной перенос — схлопнем
    t = re.sub(r'^\s*\n+', '', t)

    return t.strip()

def enforce_second_person(text: str) -> str:
    """
    Приводит формулировку к 2-му лицу (Вы) на уровне мягких правок.
    Основной упор — на промпт для LLM; функция страхует отдельные случаи.
    """
    if not isinstance(text, str):
        return text
    t = _collapse_spaces(text)

    t = re.sub(r'(?im)^\s*(человек|он|она)\b', "Вы", t, count=1)
    t = re.sub(r'(?m)(^|\.\s+)(вы)\b', r'\1Вы', t)
    t = re.sub(r'(?m)(^|\.\s+)Человек\b', r'\1Вы', t)
    t = re.sub(r'(?i)\bзадающ(ий|его|ему|ем|им)\b', "Вы", t)
    return t.strip()

# ------------------ Индикация «печатает…» ------------------
class _TypingAction:
    """
    Контекст-менеджер: пока внутри — раз в interval сек отправляется send_chat_action(TYPING).
    Использование:
        async with typing_action(message.bot, message.chat.id):
            ... долгий вызов ...
    """
    def __init__(self, bot, chat_id: int, interval: float = 4.0):
        self.bot = bot
        self.chat_id = chat_id
        self.interval = interval
        self._task: asyncio.Task | None = None

    async def __aenter__(self):
        async def _loop():
            try:
                while True:
                    await self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)
                    await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                pass

        self._task = asyncio.create_task(_loop())
        await self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

def typing_action(bot, chat_id: int, interval: float = 4.0) -> _TypingAction:
    return _TypingAction(bot, chat_id, interval)

# ------------------ Медиа из data/spreads (опционально) ------------------
def _pick_intro_media() -> str | None:
    folder = os.path.join("data", "spreads")
    if not os.path.isdir(folder):
        return None
    exts = (".mp4", ".gif", ".webm")
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
    return random.choice(files) if files else None

async def send_intro_with_caption(cb: CallbackQuery, caption: str) -> None:
    """
    Интро-медиа (если есть). В caption — только шапка.
    «Карта: ...» отправляется отдельными сообщениями далее.
    """
    path = _pick_intro_media()
    if not path:
        await cb.message.answer(_collapse_spaces(caption), parse_mode=None)
        return

    cap = caption[:1024]
    rest = caption[1024:]

    try:
        file = FSInputFile(path)
        await cb.message.answer_animation(file, caption=_collapse_spaces(cap), parse_mode=None)
        if rest.strip():
            await cb.message.answer(_collapse_spaces(rest.strip()), parse_mode=None)
    except Exception:
        await cb.message.answer(_collapse_spaces(caption), parse_mode=None)

# ------------------ Сервисные утилиты ------------------
async def _safe_cb_answer(cb: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    """Безопасный ответ на callback — сразу гасим «часики», игнорируем TelegramBadRequest."""
    try:
        await cb.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest:
        pass

# ------------------ Клавиатуры ------------------
def numbers_kb(count: int, prefix: str, add_menu: bool = True) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i in range(1, count + 1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"{prefix}:{i}"))
        if len(row) == 5:
            rows.append(row); row = []
    if row:
        rows.append(row)
    if add_menu:
        rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _norm_menu_btn(text: str) -> str:
    t = re.sub(r"(?i)\s*в\s*меню\s*", "В меню", strip_emojis(text or "")).strip()
    return "В меню" if re.search(r"(?i)меню", t) else (text or "")

def merge_advice_nav_kb(advice_kb: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """
    Добавляет к советам кнопки 'Ещё по списку' и 'В меню', убирает дубли и ссылку 'к предсказанию'.
    """
    new_rows: List[List[InlineKeyboardButton]] = []
    seen_pairs = set()
    seen_menu = False

    for row in (advice_kb.inline_keyboard if advice_kb and advice_kb.inline_keyboard else []):
        out: List[InlineKeyboardButton] = []
        for btn in row:
            text = (btn.text or "").strip()
            data = (btn.callback_data or "").strip()

            if re.search(r"(?i)к\s*предсказан", text):
                continue

            norm_text = _norm_menu_btn(text)
            if norm_text == "В меню":
                if not seen_menu:
                    seen_menu = True
                    out.append(InlineKeyboardButton(text="🏠 В меню", callback_data="nav:menu"))
                continue

            key = (norm_text, data)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            out.append(InlineKeyboardButton(text=text, callback_data=data))
        if out:
            new_rows.append(out)

    new_rows.append([InlineKeyboardButton(text="🔁 Ещё по списку", callback_data="menu:theme")])
    if not seen_menu:
        new_rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="nav:menu")])

    return InlineKeyboardMarkup(inline_keyboard=new_rows)

# =========================
# Открыть СПИСОК НАПРАВЛЕНИЙ
# =========================
@router.callback_query(F.data == "menu:theme")
async def open_direction_list(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_cb_answer(cb)

    blocks: List[str] = [f"{idx}. {title}" for idx, (title, _key) in enumerate(DIRECTIONS, start=1)]
    text = "Выберите направление\n\n" + "\n".join(blocks) + "\n\nНажмите цифру ниже 👇"

    try:
        await cb.message.edit_text(text, reply_markup=numbers_kb(len(DIRECTIONS), prefix="cat"), parse_mode=None)
    except Exception:
        await cb.message.answer(text, reply_markup=numbers_kb(len(DIRECTIONS), prefix="cat"), parse_mode=None)
    await state.set_state(ClarifyFSM.picking_direction)

# =========================
# Выбор НАПРАВЛЕНИЯ → показать сценарии
# =========================
@router.callback_query(ClarifyFSM.picking_direction, F.data.startswith("cat:"))
async def category_chosen(cb: CallbackQuery, state: FSMContext):
    await _safe_cb_answer(cb)

    idx = int(cb.data.split(":")[1]) - 1
    if idx < 0 or idx >= len(DIRECTIONS):
        await cb.answer("Некорректный выбор")
        return

    title, key = DIRECTIONS[idx]
    scenarios = SCENARIOS_BY_KEY.get(key, [])
    await state.update_data(current_direction_key=key, current_direction_title=title)

    if not scenarios:
        await cb.message.edit_text(
            f"Направление: {title}\n\nСписок сценариев будет добавлен позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Ещё по списку", callback_data="menu:theme")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="nav:menu")],
            ]),
            parse_mode=None
        )
        return

    blocks: List[str] = []
    for i, sc in enumerate(scenarios, start=1):
        inner = "\n".join([f"   • {p}" for p in sc.get("points", [])]) if sc.get("points") else ""
        blocks.append(f"{i}. {sc['title']}" + (f"\n{inner}" if inner else ""))

    text = f"Направление: {title}\n\nВыберите тему\n\n" + "\n\n".join(blocks) + "\n\nНажмите цифру ниже 👇"

    try:
        await cb.message.edit_text(text, reply_markup=numbers_kb(len(scenarios), prefix="scenario"), parse_mode=None)
    except Exception:
        await cb.message.answer(text, reply_markup=numbers_kb(len(scenarios), prefix="scenario"), parse_mode=None)
    await state.set_state(ClarifyFSM.waiting_choice)

# =========================
# ВЫБОР СЦЕНАРИЯ внутри направления
# =========================
@router.callback_query(ClarifyFSM.waiting_choice, F.data.startswith("scenario:"))
async def scenario_chosen(cb: CallbackQuery, state: FSMContext):
    await _safe_cb_answer(cb)

    # Плейсхолдер статуса (без гифок)
    try:
        if cb.message:
            await cb.message.edit_text("🔮 Готовлю расклад…", parse_mode=None)
    except TelegramBadRequest:
        pass

    data = await state.get_data()
    dir_key = data.get("current_direction_key")
    dir_title = data.get("current_direction_title") or THEME_BY_KEY.get(dir_key, "Тема")

    scenarios = SCENARIOS_BY_KEY.get(dir_key, [])
    idx = int(cb.data.split(":")[1]) - 1
    if idx < 0 or idx >= len(scenarios):
        await cb.message.answer("Некорректный выбор")
        return

    scenario = scenarios[idx]
    points = scenario.get("points", [])
    n = max(1, len(points))

    # списание
    ok, src = await spend_one_or_pass(cb.from_user.id)
    if not ok:
        kb = numbers_kb(len(DIRECTIONS), prefix="cat")
        if src == "pass_rate_limit":
            await cb.message.edit_text("⏳ Слишком часто. Попробуйте через минуту.", reply_markup=kb, parse_mode=None)
        elif src == "pass_day_limit":
            await cb.message.edit_text("📅 Дневной лимит подписки исчерпан. Попробуйте завтра.", reply_markup=kb, parse_mode=None)
        else:
            await cb.message.edit_text("❌ Нет доступных сообщений. Купите пакет или оформите подписку 🛒", parse_mode=None)
        await state.clear()
        return

    # тянем карты
    try:
        cards = draw_cards(n)
        card_names = [c.get("name") or c.get("title") for c in cards]
    except Exception:
        card_names = ["—"] * n

    await state.set_state(ClarifyFSM.processing)

    # лог
    user = await ensure_user(cb.from_user.id, cb.from_user.username)
    async with SessionLocal() as s:
        s.add(models.SpreadLog(
            user_id=user.id,
            theme=dir_title,
            spread=f"{dir_key}_scenario_{idx+1}",
            cards={"cards": card_names},
            cost=1
        ))
        await s.commit()

    # ---------- шапка ----------
    header = f"🔮 Ваш расклад готов!\n\n{dir_title} — {scenario['title']}\n\n🃏 Карты: {', '.join(card_names)}"
    combined_parts: List[str] = [f"{dir_title} — {scenario['title']}", f"Карты: {', '.join(card_names)}", ""]

    # Интро (если есть медиа)
    await send_intro_with_caption(cb, header)

    # ---------- первый пункт ----------
    start_i = 0
    if points:
        c0 = card_names[0] if card_names else "—"
        async with typing_action(cb.message.bot, cb.message.chat.id):
            try:
                raw0 = await asyncio.wait_for(
                    gpt_make_prediction(
                        question=points[0], theme=dir_title, spread="auto", cards_list=c0, scenario_ctx=scenario["title"]
                    ),
                    timeout=60
                )
                a0 = sanitize_answer(raw0)
                a0 = drop_leading_card_header(a0, c0)
            except asyncio.TimeoutError:
                a0 = "Толкование готовится дольше обычного. Попробуйте ещё раз."
            except Exception:
                a0 = "Не удалось получить толкование. Попробуйте ещё раз позже."

        first_block = starify_card_header_block(f"Карта: {c0}\n\n{a0}")
        await cb.message.answer(first_block, parse_mode=None)

        combined_parts += [first_block, ""]
        start_i = 1

    # ---------- остальные пункты ----------
    for i in range(start_i, len(points)):
        c = card_names[i] if i < len(card_names) else "—"
        async with typing_action(cb.message.bot, cb.message.chat.id):
            try:
                raw = await asyncio.wait_for(
                    gpt_make_prediction(
                        question=points[i], theme=dir_title, spread="auto", cards_list=c, scenario_ctx=scenario["title"]
                    ),
                    timeout=60
                )
                a = sanitize_answer(raw)
                a = drop_leading_card_header(a, c)
            except asyncio.TimeoutError:
                a = "Толкование готовится дольше обычного. Попробуйте ещё раз."
            except Exception:
                a = "Не удалось получить толкование. Попробуйте ещё раз позже."

        block = starify_card_header_block(f"Карта: {c}\n\n{a}")
        await cb.message.answer(block, parse_mode=None)
        combined_parts += [block, ""]

    # ---------- общий итог ----------
    async with typing_action(cb.message.bot, cb.message.chat.id):
        try:
            # Собираем ТОЛЬКО тексты толкований без заголовков "Карта: ..."
            card_texts_only: List[str] = []
            for block in combined_parts:
                cleaned = re.sub(r"(?im)^[🃏⭐️]?\s*Карта:\s*[^\n]*\n+", "", block).strip()
                if cleaned:
                    card_texts_only.append(cleaned)
            full_context = "\n".join(card_texts_only)

            summary_raw = await asyncio.wait_for(
                gpt_make_prediction(
                    question=(
                        "Сформулируй общий ИТОГ расклада строго в 3 предложениях. "
                        "Проанализируй весь расклад целиком по смыслу. "
                        "Не упоминай названия карт и не перечисляй пункты. "
                        "Пиши от второго лица («Вы»), обращаясь к задающему вопрос. "
                        "Избегай третьего лица («он», «она», «человек»). "
                        "Без советов/рекомендаций, без списков и эмодзи."
                    ),
                    theme=dir_title,
                    spread="summary",
                    cards_list=", ".join(card_names),
                    scenario_ctx=f"{scenario['title']}\n\n{full_context}",
                ),
                timeout=90
            )

            # чистим и нормализуем итог под требования
            summary_clean = sanitize_summary(summary_raw)
            final_summary = itog_three_sentences_no_advice(summary_clean)
            final_summary = enforce_second_person(final_summary)

        except asyncio.TimeoutError:
            final_summary = (
                "Ситуация развивается последовательно. "
                "Динамика остаётся устойчивой. "
                "Основные тенденции уже проявились."
            )
        except Exception:
            final_summary = (
                "Карты указывают на ключевые тенденции. "
                "Важные влияния продолжают действовать. "
                "Контекст остаётся неизменным."
            )

    # Заглавная буква
    if final_summary and len(final_summary) > 1:
        final_summary = final_summary[0].upper() + final_summary[1:]

    await cb.message.answer(f"Итог\n\n{final_summary}\n\n{MAGIC_FOOTER}", parse_mode=None)

    # ---------- состояние для советов ----------
    combined_text = "\n".join(combined_parts).strip()
    await state.update_data(
        last_prediction_text=combined_text,
        last_theme=dir_title,
        last_spread=f"{dir_key}_scenario_{idx+1}",
        last_cards=card_names,
        last_question=scenario["title"],
        last_scenario=scenario["title"],
        last_summary=final_summary,
        current_direction_key=dir_key,
        current_direction_title=dir_title,
    )

    # ---------- кнопки: советы + навигация ----------
    base_advice_kb = advice_inline_limits(allow_one=True, allow_three=True)
    final_kb = merge_advice_nav_kb(base_advice_kb)
    await cb.message.answer(
        "Вы можете получить совет на основе разбора или выбрать другое направление.",
        reply_markup=final_kb
    )
