"""Unit tests for the user's local time sentence used in the agent prompt."""

from assistant.agent.clock import describe_now
from assistant.agent.graph import build_system_prompt


def test_client_time_is_described_in_spanish_with_zone():
    text = describe_now("2026-10-30T14:05:09-06:00", "America/Mexico_City")

    assert text == "viernes 30 de octubre de 2026, 14:05 (America/Mexico_City, UTC-06:00)"


def test_offset_only_when_zone_name_is_missing():
    assert describe_now("2026-01-04T09:30:00+05:30", None).endswith("09:30 (UTC+05:30)")


def test_invalid_or_naive_time_falls_back_to_utc():
    for value in (None, "not a date", "2026-10-30T14:05:00"):
        assert "the user's time zone is unknown" in describe_now(value, "Europe/Madrid")


def test_system_prompt_carries_the_time_and_the_name():
    prompt = build_system_prompt([], [], now="viernes 30 de octubre de 2026, 14:05 (UTC-06:00)")

    assert "viernes 30 de octubre de 2026, 14:05" in prompt
    assert "Isabel" in prompt
