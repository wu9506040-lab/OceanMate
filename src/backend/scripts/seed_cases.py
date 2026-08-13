"""Seed cases → Chroma cases_vec（demo 占位案例）。

用法：
    cd src/backend
    python scripts/seed_cases.py
    python scripts/seed_cases.py --reset
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from app.implementations.rag.chroma_rag import ChromaRAGEngine, COLLECTION_CASES
from app.implementations.chunking import SmartChunker
from app.implementations.pipelines import IngestionPipeline


# Demo 占位案例（12 条）—— 真实对接时从 cases.json / 飞书多维表格同步
# 案例来源：行业最佳实践（Visa VROL / Mastercard Collaboration）+ OP 客服常见工单
_DEMO_CASES = [
    {
        "id": "case_demo_001",
        "problem_desc": "BR 区域商户 Visa 支付失败 ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        "diagnosis": "BR Visa 渠道风控规则命中，单笔金额超阈值 + 短时间内多次尝试",
        "resolution": "联系风控团队确认规则阈值；必要时加入白名单；建议商户开启 BR 区域 3DS 配置",
        "country": "BR",
        "channel": "Visa",
        "problem_type": "支付失败",
        "error_code": "ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        "confidence": 0.85,
    },
    {
        "id": "case_demo_002",
        "problem_desc": "BR 区域 3DS 认证未通过 ERR_DEMO_3DS_REQUIRED_001",
        "diagnosis": "BR 区域 Visa 必须配套 3DS 配置；当前商户未开启或持卡人 3DS 认证失败",
        "resolution": "检查 Merchant Console 3DS 配置；联系商户开启 BR 区域 3DS",
        "country": "BR",
        "channel": "Visa",
        "problem_type": "支付失败",
        "error_code": "ERR_DEMO_3DS_REQUIRED_001",
        "confidence": 0.90,
    },
    {
        "id": "case_demo_003",
        "problem_desc": "US 区域商户 Visa 拒付 chargeback ERR_DEMO_CHARGEBACK_001",
        "diagnosis": "持卡人在发卡行侧发起 dispute，需走 RDR/CDRN 流程",
        "resolution": "准备 CB 申诉材料（订单/物流/签收凭证）；通过 Verifi/Mastercard RDR 提前拦截",
        "country": "US",
        "channel": "Visa",
        "problem_type": "拒付",
        "error_code": "ERR_DEMO_CHARGEBACK_001",
        "confidence": 0.78,
    },
    {
        "id": "case_demo_004",
        "problem_desc": "PayPal 退款被拒 ERR_DEMO_REFUND_REJECTED_001",
        "diagnosis": "原交易超退款窗口（>180 天）或通道拒绝退款",
        "resolution": "走 OP 财务团队特批流程；商户端沟通替代方案（账户余额 / 重新下单）",
        "country": "GLOBAL",
        "channel": "PayPal",
        "problem_type": "退款异常",
        "error_code": "ERR_DEMO_REFUND_REJECTED_001",
        "confidence": 0.72,
    },
    # === Day 9 真实行业案例（来自 Visa/Mastercard 公开规则 + OP 客服常见工单）===
    {
        "id": "case_demo_005",
        "problem_desc": "Visa reason code 13.1 (Merchandise/Services Not Received) 高发于数字商品电商",
        "diagnosis": "数字商品（软件/课程/会员）因即时交付特性，13.1（未收到货）拒付率显著高于实物。持卡人 dispute 时发卡行直接判商户败诉比例高。",
        "resolution": "1) 启用 Visa Rapid Dispute Resolution (RDR) - 满足阈值（<$5K 且争议≤365天）可秒级退款；2) 强化交付凭证（IP/邮箱/激活码/登录日志）；3) 退款政策提前在 checkout 页明示",
        "country": "GLOBAL",
        "channel": "Visa",
        "problem_type": "拒付",
        "error_code": "CB_13.1",
        "confidence": 0.92,
    },
    {
        "id": "case_demo_006",
        "problem_desc": "Mastercard reason code 4837 (No Cardholder Authorization) - 持卡人否认交易",
        "diagnosis": "4837 是 MC 体系最常见的拒付码之一（约占 40%）。触发场景：未授权交易 / 家庭成员盗用 / BIN 撞库攻击。",
        "resolution": "1) 优先 MATCH 名单核查（确认是否命中）；2) Ethoca/Verifi 提前拦截；3) 3DS 2.0 强制开启（liability shift 到发卡行）；4) 准备 3DS 认证日志作为 CB 申诉证据",
        "country": "GLOBAL",
        "channel": "Mastercard",
        "problem_type": "拒付",
        "error_code": "CB_4837",
        "confidence": 0.88,
    },
    {
        "id": "case_demo_007",
        "problem_desc": "BR Pix 通道偶发 T+0 结算延迟",
        "diagnosis": "BR Pix 央行系统虽 7x24，但商户端偶发清算延迟与银行批处理窗口冲突；周六 22:00-周日 06:00 BRT 出现概率较高。",
        "resolution": "1) 商户端切到 Boleto 兜底；2) 提示商户该时段属预期延迟，避免升级投诉；3) PIX SPI 故障时通知商户切换备用通道",
        "country": "BR",
        "channel": "Pix",
        "problem_type": "支付失败",
        "error_code": "ERR_PIX_SPI_DELAY",
        "confidence": 0.75,
    },
    {
        "id": "case_demo_008",
        "problem_desc": "US 订阅类商户 Visa 12.6.1 (Duplicate Processing) 高发",
        "diagnosis": "订阅扣款场景因用户首次失败重试 + 系统未做幂等，触发 12.6.1（重复处理）。Visa 12.6.1 持卡人可主张商户多扣款拒付。",
        "resolution": "1) 商户系统强制 idempotency-key；2) 首次失败 N 秒内不重试同一卡号；3) webhook + 清算文件对账，重复记录自动退款；4) Visa VROL Self-Service Refund 提前主动退",
        "country": "US",
        "channel": "Visa",
        "problem_type": "拒付",
        "error_code": "CB_12.6.1",
        "confidence": 0.87,
    },
    {
        "id": "case_demo_009",
        "problem_desc": "MX OXXO 现金支付商户对账不平",
        "diagnosis": "OXXO 是 MX 主流现金支付（占电商 25%+），但用户支付后需 24-72h 回执确认；商户系统用同步 callback 易导致订单误判未支付。",
        "resolution": "1) 不依赖 callback，改用对账文件（每天拉取 OP settlement）；2) 订单状态机增加 'awaiting_cash' 中间态；3) 提示商户付款 72h 后再发货",
        "country": "MX",
        "channel": "OXXO",
        "problem_type": "支付失败",
        "error_code": "ERR_OXXO_RECONCILIATION",
        "confidence": 0.80,
    },
    {
        "id": "case_demo_010",
        "problem_desc": "DE iDEAL 大额支付偶发 3DS 二次挑战失败",
        "diagnosis": "iDEAL 是 DE/NL 主流银行直连，>€30 触发强客户认证 (SCA)；DE 持卡人银行 PSD2 认证页超时率高（30-60s），失败率显著高于其他通道。",
        "resolution": "1) UI 显式提示认证时长；2) 提供 retry 时自动保留原订单号；3) 失败后切 SEPA Direct Debit 兜底；4) 提交 iDEAL + SEPA 双通道备用",
        "country": "DE",
        "channel": "iDEAL",
        "problem_type": "支付失败",
        "error_code": "ERR_IDEAL_SCA_TIMEOUT",
        "confidence": 0.83,
    },
    {
        "id": "case_demo_011",
        "problem_desc": "US PayPal 退款通道拒退 (insufficient funds)",
        "diagnosis": "PayPal 商户账户余额不足时，退款请求被 PayPal 自动挂起；超 30 天商户未补款则自动转纠纷。",
        "resolution": "1) 商户端预充值 PayPal 余额（建议月流水的 5%）；2) 启用 PayPal Adaptive 预扣；3) 超额退款走 OP 财务特批；4) 商户控制台加余额预警",
        "country": "US",
        "channel": "PayPal",
        "problem_type": "退款异常",
        "error_code": "ERR_PAYPAL_INSUFFICIENT_FUNDS",
        "confidence": 0.89,
    },
    {
        "id": "case_demo_012",
        "problem_desc": "JP 信用卡通道 (JCB) 海外商户 3DS 认证覆盖率低",
        "diagnosis": "JCB 持卡人多用本地银行发行的 JCB 卡，海外商户 3DS 适配率低时失败率高；JP 持卡人对认证页 loading 时间容忍度极低（>5s 流失）。",
        "resolution": "1) 切 JCB 专用 3DS 通道（与 J/Secure 兼容）；2) UI 预加载认证页；3) 启用 JCB 一次性 token 减少重复认证；4) >¥5000 自动建议 Konbini 现金支付",
        "country": "JP",
        "channel": "JCB",
        "problem_type": "支付失败",
        "error_code": "ERR_JCB_3DS_NOT_SUPPORTED",
        "confidence": 0.78,
    },
]


def _to_records() -> list[dict]:
    """Demo cases → Pipeline records。"""
    records = []
    for c in _DEMO_CASES:
        # text 拼接 problem + diagnosis + resolution（向量含完整问题-诊断-处理链）
        text = (
            f"{c['problem_desc']}。"
            f"诊断：{c['diagnosis']}。"
            f"处理建议：{c['resolution']}"
        )
        records.append({
            "id": c["id"],
            "text": text,
            "country": c["country"],
            "channel": c["channel"],
            "problem_type": c["problem_type"],
            "error_code": c["error_code"],
            "confidence": c["confidence"],
        })
    return records


def seed(reset: bool = False, collection: str = COLLECTION_CASES) -> dict:
    engine = ChromaRAGEngine()

    if reset:
        existing = engine._collections[collection].get(limit=10000)
        existing_ids = existing.get("ids", []) if existing else []
        if existing_ids:
            for doc_id in existing_ids:
                engine.delete_document(doc_id, collection_name=collection)
            print(f"[reset] 清除 {len(existing_ids)} 条旧文档")

    records = _to_records()
    pipeline = IngestionPipeline(rag=engine, chunker=SmartChunker())
    stats = pipeline.ingest(
        records=records,
        source_table="cases_demo",
        collection_name=collection,
    )

    return {
        "source_records": len(records),
        **stats,
        "collection_total": engine.get_collection_stats()[collection],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo cases to Chroma cases_vec")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    result = seed(reset=args.reset)

    print(f"[OK] Cases Seed 完成")
    print(f"   source_records:  {result['source_records']}")
    print(f"   total_chunks:    {result['total_chunks']}")
    print(f"   skipped_records: {result['skipped_records']}")
    print(f"   strategies_used: {result['strategies_used']}")
    print(f"   collection_total: {result['collection_total']}")