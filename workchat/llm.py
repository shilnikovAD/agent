"""Вызов модели через OpenRouter с кэшем промпта и записью в журнал.

Кэш: начало запроса (инструменты и системный промпт) одинаково для всех сообщений. У Claude это начало помечается
cache_control, у OpenAI кэш включается сам от 1024 токенов. cache=False ставит в начало системного промпта уникальную
метку, и кэш не срабатывает ни у кого: так меряется цена «до».
"""
import time
import uuid

import requests

from workchat import config
from workchat.ledger import Ledger, TaskMeter

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


def build_body(messages, model, tools=None, cache=True, max_tokens=700):
    messages = [dict(m) for m in messages]
    system = messages[0]
    if not cache:
        system["content"] = f"[run {uuid.uuid4().hex}]\n" + system["content"]
    elif model.startswith("anthropic/"):
        system["content"] = [{"type": "text", "text": system["content"], "cache_control": {"type": "ephemeral"}}]
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens, "usage": {"include": True}}
    if tools:
        body["tools"] = tools
    return body


def chat(messages, model, meter: TaskMeter, ledger: Ledger, tools=None, cache=True, tag="chat"):
    ledger.check(meter)
    body = build_body(messages, model, tools, cache)
    started, problem = time.perf_counter(), "нет ответа"
    for attempt in range(5):
        try:
            r = requests.post(config.OPENROUTER_URL, json=body, timeout=120,
                              headers={"Authorization": f"Bearer {config.api_key()}", "X-Title": "workchat-agent"})
            if r.status_code == 200 and "choices" in r.json():
                data = r.json()
                break
            problem = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code not in RETRY_STATUS:
                raise RuntimeError(problem)
        except requests.RequestException as e:
            problem = type(e).__name__
        time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(problem)
    usage = data.get("usage") or {}
    msg = data["choices"][0]["message"]
    details = usage.get("prompt_tokens_details") or {}
    ledger.record(meter, kind="llm", tag=tag, model=model.split("/")[-1], prompt=usage.get("prompt_tokens", 0),
                  cached=details.get("cached_tokens", 0) or 0, cache_write=details.get("cache_write_tokens", 0) or 0,
                  completion=usage.get("completion_tokens", 0), cost=usage.get("cost") or 0.0,
                  seconds=round(time.perf_counter() - started, 2),
                  tool_calls=[c["function"]["name"] for c in msg.get("tool_calls") or []])
    return msg
