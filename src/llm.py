"""
llm.py : LLM 接口（可配置）
================================
- 有 OPENAI_API_KEY 时走真实 OpenAI；否则用 MockLLM。
- MockLLM 不是"瞎编"，而是基于本周真实聚合数据生成有依据的复盘报告，
  保证无 key 也能跑通 demo（求职作品集可在本机直接演示）。
"""
from typing import Optional


class LLMClient:
    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class MockLLM(LLMClient):
    """用真实计算指标填充 RACAE 模板，输出可被 eval 解析的结构化报告。"""
    def complete(self, prompt: str) -> str:
        # weekly_review 会把 agg 以 <<REPORT>> 标记注入 prompt 末尾
        if "<<REPORT>>" in prompt:
            return prompt.split("<<REPORT>>", 1)[1].strip()
        return "(mock) 报告生成失败：缺少聚合数据。"


class OpenAILLM(LLMClient):
    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        import os
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = model

    def complete(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""


def get_llm() -> LLMClient:
    import os
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAILLM()
        except Exception:
            pass
    return MockLLM()
