"""
Scraper med to strategier:
  - shopify:    Henter products.json direkte (hurtig, ingen browser)
  - playwright: Starter en rigtig browser, korer JS, finder produkter automatisk
"""

import asyncio
import re
import requests
import urllib3
from bs4 import BeautifulSoup
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

SHOPIFY_COLLECTIONS = [
    "mountainbike", "mountain-bike", "mtb",
    "cykler", "fahrraeder", "velos", "all",
]

# JavaScript der korer inde i browseren og finder produkter automatisk
FIND_PRODUCTS_JS = """
() => {
    const results = [];
    const priceRe = /\\d[\\d.,]+\\s*(kr\\.?|dkk|€|eur)/i;
    const seen = new Set();

    // Find alle elementer med pris-lignende tekst
    document.querySelectorAll('*').forEach(el => {
        const own = (el.childNodes[0] || {}).textContent || '';
        if (!priceRe.test(own) || own.length > 60) return;

        // Gaa op i DOM til vi finder container med heading + link
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

                // Find original pris (gennemstreget)
                const crossed = node.querySelector('s, del, [class*="old"], [class*="was"], [class*="before"], [class*="original"], [class*="compare"]');

                results.push({
                    title:         h.innerText.trim().split('\\n')[0],
                    price:         own.trim(),
                    original_price: crossed ? crossed.innerText.trim() : null,
                    url:           url
                });
                break;
            }
        }
    });

    return results;
}
"""


# ── Shopify JSON API ─────────────────────────────────────────────────────────

def fetch_shopify(dealer):
    base = dealer["base_url"].rstrip("/")
    results = []

    for collection in SHOPIFY_COLLECTIONS:
        page, found = 1, False
        while True:
            url = f"{base}/collections/{collection}/products.json?limit=250&page={page}"
            try:
                r = requests.get(url, headers=HEADERS, timeout=12, verify=False)
                if r.status_code != 200:
                    break
                products = r.json().get("products", [])
                if not products:
                    break

                for p in products:
                    title = p.get("title", "")
                    variants = p.get("variants", [])
                    if not variants:
                        continue

                    prices   = [float(v["price"]) for v in variants if v.get("price")]
                    compares = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]

                    if not prices:
                        continue

                    sale_price = min(prices)
                    orig_price = max(compares) if compares else None
                    on_sale    = orig_price and orig_price > sale_price

                    pct = int((orig_price - sale_price) / orig_price * 100) if on_sale else 0

                    handle = p.get("handle", "")
                    results.append({
                        "dealer":       dealer["name"],
                        "title":        title,
                        "price":        sale_price,
                        "orig_price":   orig_price,
                        "discount_pct": pct,
                        "on_sale":      bool(on_sale),
                        "url":          f"{base}/products/{handle}",
                    })
                    found = True

                if len(products) < 250:
                    break
                page += 1

            except Exception as e:
                print(f"    Shopify fejl ({collection}): {e}")
                break

        if found:
            break  # Fandt produkter i denne collection — stop

    return results


# ── Playwright auto-discovery ────────────────────────────────────────────────

def parse_price(text):
    """'12.499 kr.' → 12499.0"""
    cleaned = re.sub(r"[^\d,.]", "", text.replace(".", "").replace(",", "."))
    try:
        return float(cleaned)
    except ValueError:
        return None


async def fetch_playwright_async(dealer):
    results = []
    url = dealer.get("url", "")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="da-DK",
            extra_http_headers={"Accept-Language": "da-DK,da;q=0.9"},
        )
        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Vent paa at siden er naesten klar
            await page.wait_for_timeout(3000)

            raw = await page.evaluate(FIND_PRODUCTS_JS)

            for item in raw:
                price    = parse_price(item.get("price", ""))
                orig_raw = item.get("original_price")
                orig     = parse_price(orig_raw) if orig_raw else None
                on_sale  = bool(orig and orig > (price or 0))
                pct      = int((orig - price) / orig * 100) if on_sale else 0

                if not price:
                    continue

                results.append({
                    "dealer":       dealer["name"],
                    "title":        item["title"],
                    "price":        price,
                    "orig_price":   orig,
                    "discount_pct": pct,
                    "on_sale":      on_sale,
                    "url":          item["url"],
                })

        except Exception as e:
            print(f"    Playwright fejl ({dealer['name']}): {e}")
        finally:
            await browser.close()

    return results


def fetch_playwright(dealer):
    return asyncio.run(fetch_playwright_async(dealer))


# ── Samler alt ───────────────────────────────────────────────────────────────

def fetch_all(config):
    results = []
    dealers = [d for d in config.get("dealers", []) if d.get("active", True)]

    for dealer in dealers:
        name = dealer["name"]
        dtype = dealer.get("type", "playwright")
        print(f"  [{dtype}] {name}...")
        try:
            if dtype == "shopify":
                data = fetch_shopify(dealer)
            else:
                data = fetch_playwright(dealer)
            print(f"    -> {len(data)} produkter")
            results += data
        except Exception as e:
            print(f"    -> FEJL: {e}")

    # Dedupliker paa URL
    seen, unique = set(), []
    for item in results:
        k = item.get("url", item.get("title", ""))
        if k not in seen:
            seen.add(k)
            unique.append(item)

    return unique
