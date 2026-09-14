import os
import time
import urllib.parse
from playwright.sync_api import sync_playwright

BASE_DOMAIN = "https://www.autodoc.de"

# Product cards use <div data-product-item data-article-id="..."> (listing view)
# and <div class="listing-item-inline" data-article-id="..."> (catalog view).
CARD_SELECTOR = "div[data-article-id][data-product-item], div.listing-item-inline[data-article-id]"

CHALLENGE_MARKERS = ("nur einen moment", "just a moment", "checking your browser")

# NOTE: no custom user agent here on purpose. Playwright's default UA matches
# its bundled Chromium version exactly; a hardcoded Chrome/126 UA while running
# Chromium 151 is an instant Cloudflare bot flag (engine/UA mismatch).


def build_search_url(part: str, brand: str, model: str) -> str:
    """Builds the Autodoc keyword-search URL from the part / brand / model inputs."""
    keyword = " ".join(filter(None, (part, brand, model)))
    return f"{BASE_DOMAIN}/search?keyword={urllib.parse.quote(keyword)}"


def _dismiss_overlays(page):
    """Removes cookie/consent overlays that can cover the product grid."""
    try:
        page.evaluate("""() => {
            const els = document.querySelectorAll(
                '[class*="cookie"], [id*="cookie"], [class*="consent"], ' +
                'div[class*="overlay"], #turnstileContainer'
            );
            els.forEach(el => el.remove());
            document.body.style.overflow = 'auto';
        }""")
    except Exception:
        pass


def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        return ""


def _is_challenge(page) -> bool:
    text = f"{_body_text(page)} {page.title().lower()}"
    return any(marker in text for marker in CHALLENGE_MARKERS)


def _await_results(page, search_url: str, attempt_timeout: int = 45, retries: int = 3) -> bool:
    """Loads the search URL and waits until product cards render, reloading past
    Cloudflare challenges. Returns True if cards are present, False if blocked
    or the search legitimately returned no results."""
    for attempt in range(1, retries + 1):
        print(f"  attempt {attempt}: {search_url}")
        try:
            page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"  navigation error: {e}")

        deadline = time.time() + attempt_timeout
        while time.time() < deadline:
            try:
                page.wait_for_selector(CARD_SELECTOR, timeout=6000)
                _dismiss_overlays(page)
                return True
            except Exception:
                pass

            body = _body_text(page)
            if _is_challenge(page):
                print("  Cloudflare challenge detected, waiting for it to resolve...")
                # The challenge JS auto-reloads the page once solved; keep the
                # attempt alive and poll for cards instead of reloading fresh.
                time.sleep(10)
                continue
            if "keine treffer" in body or "no matches" in body:
                print("  no search results on this page")
                return False
            time.sleep(1)

        time.sleep(2)

    return False


def _extract_cards(page):
    """Reads all product cards from the rendered page into plain dicts."""
    return page.evaluate(
        """(selector) => {
            const cards = document.querySelectorAll(selector);
            const seen = new Set();
            const out = [];
            for (const card of cards) {
                const articleId = card.getAttribute('data-article-id');
                if (!articleId || seen.has(articleId)) continue;
                seen.add(articleId);

                const nameLink = card.querySelector(
                    'a.listing-item-inline__product-name, a.listing-item__product-name'
                );
                const imageLink = card.querySelector('a.listing-item-inline__image-main');
                const linkEl = nameLink || imageLink;

                let url = '';
                let title = '';
                if (linkEl) {
                    url = linkEl.href || '';
                    title = (linkEl.textContent || '').replace(/\\s+/g, ' ').trim();
                }
                if (!title) {
                    title = (card.getAttribute('data-generic-name') || '').trim();
                }

                const sale = parseFloat(card.getAttribute('data-price'));
                if (isNaN(sale) || sale <= 0) continue;

                const origAttr = card.getAttribute('data-original-price');
                const retail = origAttr ? parseFloat(origAttr) : NaN;

                const productImg = card.querySelector('a.listing-item-inline__image-main img')
                    || card.querySelector('img[src*="cdn.autodoc.de/thumb"]');
                let image = '';
                const allImgs = productImg ? [productImg] : [...card.querySelectorAll('img')];
                let best = '';
                let bestScore = 0;
                for (const img of allImgs) {
                    const candidates = [
                        img.currentSrc || '',
                        img.src || '',
                        img.getAttribute('data-src') || '',
                    ];
                    const srcset = (img.getAttribute('data-srcset') || img.getAttribute('srcset') || '')
                        .split(',');
                    for (const s of srcset) {
                        const part = (s.trim().split(' ')[0] || '');
                        if (part) candidates.push(part);
                    }
                    for (const c of candidates) {
                        if (!c) continue;
                        if (c.includes('brands/thumbs')) continue;
                        const isPhoto = c.includes('media.autodoc.de') || c.includes('cdn.autodoc.de/thumb');
                        if (!isPhoto) continue;
                        const score = c.includes('360_photos') ? 2 : 1;
                        if (score > bestScore) {
                            bestScore = score;
                            best = c;
                        }
                    }
                }
                image = best;

                out.push({
                    'article_id': articleId,
                    'url': url,
                    'title': title,
                    'sale_price': sale,
                    'retail_price': isNaN(retail) ? null : retail,
                    'image_url': image,
                    'currency': card.getAttribute('data-currency-origin') || 'EUR'
                });
            }
            return out;
        }""",
        CARD_SELECTOR,
    )


def search_autodoc_part(part: str, brand: str, model: str, limit: int = 5,
                        headless: bool = False, visible: bool = False,
                        retries: int = 3):
    """Searches Autodoc for the part and returns the cheapest matching deals
    (sale price ascending), each with product_id, title, prices, discount,
    image and raw product URL.

    Autodoc/Cloudflare blocks true headless Chromium, so this runs a real
    renderer. By default (visible=False) the window is placed off-screen so
    nothing pops up in front of the user; set AUTODOC_WINDOW_VISIBLE=1 or
    visible=True to watch it for debugging."""
    search_url = build_search_url(part, brand, model)
    deals = []

    with sync_playwright() as p:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        if not headless and not visible and os.getenv("AUTODOC_WINDOW_VISIBLE", "0") != "1":
            launch_args.append("--window-position=-32000,-32000")
        browser = p.chromium.launch(
            headless=headless,
            args=launch_args,
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 850},
            locale="de-DE",
            timezone_id="Europe/Berlin",
            extra_http_headers={"Accept-Language": "de-DE,de;q=0.9"},
        )
        context.add_init_script("""() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['de-DE', 'de'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = window.chrome || { runtime: {} };
        }""")
        page = context.new_page()

        print(f"Targeting Autodoc search for: {part} | {brand} {model}")

        # Warm up on the homepage so Cloudflare issues a clearance cookie
        # for subsequent requests inside the same browser context.
        try:
            page.goto(f"{BASE_DOMAIN}/", timeout=45000, wait_until="domcontentloaded")
            if _is_challenge(page):
                time.sleep(8)
        except Exception:
            pass

        loaded = _await_results(page, search_url, retries=retries)

        if not loaded:
            print("Autodoc did not return a product listing (blocked or no results).")
            browser.close()
            return deals

        raw_cards = _extract_cards(page)
        print(f"Found {len(raw_cards)} product cards on the page")

        for card in raw_cards:
            if not card["url"] or not card["title"]:
                continue
            retail = card["retail_price"]
            sale = card["sale_price"]
            if retail and retail > sale:
                discount = round(((retail - sale) / retail) * 100, 1)
            else:
                discount = 0.0

            deals.append({
                "product_id": f"autodoc_{card['article_id']}",
                "title": card["title"],
                "sale_price": sale,
                "retail_price": retail if retail else sale,
                "discount_percentage": discount,
                "currency": card["currency"],
                "image_url": card["image_url"],
                "raw_url": card["url"],
                "source": "autodoc",
            })

        browser.close()

    deals.sort(key=lambda d: d["sale_price"])
    return deals[:limit]


if __name__ == "__main__":
    results = search_autodoc_part(
        part="Bremsscheiben", brand="BMW", model="E46", limit=3, visible=True
    )
    if not results:
        print("\nNo deals found.")
    for idx, d in enumerate(results, start=1):
        print(f"\n--- Result #{idx} ---")
        print(f"Title: {d['title']}")
        print(f"Price: {d['sale_price']} €  (RRP {d['retail_price']} €, {d['discount_percentage']}% off)")
        print(f"Image: {d['image_url']}")
        print(f"URL: {d['raw_url']}")