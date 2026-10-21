from enum import StrEnum


class PaymentChannel(StrEnum):
    CARD = "card"
    COIN = "coin"
    BILL = "bill"


class RevenueSource(StrEnum):
    VENDISTA = "vendista"
    TELEMETRY = "telemetry"
    MANUAL = "manual"


class RentType(StrEnum):
    FIXED = "fixed"
    PERCENT = "percent"


class ExpenseCategory(StrEnum):
    PARTS = "parts"
    REPAIR = "repair"
    ACQUIRING_FEE = "acquiring_fee"
    CONNECTIVITY = "connectivity"
    TRANSPORT = "transport"
    OTHER = "other"


class MilestoneKind(StrEnum):
    MACHINE_LAUNCHED = "machine_launched"
    PAYBACK_REACHED = "payback_reached"
    LOCATION_AGREED = "location_agreed"
    CONTRACT_SIGNED = "contract_signed"
    OTHER = "other"


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    NEGOTIATING = "negotiating"
    AGREED = "agreed"
    POSTPONED = "postponed"
    REJECTED = "rejected"


class LeadActivityKind(StrEnum):
    CALL = "call"
    MESSAGE = "message"
    MEETING = "meeting"
    VISIT = "visit"


class UserRole(StrEnum):
    ADMIN = "admin"
    WORKER = "worker"


class TaskKind(StrEnum):
    INSPECTION = "inspection"
    CUSTOM = "custom"


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELED = "canceled"


class PurchaseStatus(StrEnum):
    NEW = "new"
    ORDERED = "ordered"
    DONE = "done"
