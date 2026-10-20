# -*- coding: utf-8 -*-
"""基金推荐生成不得在链路里逐只调 AI（JS-20261021-02）

【为什么要这条闸】
用户实测：在 AI 助手页面问「我买的那些基金最近都下跌有什么要关注，要不要调整？」，
回复显示「请求失败，请稍后重试」。抓接口复现：POST /api/chat 恰好 60.008s 返回 504 TIMEOUT。

逐段计时定位到真凶：
    构造 0.1s / setup 1.5s / fetch 0.1s / analyze 0.1s / generate 124.2s
`generate()` 里调了 `_enhance_with_ai()`，会对前 5 只基金**逐只串行**调一次 AI 写推荐语
（实测单次 17~32s），而 `ai_recommendation` 这个字段全仓**只有写入、没有任何读取方**——
124 秒换来一个没人用的字段。

叠加下游「总结 ~12s + 复核 ~47s」，整次问答 ~185s，必然撞上 60s 接口总闸。

【闸门含义】
`generate()` 是纯本地计算（排序 + 分级 + 拼理由 + 拼总结），不得发生任何 AI 调用。
若日后有人再把 AI 增强加回来，本测试立刻变红。
"""
import pytest

from domains.fund.domain import FundDomain


class _CountingAI:
    """假 AI 服务：只统计被调用次数，不做真实网络请求。"""

    is_available = True

    def __init__(self):
        self.calls = 0

    def analyze(self, *args, **kwargs):
        self.calls += 1
        return "AI 推荐语"


def _params(n=5):
    results = {}
    for i in range(n):
        code = "00000%d" % i
        results[code] = {
            "composite_score": {"总分": 60 + i, "等级": "B"},
            "nav_analysis": {
                "returns": {"年化收益率": 5.0 + i},
                "risk": {"最大回撤": -8.0},
                "risk_adjusted": {"夏普比率": 1.2},
            },
            "manager_evaluation": {"基金经理": "张三", "评级": "良好"},
            "holdings_analysis": {"风格倾向": "均衡"},
            "info": {"基金名称": "测试基金%d" % i, "基金类型": "混合型"},
        }
    return {"results": results}


def test_generate_makes_no_ai_calls():
    """generate() 必须全程本地计算，一次 AI 都不许调。"""
    domain = FundDomain()
    fake = _CountingAI()
    domain._ai_service = fake

    out = domain.generate(params=_params(5), top_n=10)

    assert out["status"] == "ok"
    assert out["recommended"] == 5
    assert fake.calls == 0, (
        "generate() 调用了 %d 次 AI。实测该环节逐只调 AI 让单次问答多花 124s，"
        "且 ai_recommendation 全仓无读取方，会直接把整次问答顶穿 60s 接口总闸。"
        % fake.calls
    )


def test_generate_output_has_no_dead_ai_field():
    """推荐项里不得再留 ai_recommendation 这种「只写不读」的字段。"""
    domain = FundDomain()
    out = domain.generate(params=_params(2), top_n=10)

    for pred in out["predictions"]:
        assert "ai_recommendation" not in pred, (
            "ai_recommendation 字段全仓无任何读取方，属死字段；"
            "留着它会诱使后来人再次接上逐只 AI 调用"
        )
