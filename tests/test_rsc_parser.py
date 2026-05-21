"""Tests for the RSC payload parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.plenitude.api.rsc_parser import (
    RscParseError,
    parse_rsc_tariffs,
)
from custom_components.plenitude.models import ContractTariffs, HalfHourPeriod


def test_parse_rsc_tariffs_extracts_hp_hc_and_subscription(fixtures_dir: Path) -> None:
    """parse_rsc_tariffs() extracts HP/HC rates and subscription from /contrat HTML."""
    html = (fixtures_dir / "portal_contract_page.html").read_text(encoding="utf-8")

    tariffs = parse_rsc_tariffs(html)

    assert isinstance(tariffs, ContractTariffs)
    # Values observed live for the test account
    assert tariffs.hp_eur_per_kwh == pytest.approx(0.21114, abs=1e-5)
    assert tariffs.hc_eur_per_kwh == pytest.approx(0.16614, abs=1e-5)
    assert tariffs.subscription_eur_per_month == pytest.approx(17.66790, abs=1e-4)
    assert HalfHourPeriod("07:30:00", "23:30:00") in tariffs.hp_periods
    # HC has TWO periods (wraps midnight)
    assert len(tariffs.hc_periods) == 2


def test_parse_rsc_tariffs_raises_when_payload_missing() -> None:
    """parse_rsc_tariffs() raises RscParseError on unrelated HTML."""
    with pytest.raises(RscParseError):
        parse_rsc_tariffs("<html><body>hello</body></html>")
