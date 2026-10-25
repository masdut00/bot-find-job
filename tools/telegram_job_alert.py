#!/usr/bin/env python3
"""
Telegram Job Alert Notifier — Side Job & Freelance Edition (Indonesia Focus)
Mencari lowongan kerja sampingan di Indonesia (100% remote / virtual, tanpa interview onsite).
Mencakup tugas Non-IT (Data Entry, Admin, Virtual Assistant, AI Annotation)
dan tugas IT (Web Scraping, Python, Java Web Developer Freelance).
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


# Kata kunci negatif yang mengindikasikan wajib datang ke kantor / interview tatap muka
EXCLUDED_KEYWORDS = [
    "interview onsite",
    "onsite interview",
    "tatap muka",
    "interview di kantor",
    "wawancara di kantor",
    "wajib ke kantor",
    "wajib wfo",
    "onsite",
    "hybrid",
    "harus datang ke kantor",
    "penempatan ",
    "penempatan:",
    "offline",
    "wajib hadir",
]


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

    # Default queries: Fokus Indonesia, sampingan Non-IT & IT freelance
    linkedin_queries = [
        "data entry",
        "virtual assistant",
        "admin freelance",
        "data annotator",
        "web scraping",
        "python freelance",
        "java freelance",
    ]
    freehire_queries = [
        "web scraping OR scraper",
        "python automation",
        "java developer",
    ]
    location = "Indonesia"

    if cfg.has_section("SEARCH"):
        if "LINKEDIN_QUERIES" in cfg["SEARCH"]:
            val = cfg["SEARCH"]["LINKEDIN_QUERIES"].strip()
            if val:
                linkedin_queries = [q.strip() for q in val.split(",") if q.strip()]
        if "FREEHIRE_QUERIES" in cfg["SEARCH"]:
            val = cfg["SEARCH"]["FREEHIRE_QUERIES"].strip()
            if val:
                freehire_queries = [q.strip() for q in val.split(",") if q.strip()]
        if "LOCATION" in cfg["SEARCH"]:
            val = cfg["SEARCH"]["LOCATION"].strip()
            if val:
                location = val

    if not bun_bin:
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
        "linkedin_queries": linkedin_queries,
        "freehire_queries": freehire_queries,
        "location": location,
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


def is_job_eligible(job: dict) -> bool:
    """Filter out jobs that require onsite attendance or onsite interview."""
    text_check = f"{job.get('title', '')} {job.get('location', '')} {job.get('description', '')}".lower()
    for bad_kw in EXCLUDED_KEYWORDS:
        if bad_kw in text_check:
            return False
    return True


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


def search_freehire_single(bun_bin: str, query: str) -> list[dict]:
    cli_path = ROOT_DIR / ".agents" / "skills" / "freehire-search" / "cli" / "src" / "cli.ts"
    if not cli_path.exists():
        return []

    cmd = [
        bun_bin, "run", str(cli_path),
        "search",
        "-q", query,
        "--remote", "remote",
        "--limit", "6",
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


def escape_html(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def categorize_job(title: str) -> str:
    """Kelompokkan lowongan ke kategori pekerjaan sampingan."""
    t = title.lower()

    # 1. Non-IT: Data Entry, Virtual Assistant, Admin
    if any(k in t for k in ["data entry", "entry data", "input data", "virtual assistant", "assistant", "admin", "registration", "transkrip"]):
        return "📋 Data Entry & Admin Online (Non-IT)"

    # 2. Non-IT / Semi-Tech: Data Annotation & AI Training
    elif any(k in t for k in ["annotat", "ai training", "labeling", "labelling", "evaluat", "prompt", "content review", "ai trainer", "annotator"]):
        return "🏷️ Data Annotation & AI Training"

    # 3. Tech: Web Scraping & Data Extraction (Niche per-project/bot)
    elif any(k in t for k in ["scrap", "crawl", "extract", "parser", "playwright", "selenium"]):
        return "🕸️ Web Scraping & Data Extraction"

    # 4. Tech: Java Web & Backend Development
    elif any(k in t for k in ["java", "spring"]):
        return "☕ Java Web Developer (Freelance/Part-time)"

    # 5. Tech: Python & Scripting Automation
    elif any(k in t for k in ["python", "django", "fastapi", "flask", "bot", "etl"]):
        return "🐍 Python Automation & Bot (Side-Gig)"

    else:
        return "💼 Pekerjaan Sampingan Fleksibel Lainnya"


def format_jobs_list_message(jobs: list[dict], date_str: str) -> list[str]:
    """Format daftar lowongan menjadi pesan list Telegram berstruktur pohon per kategori."""
    if not jobs:
        return []

    # Kelompokkan jobs berdasarkan kategori yang terurut
    category_order = [
        "📋 Data Entry & Admin Online (Non-IT)",
        "🏷️ Data Annotation & AI Training",
        "🕸️ Web Scraping & Data Extraction",
        "☕ Java Web Developer (Freelance/Part-time)",
        "🐍 Python Automation & Bot (Side-Gig)",
        "💼 Pekerjaan Sampingan Fleksibel Lainnya",
    ]

    grouped = {}
    for j in jobs:
        cat = categorize_job(j["title"])
        grouped.setdefault(cat, []).append(j)

    messages = []
    header = (
        f"🤖 <b>JOB SAMPINGAN INDONESIA (100% REMOTE)</b>\n"
        f"📅 <i>{date_str}</i>\n"
        f"✅ <i>Filter: Tanpa Interview Onsite | Jam Fleksibel</i>\n\n"
        f"🎯 <b>{len(jobs)} Lowongan Sampingan Baru Ditemukan:</b>\n\n"
    )

    current_chunk = header

    for cat_name in category_order:
        if cat_name not in grouped:
            continue
        cat_jobs = grouped[cat_name]
        cat_header = f"<b>{cat_name}</b> ({len(cat_jobs)} lowongan)\n"
        items_text = ""

        for i, j in enumerate(cat_jobs):
            is_last = (i == len(cat_jobs) - 1)
            prefix = "└──" if is_last else "├──"
            branch = "    " if is_last else "│   "

            title = escape_html(j["title"])
            company = escape_html(j["company"])
            location = escape_html(j.get("location") or "Indonesia (Remote)")
            source = escape_html(j.get("source") or "")
            url = j.get("url") or "#"

            items_text += (
                f"<code>{prefix}</code> 💼 <a href=\"{url}\"><b>{title}</b></a>\n"
                f"<code>{branch}</code> 🏢 {company} | 📍 {location} (<i>{source}</i>)\n"
            )

        block = cat_header + items_text + "\n"

        if len(current_chunk) + len(block) > 3800:
            messages.append(current_chunk.rstrip())
            current_chunk = f"<i>(Lanjutan lowongan sampingan...)</i>\n\n" + block
        else:
            current_chunk += block

    footer = f"💡 <i>Tips: Cocok dijadikan kerjaan sampingan tanpa mengganggu job Java Developer utama Anda.</i>"
    if len(current_chunk) + len(footer) <= 4000:
        current_chunk += footer
        messages.append(current_chunk.rstrip())
    else:
        messages.append(current_chunk.rstrip())
        messages.append(footer.strip())

    return messages


def main():
    parser = argparse.ArgumentParser(description="Telegram Job Alert Notifier — Side Job Edition")
    parser.add_argument("--dry-run", action="store_true", help="Print formatted message to console without sending to Telegram")
    parser.add_argument("--force", action="store_true", help="Ignore seen jobs cache")
    parser.add_argument("--test", action="store_true", help="Send a test message to Telegram to verify credentials")
    args = parser.parse_args()

    settings = get_settings()
    token = settings["token"]
    chat_id = settings["chat_id"]
    bun_bin = settings["bun_bin"]
    location = settings["location"]

    if args.test:
        test_msg = "🔔 <b>Test Notifikasi: Bot Side Job Finder</b>\nKoneksi ke bot Telegram berhasil!"
        if send_telegram_notification(token, chat_id, test_msg):
            print("Pesan tes berhasil dikirim ke Telegram!")
            return 0
        else:
            print("Gagal mengirim pesan tes. Periksa kembali token dan chat_id.", file=sys.stderr)
            return 1

    seen = set() if args.force else load_seen_jobs()
    new_jobs = []

    # 1. Search LinkedIn (Fokus Indonesia & Remote)
    print(f"[TelegramAlert] Mencari lowongan sampingan di LinkedIn (Lokasi: {location})...")
    for q in settings["linkedin_queries"]:
        results = search_linkedin_single(bun_bin, q, location)
        for j in results:
            if not is_job_eligible(j):
                continue
            jid = f"li_{j.get('id')}"
            if jid not in seen:
                seen.add(jid)
                new_jobs.append({
                    "id": jid,
                    "title": j.get("title", "No Title"),
                    "company": j.get("company", "Unknown"),
                    "location": j.get("location") or "Indonesia (Remote)",
                    "url": j.get("url") or f"https://www.linkedin.com/jobs/view/{j.get('id')}",
                    "source": "LinkedIn"
                })

    # 2. Search Freehire (Remote Freelance Tech)
    print("[TelegramAlert] Mencari lowongan remote di Freehire...")
    for q in settings["freehire_queries"]:
        results = search_freehire_single(bun_bin, q)
        for j in results:
            if not is_job_eligible(j):
                continue
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

    if not new_jobs:
        print("[TelegramAlert] Tidak ada lowongan sampingan baru yang ditemukan.")
        return 0

    now_str = datetime.now().strftime("%d %b %Y")
    messages = format_jobs_list_message(new_jobs, now_str)

    if args.dry_run:
        print("\n=== FORMATTED TELEGRAM MESSAGE (DRY-RUN) ===\n")
        for idx, m in enumerate(messages, 1):
            print(f"--- Bagian {idx} ---")
            print(m)
            print()
        print(f"Total lowongan sampingan baru: {len(new_jobs)}")
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
