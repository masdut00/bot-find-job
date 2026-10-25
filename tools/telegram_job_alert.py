#!/usr/bin/env python3
"""
Telegram Job Alert Notifier
Searches for new remote/freelance Python, Web Scraping, and Java Web Developer jobs
and sends a clean list notification to a Telegram Bot, styled consistently with Duta's productivity reminder tools.
"""

import argparse
import configparser
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.ini"
SEEN_FILE = ROOT_DIR / "job_scraper" / "seen_telegram_jobs.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def get_settings():
    """Load settings from config.ini or environment variables."""
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf-8")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    bun_bin = os.getenv("BUN_BIN")

    if not token and cfg.has_section("TELEGRAM") and "BOT_TOKEN" in cfg["TELEGRAM"]:
        token = cfg["TELEGRAM"]["BOT_TOKEN"].strip()
    if not chat_id and cfg.has_section("TELEGRAM") and "CHAT_ID" in cfg["TELEGRAM"]:
        chat_id = cfg["TELEGRAM"]["CHAT_ID"].strip()
    if not bun_bin and cfg.has_section("SETTINGS") and "BUN_BIN" in cfg["SETTINGS"]:
        bun_bin = cfg["SETTINGS"]["BUN_BIN"].strip()

    freehire_queries = ["web scraping OR scraper", "python automation", "java developer"]
    linkedin_queries = ["web scraping", "python scraper", "java developer"]
    linkedin_location = "Remote"

    if cfg.has_section("SEARCH"):
        if "FREEHIRE_QUERIES" in cfg["SEARCH"]:
            val = cfg["SEARCH"]["FREEHIRE_QUERIES"].strip()
            if val:
                freehire_queries = [q.strip() for q in val.split(",") if q.strip()]
        if "LINKEDIN_QUERIES" in cfg["SEARCH"]:
            val = cfg["SEARCH"]["LINKEDIN_QUERIES"].strip()
            if val:
                linkedin_queries = [q.strip() for q in val.split(",") if q.strip()]
        if "LINKEDIN_LOCATION" in cfg["SEARCH"]:
            val = cfg["SEARCH"]["LINKEDIN_LOCATION"].strip()
            if val:
                linkedin_location = val

    if not bun_bin:
        # Detect common bun locations
        which_bun = shutil.which("bun")
        if which_bun:
            bun_bin = which_bun
        else:
            win_bun = Path(os.environ.get("USERPROFILE", "")) / ".bun" / "bin" / "bun.exe"
            unix_bun = Path.home() / ".bun" / "bin" / "bun"
            if win_bun.exists():
                bun_bin = str(win_bun)
            elif unix_bun.exists():
                bun_bin = str(unix_bun)
            else:
                bun_bin = "bun"

    return {
        "token": token,
        "chat_id": chat_id,
        "bun_bin": bun_bin,
        "freehire_queries": freehire_queries,
        "linkedin_queries": linkedin_queries,
        "linkedin_location": linkedin_location,
    }


def send_telegram_notification(token: str, chat_id: str, text: str) -> bool:
    """Send HTML-formatted message to Telegram."""
    if not token or not chat_id or token == "your_bot_token_here":
        print("[TelegramAlert] Error: BOT_TOKEN atau CHAT_ID belum dikonfigurasi di config.ini atau ENV.", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[TelegramAlert] Gagal mengirim pesan ke Telegram: {e}", file=sys.stderr)
        return False


def load_seen_jobs() -> set:
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data)
        except Exception:
            return set()
    return set()


def save_seen_jobs(seen: set):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(list(seen)), indent=2), encoding="utf-8")


def parse_job_results(output: str) -> list[dict]:
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            return data.get("results", [])
        elif isinstance(data, list):
            return data
    except Exception as e:
        print(f"[TelegramAlert] Error parsing JSON: {e}", file=sys.stderr)
    return []


def search_freehire_single(bun_bin: str, query: str) -> list[dict]:
    cli_path = ROOT_DIR / ".agents" / "skills" / "freehire-search" / "cli" / "src" / "cli.ts"
    if not cli_path.exists():
        return []

    cmd = [
        bun_bin, "run", str(cli_path),
        "search",
        "-q", query,
        "--remote", "remote",
        "--limit", "10",
        "--format", "json"
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True
        )
        return parse_job_results(res.stdout)
    except Exception as e:
        print(f"[TelegramAlert] Freehire search error for '{query}': {e}", file=sys.stderr)
        return []


def search_linkedin_single(bun_bin: str, query: str, location: str) -> list[dict]:
    cli_path = ROOT_DIR / ".agents" / "skills" / "linkedin-search" / "cli" / "src" / "cli.ts"
    if not cli_path.exists():
        return []

    cmd = [
        bun_bin, "run", str(cli_path),
        "search",
        "-q", query,
        "-l", location,
        "--remote", "remote",
        "--jobage", "3",
        "--limit", "8",
        "--format", "json"
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True
        )
        return parse_job_results(res.stdout)
    except Exception as e:
        print(f"[TelegramAlert] LinkedIn search error for '{query}': {e}", file=sys.stderr)
        return []


def escape_html(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def categorize_job(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["scrap", "crawl", "extract", "parser", "playwright", "selenium"]):
        return "🕸️ Web Scraping & Automation"
    elif any(k in t for k in ["java", "spring"]):
        return "☕ Java & Backend Development"
    elif any(k in t for k in ["python", "django", "fastapi", "flask", "bot", "etl"]):
        return "🐍 Python & Backend Engineering"
    else:
        return "💻 Remote & Freelance Tech"


def format_jobs_list_message(jobs: list[dict], date_str: str) -> list[str]:
    """Format daftar lowongan menjadi pesan list Telegram berstruktur pohon per kategori."""
    if not jobs:
        return []

    # Kelompokkan jobs berdasarkan kategori
    grouped = {}
    for j in jobs:
        cat = categorize_job(j["title"])
        grouped.setdefault(cat, []).append(j)

    messages = []
    header = (
        f"🤖 <b>BOT FIND JOB — REKOMENDASI HARIAN</b>\n"
        f"📅 <i>{date_str}</i>\n\n"
        f"🎯 <b>LOWONGAN REMOTE / FREELANCE BARU</b>: {len(jobs)} posisi\n\n"
    )

    current_chunk = header

    for cat_name, cat_jobs in grouped.items():
        cat_header = f"<b>{cat_name}</b> ({len(cat_jobs)} lowongan)\n"
        items_text = ""

        for i, j in enumerate(cat_jobs):
            is_last = (i == len(cat_jobs) - 1)
            prefix = "└──" if is_last else "├──"
            branch = "    " if is_last else "│   "

            title = escape_html(j["title"])
            company = escape_html(j["company"])
            location = escape_html(j.get("location") or "Remote")
            source = escape_html(j.get("source") or "")
            url = j.get("url") or "#"

            items_text += (
                f"<code>{prefix}</code> 💼 <a href=\"{url}\"><b>{title}</b></a>\n"
                f"<code>{branch}</code> 🏢 {company} | 📍 {location} (<i>{source}</i>)\n"
            )

        block = cat_header + items_text + "\n"

        if len(current_chunk) + len(block) > 3800:
            messages.append(current_chunk.rstrip())
            current_chunk = f"<i>(Lanjutan lowongan...)</i>\n\n" + block
        else:
            current_chunk += block

    footer = f"✨ <i>Dipilih khusus untuk mode Full Remote / Freelance tanpa mengganggu primary job.</i>"
    if len(current_chunk) + len(footer) <= 4000:
        current_chunk += footer
        messages.append(current_chunk.rstrip())
    else:
        messages.append(current_chunk.rstrip())
        messages.append(footer.strip())

    return messages


def main():
    parser = argparse.ArgumentParser(description="Telegram Job Alert Notifier")
    parser.add_argument("--dry-run", action="store_true", help="Print formatted message to console without sending to Telegram")
    parser.add_argument("--force", action="store_true", help="Ignore seen jobs cache")
    parser.add_argument("--test", action="store_true", help="Send a test message to Telegram to verify credentials")
    args = parser.parse_args()

    settings = get_settings()
    token = settings["token"]
    chat_id = settings["chat_id"]
    bun_bin = settings["bun_bin"]

    if args.test:
        test_msg = "🔔 <b>Test Notifikasi: Bot Find Job</b>\nKoneksi ke bot Telegram berhasil!"
        if send_telegram_notification(token, chat_id, test_msg):
            print("Pesan tes berhasil dikirim ke Telegram!")
            return 0
        else:
            print("Gagal mengirim pesan tes. Periksa kembali token dan chat_id.", file=sys.stderr)
            return 1

    seen = set() if args.force else load_seen_jobs()
    new_jobs = []

    print("[TelegramAlert] Mencari lowongan di Freehire...")
    for q in settings["freehire_queries"]:
        results = search_freehire_single(bun_bin, q)
        for j in results:
            jid = f"fh_{j.get('id')}"
            if jid not in seen:
                seen.add(jid)
                new_jobs.append({
                    "id": jid,
                    "title": j.get("title", "No Title"),
                    "company": j.get("company", "Unknown"),
                    "location": j.get("location") or "Remote",
                    "url": j.get("url") or f"https://freehire.me/jobs/{j.get('id')}",
                    "source": "Freehire"
                })

    print("[TelegramAlert] Mencari lowongan di LinkedIn...")
    for q in settings["linkedin_queries"]:
        results = search_linkedin_single(bun_bin, q, settings["linkedin_location"])
        for j in results:
            jid = f"li_{j.get('id')}"
            if jid not in seen:
                seen.add(jid)
                new_jobs.append({
                    "id": jid,
                    "title": j.get("title", "No Title"),
                    "company": j.get("company", "Unknown"),
                    "location": j.get("location") or "Remote",
                    "url": j.get("url") or f"https://www.linkedin.com/jobs/view/{j.get('id')}",
                    "source": "LinkedIn"
                })

    if not new_jobs:
        print("[TelegramAlert] Tidak ada lowongan baru yang ditemukan.")
        return 0

    now_str = datetime.now().strftime("%d %b %Y")
    messages = format_jobs_list_message(new_jobs, now_str)

    if args.dry_run:
        print("\n=== FORMATTED TELEGRAM MESSAGE (DRY-RUN) ===\n")
        for idx, m in enumerate(messages, 1):
            print(f"--- Bagian {idx} ---")
            print(m)
            print()
        print(f"Total lowongan baru: {len(new_jobs)}")
        return 0

    success = True
    for m in messages:
        if not send_telegram_notification(token, chat_id, m):
            success = False

    if success:
        save_seen_jobs(seen)
        print(f"[TelegramAlert] Berhasil mengirim {len(new_jobs)} lowongan baru ke Telegram.")
        return 0
    else:
        print("[TelegramAlert] Sebagian atau seluruh pesan gagal terkirim.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
