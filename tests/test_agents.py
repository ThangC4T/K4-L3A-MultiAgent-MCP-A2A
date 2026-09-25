from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from student_agent.agents.coordinator import CoordinatorAgent
from student_agent.contracts import Contracts
from student_agent.trace import TraceWriter


class DummyGateway:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool_name: str, *, case_id: str, **arguments: Any) -> dict[str, Any]:
        self.calls.append((tool_name, {"case_id": case_id, **arguments}))
        if tool_name in self.responses:
            return self.responses[tool_name]
        return {
            "schema_version": "day09-mcp-evidence-v1",
            "evidence_ref": f"ev_{tool_name}_12345678901234567890",
            "result_hash": f"sha256:{'a'*64}",
            "domain": "order",
            "data": {},
            "warnings": [],
        }


def test_coordinator_workflow_canceled_order(tmp_path: Path) -> None:
    async def _test() -> None:
        root = Path(__file__).resolve().parents[1]
        contracts = Contracts(root / "contracts" / "schemas")
        trace_path = tmp_path / "trace.jsonl"
        trace = TraceWriter(trace_path, contracts)

        sample_order_id = "00000000000000000000000000000001"
        gateway = DummyGateway(
            {
                "get_order": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_order_0123456789012345678901",
                    "result_hash": f"sha256:{'1'*64}",
                    "domain": "order",
                    "data": {
                        "order_id": sample_order_id,
                        "order_status": "canceled",
                        "customer_id": "cust_1",
                    },
                    "warnings": [],
                },
                "get_order_payments": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_payment_01234567890123456789",
                    "result_hash": f"sha256:{'2'*64}",
                    "domain": "payment",
                    "data": [
                        {
                            "payment_sequential": 1,
                            "payment_value": 150.0,
                            "payment_type": "credit_card",
                        }
                    ],
                    "warnings": [],
                },
            }
        )

        coordinator = CoordinatorAgent(gateway, trace, contracts)
        case = {
            "case_id": "L3A_CASE_001",
            "order_id": sample_order_id,
            "customer_message": "My order was canceled but I was charged 150 BRL!",
        }

        output = await coordinator.coordinate(case)

        contracts.validate_output(output, "test_output")
        assert output["assessment"]["primary_issue"] == "canceled_order_paid"
        assert output["assessment"]["case_status"] == "action_required"
        assert output["financial_resolution"]["recommended_refund_brl"] == 150.0

        events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        event_types = [e["event_type"] for e in events]
        assert "task_assigned" in event_types
        assert "tool_result_consumed" in event_types
        assert "handoff" in event_types
        assert "policy_decided" in event_types
        assert "verification_completed" in event_types

    asyncio.run(_test())


def test_coordinator_workflow_late_delivery_logistics(tmp_path: Path) -> None:
    async def _test() -> None:
        root = Path(__file__).resolve().parents[1]
        contracts = Contracts(root / "contracts" / "schemas")
        trace_path = tmp_path / "trace_logistics.jsonl"
        trace = TraceWriter(trace_path, contracts)

        sample_order_id = "00000000000000000000000000000002"
        gateway = DummyGateway(
            {
                "get_order": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_order_0123456789012345678902",
                    "result_hash": f"sha256:{'3'*64}",
                    "domain": "order",
                    "data": {"order_id": sample_order_id, "order_status": "delivered"},
                    "warnings": [],
                },
                "get_order_items": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_items_0123456789012345678902",
                    "result_hash": f"sha256:{'4'*64}",
                    "domain": "item",
                    "data": [
                        {
                            "order_item_id": 1,
                            "price": 100.0,
                            "freight_value": 25.0,
                            "shipping_limit_date": "2026-09-05 12:00:00",
                        }
                    ],
                    "warnings": [],
                },
                "get_shipment_summary": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_shipment_01234567890123456782",
                    "result_hash": f"sha256:{'5'*64}",
                    "domain": "shipment",
                    "data": {
                        "delivered_carrier_date": "2026-09-04 10:00:00",
                        "delivered_customer_date": "2026-09-20 15:00:00",
                        "estimated_delivery_date": "2026-09-10 23:59:59",
                        "carrier_id": "carrier_fedex",
                    },
                    "warnings": [],
                },
            }
        )

        coordinator = CoordinatorAgent(gateway, trace, contracts)
        case = {"case_id": "L3A_CASE_002", "order_id": sample_order_id}
        output = await coordinator.coordinate(case)

        contracts.validate_output(output, "test_output_logistics")
        assert output["assessment"]["primary_issue"] == "late_delivery_logistics"
        assert output["assessment"]["case_status"] == "action_required"
        assert output["financial_resolution"]["recommended_refund_brl"] == 25.0
        rp = output["root_cause_analysis"]["responsible_parties"][0]
        assert rp["party_type"] == "logistics_provider"

    asyncio.run(_test())


def test_coordinator_workflow_valid_split_payment(tmp_path: Path) -> None:
    async def _test() -> None:
        root = Path(__file__).resolve().parents[1]
        contracts = Contracts(root / "contracts" / "schemas")
        trace_path = tmp_path / "trace_split.jsonl"
        trace = TraceWriter(trace_path, contracts)

        sample_order_id = "00000000000000000000000000000003"
        gateway = DummyGateway(
            {
                "get_order": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_order_0123456789012345678903",
                    "result_hash": f"sha256:{'6'*64}",
                    "domain": "order",
                    "data": {"order_id": sample_order_id, "order_status": "delivered"},
                    "warnings": [],
                },
                "get_order_items": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_items_0123456789012345678903",
                    "result_hash": f"sha256:{'7'*64}",
                    "domain": "item",
                    "data": [{"order_item_id": 1, "price": 100.0, "freight_value": 0.0}],
                    "warnings": [],
                },
                "get_order_payments": {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_payments_01234567890123456783",
                    "result_hash": f"sha256:{'8'*64}",
                    "domain": "payment",
                    "data": [
                        {
                            "payment_sequential": 1,
                            "payment_value": 60.0,
                            "payment_type": "voucher",
                        },
                        {
                            "payment_sequential": 2,
                            "payment_value": 40.0,
                            "payment_type": "credit_card",
                        },
                    ],
                    "warnings": [],
                },
            }
        )

        coordinator = CoordinatorAgent(gateway, trace, contracts)
        case = {"case_id": "L3A_CASE_003", "order_id": sample_order_id}
        output = await coordinator.coordinate(case)

        contracts.validate_output(output, "test_output_split")
        assert output["assessment"]["primary_issue"] == "valid_split_payment"
        assert output["assessment"]["case_status"] == "no_action"
        assert output["financial_resolution"]["recommended_refund_brl"] == 0.0
        assert len(output["financial_resolution"]["refund_lines"]) == 0

    asyncio.run(_test())
