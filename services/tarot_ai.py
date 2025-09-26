# tarot_yandex_backend.py
from __future__ import annotations

import os
import json
import random
import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests  # синхронный HTTP — завернём в asyncio.to_thread

# ===================== КОНФИГ =====================
YANDEX_API_KEY   = os.getenv("YANDEX_API_KEY", "AQVN08pz8w3rwgGBwMpoZfsIwYH4CsIU2OzCOHzN").strip()
YANDEX_MODEL_URI = os.getenv("YANDEX_MODEL_URI", "gpt://b1gvsrda7nthhjboi2hm/yandexgpt-lite").strip()
YANDEX_URL       = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_TEMPERATURE = float(os.getenv("YANDEX_TEMPERATURE", "0.7"))
YANDEX_MAX_TOKENS  = int(os.getenv("YANDEX_MAX_TOKENS", "2000"))

# ===================== КАРТЫ =====================
CARDS_PATH = Path(__file__).resolve().parent.parent / "data" / "tarot_cards.json"

def load_cards() -> List[Dict[str, Any]]:
    with open(CARDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

cards = load_cards()

def draw_cards(num: int) -> List[Dict[str, Any]]:
    """Вытягивает num карт из JSON-колоды (без перевёрнутых)."""
    if num > len(cards):
        raise ValueError(f"Запрошено {num} карт, но в колоде только {len(cards)}")
    return random.sample(cards, num)

# ===================== ПАРСИНГ/ПЕЙЛОАД =====================
def _extract_json_object(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        cand = text[start:end + 1]
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None

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

def _headers() -> Dict[str, str]:
    if not YANDEX_API_KEY:
        raise RuntimeError("Не задан YANDEX_API_KEY (переменная окружения).")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
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

def merge_with_scenario(base_prompt: str, scenario_ctx: str | None) -> str:
    return f"{base_prompt}\n\n{scenario_ctx}" if scenario_ctx else base_prompt

# ===================== СТОРОЖИ ТЕМ/УТОЧНЕНИЙ =====================
THEME_GUARDS: Dict[str, Dict[str, Any]] = {
    "Любовь": {
        "must": [
            "говори только о чувствах, динамике пары, совместимости, перспективах союза",
            "связывай каждую карту с взаимоотношениями и эмоциональным контекстом"
        ],
        "forbid": ["финансы", "карьера", "работа", "здоровье", "юридические советы", "общие фразы про «все сферы»"],
        "tone": "эмпатичный, деликатный, предметный",
    },
    "Работа": {
        "must": [
            "фокусируйся на карьере, росте/повышении, переговорах, KPI, навыках, видимости заслуг",
            "связывай каждую карту с карьерной ситуацией пользователя",
        ],
        "forbid": ["любовные темы", "здоровье", "эзотерические общие фразы про «все сферы»"],
        "tone": "деловой, конкретный, практичный",
    },
    "Судьба": {
        "must": ["долгосрочные тренды жизни, личные уроки, трансформации"],
        "forbid": ["узкая любовь/работа без связи с жизненным путём"],
        "tone": "взвешенный, спокойный",
    },
    "Саморазвитие": {
        "must": ["привычки, навыки, мышление, дисциплина, ресурсы, личный рост"],
        "forbid": ["узкая любовь/работа без привязки к развитию"],
        "tone": "поддерживающий, структурный",
    },
}

# Ключевые слова для авто-детекта уточнения (можно расширять)
SCENARIO_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "Работа": {
        "Рост/повышение": ["рост", "повышен", "повышение", "карьер", "продвижен", "promotion", "increase title"],
        "Зарплата/переговоры": ["зарплат", "повышение зарплаты", "переговор", "оценка", "review", "raise"],
        "Смена работы": ["смена работы", "новая работа", "поиск", "вакансия", "headhunter", "hh"],
    },
    "Любовь": {
        "Любимый человек": ["любимый", "партнер", "его чувства", "его мысли", "отношен", "пара", "boyfriend", "girlfriend"],
        "Новое знакомство": ["знакомств", "новый человек", "будущий партн", "поиск любви", "dating"],
    },
}

FORBIDDEN_BY_THEME: Dict[str, List[str]] = {
    "Любовь": ["финанс", "карьер", "работ", "инвест", "здоров", "юрид"],
    "Работа": ["роман", "отношен", "любов", "интим", "партнер"],
    "Судьба": [],
    "Саморазвитие": [],
}

def _auto_detect_scenario(question: str, theme: str) -> Optional[str]:
    """Пытаемся вывести уточнение из текста вопроса."""
    theme_map = SCENARIO_KEYWORDS.get(theme)
    if not theme_map:
        return None
    q = (question or "").lower()
    for scen, kws in theme_map.items():
        if any(k in q for k in kws):
            return scen
    return None

def _topic_check(text: str, theme: str, scenario: Optional[str]) -> Tuple[bool, str]:
    """
    Простой хардчек: есть ли связи с нужной темой/уточнением и нет ли явных оффтоп-триггеров.
    Возвращает (ok, reason_if_not_ok)
    """
    t = (text or "").lower()

    # 1) запреты по теме
    forbad = FORBIDDEN_BY_THEME.get(theme, [])
    if any(bad in t for bad in forbad):
        return False, "Найдены оффтоп-темы для выбранной темы."

    # 2) если задан сценарий — требуем упоминаний/лексики про него
    if scenario:
        scen_kws = []
        for s, kws in SCENARIO_KEYWORDS.get(theme, {}).items():
            if s.lower() == scenario.lower():
                scen_kws = kws
                break
        # если есть словарь — потребуем хотя бы одно попадание
        if scen_kws and not any(k in t for k in [kw.lower() for kw in scen_kws]):
            return False, "Ответ слабо отражает уточняющий сценарий."

    # 3) слишком общие «все сферы жизни»
    if "все сферы" in t or "во всех сферах" in t:
        return False, "Обнаружены общие фразы про «все сферы»."

    # 4) должен явно фигурировать контекст темы (для подстраховки)
    if theme == "Работа" and not any(w in t for w in ["карьер", "повышен", "работ", "руковод", "задач", "проект", "kpi", "команда"]):
        return False, "Мало упоминаний рабочей/карьерной лексики."

    if theme == "Любовь" and not any(w in t for w in ["отношен", "чувств", "партнер", "пара", "эмоци"]):
        return False, "Мало упоминаний любовной лексики."

    return True, ""

# ===================== СБОРКА МЕССЕДЖЕЙ =====================
def _build_messages_for_prediction(
    *,
    question: str,
    theme: str,
    spread: str,
    cards_list: str,
    scenario_ctx: Optional[str] = None,
    stricter: bool = False
) -> List[Dict[str, str]]:
    guard = THEME_GUARDS.get(theme, {
        "must": ["держись строго в рамках заявленной темы"],
        "forbid": ["уход в посторонние сферы"],
        "tone": "нейтральный, понятный",
    })
    forbid_line = '; '.join(guard["forbid"])
    must_line   = '; '.join(guard["must"])

    scenario_line = f"\nУточнение/сценарий: {scenario_ctx}" if scenario_ctx else ""
    anti_offtop = (
        "\nНЕ УПОМИНАЙ финансы/работу/здоровье/юридические темы, если это не относится к теме и уточнению."
        if not stricter else
        "\nСТРОГО ЗАПРЕЩЕНО упоминать любые темы вне указанных. Если мысль не относится к теме и уточнению — опусти её."
    )

    system = (
        "Ты опытный таролог с 20-летним стажем. Отвечай на русском, кратко и по делу.\n"
        "Строго соблюдай тему расклада и уточняющий сценарий. "
        "Сначала проведи внутреннюю проверку соответствия теме/сценарию (НЕ выводи её), затем выдай только финальный ответ.\n\n"
        f"Требования по теме «{theme}»:\n"
        f"- Обязательно: {must_line}.\n"
        f"- Запрещено: {forbid_line}.\n"
        f"- Тон: {guard['tone']}."
        f"{anti_offtop}\n\n"
        "Формат ответа:\n"
        "1) По порядку перечисли карты: «Название — толкование в контексте темы/сценария» (кратко, предметно).\n"
        "2) Итог: 2–4 предложения СТРОГО по теме/уточнению (без общих фраз вроде «во всех сферах»)."
    )

    user = (
        f"Тема: {theme}{scenario_line}\n"
        f"Расклад: {spread}\n"
        f"Карты (в порядке): {cards_list}\n"
        f"Вопрос пользователя: {question}\n\n"
        "Сделай толкование ТОЛЬКО в рамках темы и уточнения. "
        "Если замечаешь выход за рамки — переформулируй и убери оффтоп. "
        "Не используй маркированные/звёздочки, обычный текст."
    )

    return [
        {"role": "system", "text": system},
        {"role": "user",   "text": user},
    ]

# ===================== ВЫЗОВ LLM =====================
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

chat_completion = qwen_chat_completion

# ===================== ВСПОМОГАТЕЛЬНОЕ: ПОДБОР ТЕМЫ/РАСКЛАДА =====================
async def gpt_analyze_question(question: str) -> Dict[str, str]:
    prompt = f"""
Ты — опытный таролог и психолог с 20-летним стажем.
Твоя задача — определить подходящую тему и расклад для вопроса пользователя.

Вопрос пользователя: "{question}"

Правила:
1. Возможные темы: любовь, работа, судьба, саморазвитие.
2. Возможные расклады: "Три карты", "Подкова", "Алхимик".
3. Выбирай тему и расклад исходя из сути вопроса, а не случайно.
4. Объясни свой выбор в одном-двух предложениях, без воды.

Ответ строго в JSON:
{{
  "theme": "одна из тем",
  "spread": "один из раскладов",
  "reason": "краткое, но осмысленное объяснение выбора"
}}
""".strip()

    response_text = await qwen_chat_completion(prompt)
    obj = _extract_json_object(response_text)

    if obj and isinstance(obj, dict):
        theme  = obj.get("theme")  or "судьба"
        spread = obj.get("spread") or "Три карты"
        reason = obj.get("reason") or "Автовыбор по умолчанию"
        return {"theme": theme, "spread": spread, "reason": reason}
    else:
        return {"theme": "судьба", "spread": "Три карты", "reason": "Ошибка парсинга"}

# ===================== ГЛАВНАЯ: ПРЕДСКАЗАНИЕ С ЖЁСТКОЙ ПРИВЯЗКОЙ К СЦЕНАРИЮ =====================
async def gpt_make_prediction(
    question: str,
    theme: str,
    spread: str,
    cards_list: str,
    scenario_ctx: Optional[str] = None
) -> str:
    """
    1) Собираем строгие system+user с темой и уточнением (или авто-детектим его по вопросу).
    2) Проверяем ответ хардчекером; если оффтоп — один ретрай с усилением ограничений.
    """
    scenario = scenario_ctx or _auto_detect_scenario(question, theme)

    # Первый вызов — обычный строгий
    msgs = _build_messages_for_prediction(
        question=question, theme=theme, spread=spread, cards_list=cards_list, scenario_ctx=scenario, stricter=False
    )
    text1 = await qwen_chat_completion_messages(msgs, temperature=YANDEX_TEMPERATURE)

    ok, reason = _topic_check(text1, theme, scenario)
    if ok:
        return text1

    # РЕТРАЙ (один раз): усиливаем запреты, понижаем температуру
    retry_note = (
        f"Предыдущий ответ ушёл от темы/уточнения ({reason}). "
        f"Сконцентрируйся на теме «{theme}»"
        + (f" и уточнении «{scenario}»." if scenario else ".")
        + " Удали всё, что не относится к теме/уточнению."
    )
    msgs2 = _build_messages_for_prediction(
        question=question + " " + retry_note,
        theme=theme,
        spread=spread,
        cards_list=cards_list,
        scenario_ctx=scenario,
        stricter=True
    )
    text2 = await qwen_chat_completion_messages(msgs2, temperature=0.2)

    ok2, _ = _topic_check(text2, theme, scenario)
    return text2 if ok2 else text1  # вернём лучший из двух