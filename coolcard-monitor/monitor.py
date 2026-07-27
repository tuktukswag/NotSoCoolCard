import os
import json
import time
import logging
import re
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "seen_products.json"
CATEGORY_URL = "https://www.coolcard.se/category/magic?sortBy=idDesc&page=1"
PRODUCT_BASE = "https://www.coolcard.se"
CHECK_INTERVAL = 300  # seconds (5 minutes)

load_dotenv(BASE_DIR / ".env")

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
USER_ID = os.environ.get("DISCORD_USER_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Minimum products expected per page — if we get fewer, assume parse failure
MIN_PRODUCTS_EXPECTED = 5


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------
def fetch_products():
    """Fetch the category page and return a list of product dicts, or None on error."""
    try:
        resp = requests.get(CATEGORY_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Failed to fetch category page: %s", exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []
    seen_hrefs: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"]

        # Only product detail links
        if not href.startswith("/product/"):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        slug = href.rstrip("/").split("/")[-1]
        if not slug:
            continue

        full_url = PRODUCT_BASE + href
        raw_text = a_tag.get_text(separator=" ", strip=True)

        # Extract price: e.g. "1 399 KR" or "79 KR"
        price_match = re.search(r"(\d[\d\s]*\d|\d)\s*KR", raw_text, re.IGNORECASE)
        price = price_match.group(0).strip() if price_match else ""

        # Name = everything before the price, truncated to 120 chars
        if price_match:
            name_raw = raw_text[: price_match.start()].strip()
        else:
            name_raw = raw_text.strip()

        name = re.sub(r"\s+", " ", name_raw).strip(" -").strip()
        if len(name) > 120:
            name = name[:117] + "..."

        if not name:
            name = slug.replace("-", " ").title()

        products.append(
            {
                "slug": slug,
                "name": name,
                "price": price,
                "url": full_url,
            }
        )

    return products


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def load_state() -> set[str] | None:
    """Return set of known slugs, or None if no state file yet (first run)."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return set(json.load(fh))
    return None


def save_state(slugs: set[str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(sorted(slugs), fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Discord notification
# ---------------------------------------------------------------------------
def post_discord_startup() -> None:
    mention = f"<@{USER_ID}>" if USER_ID else ""
    lines = [
        "✅ **Coolcard monitor started!**",
        f"Watching for new Magic products every {CHECK_INTERVAL // 60} minutes.",
        f"🌐 {CATEGORY_URL}",
    ]
    if mention:
        lines.append(mention)
    payload = {"content": "\n".join(lines)}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Startup notification sent to Discord")
    except requests.RequestException as exc:
        log.error("Failed to send startup notification: %s", exc)


def post_discord(product: dict) -> None:
    mention = f"<@{USER_ID}>" if USER_ID else ""
    price_part = f" — **{product['price']}**" if product["price"] else ""
    lines = [
        "🆕 **New product on Coolcard!**",
        f"**{product['name']}**{price_part}",
        f"🔗 {product['url']}",
        f"🌐 {CATEGORY_URL}",
    ]
    if mention:
        lines.append(mention)

    payload = {"content": "\n".join(lines)}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Discord notification sent for: %s", product["name"])
    except requests.RequestException as exc:
        log.error("Failed to post Discord message: %s", exc)


# ---------------------------------------------------------------------------
# Main check cycle
# ---------------------------------------------------------------------------
def check_once() -> None:
    products = fetch_products()
    if products is None:
        log.warning("Skipping check — fetch failed")
        return

    if len(products) < MIN_PRODUCTS_EXPECTED:
        log.warning(
            "Only %d products returned — likely a parse failure. Skipping diff.",
            len(products),
        )
        return

    current_slugs = {p["slug"] for p in products}
    known_slugs = load_state()

    if known_slugs is None:
        # First run: establish silent baseline
        save_state(current_slugs)
        log.info(
            "First run: %d products saved as baseline — no notifications sent.",
            len(current_slugs),
        )
        return

    new_slugs = current_slugs - known_slugs
    if new_slugs:
        slug_map = {p["slug"]: p for p in products}
        for slug in new_slugs:
            product = slug_map[slug]
            log.info("New product detected: %s (%s)", product["name"], product["price"])
            if WEBHOOK_URL:
                post_discord(product)
            else:
                log.warning("DISCORD_WEBHOOK_URL not set — skipping notification")
        save_state(known_slugs | new_slugs)
    else:
        log.info("No new products (%d total on page).", len(current_slugs))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    if not WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL is not set — all notifications will be skipped")
    log.info(
        "Coolcard monitor started. Interval: %ds. Watching: %s",
        CHECK_INTERVAL,
        CATEGORY_URL,
    )

    if WEBHOOK_URL:
        post_discord_startup()

    while True:
        try:
            check_once()
        except Exception:
            log.exception("Unexpected error in check_once — continuing")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
