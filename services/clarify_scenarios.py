from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class Scenario:
    id: str
    title: str
    bullets: List[str]

@dataclass
class ThemeScenarios:
    theme_id: str          # канонический id
    title: str             # отображаемое имя
    scenarios: List[Scenario]
    aliases: List[str]     # какие id считаем эквивалентными

# ====== РОВНО ВАШИ ТЕМЫ ======
CATALOG: Dict[str, ThemeScenarios] = {
    # 1) ЛЮБОВЬ
    "Любовь": ThemeScenarios(
        theme_id="Любовь",
        title="Любовь",
        aliases=["relations", "lyubov", "theme_love"],
        scenarios=[
            Scenario(
                id="current_partner",
                title="Гадание на любимого человека",
                bullets=[
                    "его чувства", "его мысли", "его отношение к вам",
                    "ваше ближайшее будущее", "возможные препятствия"
                ],
            ),
            Scenario(
                id="new_meet",
                title="Гадание на новое знакомство",
                bullets=[
                    "способствуют ли ваши действия и текущие обстоятельства знакомству",
                    "каким вас видят потенциальные партнёры",
                    "характер возможных отношений",
                    "характер человека, который может появиться"
                ],
            ),
            Scenario(
                id="past_rel",
                title="Гадание на прошлые отношения",
                bullets=[
                    "думает ли о вас бывший партнёр",
                    "почему начались ваши отношения",
                    "что наносило вред отношениям",
                    "будет ли он/она проявляться снова"
                ],
            ),
        ],
    ),

    # 2) РАБОТА
    "Работа": ThemeScenarios(
        theme_id="Работа",
        title="Работа",
        aliases=["career", "rabota", "theme_work"],
        scenarios=[
            Scenario(
                id="growth",
                title="Рост/повышение",
                bullets=[
                    "текущие сильные стороны и ограничения",
                    "что делать, чтобы ускорить рост",
                    "возможные препятствия и как их обойти",
                    "сроки и ближайшие возможности"
                ],
            ),
            Scenario(
                id="change_job",
                title="Смена работы",
                bullets=[
                    "насколько благоприятен переход сейчас",
                    "какие условия/направления дадут лучший результат",
                    "риски/подводные камни",
                    "практический совет на ближайший месяц"
                ],
            ),
            Scenario(
                id="conflict",
                title="Конфликт на работе",
                bullets=[
                    "корневая причина напряжения",
                    "позиции и мотивация сторон",
                    "что поможет разрядить ситуацию",
                    "чего лучше избегать в ближайшее время"
                ],
            ),
            Scenario(
                id="project_outcome",
                title="Исход по проекту",
                bullets=[
                    "сильные и слабые места проекта",
                    "скрытые риски и зависимые факторы",
                    "что усилить уже сейчас",
                    "вероятный сценарий развития в ближайшие недели"
                ],
            ),
        ],
    ),

    # 3) СУДЬБА
    "Судьба": ThemeScenarios(
        theme_id="Судьба",
        title="Судьба",
        aliases=["destiny", "sudba", "theme_fate"],
        scenarios=[
            Scenario(
                id="life_path",
                title="Жизненный путь",
                bullets=[
                    "ключевая тема текущего этапа",
                    "какой урок проживается",
                    "куда направить внимание",
                    "что поможет двигаться ровнее"
                ],
            ),
            Scenario(
                id="near_future",
                title="Ближайшие события",
                bullets=[
                    "главная тенденция ближайших недель",
                    "чем может быть полезен этот период",
                    "возможное препятствие",
                    "знак/сигнал, на который стоит обратить внимание"
                ],
            ),
            Scenario(
                id="karmic",
                title="Кармический урок",
                bullets=[
                    "ядро повторяющегося сценария",
                    "какое поведение закрепляет проблему",
                    "что помогает развернуть опыт в плюс",
                    "как увидеть прогресс"
                ],
            ),
            Scenario(
                id="fateful_meeting",
                title="Судьбоносная встреча",
                bullets=[
                    "вероятность и контекст встречи",
                    "какие качества важны с вашей стороны",
                    "что может помешать",
                    "как подготовиться внутренне"
                ],
            ),
        ],
    ),

    # 4) САМООРАЗВИТИЕ
    "Саморазвитие": ThemeScenarios(
        theme_id="Саморазвитие",
        title="Самопознание",
        aliases=["self", "samorazvitie", "theme_self"],
        scenarios=[
            Scenario(
                id="personal_growth",
                title="Личный рост",
                bullets=[
                    "что тормозит развитие сейчас",
                    "ресурсы и опоры",
                    "малые шаги с большим эффектом",
                    "ошибка, которой лучше избежать"
                ],
            ),
            Scenario(
                id="habits",
                title="Привычки и режим",
                bullets=[
                    "что тянет энергию вниз",
                    "какая одна привычка даст максимум пользы",
                    "как её закрепить",
                    "подводный камень ближайшего месяца"
                ],
            ),
            Scenario(
                id="focus_energy",
                title="Ресурсное состояние",
                bullets=[
                    "что утекает из вашей энергии",
                    "что наполняет",
                    "границы, которые важно удерживать",
                    "малый ритуал на 7 дней"
                ],
            ),
            Scenario(
                id="overcome_fears",
                title="Преодоление страхов",
                bullets=[
                    "корень страха",
                    "переформулировка задачи",
                    "первое безопасное действие",
                    "как отследить прогресс"
                ],
            ),
        ],
    ),
}

# ====== УТИЛИТЫ ======
# Быстрый индекс алиасов → канон. id
_ALIAS_INDEX: Dict[str, str] = {}
for key, theme in CATALOG.items():
    _ALIAS_INDEX[key] = key
    for a in theme.aliases:
        _ALIAS_INDEX[a] = key

def get_theme(theme_id: str, fallback_title: Optional[str] = None) -> ThemeScenarios:
    """
    Нормализует theme_id через алиасы и возвращает тему.
    Если не найдена — поднимаем минимальный фолбэк, чтобы бот не падал.
    """
    canon = _ALIAS_INDEX.get((theme_id or "").strip(), None)
    if canon and canon in CATALOG:
        return CATALOG[canon]
    # Фолбэк — универсальные сценарии
    return ThemeScenarios(
        theme_id=theme_id,
        title=fallback_title or "Тема",
        aliases=[],
        scenarios=[
            Scenario(
                id="general_future",
                title="Общий прогноз",
                bullets=[
                    "текущее положение дел",
                    "ближайшие тенденции",
                    "скрытые факторы",
                    "практический совет на 2 недели",
                ],
            ),
        ],
    )

def build_scenario_context(theme_title: str, scenario_title: str, bullets: List[str]) -> str:
    lines = [
        f"Тема: {theme_title}",
        f"Сценарий: {scenario_title}",
        "Уточняющие аспекты для интерпретации:"
    ]
    for b in bullets:
        lines.append(f"- {b}")
    return "\n".join(lines)
