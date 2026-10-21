from dataclasses import dataclass
from datetime import timedelta

INSPECTION_INTERVAL = timedelta(days=7)
# Reminders go out this many days before a task is due, once each.
REMINDER_OFFSETS = (2, 1)


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    key: str
    # Short name kept with the answer and shown in reports.
    label: str
    question: str
    hint: str


# When the machine as a whole doesn't work it is marked broken and weekly inspections pause.
MACHINE_WORKS = ChecklistItem(
    "machine",
    "Силомер",
    "Силомер работает?",
    "«Да» — если клиент может оплатить хоть одним способом и ударить. "
    "«Нет» — если не включается, не работает экран, не опускается груша, "
    "не работает ни одна оплата или груша порвана так, что бить нельзя.",
)

CHECKLIST: tuple[ChecklistItem, ...] = (
    MACHINE_WORKS,
    ChecklistItem(
        "coin", "Монетоприёмник", "Монетоприёмник работает?", "Монета принимается и засчитывается"
    ),
    ChecklistItem(
        "bill", "Купюроприёмник", "Купюроприёмник работает?", "Купюра затягивается и засчитывается"
    ),
    ChecklistItem(
        "card", "Вендиста", "Терминал безнала (Вендиста) работает?", "Оплата картой проходит"
    ),
)
