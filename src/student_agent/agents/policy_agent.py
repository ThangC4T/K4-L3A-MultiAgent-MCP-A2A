from __future__ import annotations

import logging
from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..rules.classifiers import classify_case
from ..state import CaseState
from ..trace import TraceWriter

logger = logging.getLogger(__name__)


class PolicyAgent:
    def __init__(self, gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.gateway = gateway
        self.trace = trace

    async def decide(self, state: CaseState) -> dict[str, Any]:
        # 1. Fetch authoritative policy
        pver = state.policy_version or "EC_POLICY_V1"
        try:
            pol_ev = await self.gateway.call(
                "get_policy", case_id=state.case_id, policy_version=pver
            )
            ev_ref = pol_ev.get("evidence_ref")
            if ev_ref:
                state.evidence_refs.append(ev_ref)
                self.trace.emit(
                    case_id=state.case_id,
                    event_type="tool_result_consumed",
                    actor="policy-agent",
                    tool_name="get_policy",
                    evidence_refs=[ev_ref],
                )
            state.policy_data = pol_ev.get("data") or {}
        except Exception as exc:
            logger.warning(f"Policy fetch error for {pver} on {state.case_id}: {exc}")

        # 2. Classify based on evidence
        classification = classify_case(state)

        primary_issue = classification["primary_issue"]
        case_status = classification["case_status"]
        confidence = float(classification["confidence"])
        cause_code = classification["cause_code"]
        responsible_parties = [classification["responsible_party"]]
        refund_amount = round(float(classification.get("refund_amount", 0.0)), 2)
        reason_code = classification.get("reason_code", "GENERAL_RESOLUTION")
        actions = list(classification.get("actions", ["no_action_required"]))

        # 3. Align with authoritative policy rules if provided
        policy_rules = {}
        if isinstance(state.policy_data, dict):
            policy_rules = state.policy_data.get("rules", {})
        if isinstance(policy_rules, dict) and primary_issue in policy_rules:
            matched_rule = policy_rules[primary_issue]
            if isinstance(matched_rule, dict):
                if matched_rule.get("case_status"):
                    case_status = str(matched_rule["case_status"])
                if "refund_brl" in matched_rule:
                    refund_amount = round(float(matched_rule["refund_brl"]), 2)
                if matched_rule.get("recommended_action"):
                    actions.insert(0, str(matched_rule["recommended_action"]))
                if matched_rule.get("responsible_parties"):
                    raw_parties = matched_rule["responsible_parties"]
                    if isinstance(raw_parties, list) and raw_parties:
                        responsible_parties = raw_parties

        # 4. Assemble Draft Output
        unique_evidence_refs = list(dict.fromkeys(state.evidence_refs))[:30]

        refund_lines = []
        if case_status == "action_required" and refund_amount > 0:
            refund_lines.append(
                {
                    "reason_code": reason_code,
                    "amount_brl": refund_amount,
                    "entity_id": state.order_id,
                }
            )
        else:
            refund_amount = 0.0

        # Build claim assessments if claims were present in the raw input
        req = state.raw_case.get("customer_request") or {}
        raw_claims = (
            req.get("claims")
            if isinstance(req, dict)
            else state.raw_case.get("claims")
        ) or []

        claim_assessments = []
        if isinstance(raw_claims, list):
            for claim in raw_claims[:5]:
                if isinstance(claim, dict):
                    cid = claim.get("claim_id") or "CLM_001"
                    topic = str(claim.get("topic") or "").lower()

                    is_topic_supported = (
                        topic == primary_issue
                        or (topic == "requested_full_refund" and case_status == "action_required")
                    )
                    if case_status == "needs_investigation":
                        verdict = "insufficient_evidence"
                    elif is_topic_supported:
                        verdict = "supported"
                    elif case_status == "action_required":
                        verdict = "partially_supported"
                    else:
                        verdict = "unsupported"

                    claim_assessments.append(
                        {
                            "claim_id": str(cid),
                            "verdict": verdict,
                            "confidence": confidence,
                            "evidence_refs": unique_evidence_refs[:10],
                        }
                    )

        draft_output: dict[str, Any] = {
            "schema_version": "day09-l3a-output-v2",
            "case_id": state.case_id,
            "assessment": {
                "primary_issue": primary_issue,
                "case_status": case_status,
                "confidence": confidence,
            },
            "affected_entities": {
                "order_ids": sorted(list(state.order_ids))[:20],
                "item_ids": sorted(list(state.item_ids))[:20],
                "seller_ids": sorted(list(state.seller_ids))[:20],
                "payment_references": sorted(list(state.payment_references))[:20],
                "shipment_ids": sorted(list(state.shipment_ids))[:20],
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": cause_code, "rank": 1}],
                "responsible_parties": responsible_parties[:5],
            },
            "evidence_refs": unique_evidence_refs,
            "data_conflicts": state.data_conflicts[:5],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": refund_amount,
                "refund_lines": refund_lines[:10],
            },
            "resolution_actions": list(dict.fromkeys(actions))[:8],
        }

        if claim_assessments:
            draft_output["claim_assessments"] = claim_assessments

        # Emit policy_decided trace event
        self.trace.emit(
            case_id=state.case_id,
            event_type="policy_decided",
            actor="policy-agent",
            decision_code=primary_issue,
            evidence_refs=unique_evidence_refs[:10] if unique_evidence_refs else None,
            attributes={"status": case_status, "confidence": confidence},
        )

        return draft_output
