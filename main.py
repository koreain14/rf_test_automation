import sys
import logging
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication

from infrastructure.db import init_db
from infrastructure.plan_repo_sqlite import PlanRepositorySQLite
from infrastructure.run_repo_sqlite import RunRepositorySQLite

from application.plan_service import PlanService
from application.preset_seeder import seed_presets_from_folder
from application.run_service_step import RunServiceStep

from ui.main_window import MainWindow


def setup_logging() -> None:
    """Configure app-wide logging.

    Why we do this:
    - RF automation is I/O heavy (instruments/DB/UI). Silent failures are painful.
    - We want every traceback to be visible in BOTH:
      1) VSCode terminal (StreamHandler)
      2) logs/app.log (FileHandler)
    """
    Path("logs").mkdir(exist_ok=True)

    # NOTE: basicConfig should be called once at process start.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/app.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def install_global_excepthook() -> None:
    """Catch uncaught exceptions and write them to logs/app.log.

    This helps when:
    - Exceptions occur outside our RunWorker try/except
      (e.g., Qt event callbacks, signals, background threads, etc.)
    """
    log = logging.getLogger("global")

    def excepthook(exctype, value, tb):
        msg = "".join(traceback.format_exception(exctype, value, tb))
        log.error("Uncaught exception:\n%s", msg)
        # Keep default behavior (prints to stderr) for dev visibility.
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = excepthook


def main():
    # ✅ Must be done first (before any UI / services start)
    setup_logging()
    install_global_excepthook()

    log = logging.getLogger("main")
    log.info("Starting RF Test Automation...")

    # ✅ DB init (schema)
    init_db()

    plan_repo = PlanRepositorySQLite()
    run_repo = RunRepositorySQLite()

    # ✅ Ensure a default demo project exists.
    project_id = plan_repo.ensure_demo_project("DEMO_PROJECT")
    log.info("Using project_id=%s", project_id)

    # ✅ Seed presets from presets/ folder into DB.
    inserted, updated = seed_presets_from_folder(
        repo=plan_repo,
        project_id=project_id,
        presets_dir=Path("presets"),
        update_policy="if_ruleset_version_changed",
    )
    log.info("Preset seed done. inserted=%s updated=%s", inserted, updated)

    # Application services (business orchestration)
    svc = PlanService(repo=plan_repo, run_repo=run_repo, ruleset_dir=Path("rulesets"))
    run_service = RunServiceStep(run_repo=run_repo)

    # UI
    app = QApplication(sys.argv)
    w = MainWindow(plan_service=svc, run_repo=run_repo, run_service=run_service)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
