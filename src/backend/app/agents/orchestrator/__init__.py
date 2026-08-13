"""Orchestrator - 商户成功 AI 中枢（意图分流 + Tool 编排）。"""

from app.agents.orchestrator.orchestrator import Orchestrator


def create_default_orchestrator(
    db_path: str = "data/oceanmate.db",
    chroma_path: str = "data/chroma",
    auto_init_db: bool = True,
) -> Orchestrator:
    """工厂函数：装配 4 Tool + DB + RAG 的默认 Orchestrator。

    设计：
    - 4 Tool 全部注册（MSA / PDA / TRA / KEA）
    - 共享一个 SQLite DB + Chroma RAG
    - DB 路径不存在时自动初始化（执行 DDL）
    - 用于 FastAPI 启动时单例构造

    Args:
        db_path: SQLite 数据库路径
        chroma_path: Chroma 数据目录
        auto_init_db: 自动初始化 DB（执行 DDL），默认 True

    Returns:
        Orchestrator 实例
    """
    from pathlib import Path
    from app.implementations.db.sqlite_db import SQLiteDatabase
    from app.implementations.db.repositories import (
        MerchantRepository,
        TicketRepository,
        CaseRepository,
    )
    from app.implementations.rag.chroma_rag import ChromaRAGEngine
    from app.agents.msa import MSATool
    from app.agents.pda import PDATool
    from app.agents.tra import TRATool
    from app.agents.kea import KEATool
    from app.implementations.llm.qwen_gateway import get_default_gateway  # Day 10: 真 LLM 注入

    # Auto-init DB
    if auto_init_db:
        db_file = Path(db_path)
        if not db_file.exists():
            from scripts.init_db import DDL_STATEMENTS
            import sqlite3
            db_file.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_file))
            conn.execute("PRAGMA foreign_keys = ON")
            for ddl in DDL_STATEMENTS:
                conn.execute(ddl)
            conn.commit()
            conn.close()

    # 装配
    db = SQLiteDatabase(Path(db_path))
    rag = ChromaRAGEngine(data_dir=Path(chroma_path))
    merchant_repo = MerchantRepository(db)
    ticket_repo = TicketRepository(db)
    case_repo = CaseRepository(db)

    # Day 10: 注入真 LLM（get_default_gateway 自动检测 DASHSCOPE_API_KEY，有则 Qwen，否则 Mock）
    llm = get_default_gateway()
    orch = Orchestrator()
    orch.register_tool(MSATool(rag=rag, llm=llm))
    orch.register_tool(PDATool())  # PDA 内部自管 service，LLM 自带降级
    orch.register_tool(TRATool(ticket_repo=ticket_repo))
    orch.register_tool(KEATool(
        case_repo=case_repo,
        rag=rag,
        embedding_meta_repo=db,
    ))
    return orch


__all__ = ["Orchestrator", "create_default_orchestrator"]
