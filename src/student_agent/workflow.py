from __future__ import annotations

from typing import Any

from .agents.coordinator import CoordinatorAgent
from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter


async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    """Execute the L3A Multi-Agent workflow with Coordinator, Specialists and Verifier."""
    coordinator = CoordinatorAgent(gateway, trace, trace.contracts)
    return await coordinator.coordinate(case)
