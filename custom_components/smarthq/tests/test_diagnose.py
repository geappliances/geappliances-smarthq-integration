"""Tests for the smarthq.diagnose service helpers."""

from custom_components.smarthq import _diagnose_service_details

SERVICES = [
    {
        "serviceId": "c97c8d939a6b0000",
        "serviceType": "cloud.smarthq.service.integer",
        "domainType": "cloud.smarthq.domain.savings.strategy",
        "supportedCommands": ["cloud.smarthq.command.integer.set"],
        "config": {"minimum": 0, "maximum": 255, "label": "Strategy", "ownerId": "secret-owner"},
    },
    {
        "serviceId": "1184e3905371",
        "serviceType": "cloud.smarthq.service.leaksensor.pairing",
        "domainType": "cloud.smarthq.domain.pair",
        "supportedCommands": [],
        "config": {"sensorMacAddress": "000000000000"},
    },
]


def test_lists_only_matching_services_with_commands_and_config() -> None:
    text = _diagnose_service_details(SERVICES, "Strategy")
    assert "savings.strategy" in text
    assert "cloud.smarthq.command.integer.set" in text
    assert "'maximum': 255" in text
    assert "leaksensor" not in text


def test_identifier_like_config_values_are_redacted() -> None:
    text = _diagnose_service_details(SERVICES, "strategy") + _diagnose_service_details(SERVICES, "pair")
    assert "secret-owner" not in text
    assert "000000000000" not in text
    assert "<redacted>" in text


def test_reports_when_no_service_matches_or_data_is_missing() -> None:
    assert "no service domain contains 'nothing'" in _diagnose_service_details(SERVICES, "nothing")
    assert "no service domain contains 'strategy'" in _diagnose_service_details(None, "strategy")
