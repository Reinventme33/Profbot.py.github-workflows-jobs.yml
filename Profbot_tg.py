import html
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

SEARCH_URL = "https://www.profesia.sk/praca/bratislava/administrativny-pracovnik-pracovnicka/?jobtype_id=4&languages=73&radius=radius30"
BASE_URL = "https://www.profesia.sk"
SEEN_FILE = Path("seen_jobs.json")
MAX_PER_RUN = 10

HEADERS = {
    "User-Agent": "personal-job-alert-bot"
}

# Ссылка на вакансию на Profesia заканчивается ID вида /O1234567
OFFER_ID_RE = re.compile(r"/(O\d+)/?$")


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return None  # None = первый запуск


def save_seen(seen):
    tmp = SEEN_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(SEEN_FILE)  # атомарная запись: файл не побьётся при сбое


def offer_id(url):
    match = OFFER_ID_RE.search(url)
    return match.group(1) if match else None


def parse_card(card, link):
    url = urljoin(BASE_URL, link.get("href", "")).split("?")[0].split("#")[0]
    oid = offer_id(url)
    if not oid:
        return None

    title = link.get_text(" ", strip=True)
    if not title:
        return None

    company = "Neuvedené"
    # Ищем по очереди и берём первый непустой текст
    # (ссылка-логотип компании тоже подходит под селектор, но она без текста)
    for selector in ("span.employer", ".employer", "[class*='company']"):
        tag = card.select_one(selector)
        text = tag.get_text(" ", strip=True) if tag else ""
        if text:
            company = text
            break

    return {"id": oid, "title": title, "company": company, "url": url}


def fetch_jobs():
    response = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    jobs = {}

    # Основной вариант: строки списка вакансий
    for card in soup.select("li.list-row"):
        link = card.select_one("h2 a[href], a.title[href]")
        if not link:
            continue
        job = parse_card(card, link)
        if job:
            jobs[job["id"]] = job

    # Запасной вариант, если вёрстка изменилась: любые ссылки с ID вакансии
    if not jobs:
        for link in soup.select("a[href*='/praca/']"):
            if not offer_id(link.get("href", "").split("?")[0]):
                continue
            card = link.find_parent(["li", "article", "div"]) or link
            job = parse_card(card, link)
            if job and job["id"] not in jobs:
                jobs[job["id"]] = job

    return list(jobs.values())


def send_message(text, retries=3):
    for _ in range(retries):
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if response.status_code == 429:  # Telegram просит подождать
            wait = response.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(wait + 1)
            continue
        response.raise_for_status()
        return
    raise RuntimeError("Telegram: не удалось отправить сообщение после повторов")


def format_job(job):
    e = html.escape
    return (
        "<b>Nová pracovná ponuka</b>\n\n"
        f"<b>{e(job['title'])}</b>\n"
        f"🏢 {e(job['company'])}\n\n"
        f"<a href=\"{e(job['url'], quote=True)}\">Otvoriť na Profesia.sk</a>"
    )


def run_once():
    seen = load_seen()
    jobs = fetch_jobs()

    if not jobs:
        print("Внимание: на странице не найдено ни одной вакансии — "
              "возможно, изменилась вёрстка сайта.", file=sys.stderr)
        return

    # Первый запуск: запоминаем текущие вакансии, но не спамим ими
    if seen is None:
        save_seen({job["id"] for job in jobs})
        send_message(
            "✅ Бот запущен. Сейчас на сайте "
            f"{len(jobs)} вакансий — буду присылать только новые."
        )
        print(f"Первый запуск: запомнено {len(jobs)} вакансий")
        return

    new_jobs = [job for job in jobs if job["id"] not in seen]

    for job in new_jobs[:MAX_PER_RUN]:
        send_message(format_job(job))
        seen.add(job["id"])
        save_seen(seen)  # сохраняем сразу, чтобы при сбое не было повторов
        time.sleep(1)

    left = len(new_jobs) - MAX_PER_RUN
    print(f"Новых вакансий: {len(new_jobs)}"
          + (f", ещё {left} придут при следующем запуске" if left > 0 else ""))


if __name__ == "__main__":
    run_once()


