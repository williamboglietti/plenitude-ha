"""Data models for the Plenitude integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class HalfHourPeriod:
    """Time-of-day period like '07:30:00' → '23:30:00'."""

    start: str  # "HH:MM:SS"
    end: str  # "HH:MM:SS"


@dataclass(slots=True, frozen=True)
class ConsumptionInterval:
    """A single consumption reading for an interval (typically 30 min)."""

    start: datetime
    end: datetime
    kwh_total: float
    kwh_hp: float
    kwh_hc: float
    unit: str = "kWh"

    def __post_init__(self) -> None:
        if self.unit != "kWh":
            raise ValueError(f"unsupported unit: {self.unit}")
        if self.end < self.start:
            raise ValueError("end must be >= start")


@dataclass(slots=True, frozen=True)
class ContractTariffs:
    """Active electricity tariff for a contract."""

    hp_eur_per_kwh: float
    hc_eur_per_kwh: float
    subscription_eur_per_month: float
    hp_periods: tuple[HalfHourPeriod, ...]
    hc_periods: tuple[HalfHourPeriod, ...]
    valid_from: datetime
    valid_to: datetime | None = None

    def is_active_at(self, when: datetime) -> bool:
        """Return True if these tariffs apply at the given datetime."""
        if when < self.valid_from:
            return False
        if self.valid_to is not None and when >= self.valid_to:
            return False
        return True


@dataclass(slots=True, frozen=True)
class ContractInfo:
    """Static information about the contract."""

    site_id: str  # e.g. "A-TEST0000"
    pdl: str | None  # meter point reference, e.g. "12345678901234"
    offer_name: str  # e.g. "Energie Fixe 2 ans Elec"
    tariffs: ContractTariffs


@dataclass(slots=True, frozen=True)
class ConsumptionSnapshot:
    """A normalized snapshot of recent consumption for a site."""

    site_id: str
    intervals: tuple[ConsumptionInterval, ...] = field(default_factory=tuple)
    last_reading_at: datetime | None = None

    @property
    def total_kwh(self) -> float:
        return sum(i.kwh_total for i in self.intervals)

    @property
    def total_hp_kwh(self) -> float:
        return sum(i.kwh_hp for i in self.intervals)

    @property
    def total_hc_kwh(self) -> float:
        return sum(i.kwh_hc for i in self.intervals)
