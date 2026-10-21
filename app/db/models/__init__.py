from app.db.models.crm import Lead, LeadActivity, Milestone
from app.db.models.finance import DailyRevenue, Expense, SyncState
from app.db.models.location import Location, Machine
from app.db.models.rent import RentContract, RentPayment
from app.db.models.staff import Attachment, InspectionCheck, Task, User
from app.db.models.telemetry import ConnectionEvent, EstimatedUptime, TelemetrySale

__all__ = [
    "Attachment",
    "ConnectionEvent",
    "DailyRevenue",
    "EstimatedUptime",
    "Expense",
    "InspectionCheck",
    "Lead",
    "LeadActivity",
    "Location",
    "Machine",
    "Milestone",
    "RentContract",
    "RentPayment",
    "SyncState",
    "Task",
    "TelemetrySale",
    "User",
]
