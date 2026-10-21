from dataclasses import dataclass
from datetime import timedelta

INSPECTION_INTERVAL = timedelta(days=7)
# Reminders go out this many days before a task is due, once each.
REMINDER_OFFSETS = (2, 1)


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    key: str
    label: str
    hint: str


# When the machine as a whole doesn't work it is marked broken and weekly inspections pause.
MACHINE_WORKS = ChecklistItem("machine", "Силомер работает", "Включается, удар засчитывается")

CHECKLIST: tuple[ChecklistItem, ...] = (
    MACHINE_WORKS,
    ChecklistItem("coin", "Монетоприёмник", "Монета принимается и засчитывается"),
    ChecklistItem("bill", "Купюроприёмник", "Купюра затягивается и засчитывается"),
    ChecklistItem("card", "Терминал оплаты картой", "Терминал включён и принимает оплату"),
)
