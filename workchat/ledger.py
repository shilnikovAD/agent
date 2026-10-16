"""Журнал вызовов и потолки денег.

Каждый вызов модели и инструмента пишется строкой в runs/calls-ГГГГММДД.jsonl: модель, токены (в том числе из кэша),
цена, вызванные инструменты. Траты за день копятся в runs/spend.json. Потолки проверяются кодом до вызова модели.
"""
import json
import threading
import time
from dataclasses import dataclass, field

from workchat import config


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class TaskMeter:
    """Счётчик одной задачи (одного входящего сообщения)."""
    task_id: str
    cap_usd: float = config.MAX_USD_PER_TASK
    cost: float = 0.0
    calls: int = 0
    prompt: int = 0
    cached: int = 0
    completion: int = 0
    tools: list = field(default_factory=list)


class Ledger:
    def __init__(self, day_cap: float = config.MAX_USD_PER_DAY):
        self.lock = threading.Lock()
        self.day_cap = day_cap
        self.spend_file = config.RUNS / "spend.json"

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d")

    def spent_today(self) -> float:
        if not self.spend_file.exists():
            return 0.0
        return json.loads(self.spend_file.read_text(encoding="utf-8")).get(self._day(), 0.0)

    def check(self, meter: TaskMeter):
        if meter.cost >= meter.cap_usd:
            raise BudgetExceeded(f"потолок на задачу {meter.cap_usd}$ исчерпан ({meter.cost:.4f}$)")
        if self.spent_today() >= self.day_cap:
            raise BudgetExceeded(f"дневной потолок {self.day_cap}$ исчерпан")

    def record(self, meter: TaskMeter, **row):
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "task": meter.task_id, **row}
        with self.lock:
            if row.get("kind") == "llm":
                meter.cost += row["cost"]
                meter.calls += 1
                meter.prompt += row["prompt"]
                meter.cached += row["cached"]
                meter.completion += row["completion"]
                spend = json.loads(self.spend_file.read_text(encoding="utf-8")) if self.spend_file.exists() else {}
                spend[self._day()] = round(spend.get(self._day(), 0.0) + row["cost"], 6)
                self.spend_file.write_text(json.dumps(spend, indent=1), encoding="utf-8")
            else:
                meter.tools.append(row.get("tool"))
            with (config.RUNS / f"calls-{time.strftime('%Y%m%d')}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
