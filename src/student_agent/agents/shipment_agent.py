from __future__ import annotations

import logging

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter

logger = logging.getLogger(__name__)


class ShipmentAgent:
    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def investigate(self, state: CaseState) -> None:
        if not state.order_id:
            return

        try:
            ship_ev = await self.gateway.call(
                "get_shipment_summary", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = ship_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="shipment-agent",
                    tool_name="get_shipment_summary",
                    evidence_refs=[ev_ref],
                )
            data = ship_ev.get("data") or {}
            state.shipment_summary = data

            # Extract shipment / tracking identifiers
            shipment_id = (
                data.get("shipment_id")
                or data.get("tracking_number")
                or data.get("carrier_tracking_id")
            )
            if shipment_id:
                state.shipment_ids.add(str(shipment_id))
            
            # Check shipments list if present
            shipments_list = data.get("shipments") or []
            if isinstance(shipments_list, list):
                for s in shipments_list:
                    if isinstance(s, dict):
                        sid = s.get("shipment_id") or s.get("tracking_id")
                        if sid:
                            state.shipment_ids.add(str(sid))
        except Exception as exc:
            logger.warning(f"Error fetching shipment summary for {state.case_id}: {exc}")
