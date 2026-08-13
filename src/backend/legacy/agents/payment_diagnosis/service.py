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

        # Step 1: 先按 error_code 推断问题类型（决定证据相关性过滤）
        problem_type = self._infer_problem_type(problem)

        # Step 2: 多源证据融合（含 Chroma 知识库真实检索 · Day 14 P0-1）
        evidence = self.evidence_store.collect_evidence(problem, problem_type)

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
    def _infer_problem_type(problem: ProblemRecord, evidence=None) -> str:
        """根据 error_code 前缀 / 原始问法推断问题类型。

        Day 14 P0-2：error_code 可为空（场景类问题），此时退回 query_text 关键词。
        """
        ec = (problem.error_code or "").upper()
        if "WEBHOOK" in ec or "CALLBACK" in ec:
            return "Webhook 回调失败"
        if "RISK" in ec or "BLOCK" in ec or "3DS" in ec:
            return "支付失败"
        # Day 9: CB_ 开头（Visa/MC 真实拒付码）也是拒付
        if "CHARGEBACK" in ec or ec.startswith("CB_"):
            return "拒付"
        if "REFUND" in ec:
            return "退款异常"
        # 无 error_code → 看商户原话
        q = getattr(problem, "query_text", "") or ""
        if "webhook" in q.lower() or "回调" in q:
            return "Webhook 回调失败"
        if "拒付" in q or "chargeback" in q.lower():
            return "拒付"
        if "退款" in q:
            return "退款异常"
        if any(kw in q for kw in ("延迟", "慢", "不到账", "到账", "结算", "对账")):
            return "结算延迟"
        return "支付失败"