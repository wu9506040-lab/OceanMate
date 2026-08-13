"""LLM Provider 抽象层 - 优先 Qwen，无 key 自动降级 Mock。

对接策略：
- 有 DASHSCOPE_API_KEY 环境变量 → 调用 Qwen (DashScope)
- 否则 → 使用基于规则的 Mock LLM（保证 Demo 始终能跑）
"""

import json
import os
import re
from pathlib import Path
from typing import List, Optional

from .schemas import EvidenceItem

# Day 14 P0-1：脚本 / 测试直接 import 时也要能读到项目根 .env（否则静默降级 Mock）
try:
    from dotenv import load_dotenv
    _cur = Path(__file__).resolve().parent
    for _ in range(7):
        if (_cur / ".env").exists():
            load_dotenv(_cur / ".env", override=False)
            break
        _cur = _cur.parent
except Exception:
    pass


class LLMProvider:
    """LLM 提供方抽象（Protocol 风格）。"""

    def generate_diagnosis(
        self,
        problem_type_hint: str,
        country: str,
        channel: str,
        evidence: List[EvidenceItem],
    ) -> dict:
        """生成结构化诊断 JSON。

        Returns: dict with keys: root_causes, recommended_actions, confidence
        """
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """基于规则的 Mock LLM - 保证无 key 时 Demo 也能跑。

    Day 14 P0 修复：不再无脑推 3DS。
    - Pix/iDEAL/UnionPay 等本地支付方式不需要 3DS
    - 信用卡类（Visa/MC/Amex/Discover）才涉及 3DS
    """

    # 业务规则：哪些渠道不涉及 3DS（Day 14 P0-4）
    NON_CARD_CHANNELS = {"Pix", "iDEAL", "UnionPay", "Klarna", "PayPal", "OXXO", "Boleto"}

    def generate_diagnosis(
        self,
        problem_type_hint: str,
        country: str,
        channel: str,
        evidence: List[EvidenceItem],
    ) -> dict:
        # 规则 1: 看 evidence 中是否含 3DS 配置缺失（仅信用卡类渠道）
        is_card_channel = channel not in self.NON_CARD_CHANNELS
        has_3ds_issue = is_card_channel and any(
            "3DS" in (e.description or "") for e in evidence
        )

        # 规则 2: 看通道是否 degraded/down
        channel_degraded = any(
            "degraded" in (e.description or "") or "down" in (e.description or "")
            for e in evidence
            if e.type == "channel_status"
        )

        # 规则 3（Day 14 P0-1）：知识库命中优先——用真实案例文本给人话结论
        kb_items = [e for e in evidence if e.type == "knowledge_base"]
        risk_items = [e for e in evidence if e.type == "risk_rule"]

        root_causes = []
        actions = []

        if kb_items or risk_items:
            for item in (risk_items + kb_items)[:2]:
                cause, act = self._split_kb_text(item.description or "")
                if cause:
                    root_causes.append(cause)
                if act:
                    actions.append(act)

        if has_3ds_issue:
            root_causes.append(
                f"{country} {channel} 渠道 3DS 认证配置问题（按当地合规要求可能强制，具体由 OP 规则决定）"
            )
            actions.append(f"检查 {country} 区域 3DS 配置（Merchant Console → 风控设置）")
        if channel_degraded:
            root_causes.append(f"{country} {channel} 通道当前处于 degraded/down 状态")
            actions.append(f"切换备用通道或等待 {channel} 通道恢复")

        if not root_causes:
            root_causes.append("证据不足，暂无法定位根因，建议补充错误码或联系 OP 客服")
        if not actions:
            actions.append("联系 OP 客服并提供订单号 + 错误截图，我们协助定位")
        actions.append("如需人工跟进，回复「转人工」我为您建工单")

        # 置信度：有真实证据（风控规则 / 知识库）才给高分
        real_count = len(risk_items) + len(kb_items)
        if real_count == 0:
            confidence = 0.3
        else:
            confidence = min(0.9, 0.6 + 0.1 * real_count)

        return {
            "root_causes": self._dedup(root_causes),
            "recommended_actions": self._dedup(actions),
            "confidence": round(confidence, 2),
        }

    @staticmethod
    def _dedup(items: List[str]) -> List[str]:
        seen, out = set(), []
        for x in items:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    @staticmethod
    def _split_kb_text(text: str) -> tuple:
        """把知识库文本拆成「根因」和「建议」两段（案例文本格式：诊断:xxx 处理建议:xxx）。"""
        cause, action = "", ""
        for cause_kw in ("诊断:", "诊断：", "问题:", "问题："):
            if cause_kw in text:
                cause = text.split(cause_kw, 1)[1]
                break
        else:
            cause = text
        for act_kw in ("处理建议:", "处理建议：", "解决方案:", "解决方案：", "建议处理："):
            if act_kw in text:
                action = text.split(act_kw, 1)[1]
                cause = cause.split(act_kw)[0]
                break
        return cause.strip()[:180], action.strip()[:180]


class QwenProvider(LLMProvider):
    """Qwen (DashScope) 实现 - 需要 DASHSCOPE_API_KEY 环境变量。"""

    def __init__(self):
        try:
            import dashscope  # noqa: F401
            self._client = dashscope
        except ImportError as e:
            raise ImportError(
                "dashscope 未安装。请运行: pip install dashscope"
            ) from e

    def generate_diagnosis(
        self,
        problem_type_hint: str,
        country: str,
        channel: str,
        evidence: List[EvidenceItem],
    ) -> dict:
        from dashscope import Generation

        prompt = self._build_prompt(problem_type_hint, country, channel, evidence)
        try:
            resp = Generation.call(
                model="qwen-turbo",
                prompt=prompt,
                result_format="message",
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Qwen 调用失败: {resp.message}")
            content = resp.output.choices[0].message.content
            return self._parse_json(content)
        except Exception as e:
            # 真实环境失败 → 降级 Mock
            print(f"[QwenProvider] 调用失败，降级 Mock: {e}")
            return MockLLMProvider().generate_diagnosis(
                problem_type_hint, country, channel, evidence
            )

    @staticmethod
    def _build_prompt(problem_type_hint, country, channel, evidence):
        evidence_lines = "\n".join(
            f"- [{e.type}] {e.id} | {e.description}" for e in evidence
        )

        # Day 14 P0-4：业务规则校验（Pix/iDEAL 等本地支付不需要 3DS）
        non_card_channels = MockLLMProvider.NON_CARD_CHANNELS
        card_only_rule = ""
        if channel in non_card_channels:
            card_only_rule = (
                f"\n⚠️ 业务约束：{channel} 是本地/钱包支付方式，"
                f"**不涉及 3DS 验证**。3DS 仅适用于信用卡类（Visa/MC/Amex/Discover/JCB）。"
                f"绝对不要推荐「3DS 验证」相关方案。"
            )

        # Day 14 P0-4：硬约束 —— 禁止编造
        # 真实证据 = risk_rule / channel_status / knowledge_base（Chroma 真实召回）
        has_real_evidence = any(
            e.type in ("risk_rule", "channel_status", "knowledge_base") for e in evidence
        )

        if not has_real_evidence:
            evidence_rule = (
                "\n⚠️ 当前证据链里**没有真实的风险规则、通道状态或知识库命中**（只有 config_snapshot 占位），"
                "**confidence 必须 ≤ 0.3**，root_causes 写「证据不足，建议补充错误码或联系 OP 客服」，"
                "不要硬填具体错误码。"
            )
        else:
            evidence_rule = (
                "\n✓ 证据链里有真实规则 / 知识库命中，请**完全基于这些文本**给出诊断（confidence 0.7-0.9）。"
            )

        return (
            f"你是 OP 跨境支付的支付诊断专家，正在直接回答商户的提问。\n"
            f"问题：{country} {channel} 渠道，问题类型={problem_type_hint}\n"
            f"\n## ⚠️ 重要约束（必须严格遵守）\n"
            f"1. **只基于下方【证据链】回答，禁止编造证据中不存在的规则、配置参数、API 名称、URL**\n"
            f"2. 证据里出现 example.com、<DEMO_xxx>、「Demo 占位」等字样 → 这是占位数据，**绝对不要写进答案**\n"
            f"3. 用大白话给商户看，不要技术黑话（如 `3DS_enabled = false` 写成「3DS 验证未开启」）\n"
            f"4. recommended_actions 必须可执行：谁做、做什么、需要什么材料\n"
            f"5. root_causes 每条 ≤ 60 字，recommended_actions 每条 ≤ 50 字"
            f"{card_only_rule}"
            f"{evidence_rule}\n"
            f"\n## 示例（照这个风格写）\n"
            f'输入证据：[knowledge_base] Visa 13.1 未收到货，数字商品高发。处理建议:启用 Visa RDR\n'
            f'输出：{{"root_causes": ["持卡人主张未收到数字商品，Visa 13.1 在软件/课程类目高发"], '
            f'"recommended_actions": ["准备交付凭证：登录日志、下载记录、激活时间", "开通 Visa RDR 提前拦截争议"], '
            f'"confidence": 0.85}}\n'
            f"\n## 证据链\n{evidence_lines}\n"
            f'\n请只输出 JSON：{{"root_causes": [...], "recommended_actions": [...], "confidence": 0.0-1.0}}'
        )

    @staticmethod
    def _parse_json(content: str) -> dict:
        # 尝试从 markdown code block 中提取
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            return json.loads(m.group(0))
        return json.loads(content)


def get_default_provider() -> LLMProvider:
    """工厂：优先 Qwen，无 key 自动 Mock。"""
    if os.getenv("DASHSCOPE_API_KEY"):
        try:
            return QwenProvider()
        except ImportError:
            pass
    return MockLLMProvider()