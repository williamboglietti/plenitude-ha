"""Cost calculation from consumption + tariffs."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime

from .models import ConsumptionSnapshot, ContractTariffs


@dataclass(slots=True, frozen=True)
class CostBreakdown:
    """Cost decomposition for a snapshot."""

    hp_eur: float
    hc_eur: float
    energy_eur: float  # hp_eur + hc_eur
    subscription_eur_prorated: float  # subscription × (elapsed days this month / total days)
    total_eur: float  # energy + subscription_prorated


def calculate_cost(
    snapshot: ConsumptionSnapshot,
    tariffs: ContractTariffs,
    *,
    now: datetime,
) -> CostBreakdown:
    """Compute the cost given the consumption snapshot and tariffs."""
    hp_eur = snapshot.total_hp_kwh * tariffs.hp_eur_per_kwh
    hc_eur = snapshot.total_hc_kwh * tariffs.hc_eur_per_kwh
    energy_eur = hp_eur + hc_eur

    days_in_month = monthrange(now.year, now.month)[1]
    # Elapsed days this month including fractional current day
    elapsed_seconds = (
        (now.day - 1) * 86400
        + now.hour * 3600
        + now.minute * 60
        + now.second
    )
    elapsed_fraction = elapsed_seconds / (days_in_month * 86400)
    subscription_prorated = tariffs.subscription_eur_per_month * elapsed_fraction

    return CostBreakdown(
        hp_eur=hp_eur,
        hc_eur=hc_eur,
        energy_eur=energy_eur,
        subscription_eur_prorated=subscription_prorated,
        total_eur=energy_eur + subscription_prorated,
    )
