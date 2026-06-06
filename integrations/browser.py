"""Headless browser automation via Playwright (computer-use style).

For pages that need JavaScript to render (or interaction) where plain requests +
BeautifulSoup fall short. Playwright is imported lazily and is optional; if it's
not installed the tools return clear setup guidance instead of crashing.

Setup:  pip install playwright   &&   python -m playwright install chromium
"""
import logging

logger = logging.getLogger(__name__)

SETUP_HINT = ("Browser automation needs Playwright. Run: "
              "pip install playwright && python -m playwright install chromium")


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def fetch_rendered(url: str, max_chars: int = 6000, wait_ms: int = 1500) -> dict:
    """Render a page with a headless browser and return its visible text."""
    if not available():
        return {"error": SETUP_HINT}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            title = page.title()
            text = page.inner_text("body")
            browser.close()
        return {"url": url, "title": title, "text": " ".join(text.split())[:max_chars]}
    except Exception as e:
        logger.error(f"[browser] fetch_rendered failed: {e}")
        return {"error": f"Browser fetch failed: {e}"}
