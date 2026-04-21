from __future__ import annotations

import logging
from typing import Dict, List


log = logging.getLogger(__name__)


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
        log.info("identify_resource called | resource=%s timeout_ms=%s", resource, timeout_ms)
        try:
            import pyvisa  # type: ignore

            rm = pyvisa.ResourceManager()
            inst = rm.open_resource(resource)
            try:
                try:
                    inst.timeout = timeout_ms
                except Exception:
                    pass
                idn = str(inst.query("*IDN?")).strip()
                log.info("identify_resource idn response | resource=%s idn=%s", resource, idn)
            finally:
                try:
                    inst.close()
                except Exception:
                    pass
                try:
                    rm.close()
                except Exception:
                    pass
            return self._build_identify_result(resource=resource, idn=idn, status="OK")
        except Exception as e:
            log.exception("identify_resource failed | resource=%s timeout_ms=%s", resource, timeout_ms)
            return self._build_identify_result(resource=resource, idn="", status=f"ERROR: {e}")

    def identify_tcpip_resource(self, resource: str, timeout_ms: int = 10000) -> Dict[str, str]:
        log.info("identify_tcpip_resource called | resource=%s timeout_ms=%s", resource, timeout_ms)
        try:
            import pyvisa  # type: ignore

            rm = pyvisa.ResourceManager()
            inst = rm.open_resource(resource)
            tuning: Dict[str, object] = {
                "timeout_ms": timeout_ms,
                "resource_kind": self._resource_kind(resource),
                "read_termination_applied": False,
                "write_termination_applied": False,
                "suppress_end_applied": False,
                "query_delay_applied": False,
            }
            try:
                self._apply_tcpip_probe_settings(
                    inst,
                    resource=resource,
                    timeout_ms=timeout_ms,
                    tuning=tuning,
                )
                idn = self._query_idn_for_tcpip_probe(inst, resource=resource)
            finally:
                try:
                    inst.close()
                except Exception:
                    pass
                try:
                    rm.close()
                except Exception:
                    pass

            result = self._build_identify_result(resource=resource, idn=idn, status="OK")
            result["transport_tuning"] = tuning
            return result
        except Exception as e:
            log.exception("identify_tcpip_resource failed | resource=%s timeout_ms=%s", resource, timeout_ms)
            result = self._build_identify_result(resource=resource, idn="", status=f"ERROR: {e}")
            result["transport_tuning"] = {
                "timeout_ms": timeout_ms,
                "resource_kind": self._resource_kind(resource),
            }
            return result

    def _apply_tcpip_probe_settings(
        self,
        inst,
        *,
        resource: str,
        timeout_ms: int,
        tuning: Dict[str, object],
    ) -> None:
        try:
            inst.timeout = timeout_ms
        except Exception as exc:
            log.info("tcpip probe timeout apply skipped | resource=%s err=%s", resource, exc)

        try:
            inst.query_delay = 0.2
            tuning["query_delay_applied"] = True
        except Exception as exc:
            log.info("tcpip probe query_delay apply skipped | resource=%s err=%s", resource, exc)

        if self._is_socket_resource(resource):
            try:
                inst.read_termination = "\n"
                tuning["read_termination_applied"] = True
            except Exception as exc:
                log.info("tcpip probe read_termination apply skipped | resource=%s err=%s", resource, exc)

            try:
                inst.write_termination = "\n"
                tuning["write_termination_applied"] = True
            except Exception as exc:
                log.info("tcpip probe write_termination apply skipped | resource=%s err=%s", resource, exc)

        if self._supports_real_attr(inst, "suppress_end"):
            try:
                inst.suppress_end = False
                tuning["suppress_end_applied"] = True
            except Exception as exc:
                log.info("tcpip probe suppress_end apply skipped | resource=%s err=%s", resource, exc)
        else:
            log.info("tcpip probe suppress_end unsupported | resource=%s", resource)

    def _query_idn_for_tcpip_probe(self, inst, *, resource: str) -> str:
        log.info("tcpip probe idn query start | resource=%s", resource)
        try:
            response = str(inst.query("*IDN?")).strip()
            log.info("tcpip probe idn query response | resource=%s idn=%s", resource, response)
            return response
        except Exception as exc:
            log.info("tcpip probe idn query failed -> fallback write/read | resource=%s err=%s", resource, exc)

        inst.write("*IDN?")
        response = str(inst.read()).strip()
        log.info("tcpip probe idn fallback response | resource=%s idn=%s", resource, response)
        return response

    def _supports_real_attr(self, inst, attr_name: str) -> bool:
        for cls in type(inst).__mro__:
            if attr_name in getattr(cls, "__dict__", {}):
                return True
        return False

    def _is_socket_resource(self, resource: str) -> bool:
        return "::SOCKET" in str(resource or "").upper()

    def _resource_kind(self, resource: str) -> str:
        if self._is_socket_resource(resource):
            return "SOCKET"
        if "::INSTR" in str(resource or "").upper():
            return "INSTR"
        return "UNKNOWN"

    def _build_identify_result(self, *, resource: str, idn: str, status: str) -> Dict[str, str]:
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
            "status": status,
        }

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
