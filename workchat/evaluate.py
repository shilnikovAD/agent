"""Прогон набора задач на нескольких конфигурациях и таблица: доля верных, вызовы, токены, кэш, центы, задержка.

Проверка ответа кодом, без судьи-модели:
  1) действие совпало с ожидаемым (auto / draft / ignore);
  2) в ответе есть хотя бы одна подстрока из каждой группы must (сравнение по основам слов);
  3) в ответе нет ни одной подстроки из must_not.
Подробности каждого ответа — в runs/eval/<конфигурация>.jsonl.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from workchat import config
from workchat.agent import AgentConfig, handle
from workchat.ledger import Ledger
from workchat.mcp_tools import KB

CONFIGS = {
    "strong": AgentConfig("Sonnet в одиночку (без хуков)", config.MODELS["strong"], hooks=False),
    "best": AgentConfig("mini + хуки", config.MODELS["cheap"], hooks=True),
    "nohooks": AgentConfig("mini без хуков", config.MODELS["cheap"], hooks=False),
    "haiku": AgentConfig("Haiku + хуки", config.MODELS["mid"], hooks=True),
    "best_nocache": AgentConfig("mini + хуки, кэш выключен", config.MODELS["cheap"], hooks=True, cache=False),
    "best_notrim": AgentConfig("mini + хуки, без сжатия контекста", config.MODELS["cheap"], hooks=True, trim=False),
    "haiku_nocache": AgentConfig("Haiku + хуки, кэш выключен", config.MODELS["mid"], hooks=True, cache=False),
}

ENDINGS = re.compile(r"(ому|ему|ого|его|ыми|ими|ая|яя|ое|ее|ые|ие|ый|ий|ой|ом|ем|ам|ям|ах|ях|ов|ев|ей|ую|юю|а|я|о|е|ы|и|у|ю|ь)$")


def norm(text: str) -> str:
    return " ".join(re.findall(r"[\w./:@-]+", (text or "").lower().replace("ё", "е")))


def stem(word: str) -> str:
    base = ENDINGS.sub("", word)
    return base if len(base) >= 3 else word


def contains(reply: str, needle: str) -> bool:
    got, want = norm(reply), norm(needle)
    if want in got:
        return True
    words = got.split()
    return all(any(w.startswith(stem(g)) for w in words) for g in want.split()) if re.search(r"[а-я]", want) else False


def check(task: dict, action: str, reply: str) -> list[str]:
    problems = []
    if action != task["expect"]:
        problems.append(f"действие {action}, ждали {task['expect']}")
    if action != "ignore":
        for group in task.get("must", []):
            if not any(contains(reply, s) for s in group):
                problems.append(f"нет «{' / '.join(group)}»")
    for s in task.get("must_not", []):
        if norm(s) in norm(reply):
            problems.append(f"есть запрещённое «{s}»")
    return problems


def load_tasks():
    return [json.loads(l) for l in (config.ROOT / "tasks" / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def run(cfg: AgentConfig, tasks, kb, ledger, workers=4):
    def one(task):
        d = handle(task, cfg, kb, ledger, task_id=f"{cfg.name}:{task['id']}")
        problems = check(task, d.action, d.reply)
        m = d.meter
        return {"id": task["id"], "kind": task["kind"], "expect": task["expect"], "action": d.action, "ok": not problems,
                "problems": problems, "reply": d.reply, "reason": d.reason, "flags": d.flags, "calls": m.calls,
                "prompt": m.prompt, "cached": m.cached, "completion": m.completion, "cost": m.cost, "seconds": round(d.seconds, 2),
                "tools": m.tools}
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(one, tasks))
    out = config.RUNS / "eval"
    out.mkdir(exist_ok=True)
    (out / f"{cfg.name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return rows


def summary(name, rows):
    n, ok = len(rows), sum(r["ok"] for r in rows)
    cost, prompt = sum(r["cost"] for r in rows), sum(r["prompt"] for r in rows)
    return {"конфигурация": name, "верно": f"{ok}/{n}", "доля": round(ok / n, 3),
            "вызовов на задачу": round(sum(r["calls"] for r in rows) / n, 2),
            "токенов на задачу": round((prompt + sum(r["completion"] for r in rows)) / n),
            "доля входа из кэша": round(sum(r["cached"] for r in rows) / prompt, 2) if prompt else 0.0,
            "центов на задачу": round(cost / n * 100, 4), "центов за верный": round(cost / ok * 100, 4) if ok else None,
            "задержка, с": round(sum(r["seconds"] for r in rows) / n, 2)}


def md_table(rows):
    cols = list(rows[0])
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
                     + ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows])


def main(names, limit=None, workers=4):
    tasks = load_tasks()[:limit] if limit else load_tasks()
    kb, ledger = KB(), Ledger()
    if kb.mismatched:
        raise SystemExit(f"описания инструментов MCP не совпали с отпечатками: {kb.mismatched}. Проверьте сервер, "
                         f"затем python -m workchat pins, если изменение ожидаемое")
    table = []
    try:
        for name in names:
            started = time.perf_counter()
            rows = run(CONFIGS[name], tasks, kb, ledger, workers)
            table.append(summary(CONFIGS[name].name, rows))
            print(f"{CONFIGS[name].name}: {table[-1]['верно']} за {time.perf_counter() - started:.0f} с", flush=True)
    finally:
        kb.close()
    text = md_table(table)
    (config.RUNS / "eval" / f"table-{time.strftime('%Y%m%d-%H%M%S')}.md").write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    print(f"\nпотрачено сегодня: ${ledger.spent_today():.4f}")
    return table
