from __future__ import annotations

import logging

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter

logger = logging.getLogger(__name__)


class OrderAgent:
    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def investigate(self, state: CaseState) -> None:
        if not state.order_id:
            logger.warning(f"No order_id found for case {state.case_id}")
            return

        state.order_ids.add(state.order_id)

        # 1. Get Order
        try:
            order_ev = await self.gateway.call(
                "get_order", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = order_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="order-agent",
                    tool_name="get_order",
                    evidence_refs=[ev_ref],
                )
            state.order_data = order_ev.get("data") or {}
            customer_id = state.order_data.get("customer_id")
            if customer_id and not state.customer_id:
                state.customer_id = customer_id
        except Exception as exc:
            logger.warning(f"Error fetching order for {state.case_id}: {exc}")

        # 2. Get Order Items
        try:
            items_ev = await self.gateway.call(
                "get_order_items", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = items_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="order-agent",
                    tool_name="get_order_items",
                    evidence_refs=[ev_ref],
                )
            raw_items = items_ev.get("data")
            if isinstance(raw_items, list):
                state.items_data = raw_items
            elif isinstance(raw_items, dict):
                state.items_data = raw_items.get("items", []) or [raw_items]

            for item in state.items_data:
                if isinstance(item, dict):
                    item_id = (
                        item.get("order_item_id")
                        or item.get("product_id")
                        or item.get("item_id")
                    )
                    if item_id:
                        state.item_ids.add(str(item_id))
                    seller_id = item.get("seller_id")
                    if seller_id:
                        state.seller_ids.add(str(seller_id))
        except Exception as exc:
            logger.warning(f"Error fetching order items for {state.case_id}: {exc}")

        # 3. Get Sellers
        try:
            sellers_ev = await self.gateway.call(
                "get_sellers", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = sellers_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="order-agent",
                    tool_name="get_sellers",
                    evidence_refs=[ev_ref],
                )
            raw_sellers = sellers_ev.get("data")
            if isinstance(raw_sellers, list):
                state.sellers_data = raw_sellers
            elif isinstance(raw_sellers, dict):
                state.sellers_data = raw_sellers.get("sellers", []) or [raw_sellers]
            for s in state.sellers_data:
                if isinstance(s, dict) and s.get("seller_id"):
                    state.seller_ids.add(str(s["seller_id"]))
        except Exception as exc:
            logger.warning(f"Error fetching sellers for {state.case_id}: {exc}")

        # 4. Get Product Context
        try:
            prod_ev = await self.gateway.call(
                "get_product_context", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = prod_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="order-agent",
                    tool_name="get_product_context",
                    evidence_refs=[ev_ref],
                )
            state.product_context = prod_ev.get("data")
        except Exception as exc:
            logger.warning(f"Error fetching product context for {state.case_id}: {exc}")
