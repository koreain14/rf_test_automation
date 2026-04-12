from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from application.test_type_symbols import PLAN_FILTER_TEST_TYPES
from ui.table_model import CaseTableModel, GroupSummaryTableModel


class PlanTab(QWidget):
    """Compatibility-first Plan tab.

    Keeps the legacy tree/detail layout that MainWindow expects, while adding
    the new filter/group/paging widgets needed for the Plan Manager direction.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        scenario_row = QHBoxLayout()
        self.btn_save_scenario = QPushButton("Save Scenario")
        self.btn_load_scenario = QPushButton("Load Scenario")
        self.btn_clear_scenario = QPushButton("Clear Scenario")
        scenario_row.addWidget(self.btn_save_scenario)
        scenario_row.addWidget(self.btn_load_scenario)
        scenario_row.addWidget(self.btn_clear_scenario)
        scenario_row.addStretch(1)
        root.addLayout(scenario_row)

        filter_row = QHBoxLayout()
        self.plan_filter_band = QComboBox()
        self.plan_filter_band.addItem("")
        self.plan_filter_standard = QComboBox()
        self.plan_filter_standard.addItem("")
        self.plan_filter_bw = QComboBox()
        self.plan_filter_bw.addItem("")
        self.plan_filter_test = QComboBox()
        self.plan_filter_test.addItems(["", *PLAN_FILTER_TEST_TYPES])
        self.plan_filter_channel_from = QLineEdit()
        self.plan_filter_channel_from.setPlaceholderText("CH from")
        self.plan_filter_channel_to = QLineEdit()
        self.plan_filter_channel_to.setPlaceholderText("CH to")
        self.plan_filter_enabled = QComboBox()
        self.plan_filter_enabled.addItems(["ALL"])
        self.plan_filter_enabled.setEnabled(False)
        self.plan_filter_enabled.setToolTip("Execution is driven by the current filter result. Row enable/disable is not used in this mode.")
        self.plan_filter_search = QLineEdit()
        self.plan_filter_search.setPlaceholderText("Search")
        self.btn_apply_filter = QPushButton("Apply Filter")
        self.btn_clear_filter = QPushButton("Clear Filter")
        self.btn_run_filtered = QPushButton("Run Filtered")
        self.btn_run_filtered.setToolTip("현재 필터된 케이스만 실행됩니다")
        self.plan_filter_band.setMinimumWidth(120)
        self.plan_filter_standard.setMinimumWidth(180)
        self.plan_filter_bw.setMinimumWidth(90)
        self.plan_filter_test.setMinimumWidth(120)
        self.plan_filter_enabled.setMinimumWidth(100)
        self.plan_filter_search.setMinimumWidth(220)
        self.plan_filter_band.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.plan_filter_standard.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.plan_filter_bw.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.plan_filter_test.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.plan_filter_enabled.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.plan_filter_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for label, widget in (
            ("Band", self.plan_filter_band),
            ("Standard", self.plan_filter_standard),
            ("BW", self.plan_filter_bw),
            ("Test", self.plan_filter_test),
            ("From", self.plan_filter_channel_from),
            ("To", self.plan_filter_channel_to),
            ("Search", self.plan_filter_search),
        ):
            filter_row.addWidget(QLabel(label))
            filter_row.addWidget(widget)
        filter_row.addWidget(self.btn_apply_filter)
        filter_row.addWidget(self.btn_clear_filter)
        filter_row.addWidget(self.btn_run_filtered)
        root.addLayout(filter_row)

        summary_row = QHBoxLayout()
        self.btn_group_drilldown = QPushButton("Drill Down Group")
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["100", "200", "500"])
        self.btn_prev_page = QPushButton("Prev")
        self.btn_next_page = QPushButton("Next")
        self.page_label = QLabel("Showing 0-0 / 0")
        summary_row.addWidget(self.btn_group_drilldown)
        summary_row.addSpacing(12)
        summary_row.addWidget(QLabel("Page Size"))
        summary_row.addWidget(self.page_size_combo)
        summary_row.addWidget(self.btn_prev_page)
        summary_row.addWidget(self.btn_next_page)
        summary_row.addWidget(self.page_label)
        summary_row.addStretch(1)
        root.addLayout(summary_row)

        self.group_table = QTableView()
        self.group_model = GroupSummaryTableModel([])
        self.group_table.setModel(self.group_model)
        self.group_table.setSelectionBehavior(QTableView.SelectRows)
        self.group_table.setSelectionMode(QTableView.SingleSelection)
        self.group_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.group_table)

        splitter = QSplitter(Qt.Horizontal)
        self.tree = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(["Scenario Tree"])
        self.tree.setModel(self.tree_model)

        self.table = QTableView()
        self.case_model = CaseTableModel([])
        self.table.setModel(self.case_model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)

        splitter.addWidget(self.tree)
        splitter.addWidget(self.table)
        splitter.setSizes([350, 850])
        root.addWidget(splitter, 1)
