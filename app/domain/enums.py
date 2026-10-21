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
    RENT = "rent"
    PARTS = "parts"
    REPAIR = "repair"
    CONNECTIVITY = "connectivity"
    SMARTVEND = "smartvend"
    STAFF = "staff"
    OTHER = "other"
    TAXES = "taxes"
    INSURANCE = "insurance"


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
    COUNT_CASH = "count_cash"
    DEPOSIT_CASH = "deposit_cash"


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELED = "canceled"


class PaidFrom(StrEnum):
    BANK = "bank"
    CASH = "cash"
    PERSONAL = "personal"


class EncashmentStatus(StrEnum):
    COLLECTED = "collected"
    COUNTED = "counted"
    DEPOSITED = "deposited"
