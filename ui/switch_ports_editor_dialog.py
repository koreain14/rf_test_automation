from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class SwitchPortsEditorDialog(QDialog):
    def __init__(self, ports: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Switch Ports Editor")
        self.resize(720, 360)

        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Row")
        self.btn_delete = QPushButton("Delete Row")
        self.btn_up = QPushButton("Move Up")
        self.btn_down = QPushButton("Move Down")
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_delete)
        btn_row.addWidget(self.btn_up)
        btn_row.addWidget(self.btn_down)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Path Name", "Command", "Description"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        for port in ports or []:
            self._append_row(
                str(port.get("name", "")),
                str(port.get("command", "")),
                str(port.get("description", "")),
            )

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.btn_add.clicked.connect(self.on_add_row)
        self.btn_delete.clicked.connect(self.on_delete_row)
        self.btn_up.clicked.connect(self.on_move_up)
        self.btn_down.clicked.connect(self.on_move_down)

    def _append_row(self, name: str = "", command: str = "", description: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(command))
        self.table.setItem(row, 2, QTableWidgetItem(description))

    def on_add_row(self) -> None:
        self._append_row()

    def on_delete_row(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        for idx in sorted((r.row() for r in rows), reverse=True):
            self.table.removeRow(idx)

    def _swap_rows(self, r1: int, r2: int) -> None:
        for col in range(self.table.columnCount()):
            item1 = self.table.item(r1, col)
            item2 = self.table.item(r2, col)
            t1 = item1.text() if item1 else ""
            t2 = item2.text() if item2 else ""
            self.table.setItem(r1, col, QTableWidgetItem(t2))
            self.table.setItem(r2, col, QTableWidgetItem(t1))

    def on_move_up(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self.table.selectRow(row - 1)

    def on_move_down(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row >= self.table.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)
        self.table.selectRow(row + 1)

    def _validate(self) -> tuple[bool, str]:
        names = set()
        for row in range(self.table.rowCount()):
            name = (self.table.item(row, 0).text().strip() if self.table.item(row, 0) else "")
            command = (self.table.item(row, 1).text().strip() if self.table.item(row, 1) else "")
            if not name:
                return False, f"Row {row + 1}: Path Name is required."
            if not command:
                return False, f"Row {row + 1}: Command is required."
            key = name.upper()
            if key in names:
                return False, f"Duplicate Path Name: {name}"
            names.add(key)
        return True, ""

    def _on_accept(self) -> None:
        ok, msg = self._validate()
        if not ok:
            QMessageBox.warning(self, "Validation Error", msg)
            return
        self.accept()

    def ports(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().strip() if self.table.item(row, 0) else ""
            command = self.table.item(row, 1).text().strip() if self.table.item(row, 1) else ""
            description = self.table.item(row, 2).text().strip() if self.table.item(row, 2) else ""
            out.append({"name": name, "command": command, "description": description})
        return out
