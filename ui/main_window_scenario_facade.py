from __future__ import annotations


class MainWindowScenarioFacade:
    """Scenario-related compatibility facade for MainWindow."""

    def __init__(self, window):
        self.window = window

    def scenario_plan_ids_in_tree_order(self) -> list[str]:
        return self.window._scenario_controller.scenario_plan_ids_in_tree_order()

    def clear_scenario_internal(self) -> None:
        self.window._scenario_controller.clear_scenario_internal()

    def on_save_scenario(self) -> None:
        self.window._scenario_controller.save_scenario()

    def on_load_scenario(self) -> None:
        self.window._scenario_controller.load_scenario()

    def on_clear_scenario(self) -> None:
        self.window._scenario_controller.clear_scenario()
