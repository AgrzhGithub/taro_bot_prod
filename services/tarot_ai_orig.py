from pathlib import Path
import json
import random
import asyncio
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import re

# Путь к файлу с картами
CARDS_PATH = Path(__file__).resolve().parent.parent / "data" / "tarot_cards.json"

def load_cards():
    with open(CARDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

cards = load_cards()

def draw_cards(num):
    return random.sample(cards, num)

# Модель Qwen
model = None
tokenizer = None
model_name = "Qwen/Qwen2.5-0.5B-Instruct"

def load_model():
    global model, tokenizer
    if model is None or tokenizer is None:
        print("🔄 Загрузка модели Qwen...")
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto"
        )
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        print("✅ Модель загружена")

async def qwen_chat_completion(prompt: str) -> str:
    load_model()
    messages = [
        {"role": "system", "content": "Ты опытный таролог и психолог с 20-летним стажем. Отвечай точно по инструкции."},
        {"role": "user", "content": prompt}
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

    loop = asyncio.get_event_loop()

    def do_generate():
        generated_ids = model.generate(**model_inputs, max_new_tokens=512)
        generated_ids = [
            output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        return tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]

    return await loop.run_in_executor(None, do_generate)

# Анализ вопроса
async def gpt_analyze_question(question: str):
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
"""
    import json as pyjson
    response_text = await qwen_chat_completion(prompt)
    match = re.search(r'\{[\s\S]*?\}', response_text)
    json_str = match.group(0) if match else "{}"

    try:
        return pyjson.loads(json_str)
    except pyjson.JSONDecodeError:
        return {"theme": "судьба", "spread": "Три карты", "reason": "Ошибка парсинга"}

# Толкование расклада
async def gpt_make_prediction(question: str, theme: str, spread: str, cards_list: str):
    prompt = f"""
Ты — опытный таролог и психолог.
Пользователь задал вопрос: "{question}"
Тема: {theme}
Расклад: {spread}
Карты: {cards_list}

Требования:
- Для каждой карты: название и краткое, но глубокое толкование в контексте вопроса.
- После карт: цельный и качественный итог расклада (2-3 предложения).
- Итог должен быть вдохновляющим и осмысленным, без слов "таким образом", "в целом" и лишней воды.
- Не используй **звёздочки**, оформление делай обычным текстом.

Формат:
1. Название карты — толкование
...
Итог: общий вывод.
"""
    return await qwen_chat_completion(prompt)
