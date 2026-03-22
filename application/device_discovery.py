from __future__ import annotations

from typing import List, Dict


class DeviceDiscovery:
    def parse_vendor_from_idn(self, idn: str) -> str:
        if not idn:
            return ""
        parts = [p.strip() for p in str(idn).split(",")]
        return parts[0] if len(parts) >= 1 else ""

    def parse_model_from_idn(self, idn: str) -> str:
        if not idn:
            return ""
        parts = [p.strip() for p in str(idn).split(",")]
        return parts[1] if len(parts) >= 2 else str(idn).strip()

    def parse_serial_from_idn(self, idn: str) -> str:
        if not idn:
            return ""
        parts = [p.strip() for p in str(idn).split(",")]
        return parts[2] if len(parts) >= 3 else ""

    def parse_model_from_idn(self, idn: str) -> str:
        if not idn:
            return ""
        parts = [p.strip() for p in str(idn).split(",")]
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return str(idn).strip()

    def scan_visa_resources(self) -> List[str]:
        try:
            import pyvisa  # type: ignore
            rm = pyvisa.ResourceManager()
            try:
                return list(rm.list_resources())
            finally:
                try:
                    rm.close()
                except Exception:
                    pass
        except Exception:
            return []

    def identify_resource(self, resource: str, timeout_ms: int = 3000) -> Dict[str, str]:
        try:
            import pyvisa  # type: ignore
            rm = pyvisa.ResourceManager()
            inst = rm.open_resource(resource)
            try:
                inst.timeout = timeout_ms
            except Exception:
                pass
            try:
                idn = str(inst.query("*IDN?")).strip()
            finally:
                try:
                    inst.close()
                except Exception:
                    pass
                try:
                    rm.close()
                except Exception:
                    pass
            guessed = self.guess_device_info(idn)
            vendor = self.parse_vendor_from_idn(idn)
            model = self.parse_model_from_idn(idn)
            serial_number = self.parse_serial_from_idn(idn)
            return {
                "resource": resource,
                "vendor": vendor,
                "model": model,
                "serial_number": serial_number,
                "idn": idn,
                "type": guessed.get("type", ""),
                "driver": guessed.get("driver", ""),
                "status": "OK",
            }
        except Exception as e:
            return {"resource": resource, "vendor": "", "model": "", "serial_number": "", "idn": "", "type": "", "driver": "", "status": f"ERROR: {e}"}

    def guess_device_info(self, idn: str) -> Dict[str, str]:
        s = (idn or "").upper()

        if "FSW" in s:
            return {"type": "analyzer", "driver": "rs_fsw"}
        if "ESW" in s:
            return {"type": "analyzer", "driver": "rs_esw"}
        if "N9030" in s:
            return {"type": "analyzer", "driver": "keysight_n9030"}
        if "N9020" in s:
            return {"type": "analyzer", "driver": "keysight_n9020"}
        if "E3632" in s:
            return {"type": "power_supply", "driver": "keysight_e3632a"}
        if "TMX" in s:
            return {"type": "switchbox", "driver": "generic_switch"}
        if "HCT" in s:
            return {"type": "switchbox", "driver": "generic_switch"}

        return {"type": "unknown", "driver": ""}

    def scan_and_identify(self, timeout_ms: int = 3000) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for resource in self.scan_visa_resources():
            out.append(self.identify_resource(resource, timeout_ms=timeout_ms))
        return out
