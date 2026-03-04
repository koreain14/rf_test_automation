from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox
)

DEFAULT_ITEMS = ["PSD", "OBW", "SP", "RX"]

class ExecutionOrderDialog(QDialog):
    def __init__(self, initial_order=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Execution Order (Channel-centric)")
        self.resize(320, 420)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Drag to reorder test types.\n(Outer loop: std/band/ch/bw, inner loop: test_type)"))

        self.listw = QListWidget()
        self.listw.setDragDropMode(QListWidget.InternalMove)
        self.listw.setDefaultDropAction(Qt.MoveAction)

        order = list(initial_order) if initial_order else list(DEFAULT_ITEMS)
        # 기본 항목 보장(없는 항목은 뒤에 붙임)
        for t in DEFAULT_ITEMS:
            if t not in order:
                order.append(t)

        for t in order:
            QListWidgetItem(t, self.listw)

        layout.addWidget(self.listw, 1)

        btns = QHBoxLayout()
        self.btn_reset = QPushButton("Reset")
        self.btn_ok = QPushButton("Save")
        self.btn_cancel = QPushButton("Cancel")
        btns.addWidget(self.btn_reset)
        btns.addStretch(1)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)

        self.btn_reset.clicked.connect(self.on_reset)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def on_reset(self):
        self.listw.clear()
        for t in DEFAULT_ITEMS:
            QListWidgetItem(t, self.listw)

    def get_order(self):
        return [self.listw.item(i).text() for i in range(self.listw.count())]