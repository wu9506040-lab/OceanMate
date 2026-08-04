"""KEATool - 知识进化助手（OP 命题方向 ⑤ · 案例→FAQ 自进化闭环）。

3 个 intent：
- promote_to_faq       把 cases 表中已结案的案例升格为 FAQ（写 Chroma + embedding_meta）
- search_faq           按 query 检索 FAQ（Chroma retrieve → join cases 表返回富信息）
- list_candidates      列高置信度 + 未沉淀的候选（供运营审阅 / 自动 promote）

设计要点：
- 复用 BaseRAGEngine（默认 ChromaRAGEngine.cases_vec）
- 复用 CaseRepository（SQLite cases 表）
- 复用 embedding_meta 表（SQLite ↔ Chroma 一致性追踪）
- 严格 3 步事务逻辑：
  1. promote_to_faq：先 cases.update（标记）→ 再 chroma.add → 再 embedding_meta.insert
  2. 任意一步失败 → 全回滚 / 友好降级
- 失败必须用户友好降级，不抛 raw exception
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from app.interfaces.base_tool import BaseTool
from app.interfaces.base_rag import BaseRAGEngine, Document
from app.implementations.db.repositories import CaseRepository
from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    COLLECTION_CASES,
)
from app.models import Case


# === FAQ 升级阈值（来自 OP 真实运维经验）===

DEFAULT_MIN_CONFIDENCE = 0.85
"""confidence ≥ 0.85 的案例视为高置信度，才建议升级为 FAQ。"""
DEFAULT_LIST_LIMIT = 20
"""list_candidates 默认返回条数。"""


class KEATool(BaseTool):
    """知识进化 Tool — MCP tool_spec 兼容。

    输入参数（input_schema）：
        intent            "promote_to_faq" | "search_faq" | "list_candidates"
        case_id           案例 ID（promote 时必填）
        query             检索文本（search 时必填）
        top_k             Top-K（search 可选，默认 5）
        country           国家级过滤（search 可选）
        min_confidence    置信度阈值（list 可选，默认 0.85）
        limit             返回条数（list 可选，默认 20）

    输出（output_schema）：
        intent            输入的 intent
        faqs              search 返回的富信息 list
        case_id / chroma_id   promote 返回
        candidates        list 返回的候选 list
        promoted / indexed / retrieved   数量统计
        trace             执行轨迹
    """

    name = "knowledge_evolution"
    description = (
        "知识进化助手：把 PDA 诊断的高置信度案例自动沉淀为 FAQ，"
        "下次商户提问时即时召回，支持 list_candidates / promote_to_faq / search_faq。"
        "对位 OP 命题方向 ⑤ · 案例→FAQ 自进化闭环。"
    )

    def __init__(
        self,
        case_repo: Optional[CaseRepository] = None,
        rag: Optional[BaseRAGEngine] = None,
        chroma_path: Optional[Path] = None,
        embedding_meta_repo=None,
    ):
        """初始化 KEATool。

        Args:
            case_repo: 注入 CaseRepository（默认 None → 不接 DB，仅走 RAG）
            rag: 注入 BaseRAGEngine（默认 None → ChromaRAGEngine 懒加载）
            chroma_path: Chroma 数据目录覆盖（默认走 ChromaRAGEngine 默认路径）
            embedding_meta_repo: 注入 embedding_meta 仓库（PoC 阶段直接走 SQLiteDatabase）
        """
        self.case_repo = case_repo
        self.rag = rag
        self._rag_kwargs = {}
        if chroma_path:
            self._rag_kwargs["data_dir"] = Path(chroma_path)

        # embedding_meta 仓库（不依赖 Pydantic 模型，直接用 BaseDatabase）
        self._db = None
        if embedding_meta_repo is not None:
            self._db = embedding_meta_repo
        elif case_repo is not None and hasattr(case_repo, "db"):
            # 共用 case_repo 的 db（嵌入到 BaseDatabase）
            self._db = case_repo.db

    def _ensure_rag(self) -> BaseRAGEngine:
        """懒加载 ChromaRAGEngine。"""
        if self.rag is None:
            self.rag = ChromaRAGEngine(**self._rag_kwargs)
        return self.rag

    # === MCP tool_spec schemas ===

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["promote_to_faq", "search_faq", "list_candidates"],
                    "description": "意图：promote_to_faq / search_faq / list_candidates",
                },
                "case_id": {
                    "type": "string",
                    "description": "案例 ID（promote_to_faq 时必填）",
                },
                "query": {
                    "type": "string",
                    "description": "检索文本（search_faq 时必填）",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 5,
                    "description": "Top-K 检索条数",
                },
                "country": {
                    "type": "string",
                    "description": "国家过滤（search_faq 可选）",
                },
                "min_confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": DEFAULT_MIN_CONFIDENCE,
                    "description": "置信度阈值（list_candidates 可选）",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": DEFAULT_LIST_LIMIT,
                    "description": "返回条数（list_candidates 可选）",
                },
            },
            "required": ["intent"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "count": {"type": "integer"},
                "promoted": {"type": "boolean"},
                "case_id": {"type": "string"},
                "chroma_id": {"type": "string"},
                "faqs": {"type": "array"},
                "candidates": {"type": "array"},
                "trace": {"type": "object"},
            },
            "required": ["intent"],
        }

    @property
    def capabilities(self) -> dict:
        return {
            "async_supported": True,
            "idempotent": False,  # promote 会写新 chroma_id
            "requires_auth": False,
        }

    # === 业务执行 ===

    def execute(self, params: dict) -> dict:
        intent = params["intent"]
        if intent == "promote_to_faq":
            return self._promote_to_faq(params)
        elif intent == "search_faq":
            return self._search_faq(params)
        elif intent == "list_candidates":
            return self._list_candidates(params)
        else:
            raise ValueError(f"Unknown intent: {intent}")

    # === 子能力 1：把案例升格为 FAQ ===

    def _promote_to_faq(self, params: dict) -> dict:
        """把 cases 表中已诊断好的案例写进 Chroma + embedding_meta。

        异常处理：
        - cases 表无此 ID → 友好 not_found
        - 已有 embedding_meta 记录 → 友好 already_promoted
        - Chroma add 失败 → 友好降级
        - embedding_meta insert 失败 → Chroma 已写，回滚不动；友好提示
        """
        case_id = params.get("case_id")
        if not case_id:
            return self._error_result(
                "promote_to_faq",
                error="case_id 必填",
                hint="从 PDA 诊断结果或 cases 表获取 case_id。",
            )

        if self.case_repo is None:
            return self._error_result(
                "promote_to_faq",
                error="CaseRepository 未注入，无法读取 cases",
                hint="测试或 Demo 场景：请传入 case_repo=CaseRepository(db)。",
            )

        # 1) 查 cases 表
        case = self.case_repo.get_by_id(case_id)
        if case is None:
            return self._error_result(
                "promote_to_faq",
                error=f"案例 '{case_id}' 不存在",
                hint="检查 case_id 来源（可能是 PDA 输出或人工录入）。",
            )

        # 2) 查 embedding_meta（避免重复 promote）
        chroma_id = f"faq_{case_id}_{uuid.uuid4().hex[:8]}"
        existing_meta = self._get_embedding_meta(source_table="cases", source_id=case_id)
        if existing_meta is not None:
            return self._error_result(
                "promote_to_faq",
                error=f"案例 '{case_id}' 已升级为 FAQ",
                hint=f"原 chroma_id={existing_meta}。如需更新请先 delete 再 promote。",
                promoted=False,
                already=True,
                case_id=case_id,
                existing_chroma_id=existing_meta,
            )

        # 3) 写 Chroma（cases_vec collection）
        rag_text = self._case_to_rag_text(case)
        metadata = self._case_to_metadata(case)
        rag = self._ensure_rag()
        try:
            rag.add_document(
                Document(id=chroma_id, text=rag_text, metadata=metadata),
                collection_name=COLLECTION_CASES,
            )
        except Exception as e:
            return self._error_result(
                "promote_to_faq",
                error=f"Chroma 写入失败: {e}",
                hint="检查 Chroma 服务 / 磁盘空间。",
                rag_error=str(e),
            )

        # 4) 写 embedding_meta
        if self._db is not None:
            try:
                self._db.execute(
                    """INSERT INTO embedding_meta
                    (source_table, source_id, chroma_id, collection_name)
                    VALUES (:st, :sid, :cid, :cn)""",
                    {
                        "st": "cases",
                        "sid": case_id,
                        "cid": chroma_id,
                        "cn": COLLECTION_CASES,
                    },
                )
            except Exception as e:
                return self._error_result(
                    "promote_to_faq",
                    error=f"embedding_meta 写入失败: {e}",
                    hint="Chroma 已写但 meta 未记录，后续检索可能找不到。运营可手工补登。",
                    chroma_id=chroma_id,
                    rag_written=True,
                    embedding_meta_error=str(e),
                )

        return {
            "intent": "promote_to_faq",
            "count": 1,
            "promoted": True,
            "case_id": case_id,
            "chroma_id": chroma_id,
            "trace": {
                "collection": COLLECTION_CASES,
                "chroma_id": chroma_id,
                "confidence": case.confidence,
                "problem_type": case.problem_type,
            },
        }

    # === 子能力 2：检索 FAQ ===

    def _search_faq(self, params: dict) -> dict:
        """Chroma 检索 → join cases 表 → 返回富信息。"""
        query = params.get("query")
        top_k = params.get("top_k", 5)
        country = params.get("country")

        if not query:
            return self._error_result(
                "search_faq",
                error="query 必填",
                hint="传入商户提问文本，如 'BR Visa 拒付怎么办'。",
            )

        # 1) Chroma 检索
        rag = self._ensure_rag()
        chroma_filter = {"country": country} if country else None
        try:
            docs = rag.retrieve(
                query,
                top_k=top_k,
                filter=chroma_filter,
                collection_name=COLLECTION_CASES,
            )
        except Exception as e:
            return self._error_result(
                "search_faq",
                error=f"Chroma 检索失败: {e}",
                hint="若检索持续失败，可改用 MockRAGEngine 或检查 Chroma 状态。",
                rag_error=str(e),
            )

        if not docs:
            return {
                "intent": "search_faq",
                "count": 0,
                "faqs": [],
                "trace": {
                    "query": query,
                    "top_k": top_k,
                    "country": country,
                    "empty_reason": "no_match",
                },
            }

        # 2) Join cases 表（PoC：查源 ID → 富信息）
        faqs = []
        for doc in docs:
            # chroma_id = "faq_<case_id>_<uuid8>" → 拆出 case_id
            # 例：faq_case_demo_001_abc12345
            # split("_") = ["faq", "case", "demo", "001", "abc12345"]
            # case_id = "_".join([1:-1]) = "case_demo_001"
            source_case_id = None
            if doc.id.startswith("faq_"):
                parts = doc.id.split("_")
                if len(parts) >= 3:
                    source_case_id = "_".join(parts[1:-1])
            case_info = None
            if source_case_id and self.case_repo is not None:
                case_obj = self.case_repo.get_by_id(source_case_id)
                if case_obj:
                    case_info = {
                        "problem_desc": case_obj.problem_desc,
                        "resolution": case_obj.resolution,
                        "country": case_obj.country,
                        "channel": case_obj.channel,
                        "error_code": case_obj.error_code,
                        "problem_type": case_obj.problem_type,
                        "confidence": case_obj.confidence,
                    }
            faqs.append({
                "chroma_id": doc.id,
                "case_id": source_case_id,
                "text_excerpt": doc.text[:200],
                "country": doc.metadata.get("country"),
                "problem_type": doc.metadata.get("problem_type"),
                "score_proxy": doc.metadata.get("confidence"),
                "case_info": case_info,
            })

        return {
            "intent": "search_faq",
            "count": len(faqs),
            "faqs": faqs,
            "trace": {
                "query": query,
                "top_k": top_k,
                "country_filter": country,
                "rag_results": len(docs),
            },
        }

    # === 子能力 3：列候选 FAQ ===

    def _list_candidates(self, params: dict) -> dict:
        """列高置信度 + 未沉淀的候选（confidence ≥ 阈值 + 无对应 embedding_meta）。"""
        min_confidence = params.get("min_confidence", DEFAULT_MIN_CONFIDENCE)
        limit = params.get("limit", DEFAULT_LIST_LIMIT)

        if self.case_repo is None:
            return self._error_result(
                "list_candidates",
                error="CaseRepository 未注入",
                hint="Demo 场景请传入 case_repo=CaseRepository(db)。",
            )

        # 1) 查所有 confidence ≥ 阈值的 case（先全量 list，再 Python 端过滤）
        try:
            candidates_raw = self.case_repo.list(
                filters=None,
                limit=limit * 3,  # 多查一些，扣去已 promote 的
            )
        except Exception as e:
            return self._error_result(
                "list_candidates",
                error=f"cases 查询失败: {e}",
                hint="检查 case_repo 与 DB 连接。",
            )

        candidates = []
        for c in candidates_raw:
            if c.confidence is None or c.confidence < min_confidence:
                continue
            # 2) 过滤已 promote 的（embedding_meta 中存在的）
            existing = self._get_embedding_meta(source_table="cases", source_id=c.id)
            if existing is not None:
                continue
            candidates.append({
                "case_id": c.id,
                "problem_desc": c.problem_desc,
                "resolution": c.resolution,
                "country": c.country,
                "channel": c.channel,
                "problem_type": c.problem_type,
                "confidence": c.confidence,
            })
            if len(candidates) >= limit:
                break

        return {
            "intent": "list_candidates",
            "count": len(candidates),
            "candidates": candidates,
            "trace": {
                "min_confidence": min_confidence,
                "limit": limit,
                "raw_scanned": len(candidates_raw),
            },
        }

    # === 辅助：cases 表行 → RAG text/metadata ===

    @staticmethod
    def _case_to_rag_text(case: Case) -> str:
        """把 cases 表行变成 RAG 文档文本。"""
        parts = [
            f"问题: {case.problem_desc or 'N/A'}",
            f"诊断: {case.diagnosis or 'N/A'}",
            f"解决方案: {case.resolution or 'N/A'}",
            f"国家: {case.country or 'N/A'}",
            f"渠道: {case.channel or 'N/A'}",
            f"错误码: {case.error_code or 'N/A'}",
        ]
        return "\n".join(parts)

    @staticmethod
    def _case_to_metadata(case: Case) -> dict:
        """cases 表行 → RAG metadata（用于过滤）。"""
        return {
            "case_id": case.id,
            "country": case.country or "",
            "channel": case.channel or "",
            "error_code": case.error_code or "",
            "problem_type": case.problem_type or "",
            "confidence": case.confidence if case.confidence is not None else 0.0,
        }

    # === 辅助：embedding_meta 表读写（轻量级，直接用 BaseDatabase） ===

    def _get_embedding_meta(self, source_table: str, source_id: str) -> Optional[str]:
        """从 embedding_meta 查 chroma_id（用于去重）。返回 None 表示无记录。"""
        if self._db is None:
            return None
        try:
            rows = self._db.query(
                """SELECT chroma_id FROM embedding_meta
                   WHERE source_table = :st AND source_id = :sid
                   LIMIT 1""",
                {"st": source_table, "sid": source_id},
            )
            return rows[0]["chroma_id"] if rows else None
        except Exception:
            return None

    # === 错误降级（友好提示，不抛 raw exception） ===

    @staticmethod
    def _error_result(intent: str, error: str, hint: str = "", **extras) -> dict:
        """统一错误返回（不抛 raw exception）。"""
        base = {
            "intent": intent,
            "count": 0,
            "promoted": False,
            "trace": {"error": error, "hint": hint, **extras},
        }
        if "faqs" not in extras:
            base["faqs"] = []
        if "candidates" not in extras:
            base["candidates"] = []
        return base
