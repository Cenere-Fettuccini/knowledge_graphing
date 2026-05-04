"""Quota Scraper — pulls live rate limit headroom from Google AI Studio dashboard."""

import asyncio
import logging
import os
from typing import Dict
from playwright.async_api import async_playwright
from src.core.config import settings

logger = logging.getLogger(__name__)

class QuotaScraper:
    """
    Automated scraper for Google AI Studio.
    Requires a logged-in session in the specified browser profile.
    """

    def __init__(self, profile_path: str | None = None):
        self.profile_path = profile_path or os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default")
        self.url = "https://aistudio.google.com/app/plan_management"

    async def scrape_limits(self) -> Dict[str, Dict[str, int]]:
        """
        Navigates to AI Studio and extracts RPM/TPM/RPD metrics.
        Returns mapping: model_id -> { "rpm_left": int, "rpd_left": int, ... }
        """
        results = {}
        
        async with async_playwright() as p:
            # We use launch_persistent_context to share the user's login session
            try:
                browser = await p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_path,
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                
                page = await browser.new_page()
                logger.info("Navigating to AI Studio Plan Management...")
                await page.goto(self.url, wait_until="networkidle")
                
                # Wait for the quota cards to appear
                # Note: These selectors are based on current AI Studio DOM and may need updates
                await page.wait_for_selector(".quota-card", timeout=10000)
                
                cards = await page.query_selector_all(".quota-card")
                for card in cards:
                    title_elem = await card.query_selector(".model-name")
                    if not title_elem: continue
                    
                    model_name = await title_elem.inner_text()
                    model_id = "models/" + model_name.lower().replace(" ", "-")
                    
                    # Extract values (e.g. "12 / 15 RPM")
                    # This is highly dependent on the UI layout
                    metrics = {}
                    rpm_text = await card.eval_on_selector(".rpm-value", "el => el.innerText")
                    if rpm_text:
                        # Parse "12 / 15" -> left = 15 - 12
                        used, total = map(int, rpm_text.split("/")[:2])
                        metrics["rpm_left"] = total - used
                        
                    results[model_id] = metrics
                
                await browser.close()
            except Exception as e:
                logger.error("Quota scraping failed: %s", e)
                
        return results

    def run_sync(self):
        """Helper to run the async scraper in a synchronous context."""
        return asyncio.run(self.scrape_limits())
