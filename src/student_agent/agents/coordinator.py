from __future__ import annotations

import re
from typing import Any

from ..contracts import Contracts
from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter
from .order_agent import OrderAgent
from .payment_agent import PaymentAgent
from .policy_agent import PolicyAgent
from .shipment_agent import ShipmentAgent
from .verifier import VerifierAgent

ORDER_ID_PATTERN = re.compile(r"\b([a-f0-9]{32})\b", re.IGNORECASE)


class CoordinatorAgent:
    def __init__(
        self, gateway: EvidenceGateway, trace: TraceWriter, contracts: Contracts
    ) -> None:
        self.gateway = gateway
        self.trace = trace
        self.contracts = contracts

        self.order_agent = OrderAgent(gateway, trace)
        self.payment_agent = PaymentAgent(gateway, trace)
        self.shipment_agent = ShipmentAgent(gateway, trace)
        self.policy_agent = PolicyAgent(gateway, trace)
        self.verifier_agent = VerifierAgent(contracts, trace)

    def extract_order_id(self, case: dict[str, Any]) -> str | None:
        """Extract order_id from direct field, customer_request, claims or customer message."""
        req = case.get("customer_request") or {}
        if isinstance(req, dict) and req.get("claimed_order_id"):
            return str(req["claimed_order_id"])

        if case.get("order_id"):
            return str(case["order_id"])

        order_ids = case.get("order_ids")
        if isinstance(order_ids, list) and order_ids:
            return str(order_ids[0])

        claims = req.get("claims") or case.get("claims") or []
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, dict):
                    cid = claim.get("order_id") or claim.get("claimed_order_id")
                    if cid:
                        return str(cid)

        # Regex scan message
        msg = str(req.get("message") or case.get("customer_message") or "")
        match = ORDER_ID_PATTERN.search(msg)
        if match:
            return match.group(1)

        return None

    async def coordinate(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]
        order_id = self.extract_order_id(case)
        customer_id = case.get("customer_id")
        customer_unique_id = case.get("customer_unique_id")
        policy_version = case.get("policy_version") or "EC_POLICY_V1"

        state = CaseState(
            case_id=case_id,
            raw_case=case,
            order_id=order_id,
            customer_id=customer_id,
            customer_unique_id=customer_unique_id,
            policy_version=policy_version,
        )

        # 1. Dispatch Order Agent
        self.trace.emit(
            case_id=case_id,
            event_type="task_assigned",
            actor="coordinator",
            target="order-agent",
            decision_code="DISPATCH_ORDER_INVESTIGATION",
        )
        await self.order_agent.investigate(state)

        # 2. Handoff to Payment Agent
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="order-agent",
            target="payment-agent",
            decision_code="HANDOFF_TO_PAYMENT_INVESTIGATION",
        )
        await self.payment_agent.investigate(state)

        # 3. Handoff to Shipment Agent
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="payment-agent",
            target="shipment-agent",
            decision_code="HANDOFF_TO_SHIPMENT_INVESTIGATION",
        )
        await self.shipment_agent.investigate(state)

        # 4. Handoff to Policy Agent
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="shipment-agent",
            target="policy-agent",
            decision_code="HANDOFF_TO_POLICY_RESOLUTION",
        )
        draft_output = await self.policy_agent.decide(state)

        # 5. Handoff to Verifier Agent
        self.trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor="policy-agent",
            target="verifier",
            decision_code="HANDOFF_TO_VERIFIER",
        )
        final_output = self.verifier_agent.verify_and_finalize(draft_output, state)

        return final_output
