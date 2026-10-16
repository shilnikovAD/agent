# -*- coding: utf-8 -*-
"""Свой корпус для RAG: русская Википедия о событиях сентября 2026 года.

Источники — те, откуда взяты свои вопросы fresh-125 … fresh-144 из ДЗ 1:
  * конкретные правки (oldid) ленты «Портал:Текущие события/Последние события»
    и новостей заглавной страницы — в них цитаты-эталоны есть дословно;
  * тематические статьи про те же события (Эмми, Венеция, US Open, Тачи …);
  * хроники месяцев и обзор «2026 год»;
  * статьи-отвлекающие про прошлые годы тех же событий (Эмми 2025, Венеция-82,
    выборы в Швеции 2022), чтобы поиску было из чего ошибаться.

Запуск: python fetch_corpus_ru.py
Результат: data/corpus_ru.jsonl (страница, ссылка, текст).
"""
import html, json, re, sys, time
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
WIKI = "https://ru.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "agents-course-hw4/1.0 (educational project)"}

# правки, на которые ссылаются вопросы fresh-125 … fresh-144
REVISIONS = {
    "Шаблон:Текущие события на заглавной странице": [155327431, 155341644, 155352400, 155360992, 155428903],
    "Портал:Текущие события/Последние события": [155197160, 155216666, 155284195, 155289332],
}
ARTICLES = [
    # события своих вопросов
    "Эмми (премия, 2026)", "Тачи, Хашим", "Leopardus tilcayo", "Парламентские выборы в Швеции (2026)",
    "Чемпионат мира по баскетболу среди женщин 2026", "Открытый чемпионат США по теннису 2026",
    "Открытый чемпионат США по теннису 2026 в мужском одиночном разряде",
    "Открытый чемпионат США по теннису 2026 в женском одиночном разряде", "83-й Венецианский кинофестиваль",
    # хроники и обзоры
    "Август 2026 года", "Сентябрь 2026 года", "Октябрь 2026 года", "2026 год", "2026 год в науке", "2026 год в спорте",
    # отвлекающие: те же события в прошлые годы
    "Эмми (премия, 2025)", "82-й Венецианский кинофестиваль", "Парламентские выборы в Швеции (2022)",
]


def api(params, attempts=6):
    for attempt in range(attempts):
        wait = 10 * (attempt + 1)
        try:
            r = requests.get(WIKI, timeout=40, headers=HEADERS, params={**params, "format": "json", "formatversion": 2})
            if r.status_code == 200:
                return r.json()
            # на частые запросы Википедия отвечает 429 и сама говорит, сколько ждать
            wait = max(wait, int(r.headers.get("Retry-After", 0) or 0))
        except requests.RequestException:
            pass
        time.sleep(wait)
    raise RuntimeError(f"Википедия не ответила: {params}")


def article(title):
    # parse, а не extracts: в выдержке пропадают таблицы и списки, а в них половина фактов
    page = api({"action": "parse", "page": title, "prop": "text", "redirects": 1})["parse"]
    return page["title"], html_to_text(page["text"])


def html_to_text(markup):
    """HTML правки -> строки текста; заголовки разделов в виде '== … ==', как в explaintext."""
    markup = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    markup = re.sub(r'<sup[^>]*class="[^"]*reference[^"]*"[^>]*>.*?</sup>', "", markup, flags=re.S)
    markup = re.sub(r"<h([2-4])[^>]*>(.*?)</h\1>", lambda m: "\n== " + m.group(2) + " ==\n", markup, flags=re.S)
    markup = re.sub(r"</t[dh]>", " | ", markup)
    markup = re.sub(r"</?(li|p|br|div|tr|dd|dt|ul|ol|table)[^>]*>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    # «[править]» и пометки шаблона нп5 вроде «[англ.]» рвут цитаты посередине
    text = re.sub(r"\[править[^\]]*\]|\[[а-яё]{2,5}\.\]", "", text)
    text = "\n".join(" ".join(line.split()).strip(" |") for line in text.splitlines())
    # служебный хвост статьи поиску не нужен
    text = re.split(r"\n== (?:Примечания|Ссылки|Литература|См\. также) ==", text)[0]
    return tidy(text)


def tidy(text):
    """Таблицы разваливаются на клетки по строке: склеиваем короткие обрывки с соседями в одну строку."""
    out, buf = [], []
    for line in text.splitlines():
        if not line or line.startswith("=="):
            if buf: out.append(" ".join(buf)); buf = []
            if line: out.append(line)
        elif len(line) < 40:
            buf.append(line)
        else:
            if buf: out.append(" ".join(buf)); buf = []
            out.append(line)
    if buf: out.append(" ".join(buf))
    return "\n".join(out)


def revision(oldid):
    text = html_to_text(api({"action": "parse", "oldid": oldid, "prop": "text"})["parse"]["text"])
    # у шаблона под новостями идёт документация с правилами проекта, к событиям она отношения не имеет
    return text.split("\nДокументация\n")[0]


if __name__ == "__main__":
    corpus = []
    for title, oldids in REVISIONS.items():
        # правки одной ленты сильно пересекаются: склеиваем их в один документ без повторов строк
        # заголовок даты пишем, только если под ним в этой правке есть хоть одна новая строка
        lines, seen = [], set()
        for oldid in oldids:
            heading = None
            for line in revision(oldid).splitlines():
                if line.startswith("=="):
                    heading = line
                elif line and line not in seen:
                    if heading and heading not in lines[-5:]:
                        lines.append(heading)
                    seen.add(line); lines.append(line)
            time.sleep(1.5)
        text = "\n".join(lines)
        url = "https://ru.wikipedia.org/w/index.php?oldid=" + ",".join(map(str, oldids))
        corpus.append({"page": title, "url": url, "text": text})
        print(f"{title:50s} {len(text):8d} символов, правок {len(oldids)}")
    for title in ARTICLES:
        real, text = article(title)
        if text:
            corpus.append({"page": real, "url": "https://ru.wikipedia.org/wiki/" + real.replace(" ", "_"), "text": text})
        print(f"{real:50s} {len(text):8d} символов")
        time.sleep(1.5)
    with (DATA / "corpus_ru.jsonl").open("w", encoding="utf-8") as f:
        for c in corpus:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    lines = sum(len([l for l in c["text"].splitlines() if len(l.strip()) > 40]) for c in corpus)
    print(f"\nстраниц: {len(corpus)}, символов: {sum(len(c['text']) for c in corpus)}, содержательных строк: {lines}")
