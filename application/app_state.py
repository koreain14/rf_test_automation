from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AppState:
    project_id: Optional[str] = None
    preset_id: Optional[str] = None
    current_plan_node_id: Optional[str] = None
    current_filter: Optional[Dict[str, Any]] = None
    current_offset: int = 0
