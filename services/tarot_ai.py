# services/tarot_ai.py
from __future__ import annotations

import os
import json
import random
import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests  # синхронный HTTP — оборачиваем в asyncio.to_thread


# ===================== КОНФИГ ЯНДЕКС LLM =====================
YANDEX_API_KEY     = os.getenv("YANDEX_API_KEY", "AQVN08pz8w3rwgGBwMpoZfsIwYH4CsIU2OzCOHzN").strip()
YANDEX_MODEL_URI   = os.getenv("YANDEX_MODEL_URI", "gpt://b1gvsrda7nthhjboi2hm/yandexgpt-lite").strip()
YANDEX_URL         = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_TEMPERATURE = float(os.getenv("YANDEX_TEMPERATURE", "0.7"))
YANDEX_MAX_TOKENS  = int(os.getenv("YANDEX_MAX_TOKENS", "2000"))


# ===================== КОНФИГ ПЕРЕВЁРНУТЫХ КАРТ =====================
# Можно отключить перевёрнутые карты полностью и настроить вероятность.
TAROT_ALLOW_REVERSED: bool = os.getenv("TAROT_ALLOW_REVERSED", "1").strip() not in {"0", "false", "False", ""}
try:
    TAROT_REVERSED_PROB: float = float(os.getenv("TAROT_REVERSED_PROB", "0.5"))
    TAROT_REVERSED_PROB = 0.0 if TAROT_REVERSED_PROB < 0 else (1.0 if TAROT_REVERSED_PROB > 1 else TAROT_REVERSED_PROB)
except ValueError:
    TAROT_REVERSED_PROB = 0.5


# ===================== КАРТЫ =====================
CARDS_PATH = Path(__file__).resolve().parent.parent / "data" / "tarot_cards.json"

def load_cards() -> List[Dict[str, Any]]:
    with open(CARDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_CARDS_CACHE: Optional[List[Dict[str, Any]]] = None

def _cards() -> List[Dict[str, Any]]:
    global _CARDS_CACHE
    if _CARDS_CACHE is None:
        _CARDS_CACHE = load_cards()
    return _CARDS_CACHE

def draw_cards(
    num: int,
    *,
    allow_reversed: Optional[bool] = None,
    reversed_prob: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Вытягивает num карт из JSON-колоды.
    НИЧЕГО не меняем в других файлах: при перевороте подменяем поле `name`
    на "<Имя> (перевёрнутая)", оригинальное имя сохраняем в `base_name`.
    В словарь карты также кладём флаг `reversed: bool`.

    Управление:
      - allow_reversed: None -> берётся из TAROT_ALLOW_REVERSED
      - reversed_prob: None -> берётся из TAROT_REVERSED_PROB
    """
    cards = _cards()
    if num > len(cards):
        raise ValueError(f"Запрошено {num} карт, но в колоде только {len(cards)}")

    use_reversed = TAROT_ALLOW_REVERSED if allow_reversed is None else bool(allow_reversed)
    prob = TAROT_REVERSED_PROB if reversed_prob is None else max(0.0, min(1.0, float(reversed_prob)))

    picked = random.sample(cards, num)
    result: List[Dict[str, Any]] = []
    for c in picked:
        c = dict(c)  # не пачкаем общий кэш
        base_name = c.get("name") or c.get("title") or str(c)
        c["base_name"] = base_name
        is_rev = use_reversed and (random.random() < prob)
        c["reversed"] = bool(is_rev)
        c["name"] = f"{base_name} (перевёрнутая)" if is_rev else base_name
        result.append(c)
    return result


# ===================== ХЕЛПЕРЫ ФОРМАТИРОВАНИЯ =====================

def _force_itog_three_sentences_no_advice(text: str) -> str:
    """
    Находит блок '🌙 Итог:' и принудительно:
    - убирает советные формулировки,
    - оставляет ровно 3 предложения,
    - удаляет пустые строки и лишние отступы.
    """
    if not isinstance(text, str) or not text.strip():
        return text

    text = _ensure_moon_on_itog(text)
    lines = text.splitlines()

    # ищем строку с "🌙 Итог:"
    itog_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*🌙\s*Итог\s*:\s*", ln, flags=re.IGNORECASE):
            itog_idx = i
            break
    if itog_idx is None:
        return text

    head = lines[:itog_idx]
    itog_header = lines[itog_idx]
    after_colon = re.split(r"🌙\s*Итог\s*:\s*", itog_header, flags=re.IGNORECASE)
    itog_inline = after_colon[1].strip() if len(after_colon) > 1 else ""
    tail = " ".join(s.strip() for s in lines[itog_idx + 1:] if s.strip())
    full_itog = f"{itog_inline} {tail}".strip()

    # убираем лишние переводы строк
    full_itog = re.sub(r"\s{2,}", " ", full_itog)

    # фильтр советных фраз
    banned = [
        "совет", "советую", "рекоменд", "стоит", "следует", "лучше",
        "нужно", "необходимо", "постарайтесь", "попробуйте", "сделайте",
        "возьмите", "должны", "вам стоит", "вам следует", "рекомендую"
    ]
    sentences = re.split(r"(?<=[.!?])\s+", full_itog)
    clean_sentences = [s.strip() for s in sentences if s.strip() and not any(b in s.lower() for b in banned)]

    # если больше трёх — берём первые три, если меньше — дополняем
    clean_sentences = clean_sentences[:3]
    while len(clean_sentences) < 3:
        filler = "Ситуация развивается последовательно."
        clean_sentences.append(filler)

    # собираем итог в одну строку без переносов
        # собираем итог в одну строку без переносов
    joined = " ".join(s if s.endswith(('.', '!', '?')) else s + '.' for s in clean_sentences)
    joined = joined.strip()

    # убираем все лишние пробелы, табы и переводы строк
    joined = re.sub(r"\s*\n\s*", " ", joined)
    joined = re.sub(r"\s{2,}", " ", joined)

    # финальная сборка
    new_text = "\n".join(head + [f"🌙 Итог: {joined}"])
    return new_text.strip()



def _sanitize_plain_text(text: str) -> str:
    """
    Убирает маркдаун и маркеры списков (*, -, • и т.п.), оставляя обычный текст.
    Сохраняет нумерацию вида '1) ...', '2) ...' — потом мы её заменим на ⭐️.
    """
    if not isinstance(text, str):
        return text

    # уберём жирный/курсив (**...**, *...*, __...__)
    text = text.replace("**", "").replace("__", "")

    # построчная очистка маркеров
    cleaned_lines = []
    for line in text.splitlines():
        raw = line.lstrip()
        # уберём markdown-маркеры
        for marker in ("* ", "- ", "• ", "— ", "・ ", "∙ ", "→ ", "> "):
            if raw.startswith(marker):
                raw = raw[len(marker):]
                break
        if raw.startswith(("*— ", "*- ", "*• ", "-• ", "•- ")):
            raw = raw[2:].lstrip()
        cleaned_lines.append(raw)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _enforce_summary_no_advice(text: str) -> str:
    """
    Делает 'Итог' фактическим резюме без советов/инструкций.
    Убирает фразы с типовыми 'советными' маркерами только в блоке 'Итог'.
    """
    if not isinstance(text, str):
        return text

    lines = text.splitlines()
    itog_idx = None
    for i, ln in enumerate(lines):
        low = ln.strip().lower()
        if low.startswith("итог:") or low == "итог" or low.startswith("🌙 итог"):
            itog_idx = i
            break
    if itog_idx is None:
        return text

    head = lines[:itog_idx+1]
    tail = lines[itog_idx+1:]
    tail_text = " ".join(s.strip() for s in tail if s.strip())
    if not tail_text:
        return text

    ADVICE_HINTS = [
        "совет", "советую", "рекоменд", "стоит", "следует", "лучше",
        "нужно", "необходимо", "постарайтесь", "попробуйте", "попробуй",
        "сделайте", "сделай", "возьмите", "берите", "договоритесь",
        "оформите", "попросите", "перестаньте", "начните", "уделите",
        "сосредоточьтесь", "подумайте", "избегайте", "продолжайте",
        "не забывайте", "держитесь", "планируйте", "добейтесь"
    ]

    sentences = re.split(r"(?<=[\.\!\?])\s+", tail_text)
    cleaned = []
    for s in sentences:
        low = s.strip().lower()
        if low and not any(h in low for h in ADVICE_HINTS):
            cleaned.append(s.strip())

    if not cleaned:
        cleaned = ["Краткое резюме карт: события и тенденции, вытекающие из расклада."]

    new_tail_text = " ".join(cleaned).strip()
    new_text = "\n".join(head + [new_tail_text])
    new_text = re.sub(r"\n{3,}", "\n\n", new_text).strip()
    return new_text


def _to_star_bullets(text: str) -> str:
    """
    Заменяет ведущую нумерацию вида '1) ', '2. ', '3)  ' на '⭐️ ' для строк карт.
    Также заменяет возможный символ '★ ' на '⭐️ '.
    """
    if not isinstance(text, str):
        return text
    lines = text.splitlines()
    out = []
    for ln in lines:
        s = ln.lstrip()
        if re.match(r"^\d+[\)\.]?\s+", s):
            ln = re.sub(r"^\s*\d+[\)\.]?\s+", "⭐️ ", ln)
        ln = re.sub(r"^\s*★\s+", "⭐️ ", ln)
        out.append(ln)
    return "\n".join(out)


def _ensure_moon_on_itog(text: str) -> str:
    """
    Нормализует строку заголовка Итога в вид '🌙 Итог:'.
    Удаляет возможную ведущую ⭐️ перед Итогом.
    """
    if not isinstance(text, str):
        return text

    lines = text.splitlines()
    for i, ln in enumerate(lines):
        base = ln.strip()
        if not base:
            continue
        # любые варианты начала строки Итога
        if re.match(r"^(?:⭐️\s*)?Итог\b", base, flags=re.IGNORECASE) or base.lower().startswith("🌙 итог"):
            m = re.match(r"^(?:\s*⭐️\s*)?(?:🌙\s*)?Итог:?\s*(.*)$", ln, flags=re.IGNORECASE)
            rest = (m.group(1) if m else "").strip()
            lines[i] = ("🌙 Итог:" + (f" {rest}" if rest else "")).rstrip()
            break
    return "\n".join(lines).strip()


def _prefix_paragraphs_with_stars_except_itog(text: str) -> str:
    """
    Добавляет '⭐️ ' в начало первой непустой строки каждого абзаца,
    КРОМЕ строки заголовка Итога ('🌙 Итог:' / 'Итог:').
    Абзацы разделены пустой строкой.
    """
    if not isinstance(text, str):
        return text

    paragraphs = re.split(r"\n\s*\n", text.strip(), flags=re.DOTALL)
    result: List[str] = []

    for p in paragraphs:
        lines = p.splitlines()
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            # если это Итог — не ставим звезду и нормализуем на луну
            if re.match(r"^\s*(?:🌙\s*)?Итог\b", ln, flags=re.IGNORECASE):
                m = re.match(r"^\s*(?:🌙\s*)?Итог:?\s*(.*)$", ln, flags=re.IGNORECASE)
                rest = (m.group(1) if m else "").strip()
                lines[i] = ("🌙 Итог:" + (f" {rest}" if rest else "")).rstrip()
                break
            # иначе — обеспечиваем ведущую звезду
            if not re.match(r"^\s*⭐️\s+", ln):
                lines[i] = f"⭐️ {ln.lstrip()}"
            break
        result.append("\n".join(lines))

    return "\n\n".join(result).strip()


def _strip_star_prefixes(text: str) -> str:
    """
    Убирает любые ведущие '⭐️ ' в начале строк и перед 'Карты:'.
    Используется только для советов (там звёзд быть не должно).
    """
    if not isinstance(text, str):
        return text
    lines = text.splitlines()
    cleaned = []
    for ln in lines:
        ln = re.sub(r"^\s*⭐️\s+", "", ln)
        ln = re.sub(r"^\s*⭐️\s*(Карты:)", r"\1", ln, flags=re.IGNORECASE)
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


# ===================== УТИЛИТА ДЛЯ СЦЕНАРИЯ =====================
def merge_with_scenario(base_prompt: str, scenario_ctx: Optional[str]) -> str:
    """Просто склеивает текст с уточняющим сценарием при наличии."""
    return f"{base_prompt}\n\n{scenario_ctx}" if scenario_ctx else base_prompt


# ===================== ВЫЗОВ ЯНДЕКС LLM =====================
def _headers() -> Dict[str, str]:
    if not YANDEX_API_KEY:
        raise RuntimeError("Не задан YANDEX_API_KEY (переменная окружения).")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
    }

def _build_prompt_payload(messages: List[Dict[str, str]], *, temperature: Optional[float] = None) -> Dict[str, Any]:
    return {
        "modelUri": YANDEX_MODEL_URI,
        "completionOptions": {
            "stream": False,
            "temperature": YANDEX_TEMPERATURE if temperature is None else float(temperature),
            "maxTokens": YANDEX_MAX_TOKENS,
        },
        "messages": messages,
    }

def _extract_text_from_response(data: Dict[str, Any]) -> str:
    try:
        alts = data["result"]["alternatives"]
        if alts:
            msg = alts[0].get("message", {})
            txt = msg.get("text")
            if isinstance(txt, str) and txt.strip():
                return txt.strip()
            txt2 = alts[0].get("text")
            if isinstance(txt2, str) and txt2.strip():
                return txt2.strip()
    except Exception:
        pass
    return json.dumps(data, ensure_ascii=False)

async def _post_messages(messages: List[Dict[str, str]], *, temperature: Optional[float] = None) -> str:
    payload = _build_prompt_payload(messages, temperature=temperature)

    def _do_request(headers):
        resp = requests.post(YANDEX_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    try:
        headers = _headers()
        data = await asyncio.to_thread(_do_request, headers)
        return _extract_text_from_response(data)
    except RuntimeError as e:
        return f"Ошибка конфигурации: {e}"
    except requests.HTTPError as e:
        return f"Ошибка HTTP: {e}"
    except requests.RequestException as e:
        return f"Сетевая ошибка: {e}"
    except Exception as e:
        return f"Неожиданная ошибка: {e}"

async def qwen_chat_completion(prompt: str) -> str:
    messages = [
        {"role": "system", "text": "Ты опытный таролог и психолог с 20-летним стажем. Отвечай точно по инструкции."},
        {"role": "user", "text": prompt}
    ]
    return await _post_messages(messages)

async def qwen_chat_completion_messages(messages: List[Dict[str, str]], *, temperature: Optional[float] = None) -> str:
    return await _post_messages(messages, temperature=temperature)


# ===================== ПРЕДСКАЗАНИЕ =====================
async def gpt_make_prediction(
    question: str,
    theme: str,
    spread: str,
    cards_list: str,
    scenario_ctx: Optional[str] = None
) -> str:
    """
    Жёстко держим тему и (если есть) уточнение.
    Без маркдауна. Расшифровка карт — со '⭐️ ' вместо нумерации.
    Абзацы начинаются со '⭐️ ', а заголовок Итога — строго '🌙 Итог:' (без звезды).
    Итог — РОВНО 3 предложения резюме без советов.
    """
    scenario_line = f"\nУточняющий сценарий: {scenario_ctx}" if scenario_ctx else ""

    if theme.lower().startswith("любов"):
        forbid = "финансы/карьера/здоровье/юридические советы"
        must = "говори о чувствах, динамике отношений, совместимости, перспективах пары"
        tone = "эмпатичный, деликатный, предметный"
    elif theme.lower().startswith("работ"):
        forbid = "любовные темы/здоровье/общие фразы про «все сферы жизни»"
        must = "фокус на карьере, росте/повышении, KPI, переговорах, видимости заслуг"
        tone = "деловой, конкретный, практичный"
    elif theme.lower().startswith("саморазв"):
        forbid = "узкая любовь/работа без привязки к развитию"
        must = "привычки, навыки, мышление, дисциплина, ресурсы"
        tone = "поддерживающий, структурный"
    else:
        forbid = "узкая любовь/работа, если не связано с жизненным путём"
        must = "долгосрочные тренды жизни, личные уроки, трансформации"
        tone = "взвешенный, спокойный"

    prompt = f"""
Ты — опытный таролог. Русский язык, чётко и по делу. Один связный ответ без вступлений.

Тема: {theme}{scenario_line}
Расклад: {spread}
Карты (в порядке): {cards_list}
Вопрос пользователя: {question}

Требования по теме:
- Обязательно: {must}.
- Запрещено: {forbid}.
- Тон: {tone}.

Формат и требования:
- Для каждой карты — отдельный абзац, начинающийся с "⭐️ ".
- После названия карты дай развёрнутое толкование длиной 5–8 предложений, объясняя символику и смысл в контексте вопроса и темы.
- Если карта перевёрнутая — чётко укажи влияние перевёрнутости (ослабление, искажение, препятствие и т.п.).
- НИКАКОГО маркдауна/буллетов: *, -, •, —, >, жирного или курсива.
- Итог выводи отдельным абзацем и начинай строку с "🌙 Итог:" (без звезды).
- 🌙 Итог — РОВНО 3 предложения резюме общего послания карт, без советов, инструкций и императивов («нужно», «следует», «совет», «попробуйте» и т.п.).
""".strip()

    raw = await qwen_chat_completion(prompt)

    # Форматирование и нормализация, как было
    txt = _sanitize_plain_text(raw)
    txt = _enforce_summary_no_advice(txt)              # мягкая чистка от советов
    txt = _to_star_bullets(txt)
    txt = _ensure_moon_on_itog(txt)
    txt = _prefix_paragraphs_with_stars_except_itog(txt)

    # ЖЁСТКО: ровно 3 предложения и без советов в Итоге
    txt = _force_itog_three_sentences_no_advice(txt)
    return txt




# ===================== СОВЕТЫ =====================
async def gpt_make_advice_from_yandex_answer(
    *,
    yandex_answer_text: str,
    advice_cards_list: List[str] | None,
    advice_count: int = 1,
) -> str:
    """
    Совет БЕЗ звёзд в начале строк и без других эмодзи внутри.
    Первая строка (если есть карты) — 'Карты: ...' (без ⭐️).
    В самом конце добавляется один '🔮'.
    """
    have_cards = bool(advice_cards_list)

    length_rule = (
        "Сделай связный, практичный и развёрнутый совет на 10–15 предложений."
        if advice_count == 3 else
        "Сделай краткий, практичный совет на 2–3 предложения."
    )

    cards_line_for_prompt = f"Карты: {', '.join(advice_cards_list)}\n" if have_cards else ""

    prompt = f"""
Ты — таролог. Сформируй ПРАКТИЧНЫЙ совет на основе ответа от Яндекса ниже.
Опирайся прежде всего на раздел «Итог» и общий смысл ответа.
Один компактный ответ без вступлений.

{length_rule}

Оформление:
- НЕ используй никакие эмодзи и символы в начале строк (никаких ⭐️, 🔮 и т.п.).
- НИКАКОГО маркдауна/буллетов/жирного/курсива.
- Если есть «карты совета» — первой строкой выведи: "Карты: <...>" (без эмодзи).
- В самом конце текста добавь один магический шар: " 🔮".

Выведи результат строго так:
{cards_line_for_prompt}<дальше сразу идёт сам текст совета без заголовков>.

Ответ Яндекса:
---
{yandex_answer_text}
---
""".strip()

    raw = await qwen_chat_completion(prompt)
    text = _sanitize_plain_text(raw)
    text = re.sub(r"^\s*Текст\s+совета\s*:\s*", "", text, flags=re.IGNORECASE)

    # убираем любые случайно попавшие звёзды в начале строк
    text = _strip_star_prefixes(text)

    # если есть карты и их строка пропущена — добавим без звезды
    if have_cards and not text.lower().startswith("карты:"):
        text = f"Карты: {', '.join(advice_cards_list)}\n\n{text.strip()}"

    # гарантируем один шар в конце
    text = text.rstrip()
    if not text.endswith("🔮"):
        text = f"{text} 🔮"

    return text


async def gpt_make_advice(
    *,
    theme: str,
    scenario_ctx: Optional[str],
    question: str,
    cards_list: List[str],
    summary_text: str,
    advice_cards_list: List[str],
) -> str:
    """
    Совет на основе известного контекста. БЕЗ звёзд в начале строк.
    Первая строка (если есть карты) — 'Карты: ...'. В конце — один '🔮'.
    """
    scenario_line = f"\nУточнение/сценарий: {scenario_ctx}" if scenario_ctx else ""
    prompt = f"""
Ты опытный таролог. Один компактный ответ без вступлений.

Задача: дать ПРАКТИЧНЫЙ совет на основе готового расклада и его Итога.
Опирайся на тему/уточнение, карты основного расклада, Итог и дополнительные карты Совета.

Формат:
1) Первая строка (если карты есть): "Карты: <карта1>, <карта2>, ...".
2) Сразу за ней — сам текст совета 3–6 предложений, без заголовков.

Оформление:
- НЕ используй никакие эмодзи и символы в начале строк (никаких ⭐️, 🔮 и т.п.).
- НИКАКОГО маркдауна/буллетов/жирного/курсива.
- В самом конце текста добавь один магический шар: " 🔮".

Данные:
Тема: {theme}{scenario_line}
Вопрос пользователя: {question}
Карты основного расклада (по порядку): {", ".join(cards_list)}
Итог: {summary_text}
Карты Совета: {", ".join(advice_cards_list)}
""".strip()

    raw = await qwen_chat_completion(prompt)
    text = _sanitize_plain_text(raw)
    text = re.sub(r"^\s*Текст\s+совета\s*:\s*", "", text, flags=re.IGNORECASE)

    # убираем любые случайные звезды от модели
    text = _strip_star_prefixes(text)

    # добавим строку «Карты: ...» при необходимости (без звезды)
    if advice_cards_list and not text.lower().startswith("карты:"):
        text = f"Карты: {', '.join(advice_cards_list)}\n\n{text.strip()}"

    # один шар в конце
    text = text.rstrip()
    if not text.endswith("🔮"):
        text = f"{text} 🔮"

    return text
