from __future__ import annotations

from application.instruments_dummy import DummyInstrument


class DummyInstrumentDriver(DummyInstrument):
    """Thin adapter so future real drivers can share a common location/package."""
    pass
