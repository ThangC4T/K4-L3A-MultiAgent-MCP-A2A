from __future__ import annotations

import logging
from typing import Any

from ..contracts import Contracts
from ..state import CaseState
from ..trace import TraceWriter

logger = logging.getLogger(__name__)


class VerifierAgent:
    def __init__(self, contracts: Contracts, trace: TraceWriter) -> None:
        self.contracts = contracts
        self.trace = trace

    def verify_and_finalize(self, output: dict[str, Any], state: CaseState) -> dict[str, Any]:
        """Verify cross-field invariants, ensure evidence ownership and schema compliance."""
        assessment = output.get("assessment", {})
        status = assessment.get("case_status")
        fin = output.get("financial_resolution", {})
        lines = fin.get("refund_lines", [])

        # Invariant 1: no_action must not have refund
        if status == "no_action":
            fin["recommended_refund_brl"] = 0.0
            fin["refund_lines"] = []

        # Invariant 2: total refund must equal sum of refund lines
        elif status == "action_required":
            if lines:
                line_sum = round(sum(float(line.get("amount_brl", 0.0)) for line in lines), 2)
                fin["recommended_refund_brl"] = line_sum
            else:
                fin["recommended_refund_brl"] = 0.0

        # Invariant 3: Evidence provenance check - only retain refs collected during this case
        harvested_set = set(state.evidence_refs)
        filtered_refs = [ref for ref in output.get("evidence_refs", []) if ref in harvested_set]
        output["evidence_refs"] = list(dict.fromkeys(filtered_refs))

        # Invariant 4: Resolution actions must be unique and non-empty
        actions = output.get("resolution_actions", [])
        if not actions:
            actions = ["no_action_required" if status == "no_action" else "review_case"]
        output["resolution_actions"] = list(dict.fromkeys(actions))[:8]

        # Invariant 5: Verify public JSON schema compliance
        self.contracts.validate_output(output, f"verifier:case:{state.case_id}")

        # Emit verification_completed trace event
        self.trace.emit(
            case_id=state.case_id,
            event_type="verification_completed",
            actor="verifier",
            decision_code="VERIFIED_PASS",
            attributes={"invariants_checked": True, "evidence_count": len(output["evidence_refs"])},
        )

        return output
