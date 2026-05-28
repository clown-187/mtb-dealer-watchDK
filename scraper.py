"""
Scraper med to strategier:
  - shopify:    Henter products.json + specifikke sale-collections
  - playwright: Starter en rigtig browser, korer JS, finder produkter automatisk
"""

import asyncio
import re
import requests
import urllib3
from playwright.async_api import async_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
}

DEFAULT_COLLECTIONS = ["mountainbike", "mountain-bike", "mtb", "cykler", "all"]

FIND_PRODUCTS_JS = """
() => {
    const results = [];
    const priceRe = /\\d[\\d.,]+\\s*(kr\\.?|dkk|€|eur)/i;
    const seen = new Set();

    document.querySelectorAll('*').forEach(el => {
        const own = (el.childNodes[0] || {}).textContent || '';
        if (!priceRe.test(own) || own.length > 60) return;

        let node = el;
        for (let i = 0; i < 6; i++) {
            node = node.parentElement;
            if (!node) break;
            const h = node.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');
            const a = node.querySelector('a[href]');
            if (h && a) {
                const url = a.href;
                if (seen.has(url)) break;
                seen.add(url);
                const crossed = node.querySelector(
                    's, del, [class*="old"], [class*="was"], [class*="before"], ' +
                    '[class*="original"], [class*="compare"], [class*="crossed"], ' +
                    '[class*="regular"], [class*="Normal"]'
                );
                results.push({
                    title:          h.innerText.trim().split('\\n')[0],
                    price:          own.trim(),
                    original_price: crossed ? crossed.innerText.trim() : null,
                    url:            url
                });
                break;
            }
        }
    });
    return results;
}
"""


# ── Shopify JSON API ─────────────────────────────────────────────────────────

def _shopify_products(base, collection, verify=True):
    """Henter alle produkter fra en Shopify collection."""
    results = []
    page = 1
    while True:
        url = f"{base}/collections/{collection}/products.json?limit=250&page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12, verify=verify)
            if r.status_code != 200:
                return results
            products = r.json().get("products", [])
            if not products:
                return results
            results += products
            if len(products) < 250:
                return results
            page += 1
        except Exception as e:
            return results
    return results


def fetch_shopify(dealer):
    base    = dealer["base_url"].rstrip("/")
    results = []
    seen    = set()

    def add(products, from_sale_collection=False):
        for p in products:
            title    = p.get("title", "")
            variants = p.get("variants", [])
            if not variants:
                continue

            prices   = [float(v["price"]) for v in variants if v.get("price")]
            compares = [float(v["compare_at_price"]) for v in variants
                        if v.get("compare_at_price") and float(v["compare_at_price"]) > 0]

            if not prices:
                continue

            sale_price = min(prices)
            orig_price = max(compares) if compares else None
            on_sale    = bool(orig_price and orig_price > sale_price)
            pct        = int((orig_price - sale_price) / orig_price * 100) if on_sale else 0

            # Varer fra sale-collection er på tilbud selvom compare_at_price mangler
            if from_sale_collection and not on_sale:
                on_sale = True

            handle = p.get("handle", "")
            url    = f"{base}/products/{handle}"
            if url in seen:
                continue
            seen.add(url)

            results.append({
                "dealer":       dealer["name"],
                "title":        title,
                "price":        sale_price,
                "orig_price":   orig_price,
                "discount_pct": pct,
                "on_sale":      on_sale,
                "url":          url,
            })

    # 1) Standard collections — kun med eksplicit rabat
    for col in DEFAULT_COLLECTIONS:
        products = _shopify_products(base, col)
        if products:
            add(products, from_sale_collection=False)
            break  # Stop ved første fungerende collection

    # 2) Sale collections — returner alt herfra (selv uden compare_at_price)
    for col in dealer.get("sale_collections", []):
        products = _shopify_products(base, col)
        if products:
            add(products, from_sale_collection=True)

    return results


# ── Playwright auto-discovery ────────────────────────────────────────────────

def parse_price(text):
    if not text:
        return None
    cleaned = re.sub(r"[^\d]", "", text.replace(".", "").replace(",", ""))
    return float(cleaned) if cleaned else None


async def scrape_url(pw, url, dealer_name, is_sale_page=False):
    results = []
    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx     = await browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="da-DK",
        extra_http_headers={"Accept-Language": "da-DK,da;q=0.9"},
    )
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000)
        raw = await page.evaluate(FIND_PRODUCTS_JS)

        for item in raw:
            price = parse_price(item.get("price", ""))
            orig  = parse_price(item.get("original_price"))
            on_sale = bool(orig and orig > (price or 0))
            pct     = int((orig - price) / orig * 100) if on_sale else 0

            # Sider på sale-URL er per definition på tilbud
            if is_sale_page and not on_sale:
                on_sale = True

            if not price:
                continue

            results.append({
                "dealer":       dealer_name,
                "title":        item["title"],
                "price":        price,
                "orig_price":   orig,
                "discount_pct": pct,
                "on_sale":      on_sale,
                "url":          item["url"],
            })
    except Exception as e:
        print(f"    Playwright fejl ({dealer_name}, {url}): {e}")
    finally:
        await browser.close()
    return results


async def fetch_playwright_async(dealer):
    results = []
    seen    = set()

    async with async_playwright() as pw:
        # Scrape primær URL
        primary = await scrape_url(pw, dealer["url"], dealer["name"], is_sale_page=False)
        for item in primary:
            seen.add(item["url"])
            results.append(item)

        # Scrape sale-URL hvis defineret
        sale_url = dealer.get("sale_url")
        if sale_url:
            sale = await scrape_url(pw, sale_url, dealer["name"], is_sale_page=True)
            for item in sale:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    results.append(item)

    return results


def fetch_playwright(dealer):
    return asyncio.run(fetch_playwright_async(dealer))


# ── Samler alt ───────────────────────────────────────────────────────────────

def fetch_all(config):
    results = []
    dealers = [d for d in config.get("dealers", []) if d.get("active", True)]

    for dealer in dealers:
        name  = dealer["name"]
        dtype = dealer.get("type", "playwright")
        sale_hint = f" + {len(dealer.get('sale_collections',[]))} sale-cols" if dealer.get("sale_collections") else ""
        if dealer.get("sale_url"):
            sale_hint = " + sale-URL"
        print(f"  [{dtype}] {name}{sale_hint}...")
        try:
            data = fetch_shopify(dealer) if dtype == "shopify" else fetch_playwright(dealer)
            on_sale_count = sum(1 for d in data if d.get("on_sale"))
            print(f"    -> {len(data)} produkter ({on_sale_count} på tilbud)")
            results += data
        except Exception as e:
            print(f"    -> FEJL: {e}")

    # Dedupliker på URL
    seen, unique = set(), []
    for item in results:
        k = item.get("url", item.get("title", ""))
        if k not in seen:
            seen.add(k)
            unique.append(item)

    return unique
