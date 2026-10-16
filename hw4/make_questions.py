# -*- coding: utf-8 -*-
"""Вопросы к своему корпусу data/corpus_ru.jsonl.

1. Двадцать своих вопросов fresh-125 … fresh-144 из ДЗ 1 (hw1/data/fresh_2026.jsonl): их цитаты есть в корпусе дословно.
2. Ещё вопросы, сгенерированные по строкам корпуса: Sonnet получает одну строку и пишет к ней вопрос
   с коротким ответом, который стоит в строке дословно. Строка становится evidence. Берём только страницы
   о событиях 2026 года: на страницах-отвлекающих (Эмми 2025, Венеция-82, Швеция 2022, биография Тачи)
   сильная модель знает ответы и без поиска, такие вопросы смазали бы главный замер.

3. Сгенерированные вопросы я прочитал глазами и отбраковал негодные (список DROP с причинами ниже).

Запуск: python make_questions.py   (нужен OPENROUTER_API_KEY в ../.env)
Сырые вопросы модели лежат в data/questions_generated_raw.jsonl: если файл есть, генерация не повторяется,
и DROP указывает на те же id.
Результат: data/questions_ru.jsonl
"""
import json, os, random, re, sys
from pathlib import Path
import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
load_dotenv(HERE.parent / ".env")
OWN = HERE.parent / "hw1" / "data" / "fresh_2026.jsonl"
SKIP_PAGES = {"Эмми (премия, 2025)", "82-й Венецианский кинофестиваль", "Парламентские выборы в Швеции (2022)", "Тачи, Хашим"}
PER_PAGE, SEED = 9, 7
RAW = DATA / "questions_generated_raw.jsonl"

DROP = {
    # строки документации шаблона, а не события (документацию потом вырезал из корпуса)
    "gen-1": "документация шаблона", "gen-3": "документация шаблона", "gen-4": "документация шаблона",
    "gen-6": "документация шаблона",
    # навигация и легенда сокращений турнирной сетки: проверяет вёрстку, а не факты
    **{f"gen-{n}": "навигация «основная статья»" for n in (46, 52, 53, 54)},
    **{f"gen-{n}": "легенда сокращений сетки" for n in (56, 57, 61, 62, 63, 65, 66, 67, 68, 69, 72)},
    "gen-60": "строка про 2025 год, вопрос запутан",
    # повторяют свои вопросы fresh-130 и fresh-138
    "gen-10": "дубль fresh-138", "gen-113": "дубль fresh-130", "gen-119": "дубль fresh-130",
    "gen-29": "дубль gen-22",
    # двусмысленные: два разных верных ответа или нет контекста
    "gen-79": "приз за сценарий дан двум фильмам, эталон неоднозначен", "gen-81": "то же, что gen-79",
    "gen-2": "нет года олимпиады", "gen-5": "нет года олимпиады", "gen-26": "нет контекста («экземпляр»)",
    "gen-7": "размытый ответ «сотни человек»", "gen-82": "размытый вопрос", "gen-99": "размытый вопрос",
    "gen-101": "размытый ответ «пол века»", "gen-28": "вопрос-шутка",
    "gen-129": "Мельбурн известен без поиска, вопрос не про свежий факт",
}

PROMPT = """Ниже одна строка из русской Википедии, страница «{page}», раздел «{section}».

{line}

Составь по этой строке один вопрос на русском языке для проверки системы поиска.
Требования:
- вопрос самодостаточный: из него понятно, о каком событии речь (название, год, место), без слов «в этой строке»;
- ответ короткий (1-5 слов: имя, число, название, дата) и стоит в строке ДОСЛОВНО, символ в символ;
- в вопросе нет самого ответа;
- если строка — обрывок таблицы, перечень без смысла или в ней нет проверяемого факта, верни {{"skip": true}}.
Верни только JSON: {{"question": "...", "answer": "..."}}"""


def norm(t):
    return " ".join(re.sub(r"[^\w\s]", " ", str(t).lower()).split())


def lines_of(page):
    section = ""
    for line in page["text"].splitlines():
        if line.startswith("=="):
            section = line.strip("= ")
        elif 80 <= len(line) <= 600 and line.count("|") < 3:
            yield section, line


def ask(prompt):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=120,
                      headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                      json={"model": "anthropic/claude-sonnet-4.6", "temperature": 0, "usage": {"include": True},
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    data = r.json()
    m = re.search(r"\{.*\}", data["choices"][0]["message"]["content"], re.S)
    return (json.loads(m.group(0)) if m else {"skip": True}), data.get("usage", {}).get("cost", 0.0)

def generate(corpus, own_evidence):
    out, rng, spent = [], random.Random(SEED), 0.0
    for page in corpus:
        if page["page"] in SKIP_PAGES:
            continue
        pool = [(s, l) for s, l in lines_of(page) if norm(l) not in own_evidence]
        rng.shuffle(pool)
        taken = 0
        for section, line in pool:
            if taken == PER_PAGE:
                break
            q, cost = ask(PROMPT.format(page=page["page"], section=section, line=line))
            spent += cost
            answer = str(q.get("answer", "")).strip()
            if q.get("skip") or not answer or answer not in line or norm(answer) in norm(q.get("question", "")):
                continue
            out.append({"id": f"gen-{len(out)}", "source": "generated", "question": q["question"], "answer": answer,
                        "evidence": line, "page": page["page"], "url": page["url"], "agent_ok": None})
            taken += 1
        print(f"{page['page']:50s} вопросов {taken}")
    with RAW.open("w", encoding="utf-8") as f:
        for t in out:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"\nсгенерировано вопросов: {len(out)}, потрачено ${spent:.3f}")


if __name__ == "__main__":
    corpus = [json.loads(l) for l in (DATA / "corpus_ru.jsonl").read_text(encoding="utf-8").splitlines()]
    texts = {c["page"]: norm(c["text"]) for c in corpus}
    own = []
    for t in map(json.loads, OWN.read_text(encoding="utf-8").splitlines()):
        if int(t["id"].split("-")[1]) >= 125:
            assert norm(t["evidence"]) in texts[t["page"]], t["id"]
            own.append({"id": t["id"], "source": "own", "question": t["question"], "answer": t["answer"],
                        "evidence": t["evidence"], "page": t["page"], "url": t["url"], "agent_ok": bool(t.get("agent_ok"))})
    if not RAW.exists():
        generate(corpus, {norm(t["evidence"]) for t in own})
    raw = [json.loads(l) for l in RAW.read_text(encoding="utf-8").splitlines()]
    dropped = [t for t in raw if t["id"] in DROP]
    # после чистки корпуса цитата должна в нём остаться
    kept = [t for t in raw if t["id"] not in DROP and norm(t["evidence"]) in texts.get(t["page"], "")]
    with (DATA / "questions_ru.jsonl").open("w", encoding="utf-8") as f:
        for t in own + kept:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"вопросов: {len(own) + len(kept)} (своих {len(own)}, сгенерированных {len(kept)} из {len(raw)}: "
          f"отбраковано {len(dropped)}, цитата пропала из корпуса {len(raw) - len(kept) - len(dropped)})")
