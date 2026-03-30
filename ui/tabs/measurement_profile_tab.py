from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from application.measurement_profile_editor_support import CHOICE_OPTIONS
from application.measurement_profile_editor_support import COMMON_FIELD_SPECS
from application.measurement_profile_editor_support import MEASUREMENT_FIELD_SPECS
from application.measurement_profile_editor_support import build_override_document
from application.measurement_profile_editor_support import clone_document
from application.measurement_profile_editor_support import cycle_forbidden_base_names
from application.measurement_profile_editor_support import default_editor_document
from application.measurement_profile_editor_support import effective_base_name
from application.measurement_profile_editor_support import resolved_base_profile
from application.measurement_profile_loader import MeasurementProfileLoader
from application.measurement_profile_model import MeasurementProfileDocument
from application.test_type_symbols import CANONICAL_TEST_TYPES


class ProfileValueField(QWidget):
    def __init__(self, *, field_key: str, label: str, kind: str, display_unit: str = "", parent=None):
        super().__init__(parent)
        self.field_key = str(field_key)
        self.kind = str(kind)
        self.label = str(label)
        self.display_unit = str(display_unit or "")
        self._base_value = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.override_check = QCheckBox("Override")
        self.editor = self._build_editor()
        self.state_label = QLabel("Inherited")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFixedWidth(60)

        row.addWidget(self.override_check)
        row.addWidget(self.editor, 1)
        row.addWidget(self.state_label)
        row.addWidget(self.reset_btn)
        root.addLayout(row)

        self.inherited_label = QLabel("Inherited: -")
        self.inherited_label.setWordWrap(True)
        root.addWidget(self.inherited_label)

        self.override_check.toggled.connect(self._sync_state)
        self.reset_btn.clicked.connect(self.on_reset)
        if isinstance(self.editor, QLineEdit):
            self.editor.textChanged.connect(self._sync_state)
        else:
            self.editor.currentTextChanged.connect(self._sync_state)

    def _build_editor(self):
        if self.kind == "choice":
            combo = QComboBox()
            combo.addItem("(empty)")
            for item in CHOICE_OPTIONS.get(self.label_to_key(), []):
                combo.addItem(item)
            combo.setEditable(False)
            return combo

        edit = QLineEdit()
        if self.kind == "int":
            edit.setValidator(QIntValidator(0, 2_000_000_000, edit))
        elif self.kind == "float":
            validator = QDoubleValidator(-9999999.0, 9999999.0, 6, edit)
            validator.setNotation(QDoubleValidator.StandardNotation)
            edit.setValidator(validator)
        return edit

    def label_to_key(self) -> str:
        for key, values in CHOICE_OPTIONS.items():
            if key == self.field_key:
                return key
        return self.field_key

    def set_state(self, *, base_value: Any, effective_value: Any, overridden: bool, read_only: bool) -> None:
        self._base_value = base_value
        self.override_check.blockSignals(True)
        self.override_check.setChecked(bool(overridden))
        self.override_check.blockSignals(False)
        self._set_editor_value(effective_value)
        self.inherited_label.setText(f"Inherited: {self._format_value(base_value)}")
        self.override_check.setEnabled(not read_only)
        self.reset_btn.setEnabled((not read_only) and bool(overridden))
        self._sync_state()
        self._set_editor_read_only(read_only or not overridden)

    def _set_editor_read_only(self, read_only: bool) -> None:
        if isinstance(self.editor, QLineEdit):
            self.editor.setReadOnly(read_only)
        else:
            self.editor.setEnabled(not read_only)

    def _set_editor_value(self, value: Any) -> None:
        display_value = self._to_display_value(value)
        if isinstance(self.editor, QLineEdit):
            self.editor.blockSignals(True)
            self.editor.setText("" if display_value in (None, "") else str(display_value))
            self.editor.blockSignals(False)
            return
        self.editor.blockSignals(True)
        text_value = "" if display_value in (None, "") else str(display_value)
        idx = self.editor.findText(text_value)
        self.editor.setCurrentIndex(idx if idx >= 0 else 0)
        self.editor.blockSignals(False)

    def on_reset(self) -> None:
        self.override_check.setChecked(False)
        self._set_editor_value(self._base_value)
        self._sync_state()

    def _sync_state(self) -> None:
        overridden = self.override_check.isChecked()
        self.state_label.setText("Override" if overridden else "Inherited")
        self.reset_btn.setEnabled(overridden and self.override_check.isEnabled())
        self._set_editor_read_only((not overridden) or (not self.override_check.isEnabled()))

    def is_overridden(self) -> bool:
        return self.override_check.isChecked()

    def value(self) -> Any:
        if isinstance(self.editor, QLineEdit):
            text = self.editor.text().strip()
            if text == "":
                return None
            if self.kind == "int":
                value = int(text)
                return self._from_display_value(value)
            if self.kind == "float":
                value = float(text)
                return self._from_display_value(value)
            return self._from_display_value(text)
        text = self.editor.currentText().strip()
        value = None if text in ("", "(empty)") else text
        return self._from_display_value(value)

    def _format_value(self, value: Any) -> str:
        if value in (None, ""):
            return "-"
        display_value = self._to_display_value(value)
        if display_value in (None, ""):
            return "-"
        return str(display_value)

    def _to_display_value(self, value: Any) -> Any:
        if value in (None, ""):
            return value
        if self.display_unit == "mhz":
            try:
                return float(value) / 1_000_000.0
            except Exception:
                return value
        return value

    def _from_display_value(self, value: Any) -> Any:
        if value in (None, ""):
            return value
        if self.display_unit == "mhz":
            try:
                return float(value) * 1_000_000.0
            except Exception:
                return value
        return value


class MeasurementProfileTab(QWidget):
    def __init__(self, loader: MeasurementProfileLoader | None = None, parent=None):
        super().__init__(parent)
        self.loader = loader or MeasurementProfileLoader()
        self._current_document: MeasurementProfileDocument | None = None
        self._dirty = False
        self._loading = False
        self._common_fields: dict[str, ProfileValueField] = {}
        self._measurement_fields: dict[str, dict[str, ProfileValueField]] = {}
        self._build_ui()
        self.reload_profiles()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Measurement Profiles"))
        self.profile_list = QListWidget()
        left_layout.addWidget(self.profile_list, 1)

        left_btns = QHBoxLayout()
        self.btn_reload = QPushButton("Reload")
        self.btn_new = QPushButton("New")
        self.btn_duplicate = QPushButton("Duplicate")
        left_btns.addWidget(self.btn_reload)
        left_btns.addWidget(self.btn_new)
        left_btns.addWidget(self.btn_duplicate)
        left_layout.addLayout(left_btns)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        top_actions = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save As")
        top_actions.addStretch(1)
        top_actions.addWidget(self.btn_save)
        top_actions.addWidget(self.btn_save_as)
        right_layout.addLayout(top_actions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        self.form_layout = QVBoxLayout(scroll_body)

        general_box = QGroupBox("Profile")
        general_form = QFormLayout(general_box)
        self.name_edit = QLineEdit()
        self.base_combo = QComboBox()
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(90)
        self.mode_label = QLabel("Editable")
        general_form.addRow("Profile Name", self.name_edit)
        general_form.addRow("Base Profile", self.base_combo)
        general_form.addRow("Description", self.description_edit)
        general_form.addRow("Mode", self.mode_label)
        self.form_layout.addWidget(general_box)

        common_box = QGroupBox("Common")
        common_form = QFormLayout(common_box)
        for spec in COMMON_FIELD_SPECS:
            field = ProfileValueField(
                field_key=spec["key"],
                label=spec["label"],
                kind=spec["kind"],
                display_unit=str(spec.get("display_unit", "")),
                parent=self,
            )
            self._common_fields[spec["key"]] = field
            common_form.addRow(spec["label"], field)
        self.form_layout.addWidget(common_box)

        for test_type in CANONICAL_TEST_TYPES:
            box = QGroupBox(test_type)
            form = QFormLayout(box)
            self._measurement_fields[test_type] = {}
            for spec in MEASUREMENT_FIELD_SPECS:
                field = ProfileValueField(
                    field_key=spec["key"],
                    label=spec["label"],
                    kind=spec["kind"],
                    display_unit=str(spec.get("display_unit", "")),
                    parent=self,
                )
                self._measurement_fields[test_type][spec["key"]] = field
                form.addRow(spec["label"], field)
            self.form_layout.addWidget(box)

        self.form_layout.addStretch(1)
        scroll.setWidget(scroll_body)
        right_layout.addWidget(scroll, 1)

        self.status_label = QLabel("Ready")
        right_layout.addWidget(self.status_label)
        splitter.addWidget(right)
        splitter.setSizes([240, 860])

        self.profile_list.currentTextChanged.connect(self.on_profile_selected)
        self.btn_reload.clicked.connect(self.on_reload)
        self.btn_new.clicked.connect(self.on_new)
        self.btn_duplicate.clicked.connect(self.on_duplicate)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_save_as.clicked.connect(self.on_save_as)
        self.name_edit.textChanged.connect(self._mark_dirty)
        self.base_combo.currentTextChanged.connect(self._on_base_changed)
        self.description_edit.textChanged.connect(self._mark_dirty)

        for field in self._all_fields():
            field.override_check.toggled.connect(self._mark_dirty)
            if isinstance(field.editor, QLineEdit):
                field.editor.textChanged.connect(self._mark_dirty)
            else:
                field.editor.currentTextChanged.connect(self._mark_dirty)

    def _all_fields(self) -> list[ProfileValueField]:
        fields = list(self._common_fields.values())
        for section in self._measurement_fields.values():
            fields.extend(section.values())
        return fields

    def reload_profiles(self, select_name: str | None = None) -> None:
        documents = self.loader.list_profiles()
        current_name = select_name or (self._current_document.name if self._current_document else "")

        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for doc in documents:
            self.profile_list.addItem(doc.name)
        self.profile_list.blockSignals(False)

        target_name = current_name or (documents[0].name if documents else "")
        if target_name:
            matches = self.profile_list.findItems(target_name, Qt.MatchExactly)
            if matches:
                self.profile_list.setCurrentItem(matches[0])
                self._load_profile(matches[0].text())
                return

        self._load_document(default_editor_document(self.loader))

    def _load_profile(self, profile_name: str) -> None:
        document = self.loader.get_profile_document(profile_name)
        if document is None:
            self._load_document(default_editor_document(self.loader))
            return
        self._load_document(document)

    def _load_document(self, document: MeasurementProfileDocument) -> None:
        self._loading = True
        self._current_document = clone_document(document)

        effective_base = effective_base_name(self.loader, self._current_document)
        base_profile = resolved_base_profile(self.loader, self._current_document)
        base_common = dict(base_profile.get("common") or {})
        base_measurements = dict(base_profile.get("measurements") or {})
        is_default = self._current_document.name == "default"

        self.name_edit.setText(self._current_document.name)
        self.description_edit.setPlainText(self._current_document.description)
        self._reload_base_combo(self._current_document.name, effective_base)
        self.mode_label.setText("Read-only baseline" if is_default else "Editable override profile")
        self.name_edit.setReadOnly(is_default)
        self.base_combo.setEnabled(not is_default)
        self.description_edit.setReadOnly(is_default)

        for key, field in self._common_fields.items():
            overridden = key in self._current_document.common
            effective_value = self._current_document.common.get(key, base_common.get(key))
            field.set_state(
                base_value=base_common.get(key),
                effective_value=effective_value,
                overridden=overridden,
                read_only=is_default,
            )

        for test_type, fields in self._measurement_fields.items():
            raw_section = dict(self._current_document.measurements.get(test_type) or {})
            base_section = dict(base_measurements.get(test_type) or {})
            for key, field in fields.items():
                overridden = key in raw_section
                effective_value = raw_section.get(key, base_section.get(key))
                field.set_state(
                    base_value=base_section.get(key),
                    effective_value=effective_value,
                    overridden=overridden,
                    read_only=is_default,
                )

        self.btn_save.setEnabled(not is_default)
        self.btn_save_as.setEnabled(True)
        self._set_dirty(False)
        self.status_label.setText(f"Loaded: {self._current_document.name or '(new profile)'}")
        self._loading = False

    def _reload_base_combo(self, current_name: str, selected_base: str) -> None:
        forbidden = cycle_forbidden_base_names(self.loader, current_name)
        documents = self.loader.list_profiles()
        self.base_combo.blockSignals(True)
        self.base_combo.clear()
        self.base_combo.addItem("(None)", "")
        for doc in documents:
            if doc.name in forbidden:
                continue
            self.base_combo.addItem(doc.name, doc.name)
        idx = self.base_combo.findData(selected_base)
        self.base_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.base_combo.blockSignals(False)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        suffix = " *" if self._dirty else ""
        name = self._current_document.name if self._current_document else ""
        self.status_label.setText(f"{name or '(new profile)'}{suffix}")

    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        self._set_dirty(True)

    def _on_base_changed(self, *_args) -> None:
        if self._loading:
            return
        self._set_dirty(True)

    def on_profile_selected(self, profile_name: str) -> None:
        if not profile_name:
            return
        self._load_profile(profile_name)

    def on_reload(self) -> None:
        self.reload_profiles()

    def on_new(self) -> None:
        self._load_document(default_editor_document(self.loader))
        self.status_label.setText("New measurement profile")

    def on_duplicate(self) -> None:
        if self._current_document is None:
            self.on_new()
            return
        source = clone_document(self._current_document)
        name, ok = QInputDialog.getText(self, "Duplicate Profile", "New profile name:")
        if not ok:
            return
        clean_name = str(name or "").strip()
        if not clean_name:
            QMessageBox.warning(self, "Duplicate failed", "Profile name is required.")
            return
        source.name = clean_name
        source.source_path = None
        self._load_document(source)
        self._set_dirty(True)

    def on_save(self) -> None:
        self._save_impl(save_as=False)

    def on_save_as(self) -> None:
        self._save_impl(save_as=True)

    def _save_impl(self, *, save_as: bool) -> None:
        if self._current_document and self._current_document.name == "default":
            QMessageBox.information(self, "Read-only", "The default measurement profile is read-only. Use Duplicate or Save As.")
            return

        target_name = self.name_edit.text().strip()
        if save_as:
            new_name, ok = QInputDialog.getText(self, "Save As", "Profile name:", text=target_name)
            if not ok:
                return
            target_name = str(new_name or "").strip()
            if not target_name:
                QMessageBox.warning(self, "Save failed", "Profile name is required.")
                return

        try:
            doc = build_override_document(
                loader=self.loader,
                original_document=self._current_document,
                name=target_name,
                base=self.base_combo.currentData(),
                description=self.description_edit.toPlainText().strip(),
                common_values=self._collect_common_values(),
                measurement_values=self._collect_measurement_values(),
            )
            if doc.name == "default":
                raise ValueError("The default measurement profile is read-only.")
            self.loader.validate_payload(doc.to_dict())
            if doc.base and doc.base in cycle_forbidden_base_names(self.loader, doc.name):
                raise ValueError("Selected base profile would create a cycle.")
            saved_path = self.loader.save_profile(doc)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return

        self._current_document = MeasurementProfileDocument.from_dict(doc.to_dict(), source_path=saved_path)
        self.reload_profiles(select_name=doc.name)
        self.status_label.setText(f"Saved: {doc.name}")

    def _collect_common_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, field in self._common_fields.items():
            if field.is_overridden():
                values[key] = field.value()
        return values

    def _collect_measurement_values(self) -> dict[str, dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        for test_type, fields in self._measurement_fields.items():
            section: dict[str, Any] = {}
            for key, field in fields.items():
                if field.is_overridden():
                    section[key] = field.value()
            values[test_type] = section
        return values
