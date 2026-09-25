from __future__ import annotations

import logging

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter

logger = logging.getLogger(__name__)


class PaymentAgent:
    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def investigate(self, state: CaseState) -> None:
        if not state.order_id:
            return

        # 1. Get Order Payments
        try:
            pay_ev = await self.gateway.call(
                "get_order_payments", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = pay_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="payment-agent",
                    tool_name="get_order_payments",
                    evidence_refs=[ev_ref],
                )
            raw_payments = pay_ev.get("data")
            if isinstance(raw_payments, list):
                state.payments_data = raw_payments
            elif isinstance(raw_payments, dict):
                state.payments_data = raw_payments.get("payments", []) or [raw_payments]

            for p in state.payments_data:
                if isinstance(p, dict):
                    pref = (
                        p.get("payment_reference")
                        or p.get("payment_id")
                        or p.get("payment_sequential")
                        or p.get("transaction_id")
                    )
                    if pref is not None:
                        state.payment_references.add(str(pref))
        except Exception as exc:
            logger.warning(f"Error fetching payments for {state.case_id}: {exc}")

        # 2. Get Payment Timeline
        try:
            timeline_ev = await self.gateway.call(
                "get_payment_timeline", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = timeline_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="payment-agent",
                    tool_name="get_payment_timeline",
                    evidence_refs=[ev_ref],
                )
            state.payment_timeline = timeline_ev.get("data")
        except Exception as exc:
            logger.warning(f"Error fetching payment timeline for {state.case_id}: {exc}")

        # 3. Get Refund Timeline
        try:
            refund_ev = await self.gateway.call(
                "get_refund_timeline", case_id=state.case_id, order_id=state.order_id
            )
            ev_ref = refund_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="payment-agent",
                    tool_name="get_refund_timeline",
                    evidence_refs=[ev_ref],
                )
            state.refund_timeline = refund_ev.get("data")
        except Exception as exc:
            logger.warning(f"Error fetching refund timeline for {state.case_id}: {exc}")
