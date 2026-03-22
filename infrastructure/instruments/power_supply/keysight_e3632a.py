from __future__ import annotations


class KeysightE3632A:
    def __init__(self, driver):
        self.driver = driver

    def connect(self) -> None:
        if hasattr(self.driver, "connect"):
            self.driver.connect()

    def disconnect(self) -> None:
        if hasattr(self.driver, "disconnect"):
            self.driver.disconnect()

    def set_voltage(self, value: float) -> None:
        self.driver.set_voltage(value)

    def set_current_limit(self, value: float) -> None:
        self.driver.set_current_limit(value)

    def output_on(self) -> None:
        self.driver.output_on()

    def output_off(self) -> None:
        self.driver.output_off()
