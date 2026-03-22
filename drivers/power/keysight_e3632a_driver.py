from __future__ import annotations

from drivers.common.pyvisa_device_base import PyVisaDeviceBase


class KeysightE3632ADriver(PyVisaDeviceBase):
    def set_voltage(self, value: float) -> None:
        self.write(f"VOLT {value}")

    def set_current_limit(self, value: float) -> None:
        self.write(f"CURR {value}")

    def output_on(self) -> None:
        self.write("OUTP ON")

    def output_off(self) -> None:
        self.write("OUTP OFF")
