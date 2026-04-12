from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.preset_model import (
    PresetModel,
    WlanChannelRowModel,
    WlanExpansionModel,
    WlanModeRowModel,
)
from ui.preset_editors.base_editor import BaseExpansionEditor


class WlanExpansionEditor(BaseExpansionEditor):
    """Table-based WLAN expansion editor.

    This keeps legacy JSON compatibility while making the editor usable without
    memorizing text formats like `802.11ax|HE|20,40,80`.
    """

    content_changed = Signal()

    STANDARD_OPTIONS = ["802.11a", "802.11b", "802.11g", "802.11n", "802.11ac", "802.11ax", "802.11be"]
    PHY_OPTIONS = ["DSSS", "OFDM", "HT", "VHT", "HE", "EHT"]

    QUICK_PROFILES = {
        "2.4G Basic": {
            "mode_plan": [
                {"standard": "802.11b", "phy_mode": "DSSS", "bandwidths_mhz": [20]},
                {"standard": "802.11g", "phy_mode": "OFDM", "bandwidths_mhz": [20]},
                {"standard": "802.11n", "phy_mode": "HT", "bandwidths_mhz": [20, 40]},
                {"standard": "802.11ax", "phy_mode": "HE", "bandwidths_mhz": [20, 40]},
            ],
            "channel_plan": [
                {"bandwidth_mhz": 20, "channels": [1, 6, 11], "frequencies_mhz": [2412, 2437, 2462]},
                {"bandwidth_mhz": 40, "channels": [3, 11], "frequencies_mhz": [2422, 2462]},
            ],
        },
        "5G Basic": {
            "mode_plan": [
                {"standard": "802.11a", "phy_mode": "OFDM", "bandwidths_mhz": [20]},
                {"standard": "802.11n", "phy_mode": "HT", "bandwidths_mhz": [20, 40]},
                {"standard": "802.11ac", "phy_mode": "VHT", "bandwidths_mhz": [20, 40, 80]},
                {"standard": "802.11ax", "phy_mode": "HE", "bandwidths_mhz": [20, 40, 80]},
            ],
            "channel_plan": [
                {"bandwidth_mhz": 20, "channels": [36, 52, 100, 149], "frequencies_mhz": [5180, 5260, 5500, 5745]},
                {"bandwidth_mhz": 40, "channels": [38, 54, 102, 151], "frequencies_mhz": [5190, 5270, 5510, 5755]},
                {"bandwidth_mhz": 80, "channels": [42, 58, 106, 155], "frequencies_mhz": [5210, 5290, 5530, 5775]},
            ],
        },
        "All WLAN Modes": {
            "mode_plan": [
                {"standard": "802.11a", "phy_mode": "OFDM", "bandwidths_mhz": [20]},
                {"standard": "802.11b", "phy_mode": "DSSS", "bandwidths_mhz": [20]},
                {"standard": "802.11g", "phy_mode": "OFDM", "bandwidths_mhz": [20]},
                {"standard": "802.11n", "phy_mode": "HT", "bandwidths_mhz": [20, 40]},
                {"standard": "802.11ac", "phy_mode": "VHT", "bandwidths_mhz": [20, 40, 80]},
                {"standard": "802.11ax", "phy_mode": "HE", "bandwidths_mhz": [20, 40, 80]},
            ],
            "channel_plan": [
                {"bandwidth_mhz": 20, "channels": [1, 6, 11, 36, 52, 100, 149], "frequencies_mhz": [2412, 2437, 2462, 5180, 5260, 5500, 5745]},
                {"bandwidth_mhz": 40, "channels": [3, 11, 38, 54, 102, 151], "frequencies_mhz": [2422, 2462, 5190, 5270, 5510, 5755]},
                {"bandwidth_mhz": 80, "channels": [42, 58, 106, 155], "frequencies_mhz": [5210, 5290, 5530, 5775]},
            ],
        },
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._loading = False

        root = QVBoxLayout(self)

        help_label = QLabel(
            "Use this tab when one preset should expand into many WLAN combinations.\n"
            "1) Load a quick profile. 2) Adjust mode rows. 3) Adjust channel rows.\n"
            "Bandwidths / Channels / Frequencies are comma-separated."
        )
        help_label.setWordWrap(True)
        root.addWidget(help_label)

        quick_row = QHBoxLayout()
        self.btn_load_24g = QPushButton("Load 2.4G Basic")
        self.btn_load_5g = QPushButton("Load 5G Basic")
        self.btn_load_all = QPushButton("Load All WLAN Modes")
        self.btn_clear = QPushButton("Clear")
        for btn in (self.btn_load_24g, self.btn_load_5g, self.btn_load_all, self.btn_clear):
            quick_row.addWidget(btn)
        quick_row.addStretch(1)
        root.addLayout(quick_row)

        tables = QGridLayout()
        root.addLayout(tables, 1)

        # Mode plan table
        grp_modes = QGroupBox("Mode Plan")
        mode_layout = QVBoxLayout(grp_modes)
        self.mode_table = QTableWidget(0, 3)
        self.mode_table.setHorizontalHeaderLabels(["Standard", "PHY Mode", "Bandwidths MHz"])
        self.mode_table.horizontalHeader().setStretchLastSection(True)
        self.mode_table.verticalHeader().setVisible(False)
        mode_layout.addWidget(self.mode_table)
        mode_btns = QHBoxLayout()
        self.btn_add_mode = QPushButton("Add Mode Row")
        self.btn_remove_mode = QPushButton("Remove Selected")
        mode_btns.addWidget(self.btn_add_mode)
        mode_btns.addWidget(self.btn_remove_mode)
        mode_btns.addStretch(1)
        mode_layout.addLayout(mode_btns)
        tables.addWidget(grp_modes, 0, 0)

        # Channel plan table
        grp_channels = QGroupBox("Channel Plan")
        channel_layout = QVBoxLayout(grp_channels)
        self.channel_table = QTableWidget(0, 3)
        self.channel_table.setHorizontalHeaderLabels(["Bandwidth MHz", "Channels", "Frequencies MHz"])
        self.channel_table.horizontalHeader().setStretchLastSection(True)
        self.channel_table.verticalHeader().setVisible(False)
        channel_layout.addWidget(self.channel_table)
        channel_btns = QHBoxLayout()
        self.btn_add_channel = QPushButton("Add Channel Row")
        self.btn_remove_channel = QPushButton("Remove Selected")
        channel_btns.addWidget(self.btn_add_channel)
        channel_btns.addWidget(self.btn_remove_channel)
        channel_btns.addStretch(1)
        channel_layout.addLayout(channel_btns)
        tables.addWidget(grp_channels, 0, 1)

        self.lb_summary = QLabel()
        self.lb_summary.setWordWrap(True)
        root.addWidget(self.lb_summary)

        self.btn_load_24g.clicked.connect(lambda: self.load_quick_profile("2.4G Basic"))
        self.btn_load_5g.clicked.connect(lambda: self.load_quick_profile("5G Basic"))
        self.btn_load_all.clicked.connect(lambda: self.load_quick_profile("All WLAN Modes"))
        self.btn_clear.clicked.connect(self.clear_editor)
        self.btn_add_mode.clicked.connect(self._add_empty_mode_row)
        self.btn_remove_mode.clicked.connect(self._remove_selected_mode_rows)
        self.btn_add_channel.clicked.connect(self._add_empty_channel_row)
        self.btn_remove_channel.clicked.connect(self._remove_selected_channel_rows)
        self.mode_table.itemChanged.connect(self._on_table_changed)
        self.channel_table.itemChanged.connect(self._on_table_changed)

        self._update_summary()

    def expansion_type(self) -> str:
        return "wlan"

    def load_from_model(self, preset: PresetModel) -> None:
        wlan_model = preset.selection.wlan_expansion
        if wlan_model is None:
            meta = dict(preset.selection.metadata or {})
            wlan = dict(meta.get("wlan_expansion") or {})
            mode_plan = list(wlan.get("mode_plan") or [])
            channel_plan = list(wlan.get("channel_plan") or [])
        else:
            mode_plan = [
                {"standard": row.standard, "phy_mode": row.phy_mode, "bandwidths_mhz": list(row.bandwidths_mhz)}
                for row in wlan_model.mode_plan
            ]
            channel_plan = [
                {
                    "bandwidth_mhz": row.bandwidth_mhz,
                    "channels": list(row.channels),
                    "frequencies_mhz": list(row.frequencies_mhz),
                }
                for row in wlan_model.channel_plan
            ]

        self._loading = True
        try:
            self.mode_table.setRowCount(0)
            self.channel_table.setRowCount(0)

            for item in mode_plan:
                self._append_mode_row(
                    standard=str(item.get("standard", item.get("mode", ""))).strip(),
                    phy_mode=str(item.get("phy_mode", "")).strip(),
                    bandwidths=_csv(item.get("bandwidths_mhz") or []),
                )
            for item in channel_plan:
                self._append_channel_row(
                    bandwidth=_value_to_text(item.get("bandwidth_mhz", "")),
                    channels=_csv(item.get("channels") or []),
                    frequencies=_csv(item.get("frequencies_mhz") or []),
                )
        finally:
            self._loading = False
        self._update_summary()
        self.content_changed.emit()

    def apply_to_model(self, preset: PresetModel) -> None:
        mode_plan = self._collect_mode_rows()
        channel_plan = self._collect_channel_rows()

        preset.selection.wlan_expansion = WlanExpansionModel(
            mode_plan=[
                WlanModeRowModel(
                    standard=str(item.get("standard", item.get("mode", ""))).strip(),
                    phy_mode=str(item.get("phy_mode", "")).strip(),
                    bandwidths_mhz=[int(x) for x in (item.get("bandwidths_mhz") or [])],
                )
                for item in mode_plan
            ],
            channel_plan=[
                WlanChannelRowModel(
                    bandwidth_mhz=int(item.get("bandwidth_mhz", 20) or 20),
                    channels=[int(x) for x in (item.get("channels") or [])],
                    frequencies_mhz=[float(x) for x in (item.get("frequencies_mhz") or [])],
                )
                for item in channel_plan
            ],
        )

        preset.selection.metadata = dict(preset.selection.metadata or {})

    def load_quick_profile(self, profile_name: str) -> None:
        profile = self.QUICK_PROFILES.get(profile_name)
        if not profile:
            return
        self._loading = True
        try:
            self.mode_table.setRowCount(0)
            self.channel_table.setRowCount(0)
            for item in profile["mode_plan"]:
                self._append_mode_row(
                    standard=str(item.get("standard", "")),
                    phy_mode=str(item.get("phy_mode", "")),
                    bandwidths=_csv(item.get("bandwidths_mhz") or []),
                )
            for item in profile["channel_plan"]:
                self._append_channel_row(
                    bandwidth=_value_to_text(item.get("bandwidth_mhz", "")),
                    channels=_csv(item.get("channels") or []),
                    frequencies=_csv(item.get("frequencies_mhz") or []),
                )
        finally:
            self._loading = False
        self._update_summary()
        self.content_changed.emit()

    def clear_editor(self) -> None:
        self._loading = True
        try:
            self.mode_table.setRowCount(0)
            self.channel_table.setRowCount(0)
        finally:
            self._loading = False
        self._update_summary()
        self.content_changed.emit()

    def validate_messages(self) -> list[str]:
        msgs: list[str] = []
        for idx, row in enumerate(self._collect_mode_rows(), start=1):
            if not str(row.get("standard", "")).strip():
                msgs.append(f"WLAN mode row {idx}: standard is required.")
            if not str(row.get("phy_mode", "")).strip():
                msgs.append(f"WLAN mode row {idx}: PHY mode is required.")
            if not row.get("bandwidths_mhz"):
                msgs.append(f"WLAN mode row {idx}: at least one bandwidth is required.")
        for item in self._collect_channel_rows():
            bw = item.get("bandwidth_mhz")
            if not bw:
                msgs.append("WLAN channel row: bandwidth is required.")
            if not item.get("channels"):
                msgs.append(f"WLAN channel row {bw or '?'} MHz: channels are required.")
        return msgs

    def primary_standard(self) -> str:
        for row in self._collect_mode_rows():
            std = str(row.get("standard", "")).strip()
            if std:
                return std
        return ""

    def _append_mode_row(self, standard: str = "", phy_mode: str = "", bandwidths: str = "") -> None:
        row = self.mode_table.rowCount()
        self.mode_table.insertRow(row)

        standard_combo = self._create_combo(self.STANDARD_OPTIONS, standard)
        phy_combo = self._create_combo(self.PHY_OPTIONS, phy_mode)
        self.mode_table.setCellWidget(row, 0, standard_combo)
        self.mode_table.setCellWidget(row, 1, phy_combo)
        self.mode_table.setItem(row, 2, QTableWidgetItem(bandwidths))

    def _append_channel_row(self, bandwidth: str = "", channels: str = "", frequencies: str = "") -> None:
        row = self.channel_table.rowCount()
        self.channel_table.insertRow(row)
        self.channel_table.setItem(row, 0, QTableWidgetItem(bandwidth))
        self.channel_table.setItem(row, 1, QTableWidgetItem(channels))
        self.channel_table.setItem(row, 2, QTableWidgetItem(frequencies))

    def _create_combo(self, options: list[str], value: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setEditable(True)
        combo.addItems(options)
        if value:
            combo.setCurrentText(value)
        combo.currentTextChanged.connect(self._on_table_changed)
        return combo

    def _add_empty_mode_row(self) -> None:
        self._append_mode_row()
        self._update_summary()
        self.content_changed.emit()

    def _add_empty_channel_row(self) -> None:
        self._append_channel_row()
        self._update_summary()
        self.content_changed.emit()

    def _remove_selected_mode_rows(self) -> None:
        self._remove_selected_rows(self.mode_table)

    def _remove_selected_channel_rows(self) -> None:
        self._remove_selected_rows(self.channel_table)

    def _remove_selected_rows(self, table: QTableWidget) -> None:
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        self._loading = True
        try:
            for row in rows:
                table.removeRow(row)
        finally:
            self._loading = False
        self._update_summary()
        self.content_changed.emit()

    def _on_table_changed(self, *_args) -> None:
        if self._loading:
            return
        self._update_summary()
        self.content_changed.emit()

    def _collect_mode_rows(self) -> list[dict]:
        rows: list[dict] = []
        for row_idx in range(self.mode_table.rowCount()):
            standard_combo = self.mode_table.cellWidget(row_idx, 0)
            phy_combo = self.mode_table.cellWidget(row_idx, 1)
            bw_item = self.mode_table.item(row_idx, 2)

            standard = standard_combo.currentText().strip() if isinstance(standard_combo, QComboBox) else ""
            phy_mode = phy_combo.currentText().strip() if isinstance(phy_combo, QComboBox) else ""
            bw_text = bw_item.text().strip() if bw_item and bw_item.text() else ""

            if not standard and not phy_mode and not bw_text:
                continue

            bandwidths_mhz: list[int] = []
            if bw_text:
                for part in [p.strip() for p in bw_text.split(",") if p.strip()]:
                    try:
                        bandwidths_mhz.append(int(part))
                    except Exception:
                        continue

            rows.append({
                "standard": standard,
                "phy_mode": phy_mode,
                "bandwidths_mhz": bandwidths_mhz,
            })
        return rows

    def _collect_channel_rows(self) -> list[dict]:
        rows: list[dict] = []
        for row_idx in range(self.channel_table.rowCount()):
            bw_item = self.channel_table.item(row_idx, 0)
            ch_item = self.channel_table.item(row_idx, 1)
            freq_item = self.channel_table.item(row_idx, 2)

            bw_text = bw_item.text().strip() if bw_item and bw_item.text() else ""
            ch_text = ch_item.text().strip() if ch_item and ch_item.text() else ""
            freq_text = freq_item.text().strip() if freq_item and freq_item.text() else ""

            if not bw_text and not ch_text and not freq_text:
                continue

            try:
                bandwidth_mhz = int(bw_text) if bw_text else None
            except Exception:
                bandwidth_mhz = None

            channels: list[int] = []
            if ch_text:
                for part in [p.strip() for p in ch_text.split(",") if p.strip()]:
                    try:
                        channels.append(int(part))
                    except Exception:
                        continue

            frequencies_mhz: list[float] = []
            if freq_text:
                for part in [p.strip() for p in freq_text.split(",") if p.strip()]:
                    try:
                        frequencies_mhz.append(float(part))
                    except Exception:
                        continue

            rows.append({
                "bandwidth_mhz": bandwidth_mhz,
                "channels": channels,
                "frequencies_mhz": frequencies_mhz,
            })
        return rows

    def _update_summary(self) -> None:
        mode_rows = self._collect_mode_rows()
        channel_rows = self._collect_channel_rows()
        standards = [row.get("standard", "") for row in mode_rows if row.get("standard", "")]
        bws = sorted({int(bw) for row in mode_rows for bw in (row.get("bandwidths_mhz") or [])})
        guidance = (
            "How to use: 1) pick a quick profile, 2) adjust mode/channel rows, "
            "3) choose tests, 4) check Preview."
        )
        self.lb_summary.setText(
            guidance
            + "\nQuick Summary: "
            + f"mode rows={len(mode_rows)}, channel rows={len(channel_rows)}, "
            + f"standards={', '.join(standards) if standards else '-'}, "
            + f"bandwidths={', '.join(str(bw) for bw in bws) if bws else '-'}"
        )


def _csv(values: list[object]) -> str:
    return ", ".join(str(v) for v in values)


def _value_to_text(value: object) -> str:
    return "" if value is None else str(value)
