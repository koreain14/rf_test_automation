import sys
import logging
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication

from infrastructure.db import init_db
from infrastructure.plan_repo_sqlite import PlanRepositorySQLite
from infrastructure.run_repo_sqlite import RunRepositorySQLite

from application.plan_service import PlanService
from application.run_service_step import RunServiceStep
from application.instrument_factory import AutoInstrumentFactory, DummyInstrumentFactory, ScpiInstrumentFactory
from application.instrument_manager import InstrumentManager
from application.settings_store import SettingsStore

from ui.main_window import MainWindow


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/app.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def install_global_excepthook() -> None:
    log = logging.getLogger("global")

    def excepthook(exctype, value, tb):
        msg = "".join(traceback.format_exception(exctype, value, tb))
        log.error("Uncaught exception:\n%s", msg)
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = excepthook


def build_instrument_manager() -> InstrumentManager:
    settings_store = SettingsStore(Path("config/instrument_settings.json"))
    instrument_settings = settings_store.load_instrument_settings()

    mode = str(instrument_settings.get("mode", "AUTO")).upper()
    resource_name = str(instrument_settings.get("resource_name", "")).strip() or None
    timeout_ms = int(instrument_settings.get("timeout_ms", 10000))

    if mode == "DUMMY":
        factory = DummyInstrumentFactory()
    elif mode == "SCPI":
        factory = ScpiInstrumentFactory(resource_name=resource_name or "", timeout_ms=timeout_ms)
    else:
        factory = AutoInstrumentFactory(resource_name=resource_name, timeout_ms=timeout_ms)

    return InstrumentManager(factory)

 
def main():
    setup_logging()
    install_global_excepthook()

    log = logging.getLogger("main")
    log.info("Starting RF Test Automation...")

    init_db()

    plan_repo = PlanRepositorySQLite()
    run_repo = RunRepositorySQLite()

    projects = plan_repo.list_projects()
    if not projects:
        project_id = plan_repo.create_project(name="RF_Project", description="Default project")
        log.info("Created default project_id=%s", project_id)
    else:
        project_id = projects[0]["project_id"]
        log.info("Using existing project_id=%s", project_id)

    log.info("Preset auto-seeding is disabled. Use Preset Editor to create/import expansion presets.")

    svc = PlanService(repo=plan_repo, run_repo=run_repo, ruleset_dir=Path("rulesets"))
    instrument_manager = build_instrument_manager()
    run_service = RunServiceStep(run_repo=run_repo, instrument_manager=instrument_manager)

    app = QApplication(sys.argv)
    w = MainWindow(plan_service=svc, run_repo=run_repo, run_service=run_service)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
