"""Налог MCP в токенах: сколько входных токенов добавляют описания инструментов сервера к каждому вызову модели.

Один и тот же короткий запрос отправляется без инструментов и с инструментами роли; разница prompt_tokens — налог.
Результат в runs/mcp_tax.json.
"""
import json

from workchat import config
from workchat.ledger import Ledger, TaskMeter
from workchat.llm import chat
from workchat.mcp_tools import KB, ROLE_TOOLS


def main():
    kb, ledger = KB(), Ledger()
    probe = [{"role": "system", "content": "Reply with OK."}, {"role": "user", "content": "ping"}]
    rows = []
    try:
        for model in (config.MODELS["cheap"], config.MODELS["strong"]):
            meter = TaskMeter("tax")
            chat(probe, model, meter, ledger, cache=False, tag="tax")
            base = meter.prompt
            for role in ROLE_TOOLS:
                tools = kb.schemas(role)
                if not tools:
                    rows.append({"model": model, "role": role, "tools": [], "tax_tokens": 0})
                    continue
                m = TaskMeter("tax")
                chat(probe, model, m, ledger, tools=tools, cache=False, tag="tax")
                rows.append({"model": model, "role": role, "tools": kb.allowed(role), "tax_tokens": m.prompt - base})
    finally:
        kb.close()
    (config.RUNS / "mcp_tax.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['model']:32s} {r['role']:10s} {', '.join(r['tools']) or '—':35s} +{r['tax_tokens']} токенов на вызов")
