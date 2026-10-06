"""Horloge factice du throttle Steam, sans attente réelle."""

import pytest

from orchestration.steam import resources


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(resources.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(resources.time, "sleep", fake.sleep)
    return fake
