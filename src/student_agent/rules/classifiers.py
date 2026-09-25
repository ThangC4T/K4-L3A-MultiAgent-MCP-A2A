from __future__ import annotations

from datetime import datetime
from typing import Any

from ..state import CaseState


def _parse_dt(val: Any) -> datetime | None:
    if not val or not isinstance(val, str):
        return None
    val = val.strip().replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


def classify_case(state: CaseState) -> dict[str, Any]:
    """Analyze harvested evidence and classify primary_issue, case_status, confidence,
    ranked_causes, responsible_parties, and data_conflicts.
    """
    order = state.order_data or {}
    items = state.items_data or []
    payments = state.payments_data or []
    shipment = state.shipment_summary or {}
    refund_tl = state.refund_timeline or {}

    order_status = str(order.get("order_status") or "").lower().strip()
    primary_seller_id = next(iter(state.seller_ids), None)

    # Calculate financial totals
    total_payment = sum(
        float(p.get("payment_value", 0.0)) for p in payments if isinstance(p, dict)
    )
    total_item_price = sum(
        float(it.get("price", 0.0)) for it in items if isinstance(it, dict)
    )
    total_freight = sum(
        float(it.get("freight_value", 0.0)) for it in items if isinstance(it, dict)
    )
    total_order_value = total_item_price + total_freight

    # 1. Check Refund Status first
    refund_status = ""
    if isinstance(refund_tl, dict):
        refund_status = str(refund_tl.get("status") or refund_tl.get("refund_status") or "").lower()
    elif isinstance(refund_tl, list) and refund_tl:
        last_refund = refund_tl[-1]
        if isinstance(last_refund, dict):
            refund_status = str(last_refund.get("status") or "").lower()

    if refund_status in ("failed", "rejected", "error"):
        return {
            "primary_issue": "refund_failed",
            "case_status": "action_required",
            "confidence": 0.95,
            "cause_code": "REFUND_GATEWAY_FAILURE",
            "responsible_party": {"party_type": "payment_provider", "party_id": None},
            "refund_amount": total_payment if total_payment > 0 else total_order_value,
            "reason_code": "REFUND_RETRY_REQUIRED",
            "actions": ["reinitiate_refund_transaction", "escalate_to_payment_ops"],
        }

    if refund_status in ("pending", "processing", "initiated"):
        return {
            "primary_issue": "refund_pending",
            "case_status": "no_action",
            "confidence": 0.95,
            "cause_code": "REFUND_IN_PROGRESS_WITHIN_SLA",
            "responsible_party": {"party_type": "platform", "party_id": None},
            "refund_amount": 0.0,
            "reason_code": "REFUND_ALREADY_PENDING",
            "actions": ["notify_customer_refund_pending_sla"],
        }

    # 2. Check Order Status: Canceled / Unavailable
    if order_status == "canceled":
        return {
            "primary_issue": "canceled_order_paid",
            "case_status": "action_required",
            "confidence": 0.95,
            "cause_code": "ORDER_CANCELED_PAYMENT_CAPTURED",
            "responsible_party": {
                "party_type": "seller" if primary_seller_id else "platform",
                "party_id": primary_seller_id,
            },
            "refund_amount": total_payment if total_payment > 0 else total_order_value,
            "reason_code": "ORDER_CANCELED_FULL_REFUND",
            "actions": ["issue_full_refund", "notify_customer_refund_processed"],
        }

    if order_status == "unavailable":
        return {
            "primary_issue": "unavailable_order_paid",
            "case_status": "action_required",
            "confidence": 0.95,
            "cause_code": "SELLER_OUT_OF_STOCK",
            "responsible_party": {
                "party_type": "seller" if primary_seller_id else "platform",
                "party_id": primary_seller_id,
            },
            "refund_amount": total_payment if total_payment > 0 else total_order_value,
            "reason_code": "OUT_OF_STOCK_FULL_REFUND",
            "actions": ["issue_full_refund", "cancel_order_record"],
        }

    # 3. Check Payment Anomaly: Duplicate Charge vs Valid Split Payment vs Mismatch
    if len(payments) > 1:
        # Check duplicate charge: two payments with identical value and payment type
        payment_signatures: set[str] = set()
        duplicate_val = 0.0
        has_duplicate = False
        for p in payments:
            if isinstance(p, dict):
                val = round(float(p.get("payment_value", 0.0)), 2)
                ptype = str(p.get("payment_type", "")).lower()
                sig = f"{ptype}:{val}"
                if sig in payment_signatures and val > 0:
                    has_duplicate = True
                    duplicate_val = val
                    break
                payment_signatures.add(sig)

        if has_duplicate and (total_payment > total_order_value):
            return {
                "primary_issue": "duplicate_charge",
                "case_status": "action_required",
                "confidence": 0.95,
                "cause_code": "PAYMENT_GATEWAY_DUPLICATE_CAPTURE",
                "responsible_party": {"party_type": "payment_provider", "party_id": None},
                "refund_amount": duplicate_val,
                "reason_code": "DUPLICATE_CHARGE_REFUND",
                "actions": ["refund_duplicate_charge", "notify_customer"],
            }

        # Check valid split payment: customer used multiple payments, total matches order
        if abs(total_payment - total_order_value) <= 1.0 or total_payment > 0:
            # Check if customer claim complains about multiple charges
            return {
                "primary_issue": "valid_split_payment",
                "case_status": "no_action",
                "confidence": 0.90,
                "cause_code": "CUSTOMER_SPLIT_PAYMENT_MISUNDERSTANDING",
                "responsible_party": {"party_type": "customer", "party_id": None},
                "refund_amount": 0.0,
                "reason_code": "VALID_SPLIT_PAYMENT_CONFIRMED",
                "actions": ["clarify_split_payment_details_to_customer"],
            }

    # 4. Check Payment Mismatch (if payment differs notably from order total)
    if total_payment > 0 and total_order_value > 0 and abs(total_payment - total_order_value) > 2.0:
        diff = round(total_payment - total_order_value, 2)
        if diff > 0:
            return {
                "primary_issue": "payment_mismatch",
                "case_status": "action_required",
                "confidence": 0.85,
                "cause_code": "ORDER_PAYMENT_AMOUNT_MISMATCH",
                "responsible_party": {"party_type": "platform", "party_id": None},
                "refund_amount": diff,
                "reason_code": "EXCESS_PAYMENT_REFUND",
                "actions": ["reconcile_payment_discrepancy"],
            }

    # 5. Check Shipment & Delivery Timestamps
    delivered_customer_str = (
        shipment.get("delivered_customer_date")
        or order.get("order_delivered_customer_date")
    )
    estimated_delivery_str = (
        shipment.get("estimated_delivery_date")
        or order.get("order_estimated_delivery_date")
    )
    delivered_carrier_str = (
        shipment.get("delivered_carrier_date")
        or order.get("order_delivered_carrier_date")
    )
    shipping_limit_str = (
        shipment.get("shipping_limit_date")
        or (items[0].get("shipping_limit_date") if items else None)
    )

    delivered_customer_dt = _parse_dt(delivered_customer_str)
    estimated_delivery_dt = _parse_dt(estimated_delivery_str)
    delivered_carrier_dt = _parse_dt(delivered_carrier_str)
    shipping_limit_dt = _parse_dt(shipping_limit_str)

    is_late_delivery = bool(
        delivered_customer_dt
        and estimated_delivery_dt
        and delivered_customer_dt > estimated_delivery_dt
    )

    if is_late_delivery:
        # Check if seller dispatched late
        is_seller_late = bool(
            delivered_carrier_dt and shipping_limit_dt and delivered_carrier_dt > shipping_limit_dt
        )

        refund_freight = total_freight if total_freight > 0 else 15.0

        if is_seller_late:
            return {
                "primary_issue": "late_delivery_seller",
                "case_status": "action_required",
                "confidence": 0.95,
                "cause_code": "SELLER_LATE_DISPATCH",
                "responsible_party": {
                    "party_type": "seller" if primary_seller_id else "unknown",
                    "party_id": primary_seller_id,
                },
                "refund_amount": refund_freight,
                "reason_code": "SELLER_LATE_DELIVERY_FREIGHT_COMPENSATION",
                "actions": ["compensate_shipping_fee", "issue_seller_warning"],
            }
        else:
            return {
                "primary_issue": "late_delivery_logistics",
                "case_status": "action_required",
                "confidence": 0.95,
                "cause_code": "LOGISTICS_TRANSIT_DELAY",
                "responsible_party": {
                    "party_type": "logistics_provider",
                    "party_id": shipment.get("carrier_id") or "carrier_default",
                },
                "refund_amount": refund_freight,
                "reason_code": "CARRIER_TRANSIT_DELAY_COMPENSATION",
                "actions": ["compensate_shipping_fee", "log_carrier_sla_breach"],
            }

    # 6. If order was delivered on time and no anomalies found
    if order_status == "delivered" and not is_late_delivery:
        return {
            "primary_issue": "unsupported_claim",
            "case_status": "no_action",
            "confidence": 0.90,
            "cause_code": "UNSUBSTANTIATED_CUSTOMER_CLAIM",
            "responsible_party": {"party_type": "customer", "party_id": None},
            "refund_amount": 0.0,
            "reason_code": "DELIVERY_AND_PAYMENT_AUTHORITATIVE_CONFIRMED",
            "actions": ["reject_claim_with_evidence"],
        }

    # 7. Fallback when data is missing or incomplete
    if not order:
        return {
            "primary_issue": "insufficient_evidence",
            "case_status": "needs_investigation",
            "confidence": 0.60,
            "cause_code": "MISSING_AUTHORITATIVE_DATA",
            "responsible_party": {"party_type": "unknown", "party_id": None},
            "refund_amount": 0.0,
            "reason_code": "NO_ORDER_DATA_FOUND",
            "actions": ["request_manual_case_review"],
        }

    # Default to unsupported_claim with reasonable confidence
    return {
        "primary_issue": "unsupported_claim",
        "case_status": "no_action",
        "confidence": 0.85,
        "cause_code": "CLAIM_NOT_SUPPORTED_BY_EVIDENCE",
        "responsible_party": {"party_type": "customer", "party_id": None},
        "refund_amount": 0.0,
        "reason_code": "NO_POLICY_VIOLATION_FOUND",
        "actions": ["reject_claim_with_evidence"],
    }
