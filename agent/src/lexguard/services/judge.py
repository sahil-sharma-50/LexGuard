"""Pure deterministic verdict selection and tamper-evident certificates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from lexguard.adapters.repository import CaseRead
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import (
    CandidateStructure,
    CatalystAssessment,
    RefusalRecord,
    TradeCertificate,
)
from lexguard.domain.payoff import exact_max_loss
from lexguard.domain.policy import RiskContext, RiskPolicy
from lexguard.services.candidates import rank_candidates


class Judge:
    """Recompute proposal risk and issue exactly one certificate or refusal."""

    def __init__(
        self,
        *,
        policy: RiskPolicy | None = None,
        policy_version: str = "risk-constitution.v1",
        # The certificate must survive the evaluation-to-execution window gap
        # (five minutes) with margin; execution re-validates risk regardless.
        certificate_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        if not policy_version:
            raise ValueError("policy_version must be non-empty")
        if certificate_ttl <= timedelta(0):
            raise ValueError("certificate_ttl must be positive")
        self.policy = policy or RiskPolicy()
        self.policy_version = policy_version
        self.certificate_ttl = certificate_ttl

    def certify(
        self,
        case: CaseRead,
        candidates: Sequence[CandidateStructure],
        context: RiskContext,
        *,
        catalyst: CatalystAssessment | None = None,
    ) -> TradeCertificate | RefusalRecord:
        if catalyst is not None and catalyst.scenario == "VETO":
            return self._refusal(case, context, ("CATALYST_VETO",), len(candidates))
        if not candidates:
            return self._refusal(case, context, ("NO_ELIGIBLE_CANDIDATE",), 0)

        expires_at = context.now + self.certificate_ttl
        policy_context = context.model_copy(update={"certificate_expires_at": expires_at})
        refusals: set[str] = set()
        for proposed in rank_candidates(candidates):
            recomputed_loss = exact_max_loss(proposed)
            candidate = proposed.model_copy(update={"max_loss": recomputed_loss})
            decision = self.policy.evaluate(candidate, policy_context)
            refusals.update(decision.reason_codes)
            if candidate.robust_ev <= 0:
                refusals.add("ROBUST_EV_NON_POSITIVE")
                continue
            if not decision.allowed:
                continue
            proposal_hash = canonical_sha256(candidate)
            certificate_id = uuid5(
                NAMESPACE_URL,
                f"{case.case_id}:{proposal_hash}:{self.policy_version}",
            )
            return TradeCertificate(
                certificate_id=certificate_id,
                case_id=case.case_id,
                candidate=candidate,
                issued_at=context.now,
                expires_at=expires_at,
                policy_version=self.policy_version,
                proposal_hash=proposal_hash,
                account_equity=context.account_equity,
                daily_pnl=context.daily_pnl,
                competition_drawdown=context.competition_drawdown,
            )

        return self._refusal(case, context, tuple(sorted(refusals)), len(candidates))

    def _refusal(
        self,
        case: CaseRead,
        context: RiskContext,
        reason_codes: Sequence[str],
        candidate_count: int,
    ) -> RefusalRecord:
        return RefusalRecord(
            case_id=case.case_id,
            refused_at=context.now,
            reason_codes=tuple(sorted(set(reason_codes))),
            details={
                "candidate_count": str(candidate_count),
                "policy_version": self.policy_version,
            },
        )
