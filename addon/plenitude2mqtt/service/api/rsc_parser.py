"""Parse the RSC payload embedded in the Plenitude /contrat page.

Plenitude's portal is a Next.js App Router app that renders the contract
detail page via React Server Components. The rendered HTML contains the
SSR data sealed in JSON-escaped strings within <script> tags. We grep the
HTML for the tariff payload and JSON-decode it.

The payload contains a `consumptionRates` array (energyUseTimeSlot = PEAK or
OFF_PEAK with timeSlots and pricePerUnitWithTaxes in cents) and a `standingRate`
object (monthly subscription price). Empirical observations:
  - consumptionRates.pricePerUnitWithTaxes is €×100 per kWh (21.114 -> 0.21114 €/kWh)
  - standingRate.pricePerUnitWithTaxes is €×1200 per month (21201.48 -> 17.66790 €/month)
"""
from __future__ import annotations

import re
from datetime import datetime

from ..models import ContractTariffs, HalfHourPeriod


class RscParseError(ValueError):
    """Raised when the tariff payload cannot be found or decoded."""


# In the RSC payload the JSON is embedded in a JS string with escaped quotes:
# \"key\":value  (literal backslash + double-quote pairs in the HTML).
# In Python regex: \\" matches a literal backslash followed by a double-quote.

_Q = r'\\"'  # matches the literal \" escape sequence in the HTML (backslash + quote)

_STANDING_RATE_RE = re.compile(
    _Q + r'standingRate' + _Q + r':\{' + _Q + r'pricePerUnit' + _Q + r':[\d.-]+,'
    + _Q + r'pricePerUnitWithTaxes' + _Q + r':([\d.-]+)\}'
)

# Greedy (.+) so the blob spans from the first rate entry to the last }] before the
# closing \", stopping at the first occurrence of ],\" which closes the outer array.
_CONSUMPTION_RATES_BLOB_RE = re.compile(
    _Q + r'consumptionRates' + _Q + r':\[(.+)\],' + _Q,
    re.DOTALL,
)

# timeSlots entries are plain objects ({startAt, endAt}) with no nested arrays,
# so lazy (.+?) correctly captures one or two entries before the closing ],\"pricePerUnit.
_CONSUMPTION_RATE_RE = re.compile(
    _Q + r'energyUseTimeSlot' + _Q + r':' + _Q + r'(PEAK|OFF_PEAK)' + _Q + r','
    + _Q + r'timeSlots' + _Q + r':\[(.+?)\],'
    + _Q + r'pricePerUnit' + _Q + r':[\d.-]+,'
    + _Q + r'pricePerUnitWithTaxes' + _Q + r':([\d.-]+)',
    re.DOTALL,
)

_TIMESLOT_RE = re.compile(
    _Q + r'startAt' + _Q + r':' + _Q + r'(\d{2}:\d{2}:\d{2})' + _Q + r','
    + _Q + r'endAt' + _Q + r':' + _Q + r'(\d{2}:\d{2}:\d{2})' + _Q
)

_ISO_DATE = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)'
_AGREEMENT_DATES_RE = re.compile(
    _Q + r'endAt' + _Q + r':' + _Q + _ISO_DATE + _Q + r','
    + _Q + r'agreedFrom' + _Q + r':' + _Q + _ISO_DATE + _Q,
    re.DOTALL,
)

# Empirical conversion factors (see live fixture)
_SUBSCRIPTION_DIVISOR = 1200.0
_CONSUMPTION_DIVISOR = 100.0


def parse_rsc_tariffs(html: str) -> ContractTariffs:
    """Extract ContractTariffs from a /contrat page HTML."""
    standing_match = _STANDING_RATE_RE.search(html)
    if not standing_match:
        raise RscParseError("standingRate payload not found in HTML")
    subscription_raw = float(standing_match.group(1))

    blob_match = _CONSUMPTION_RATES_BLOB_RE.search(html)
    if not blob_match:
        raise RscParseError("consumptionRates payload not found in HTML")
    rates_blob = blob_match.group(1)

    hp_periods: list[HalfHourPeriod] = []
    hc_periods: list[HalfHourPeriod] = []
    hp_rate: float | None = None
    hc_rate: float | None = None

    for rate_match in _CONSUMPTION_RATE_RE.finditer(rates_blob):
        slot_type = rate_match.group(1)
        timeslots_blob = rate_match.group(2)
        price_ttc = float(rate_match.group(3)) / _CONSUMPTION_DIVISOR

        periods = [
            HalfHourPeriod(start=ts.group(1), end=ts.group(2))
            for ts in _TIMESLOT_RE.finditer(timeslots_blob)
        ]
        if slot_type == "PEAK":
            hp_periods.extend(periods)
            hp_rate = price_ttc
        else:
            hc_periods.extend(periods)
            hc_rate = price_ttc

    if hp_rate is None or hc_rate is None:
        raise RscParseError("expected both PEAK and OFF_PEAK consumption rates")

    # In the fixture the order is: endAt (agreement end), agreedFrom (agreement start)
    dates_match = _AGREEMENT_DATES_RE.search(html)
    if dates_match:
        valid_to: datetime | None = datetime.fromisoformat(
            dates_match.group(1).replace("Z", "+00:00")
        )
        valid_from = datetime.fromisoformat(
            dates_match.group(2).replace("Z", "+00:00")
        )
    else:
        valid_from = datetime.now().astimezone()
        valid_to = None

    return ContractTariffs(
        hp_eur_per_kwh=hp_rate,
        hc_eur_per_kwh=hc_rate,
        subscription_eur_per_month=subscription_raw / _SUBSCRIPTION_DIVISOR,
        hp_periods=tuple(hp_periods),
        hc_periods=tuple(hc_periods),
        valid_from=valid_from,
        valid_to=valid_to,
    )
