from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseState:
    case_id: str
    raw_case: dict[str, Any]
    order_id: str | None = None
    customer_id: str | None = None
    customer_unique_id: str | None = None
    policy_version: str = "EC_POLICY_V1"

    # Harvested evidence
    evidence_refs: list[str] = field(default_factory=list)
    order_data: dict[str, Any] | None = None
    items_data: list[dict[str, Any]] = field(default_factory=list)
    payments_data: list[dict[str, Any]] = field(default_factory=list)
    payment_timeline: dict[str, Any] | None = None
    refund_timeline: dict[str, Any] | None = None
    shipment_summary: dict[str, Any] | None = None
    sellers_data: list[dict[str, Any]] = field(default_factory=list)
    product_context: dict[str, Any] | None = None
    customer_history: dict[str, Any] | None = None
    policy_data: dict[str, Any] | None = None

    # Extracted entity IDs
    order_ids: set[str] = field(default_factory=set)
    item_ids: set[str] = field(default_factory=set)
    seller_ids: set[str] = field(default_factory=set)
    payment_references: set[str] = field(default_factory=set)
    shipment_ids: set[str] = field(default_factory=set)

    # Inferences
    findings: dict[str, Any] = field(default_factory=dict)
    data_conflicts: list[dict[str, Any]] = field(default_factory=list)
