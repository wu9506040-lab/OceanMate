"""Payment Diagnosis Service - 核心诊断逻辑。

流程：收集证据 → 调用 LLM 归因 → 组装诊断输出
"""

from typing import Optional

from .evidence_store import EvidenceStore
from .llm_provider import LLMProvider, get_default_provider
from .schemas import (
    Diagnosis,
    DiagnoseRequest,
    DiagnoseResponse,
    ProblemRecord,
)


class PaymentDiagnosisService:
    """Payment Diagnosis Agent 主服务。"""

    def __init__(
        self,
        evidence_store: Optional[EvidenceStore] = None,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.evidence_store = evidence_store or EvidenceStore()
        self.llm = llm_provider or get_default_provider()

    def diagnose(self, req: DiagnoseRequest) -> DiagnoseResponse:
        problem = req.problem_record

        # Step 1: 多源证据融合
        evidence = self.evidence_store.collect_evidence(problem)

        # Step 2: 根据 evidence 推断 problem_type
        problem_type = self._infer_problem_type(problem, evidence)

        # Step 3: LLM 因果归因
        llm_result = self.llm.generate_diagnosis(
            problem_type_hint=problem_type,
            country=problem.country,
            channel=problem.channel,
            evidence=evidence,
        )

        # Step 4: 组装输出
        diagnosis = Diagnosis(
            problem_type=problem_type,
            root_causes=llm_result["root_causes"],
            evidence_chain=evidence,
            recommended_actions=llm_result["recommended_actions"],
            confidence=llm_result["confidence"],
            next_agent="Ticket Routing Agent",
        )

        return DiagnoseResponse(
            diagnosis=diagnosis,
            trace={
                "evidence_count": len(evidence),
                "llm_provider": type(self.llm).__name__,
                "evidence_types": [e.type for e in evidence],
            },
        )

    @staticmethod
    def _infer_problem_type(problem: ProblemRecord, evidence) -> str:
        """根据 error_code 前缀/evidence 推断问题类型。"""
        ec = problem.error_code.upper()
        if "RISK" in ec or "BLOCK" in ec or "3DS" in ec or "WEBHOOK" in ec:
            return "支付失败"
        if "CHARGEBACK" in ec:
            return "拒付"
        if "REFUND" in ec:
            return "退款异常"
        return "支付失败"