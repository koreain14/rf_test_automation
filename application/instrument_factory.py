from __future__ import annotations

from application.instrument_base import MeasurementInstrument
from drivers.dummy_instrument_driver import DummyInstrumentDriver
from drivers.scpi_instrument_driver import SCPIInstrumentDriver


class InstrumentFactory:
    def create_measurement_instrument(self) -> MeasurementInstrument:
        raise NotImplementedError


class DummyInstrumentFactory(InstrumentFactory):
    def create_measurement_instrument(self) -> MeasurementInstrument:
        return DummyInstrumentDriver()


class ScpiInstrumentFactory(InstrumentFactory):
    def __init__(self, resource_name: str, timeout_ms: int = 10000):
        self.resource_name = resource_name
        self.timeout_ms = timeout_ms

    def create_measurement_instrument(self) -> MeasurementInstrument:
        inst = SCPIInstrumentDriver(resource_name=self.resource_name, timeout_ms=self.timeout_ms)
        inst.connect()
        return inst


class AutoInstrumentFactory(InstrumentFactory):
    """Prefer SCPI when available; fall back to Dummy so the UI remains usable."""

    def __init__(self, resource_name: str | None = None, timeout_ms: int = 10000):
        self.resource_name = resource_name
        self.timeout_ms = timeout_ms

    def create_measurement_instrument(self) -> MeasurementInstrument:
        if self.resource_name:
            inst = SCPIInstrumentDriver(resource_name=self.resource_name, timeout_ms=self.timeout_ms)
            inst.connect()
            if inst.is_connected:
                return inst
        return DummyInstrumentDriver()
