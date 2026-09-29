import os
import json
import time
import logging
import re
from urllib.parse import urljoin
import requests
import cloudscraper
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

# Cloudscraper session for Cloudflare-protected sites (magicspoiler.com)
_spoiler_scraper = cloudscraper.create_scraper()

SPOILER_BASE = "https://www.magicspoiler.com"
SPOILER_STATE_FILE = BASE_DIR / "seen_spoilers.json"
SPOILER_URLS = [
    "https://www.magicspoiler.com/mtg-set/the-hobbit/",
    "https://www.magicspoiler.com/mtg-set/reality-fracture/",
    "https://www.magicspoiler.com/mtg-set/star-trek/",
    "https://www.magicspoiler.com/mtg-set/nauctis-the-sunken-realm/",
    "https://www.magicspoiler.com/mtg-set/kamigawa-titanbreach/",
    "https://www.magicspoiler.com/mtg-set/zhalfir/",
]

EXTRA_PRODUCT_URLS = [
    "https://mysteryshack.se/products/magic-the-gathering",
    "https://manatorsk.com/collections/mtg-booster-box",
    "https://www.alaragames.se/collections/display?sort_by=created-descending",
]
EXTRA_PRODUCT_STATE_FILE = BASE_DIR / "seen_external_products.json"


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


def load_external_product_state() -> dict[str, list[str]]:
    if EXTRA_PRODUCT_STATE_FILE.exists():
        with open(EXTRA_PRODUCT_STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_external_product_state(state: dict[str, list[str]]) -> None:
    with open(EXTRA_PRODUCT_STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump({k: sorted(v) for k, v in state.items()}, fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Additional retailer scraping
# ---------------------------------------------------------------------------
def fetch_extra_products(page_url: str) -> list[dict] | None:
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Failed to fetch product page %s: %s", page_url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    products: dict[str, dict] = {}

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith("#"):
            continue
        if "javascript:" in href.lower() or href.startswith("mailto:"):
            continue
        if "/products/" not in href and "/product/" not in href:
            continue
        if "/wishlist" in href or "/cart" in href or "/checkout" in href:
            continue

        full_url = urljoin(page_url, href)
        text = a_tag.get_text(" ", strip=True)
        text = re.sub(r"(?i)\s*(wishlist|add to cart|view product|read more).*", "", text).strip()
        if not text:
            continue

        # Keep the product title clean enough but avoid too much churn from stock text
        text = re.sub(r"\s+", " ", text)
        if text.lower().endswith("sold out"):
            text = text.rsplit("sold out", 1)[0].strip()

        name = text[:140] if len(text) > 140 else text
        if not name:
            continue

        price_match = re.search(r"(\d[\d\s\.,]*\d)\s*(kr|kronor|sek)", text, re.IGNORECASE)
        price = price_match.group(0).strip() if price_match else ""

        products[full_url] = {"name": name, "url": full_url, "price": price}

    return list(products.values())


def check_extra_product_pages() -> None:
    state = load_external_product_state()
    changed = False

    for page_url in EXTRA_PRODUCT_URLS:
        source_name = page_url.split("//")[-1].split("/")[0]
        products = fetch_extra_products(page_url)
        if products is None:
            log.warning("Skipping extra product page %s — fetch failed", page_url)
            continue

        current_urls = {p["url"] for p in products}
        known_urls = set(state.get(page_url, []))

        if page_url not in state:
            state[page_url] = sorted(current_urls)
            changed = True
            log.info("First run for %s: %d products baselined.", source_name, len(current_urls))
            continue

        new_urls = current_urls - known_urls
        if new_urls:
            product_map = {p["url"]: p for p in products}
            for product_url in new_urls:
                product = product_map[product_url]
                log.info("New extra product detected at %s: %s", source_name, product["name"])
                if WEBHOOK_URL:
                    post_discord_product(product, source_name, page_url)
            state[page_url] = sorted(known_urls | new_urls)
            changed = True
        else:
            log.info("No new product additions on %s (%d items).", source_name, len(current_urls))

    if changed:
        save_external_product_state(state)


# ---------------------------------------------------------------------------
# Spoiler scraping
# ---------------------------------------------------------------------------
def _set_slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _set_name_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()


def fetch_spoilers(set_url: str) -> list[dict] | None:
    """Fetch a spoiler set page and return list of card dicts, or None on error."""
    try:
        resp = _spoiler_scraper.get(set_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        log.error("Failed to fetch spoiler page %s: %s", set_url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = []
    seen_slugs: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"]
        if "/mtg-spoiler/" not in href:
            continue
        # Skip links pointing away from magicspoiler
        if href.startswith("http") and not href.startswith(SPOILER_BASE):
            continue

        slug = href.split("/mtg-spoiler/")[-1].strip("/")
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        name = re.sub(r"\s+", " ", a_tag.get_text(strip=True)).strip()
        if not name:
            name = slug.replace("-", " ").title()

        full_url = (
            href if href.startswith("http") else SPOILER_BASE + "/mtg-spoiler/" + slug + "/"
        )

        cards.append({"slug": slug, "name": name, "url": full_url})

    return cards


def load_spoiler_state() -> dict[str, list[str]]:
    if SPOILER_STATE_FILE.exists():
        with open(SPOILER_STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_spoiler_state(state: dict[str, list[str]]) -> None:
    with open(SPOILER_STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(
            {k: sorted(v) for k, v in state.items()}, fh, ensure_ascii=False, indent=2
        )


def extract_image_url_from_html(html: str) -> str | None:
    """Best-effort extraction of the image URL for a spoiler page."""
    soup = BeautifulSoup(html, "html.parser")

    for selector in (
        "meta[property='og:image']",
        "meta[property='og:image:url']",
        "meta[name='twitter:image']",
        "meta[name='twitter:image:src']",
        "meta[property='twitter:image']",
        "meta[itemprop='image']",
    ):
        tag = soup.select_one(selector)
        if tag is None:
            continue
        candidate = tag.get("content") or tag.get("src") or tag.get("data-src")
        if candidate and candidate.strip():
            return candidate.strip()

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "srcset"):
            candidate = img.get(attr)
            if not candidate or not candidate.strip():
                continue
            candidate = candidate.strip()
            if candidate.startswith("data:"):
                continue
            if "," in candidate and candidate.split(",")[0].startswith(("http", "//", "/")):
                candidate = candidate.split(",")[0].strip()
            if candidate.startswith(("http", "//", "/")):
                return candidate

    return None


def fetch_card_image_url(card_url: str) -> str | None:
    """Fetch a spoiler card page and return the first usable card image URL."""
    try:
        resp = _spoiler_scraper.get(card_url, timeout=30, headers=HEADERS)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Failed to fetch spoiler card page %s: %s", card_url, exc)
        return None

    image_url = extract_image_url_from_html(resp.text)
    if not image_url:
        return None
    return urljoin(card_url, image_url)


def check_spoilers() -> None:
    state = load_spoiler_state()
    changed = False

    for set_url in SPOILER_URLS:
        set_slug = _set_slug_from_url(set_url)
        set_name = _set_name_from_slug(set_slug)

        cards = fetch_spoilers(set_url)
        if cards is None:
            log.warning("Skipping spoiler check for %s — fetch failed", set_name)
            continue
        if not cards:
            log.warning("No cards found for %s — skipping", set_name)
            continue

        current_slugs = {c["slug"] for c in cards}
        known_slugs = set(state.get(set_slug, []))

        if set_slug not in state:
            # First time seeing this set — baseline silently
            state[set_slug] = sorted(current_slugs)
            changed = True
            log.info("First run for %s: %d cards baselined.", set_name, len(current_slugs))
            continue

        new_slugs = current_slugs - known_slugs
        if new_slugs:
            slug_map = {c["slug"]: c for c in cards}
            for slug in new_slugs:
                card = slug_map[slug]
                image_url = fetch_card_image_url(card["url"])
                card["image_url"] = image_url
                log.info("New spoiler: %s — %s", set_name, card["name"])
                if WEBHOOK_URL:
                    post_discord_spoiler(card, set_name, set_url, image_url)
                else:
                    log.warning("DISCORD_WEBHOOK_URL not set — skipping spoiler notification")
            state[set_slug] = sorted(known_slugs | new_slugs)
            changed = True
        else:
            log.info(
                "No new spoilers for %s (%d cards total).", set_name, len(current_slugs)
            )

    if changed:
        save_spoiler_state(state)


# ---------------------------------------------------------------------------
# Discord notification
# ---------------------------------------------------------------------------
def post_discord_startup() -> None:
    mention = f"<@{USER_ID}>" if USER_ID else ""
    lines = ["✅ **Coolcard monitor is online!**"]
    if mention:
        lines.append(mention)
    payload = {"content": "\n".join(lines)}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Startup notification sent to Discord")
    except requests.RequestException as exc:
        log.error("Failed to send startup notification: %s", exc)


def post_discord_spoiler(
    card: dict, set_name: str, set_url: str, image_url: str | None = None
) -> None:
    mention = f"<@{USER_ID}>" if USER_ID else ""
    lines = [
        f"🃏 **New card spoiled for {set_name}!**",
        f"**{card['name']}**",
        f"🔗 {card['url']}",
        f"🌐 {set_url}",
    ]
    if mention:
        lines.append(mention)

    image_url = image_url or card.get("image_url")
    payload = {"content": "\n".join(lines)}
    if image_url:
        payload["embeds"] = [
            {
                "title": card["name"],
                "url": card["url"],
                "description": f"New card spoiled for {set_name}",
                "color": 0x5865F2,
                "image": {"url": image_url},
            }
        ]

    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Spoiler notification sent: %s — %s", set_name, card["name"])
    except requests.RequestException as exc:
        log.error("Failed to post spoiler Discord message: %s", exc)


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


def post_discord_product(product: dict, source_name: str, page_url: str) -> None:
    mention = f"<@{USER_ID}>" if USER_ID else ""
    price_part = f" — **{product['price']}**" if product["price"] else ""
    lines = [
        f"🆕 **New product on {source_name}!**",
        f"**{product['name']}**{price_part}",
        f"🔗 {product['url']}",
        f"🌐 {page_url}",
    ]
    if mention:
        lines.append(mention)

    payload = {"content": "\n".join(lines)}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Discord extra-product notification sent for: %s", product["name"])
    except requests.RequestException as exc:
        log.error("Failed to post extra-product Discord message: %s", exc)


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

    check_extra_product_pages()
    check_spoilers()


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
