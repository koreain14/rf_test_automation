from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import logging

from application.device_models import DeviceInfo
from application.device_registry import DeviceRegistry
from application.device_discovery import DeviceDiscovery
from application.equipment_profile_repo import EquipmentProfileRepo
from application.equipment_session import ExecutionContext, EquipmentSession
from application.instrument_base import MeasurementInstrument
from application.instrument_factory import InstrumentFactory
from drivers.analyzer.rs_fsw_driver import RSFSWDriver
from drivers.analyzer.rs_esw_driver import RSESWDriver
from drivers.analyzer.keysight_n9030_driver import KeysightN9030Driver
from drivers.analyzer.keysight_n9020_driver import KeysightN9020Driver
from drivers.motion.innco_turntable_driver import INNCOTurntableDriver
from drivers.motion.innco_mast_driver import INNCOMastDriver
from drivers.switch.switchbox_driver import SwitchBoxDriver
from drivers.power.keysight_e3632a_driver import KeysightE3632ADriver


log = logging.getLogger(__name__)


class InstrumentManager:
    """Single place to ask for instruments and build multi-device sessions."""

    def __init__(
        self,
        factory: InstrumentFactory,
        device_registry: DeviceRegistry | None = None,
        profile_repo: EquipmentProfileRepo | None = None,
        discovery: DeviceDiscovery | None = None,
    ):
        self.factory = factory
        self.device_registry = device_registry or DeviceRegistry(Path("config/devices.json"))
        self.profile_repo = profile_repo or EquipmentProfileRepo(Path("config/equipment_profiles.json"))
        self.discovery = discovery or DeviceDiscovery()

    def set_factory(self, factory: InstrumentFactory) -> None:
        self.factory = factory

    def get_measurement_instrument(self) -> MeasurementInstrument:
        return self.factory.create_measurement_instrument()

    def scan_devices(self) -> list[str]:
        return self.discovery.scan_visa_resources()

    def scan_and_identify_devices(self) -> list[dict]:
        return self.discovery.scan_and_identify()

    def test_device(self, device_name: str) -> Dict[str, Any]:
        device = self.device_registry.get_device(device_name)
        if not device:
            return {"ok": False, "error": f"Device not found: {device_name}"}
        return self.test_device_info(device)

    def test_device_info(self, device: DeviceInfo) -> Dict[str, Any]:
        try:
            inst = self._create_device(device)
            connected = getattr(inst, "is_connected", None)
            if connected is None:
                connected = getattr(inst, "connected", None)

            if connected is True:
                idn = ""
                if hasattr(inst, "query_idn"):
                    try:
                        idn = inst.query_idn()
                    except Exception:
                        idn = ""
                if hasattr(inst, "disconnect"):
                    try:
                        inst.disconnect()
                    except Exception:
                        pass
                return {"ok": True, "idn": idn, "device": device.name, "driver": device.driver}

            return {
                "ok": False,
                "error": getattr(inst, "last_connect_error", None) or "Not connected",
                "device": device.name,
                "driver": device.driver,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "device": device.name, "driver": device.driver}

    def create_session(self, profile_name: str) -> ExecutionContext:
        profile = self.profile_repo.get_profile(profile_name)
        if not profile:
            raise ValueError(f"Equipment profile not found: {profile_name}")

        return ExecutionContext(
            analyzer=self._create_named_device(profile.analyzer, expected_type="analyzer", slot_name="analyzer"),
            turntable=self._create_named_device(profile.turntable, expected_type="turntable", slot_name="turntable"),
            mast=self._create_named_device(profile.mast, expected_type="mast", slot_name="mast"),
            switchbox=self._create_named_device(profile.switchbox, expected_type="switchbox", slot_name="switchbox"),
            power_supply=self._create_named_device(profile.power_supply, expected_type="power_supply", slot_name="power_supply"),
        )




    def create_motion_session(self, profile_name: str) -> ExecutionContext:
        profile = self.profile_repo.get_profile(profile_name)
        if not profile:
            raise ValueError(f"Equipment profile not found: {profile_name}")

        return ExecutionContext(
            analyzer=None,
            turntable=self._create_named_device(profile.turntable, expected_type="turntable", slot_name="turntable"),
            mast=self._create_named_device(profile.mast, expected_type="mast", slot_name="mast"),
            switchbox=None,
            power_supply=None,
        )

    def build_session_metadata(self, equipment_profile_name: str | None, session=None, fallback_instrument=None) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "equipment_profile_name": equipment_profile_name,
            "analyzer_device_name": None,
            "analyzer_serial_number": None,
            "turntable_device_name": None,
            "turntable_serial_number": None,
            "mast_device_name": None,
            "mast_serial_number": None,
            "switchbox_device_name": None,
            "switchbox_serial_number": None,
            "power_supply_device_name": None,
            "power_supply_serial_number": None,
            "equipment_summary": "",
            "instrument_source": "fallback" if fallback_instrument is not None else "session",
            "instrument_class": type(fallback_instrument).__name__ if fallback_instrument is not None else None,
        }

        profile = self.profile_repo.get_profile(equipment_profile_name) if equipment_profile_name else None
        if profile:
            meta["analyzer_device_name"] = profile.analyzer
            meta["turntable_device_name"] = profile.turntable
            meta["mast_device_name"] = profile.mast
            meta["switchbox_device_name"] = profile.switchbox
            meta["power_supply_device_name"] = profile.power_supply

            analyzer_info = self.device_registry.get_device(profile.analyzer) if profile.analyzer else None
            turntable_info = self.device_registry.get_device(profile.turntable) if profile.turntable else None
            mast_info = self.device_registry.get_device(profile.mast) if profile.mast else None
            switchbox_info = self.device_registry.get_device(profile.switchbox) if profile.switchbox else None
            power_info = self.device_registry.get_device(profile.power_supply) if profile.power_supply else None

            meta["analyzer_serial_number"] = getattr(analyzer_info, "serial_number", None)
            meta["turntable_serial_number"] = getattr(turntable_info, "serial_number", None)
            meta["mast_serial_number"] = getattr(mast_info, "serial_number", None)
            meta["switchbox_serial_number"] = getattr(switchbox_info, "serial_number", None)
            meta["power_supply_serial_number"] = getattr(power_info, "serial_number", None)

        parts = []
        if meta.get("equipment_profile_name"):
            parts.append(f"EQ:{meta['equipment_profile_name']}")
        if meta.get("analyzer_device_name"):
            parts.append(f"AN:{meta['analyzer_device_name']}")
        if meta.get("analyzer_serial_number"):
            parts.append(f"SN:{meta['analyzer_serial_number']}")
        if meta.get("switchbox_device_name"):
            parts.append(f"SW:{meta['switchbox_device_name']}")
        if meta.get("power_supply_device_name"):
            parts.append(f"PS:{meta['power_supply_device_name']}")
        meta["equipment_summary"] = " | ".join(parts)

        if session is not None:
            for attr in ("analyzer", "turntable", "mast", "switchbox", "power_supply"):
                dev = getattr(session, attr, None)
                if dev is not None:
                    meta[f"{attr}_class"] = type(dev).__name__
        return meta

    def get_switch_path_names(self, equipment_profile_name: str | None) -> list[str]:
        if not equipment_profile_name:
            return []
        profile = self.profile_repo.get_profile(equipment_profile_name)
        if not profile or not profile.switchbox:
            return []
        device = self.device_registry.get_device(profile.switchbox)
        if not device:
            return []
        return [str(p.get("name", "")) for p in (device.ports or []) if p.get("name")]

    # Compatibility helper used by older UI code.
    def available_switch_paths(self, equipment_profile_name: str | None = None) -> list[str]:
        return self.get_switch_path_names(equipment_profile_name)

    def get_switch_port_names(self, equipment_profile_name: str | None) -> list[str]:
        if not equipment_profile_name:
            return []
        profile = self.profile_repo.get_profile(equipment_profile_name)
        if not profile or not profile.switchbox:
            return []
        device = self.device_registry.get_device(profile.switchbox)
        if not device:
            return []
        return [str(port.get("name", "")) for port in (device.ports or []) if port.get("name")]

    def _create_named_device(
        self,
        device_name: str | None,
        expected_type: str | None = None,
        slot_name: str | None = None,
    ):
        if not device_name:
            return None
        device = self.device_registry.get_device(device_name)
        if not device:
            raise RuntimeError(f"Configured device not found: {device_name}")
        if expected_type and device.type != expected_type:
            role = slot_name or expected_type
            raise RuntimeError(
                f"Equipment profile binding error for '{role}': device '{device_name}' "
                f"is type '{device.type}', expected '{expected_type}'."
            )
        inst = self._create_device(device)
        log.info(
            "device created | slot=%s expected_type=%s device=%s device_type=%s driver=%s instance=%s",
            slot_name or "(unknown)",
            expected_type,
            device.name,
            device.type,
            device.driver,
            type(inst).__name__,
        )
        return inst

    def _create_device(self, device: DeviceInfo):
        timeout_ms = int(device.options.get("timeout_ms", 10000)) if isinstance(device.options, dict) else 10000

        if device.driver == "rs_fsw":
            inst = RSFSWDriver(device.resource, timeout_ms)
            inst.connect()
            return inst
        if device.driver == "rs_esw":
            inst = RSESWDriver(device.resource, timeout_ms)
            inst.connect()
            return inst
        if device.driver == "keysight_n9030":
            inst = KeysightN9030Driver(device.resource, timeout_ms)
            inst.connect()
            return inst
        if device.driver == "keysight_n9020":
            inst = KeysightN9020Driver(device.resource, timeout_ms)
            inst.connect()
            return inst
        if device.driver == "generic_switch":
            inst = SwitchBoxDriver(device.resource, ports=device.ports, timeout_ms=timeout_ms)
            inst.connect()
            return inst
        if device.driver == "keysight_e3632a":
            inst = KeysightE3632ADriver(device.resource, timeout_ms)
            inst.connect()
            return inst
        if device.driver == "innco_co3000":
            inst = INNCOTurntableDriver(device.resource, device.options)
            inst.connect()
            return inst
        if device.driver == "innco_mast":
            inst = INNCOMastDriver(device.resource, device.options)
            inst.connect()
            return inst

        raise ValueError(f"Unsupported driver: {device.driver}")
