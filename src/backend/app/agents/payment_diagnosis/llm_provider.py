"""LLM Provider 抽象层 - 优先 Qwen，无 key 自动降级 Mock。

对接策略：
- 有 DASHSCOPE_API_KEY 环境变量 → 调用 Qwen (DashScope)
- 否则 → 使用基于规则的 Mock LLM（保证 Demo 始终能跑）
"""

import json
import os
import re
from typing import List, Optional

from .schemas import EvidenceItem


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
    """基于规则的 Mock LLM - 保证无 key 时 Demo 也能跑。"""

    def generate_diagnosis(
        self,
        problem_type_hint: str,
        country: str,
        channel: str,
        evidence: List[EvidenceItem],
    ) -> dict:
        # 规则 1: 看 evidence 中是否含 3DS 配置缺失
        has_3ds_issue = any("3DS" in (e.description or "") for e in evidence)

        # 规则 2: 看通道是否 degraded/down
        channel_degraded = any(
            "degraded" in (e.description or "") or "down" in (e.description or "")
            for e in evidence
            if e.type == "channel_status"
        )

        root_causes = []
        if has_3ds_issue:
            root_causes.append(
                f"{country} {channel} 渠道 3DS 认证配置问题（按当地合规要求可能强制，具体由 OP 规则决定）"
            )
        if channel_degraded:
            root_causes.append(f"{country} {channel} 通道当前处于 degraded/down 状态")
        if not root_causes and evidence:
            first = evidence[0]
            root_causes.append(f"主要受 {first.type} 影响（{first.id}）")
        if not root_causes:
            root_causes.append("未匹配到 Demo 数据集中的已知规则（真实环境需 OP 规则表支持）")

        # 推荐动作
        actions = []
        if has_3ds_issue:
            actions.append(f"1. 检查 {country} 区域 3DS 配置（Merchant Console → 风控设置）")
        if channel_degraded:
            actions.append(f"2. 切换备用通道或等待 {channel} 通道恢复")
        if not actions:
            actions.append("1. 参考 evidence_chain 中的规则 ID 联系对应团队")
        actions.append("2. 风控团队复核相关规则（具体规则 ID 见 evidence_chain）")

        # 置信度：evidence 越多越高
        confidence = min(0.95, 0.55 + 0.15 * len(evidence))

        return {
            "root_causes": root_causes,
            "recommended_actions": actions,
            "confidence": round(confidence, 2),
        }


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
            f"- {e.type}: {e.id} | {e.description}" for e in evidence
        )
        return (
            f"你是 OP 跨境支付的支付诊断专家。\n"
            f"问题：{country} {channel} 渠道，问题类型={problem_type_hint}\n"
            f"证据链：\n{evidence_lines}\n\n"
            f"请输出 JSON：{{'root_causes': [...], 'recommended_actions': [...], 'confidence': 0.0-1.0}}"
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