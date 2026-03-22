from __future__ import annotations


class TmxSwitch:
    def __init__(self, driver):
        self.driver = driver

    def connect(self) -> None:
        if hasattr(self.driver, "connect"):
            self.driver.connect()

    def disconnect(self) -> None:
        if hasattr(self.driver, "disconnect"):
            self.driver.disconnect()

    def list_paths(self):
        if hasattr(self.driver, "list_paths"):
            return self.driver.list_paths()
        return []

    def select_path(self, path_name: str) -> None:
        self.driver.select_path(path_name)
