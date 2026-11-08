import json
import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

SEARCH_URL = "https://www.profesia.sk/praca/bratislava/?keywords=data%20analyst"
SEEN_FILE = Path("seen_jobs.json")

HEADERS = {
    "User-Agent": "personal-job-alert-bot"
}


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_jobs():
    response = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    jobs = {}

    for card in soup.select("article, div[data-testid*='job'], div[class*='offer']"):
        link = card.select_one("a[href*='/praca/']")
        title = card.select_one("h2, h3, a")

        if not link or not title:
            continue

        url = link.get("href", "")
        if url.startswith("/"):
            url = "https://www.profesia.sk" + url

        url = url.split("?")[0]
        company_tag = card.select_one(
            "a[href*='/zamestnavatelia/'], span[class*='company']"
        )
        company = company_tag.get_text(strip=True) if company_tag else "Neuvedené"

        jobs[url] = {
            "title": title.get_text(strip=True),
            "company": company,
            "url": url,
        }

    return list(jobs.values())


def send_message(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=30,
    ).raise_for_status()


def run_once():
    seen = load_seen()
    jobs = fetch_jobs()
    new_jobs = [job for job in jobs if job["url"] not in seen]

    for job in new_jobs[:10]:
        send_message(
            "<b>Nová pracovná ponuka</b>\n\n"
            f"<b>{job['title']}</b>\n"
            f"🏢 {job['company']}\n\n"
            f"<a href=\"{job['url']}\">Otvoriť na Profesia.sk</a>"
        )
        seen.add(job["url"])

    save_seen(seen)
    print(f"Nových ponúk: {len(new_jobs)}")


if __name__ == "__main__":
    run_once()
