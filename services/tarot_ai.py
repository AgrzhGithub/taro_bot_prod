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
YANDEX_TEMPERATURE = float(os.getenv("YANDEX_TEMPERATURE", "0.6"))
YANDEX_MAX_TOKENS  = int(os.getenv("YANDEX_MAX_TOKENS", "2000"))

# ===================== КАРТЫ =====================
CARDS_PATH = Path(__file__).resolve().parent.parent / "data" / "tarot_cards.json"

def load_cards() -> List[Dict[str, Any]]:
    with open(CARDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

cards = load_cards()

def draw_cards(num: int) -> List[Dict[str, Any]]:
    if num > len(cards):
        raise ValueError(f"Запрошено {num} карт, но в колоде только {len(cards)}")
    return random.sample(cards, num)

# ===================== ВСПОМОГАТЕЛЬНОЕ =====================
def _extract_json_object(text: str) -> Optional[dict]:
    """
    Надёжно вынимаем JSON-объект из произвольного текста.
    """
    text = text.strip()

    # Попытка 1: целиком
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Попытка 2: от первой { до последней }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end+1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # Попытка 3: жадный regex
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None

def _build_prompt_payload(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Собираем payload ровно в формате твоего рабочего примера.
    """
    return {
        "modelUri": YANDEX_MODEL_URI,
        "completionOptions": {
            "stream": False,
            "temperature": YANDEX_TEMPERATURE,
            "maxTokens": YANDEX_MAX_TOKENS,  # число, не строка
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
    """
    Достаём текст из разных возможных раскладок ответа.
    """
    # Каноничный путь
    try:
        alts = data["result"]["alternatives"]
        if alts:
            msg = alts[0].get("message", {})
            txt = msg.get("text")
            if isinstance(txt, str) and txt.strip():
                return txt.strip()
            # иногда "text" лежит прямо в alternative
            txt2 = alts[0].get("text")
            if isinstance(txt2, str) and txt2.strip():
                return txt2.strip()
    except Exception:
        pass
    # Если формат неожиданно другой — вернём весь JSON строкой (чтобы UI не падал)
    return json.dumps(data, ensure_ascii=False)

# ===================== ЕДИНАЯ ТОЧКА — ЗАМЕНА QWEN =====================
async def qwen_chat_completion(prompt: str) -> str:
    """
    Полная замена локального Qwen. Интерфейс сохранён.
    Внутри — твой рабочий формат запроса к YandexGPT.
    """
    messages = [
        {
            "role": "system",
            "text": "Ты опытный таролог и психолог с 20-летним стажем. Отвечай точно по инструкции."
        },
        {
            "role": "user",
            "text": prompt
        }
    ]

    payload = _build_prompt_payload(messages)
    headers = _headers()

    def _do_request():
        resp = requests.post(YANDEX_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    try:
        data = await asyncio.to_thread(_do_request)
    except requests.HTTPError as e:
        # Вернём короткое объяснение — удобно для показа пользователю
        return f"Ошибка HTTP: {e}"
    except requests.RequestException as e:
        return f"Сетевая ошибка: {e}"
    except Exception as e:
        return f"Неожиданная ошибка: {e}"

    return _extract_text_from_response(data)

# Алиас (если где-то используешь именно это имя)
chat_completion = qwen_chat_completion

# ===================== СТАРЫЕ ФУНКЦИИ С ТЕМ ЖЕ ИНТЕРФЕЙСОМ =====================
async def gpt_analyze_question(question: str) -> Dict[str, str]:
    prompt = f"""
Ты — опытный таролог и психолог с 20-летним стажем.
Твоя задача — определить подходящую тему и расклад для вопроса пользователя.

Вопрос пользователя: "{question}"

Правила:
1. Возможные темы: любовь, работа, судьба, саморазвитие.
2. Возможные расклады: "Три карты" (краткий анализ ситуации), "Подкова" (глубокое понимание и предсказание), "Алхимик" (расширенный расклад с детальной проработкой).
3. Выбирай тему и расклад исходя из сути вопроса, а не случайно.
4. Объясни свой выбор в одном-двух предложениях, без лишних слов.

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

async def gpt_make_prediction(question: str, theme: str, spread: str, cards_list: str) -> str:
    prompt = f"""
Ты — опытный таролог и психолог.
Пользователь задал вопрос: "{question}"
Тема: {theme}
Расклад: {spread}
Карты: {cards_list}

Требования:
* Для каждой карты: название и краткое, но глубокое толкование в контексте вопроса.
* После карт: цельный и качественный итог расклада (2–3 предложения).
* Итог должен быть вдохновляющим и осмысленным, без слов "таким образом", "в целом" и лишней воды.
* Не используй звёздочки, оформление обычным текстом.

Формат:
1. Название карты — толкование
...
Итог: общий вывод.
""".strip()

    return await qwen_chat_completion(prompt)
