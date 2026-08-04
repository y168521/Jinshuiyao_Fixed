# -*- coding: utf-8 -*-
"""金水谣 · 免费模型自动同步工具 (sync_free_models.py)

核心理念（用户约定）：不需要高级推理的任务（自动任务/审查/闲聊）优先免费模型，
实在不行才退而求其次用付费。硅基流动免费模型多，应自动精准匹配质量高的。

功能：
  1. 调用硅基流动 /v1/models 拉取全部可用模型清单
  2. 对候选 LLM 逐个发极轻探活请求（max_tokens=5），剔除不可用/超时/无 key
  3. 内置质量评分表（按模型家族/参数量/实测审查能力），自动排序写入 config/free_models.json
  4. 保留人工 enabled/priority 覆盖（手动配置优先于自动排序）
  5. 探活结果写入 金水谣数据/free_model_status.json（健康闭环复用）

用法：
  py -3.14 tools/sync_free_models.py            # 全量同步（建议每月/换模型时手动跑）
  py -3.14 tools/sync_free_models.py --dry-run  # 只打印候选不写文件
  py -3.14 tools/sync_free_models.py --keep     # 保留现有配置中的手动条目(默认覆盖)
  py -3.14 tools/sync_free_models.py --include-all  # 全量纳入所有探活成功的模型(不推荐, 会把付费当免费)

安全：探活只发 5 token 的极小请求，不产生实质费用；只写 config/ 与 金水谣数据/ 非 git 敏感区。
"""

import os
import sys
import json
import time
import urllib.request

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG = os.path.join(_BASE, "config", "free_models.json")
_STATUS = os.path.join(_BASE, "金水谣数据", "free_model_status.json")
_SECRET_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")

# ── 质量评分表（0-100）：按模型家族 + 参数量 + 已知审查/推理能力 ──
# 实测校准（2026-08-04）：GLM-4-32B-0414 检出4条含注入P0 > GLM-4.5-Air 3条 > R1-8B 4条偏保守
# > GLM-4-9B-0414 3条 > Qwen2.5-7B 弱
_QUALITY_TABLE = [
    # (前缀匹配, 质量分)
    ("THUDM/GLM-4-32B", 95),
    ("zai-org/GLM-4.5-Air", 92),
    ("zai-org/GLM-5", 96),
    ("THUDM/GLM-Z1-32B", 94),
    ("deepseek-ai/DeepSeek-R1-0528", 80),
    ("deepseek-ai/DeepSeek-V3", 90),
    ("deepseek-ai/DeepSeek-V4", 93),
    ("Qwen/Qwen3.5-30B", 88),
    ("Qwen/Qwen3.5-32B", 88),
    ("Qwen/Qwen3.5-27B", 85),
    ("Qwen/Qwen3.5-14B", 82),
    ("Qwen/Qwen3.5-9B", 78),
    ("Qwen/Qwen3.5-4B", 70),
    ("Qwen/Qwen2.5-7B", 60),
    ("Qwen/Qwen2.5-72B", 89),
    ("THUDM/GLM-4-9B", 75),
    ("THUDM/GLM-Z1-9B", 76),
    ("tencent/Hunyuan-A13B", 77),
    ("moonshotai/Kimi-K2.7", 91),
    ("stepfun-ai/Step-3.5-Flash", 79),
    ("inclusionAI/Ling-flash-2.0", 72),
    ("inclusionAI/Ling-mini-2.0", 62),
]

_JSON_MODE_SUPPORT = {
    "THUDM/GLM-4-32B-0414": True,
    "THUDM/GLM-4-9B-0414": True,
    "zai-org/GLM-4.5-Air": False,   # 实测 400
    "Qwen/Qwen2.5-7B-Instruct": True,
}

# ── 免费/低费用额度白名单 ──
# 硅基流动对开源模型普遍提供免费额度(每月限量)；旗舰付费模型(GLM-5.2/V4-Pro/Kimi-K2.7等)不进入免费池。
# 只同步这些家族；--include-all 时才全量纳入（不推荐，会把付费模型当免费用）。
_FREE_HINT_PREFIXES = (
    "THUDM/GLM-4-", "THUDM/GLM-Z1-", "zai-org/GLM-4.5", "zai-org/GLM-4.7",
    "deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1-0528",
    "Qwen/Qwen2.5-", "Qwen/Qwen3-", "Qwen/Qwen3.5-", "Qwen/Qwen3.6-",
    "tencent/Hunyuan-A13B", "tencent/Hunyuan-MT",
    "inclusionAI/Ling-", "stepfun-ai/Step-3.5-Flash",
    "moonshotai/Kimi-K2.7-Code", "meituan-longcat/LongCat-",
)

# 非 LLM 模型（图像/视频/语音/嵌入/重排）直接跳过
_NON_LLM_HINTS = ("Image", "VL-", "Embedding", "Reranker", "ASR", "T2V", "I2V",
                  "OCR", "Whisper", "Text2Audio", "TTS", "SD-", "FLUX")


def _read_secret(fname):
    p = os.path.join(_SECRET_DIR, fname)
    try:
        if os.path.isfile(p):
            return open(p, "r").read().strip()
    except Exception:
        pass
    return ""


def _quality(mid):
    for prefix, q in _QUALITY_TABLE:
        if mid.startswith(prefix):
            return q
    return 40


def _is_llm(mid):
    low = mid
    return not any(h in low for h in _NON_LLM_HINTS)


def _in_free_hint(mid):
    return any(mid.startswith(p) for p in _FREE_HINT_PREFIXES)


def _probe(mid, api_key, base_url, json_mode, timeout=20):
    """极轻探活：max_tokens=5 的 pong 请求。返回 (ok, err)"""
    body = {
        "model": mid,
        "messages": [{"role": "user", "content": "pong"}],
        "max_tokens": 5,
        "temperature": 0.1,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    payload = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        req = urllib.request.Request(base_url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, ""
    except Exception as e:
        return False, str(e)[:100]


def _load_existing():
    try:
        with open(_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(cfg):
    os.makedirs(os.path.dirname(_CONFIG), exist_ok=True)
    with open(_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def main():
    dry_run = "--dry-run" in sys.argv
    keep_manual = "--keep" in sys.argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    old_cfg = _load_existing()
    old_models = {}
    for prov, pdata in old_cfg.get("providers", {}).items():
        for m in pdata.get("models", []):
            old_models[m.get("id")] = m

    key = _read_secret("siliconflow_key.txt")
    if not key:
        print("[sync_free_models] 无硅基流动密钥(~/.jinshuiyao-secrets/siliconflow_key.txt)，退出")
        return 1

    # 1) 拉模型清单
    try:
        req = urllib.request.Request(
            "https://api.siliconflow.cn/v1/models",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[sync_free_models] 拉取模型清单失败: {e}")
        return 1
    all_ids = sorted({m.get("id", "") for m in data.get("data", []) if m.get("id")})
    llm_ids = [i for i in all_ids if _is_llm(i)]
    include_all = "--include-all" in sys.argv
    if not include_all:
        keep = [i for i in llm_ids if _in_free_hint(i)]
        print(f"[sync_free_models] 平台共 {len(all_ids)} 个模型，LLM 候选 {len(llm_ids)} 个，免费额度白名单 {len(keep)} 个"
              + "（--include-all 可全量，不推荐）")
        llm_ids = keep
    else:
        print(f"[sync_free_models] 平台共 {len(all_ids)} 个模型，LLM 候选 {len(llm_ids)} 个（--include-all 全量）")

    # 2) 逐个探活（只探前 25 个质量最高的，控制耗时）
    llm_ids.sort(key=_quality, reverse=True)
    live = []
    for i, mid in enumerate(llm_ids[:25]):
        q = _quality(mid)
        jm = _JSON_MODE_SUPPORT.get(mid, True)
        ok, err = _probe(mid, key, "https://api.siliconflow.cn/v1/chat/completions", jm)
        tag = "OK " if ok else "ERR"
        print(f"  [{tag}] q={q:3d} {mid}" + ("" if ok else f" ({err})"))
        if ok:
            live.append((q, mid))
        time.sleep(0.5)

    if not live:
        print("[sync_free_models] 无可用免费模型，保留现有配置")
        return 0
    live.sort(key=lambda x: -x[0])

    # 3) 生成新配置（保留旧条目手动覆盖字段）
    models = []
    for idx, (q, mid) in enumerate(live, start=1):
        old = old_models.get(mid, {})
        models.append({
            "id": mid,
            "priority": old.get("priority", idx),
            "quality": old.get("quality", q),
            "json_mode": old.get("json_mode", _JSON_MODE_SUPPORT.get(mid, True)),
            "enabled": old.get("enabled", True),
            "note": old.get("note", f"自动发现({time.strftime('%Y-%m-%d')}) quality={q}"),
        })
    # 保留手动配置但探活失败的（--keep 时）
    if keep_manual:
        live_ids = {m["id"] for m in models}
        for mid, m in old_models.items():
            if mid not in live_ids and m.get("enabled", False):
                models.append(m)
                print(f"  [KEEP] {mid} (手动条目，探活未验证)")
        models.sort(key=lambda x: x.get("priority", 99))

    cfg = {
        "_说明": old_cfg.get("_说明", "免费模型池配置（tools/sync_free_models.py 自动同步）"),
        "providers": {
            "siliconflow": {
                "base_url": old_cfg.get("providers", {}).get("siliconflow", {}).get(
                    "base_url", "https://api.siliconflow.cn/v1/chat/completions"),
                "api_key_file": "siliconflow_key.txt",
                "json_mode": True,
                "models": models,
            }
        },
        "fallback": old_cfg.get("fallback", {
            "provider": "deepseek",
            "api_key_file": "deepseek_key.txt",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model_env": "DEEPSEEK_MODEL",
            "default_model": "deepseek-v4-pro",
        }),
        "health_check": old_cfg.get("health_check", {
            "enabled": True, "interval_minutes": 60,
            "timeout_seconds": 15, "probe_prompt": "ping",
            "max_failures_before_down": 2,
        }),
        "notify": old_cfg.get("notify", {
            "on_all_free_down": True, "channel": "log",
            "status_file": "金水谣数据/free_model_status.json",
        }),
    }

    if dry_run:
        print(f"\n[dry-run] 将写入 {len(models)} 个模型（未实际保存）:")
        for m in models:
            print(f"  p={m['priority']:2d} q={m['quality']:3d} {m['id']}")
        return 0

    _save(cfg)
    print(f"\n[sync_free_models] 已更新 {_CONFIG}: {len(models)} 个模型，按质量排序")
    return 0


if __name__ == "__main__":
    sys.exit(main())
