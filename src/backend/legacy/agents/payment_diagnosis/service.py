"""Payment Diagnosis Service - 核心诊断逻辑。

流程：收集证据 → 调用 LLM 归因 → 组装诊断输出
"""

from typing import Optional  # noqa: F401

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

        # Step 5: Day 9 新增 — 若 error_code 匹配拒付码（CB_xxx），附加配图
        error_image_path = self._lookup_error_image(problem.error_code)

        return DiagnoseResponse(
            diagnosis=diagnosis,
            trace={
                "evidence_count": len(evidence),
                "llm_provider": type(self.llm).__name__,
                "evidence_types": [e.type for e in evidence],
                "error_image_path": error_image_path or "",  # 给 webhook/poller 推图用
            },
        )

    @staticmethod
    def _lookup_error_image(error_code: str) -> Optional[str]:
        """根据 error_code（如 CB_13.1）查 SVG 配图路径。

        规则：CB_ 开头 → 把 . 替换为 _ → cb_demo_<code> → data/error_images/<id>.png
        例：CB_13.1 → cb_demo_13_1 → data/error_images/cb_demo_13_1.png

        文件路径：service.py 在 src/backend/legacy/agents/payment_diagnosis/，
        parents[5] = ai-pioneer/（项目根），error_images 就在项目根 data/ 下。
        """
        from pathlib import Path
        if not error_code or not error_code.upper().startswith("CB_"):
            return None
        code = error_code[3:]  # 13.1
        # SVG id 规则：cb_demo_10_1 / cb_demo_10_1_2 (multi-level)
        rid = "cb_demo_" + code.replace(".", "_")
        workspace = Path(__file__).resolve().parents[5]  # ai-pioneer/
        png_path = workspace / "data" / "error_images" / f"{rid}.png"
        if png_path.exists():
            return f"data/error_images/{rid}.png"
        return None

    @staticmethod
    def _infer_problem_type(problem: ProblemRecord, evidence) -> str:
        """根据 error_code 前缀/evidence 推断问题类型。"""
        ec = problem.error_code.upper()
        if "RISK" in ec or "BLOCK" in ec or "3DS" in ec or "WEBHOOK" in ec:
            return "支付失败"
        # Day 9: CB_ 开头（Visa/MC 真实拒付码）也是拒付
        if "CHARGEBACK" in ec or ec.startswith("CB_"):
            return "拒付"
        if "REFUND" in ec:
            return "退款异常"
        return "支付失败"