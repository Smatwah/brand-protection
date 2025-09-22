"""
Render & Screenshot: Captures and processes web pages
"""
import asyncio
import os
from datetime import datetime
from typing import Dict, Optional
from playwright.async_api import async_playwright
import logging

logger = logging.getLogger(__name__)

class RenderScreenshot:
    def __init__(self, config):
        self.config = config
        self.playwright = None
        self.browser = None
        self.context = None
    
    async def initialize(self):
        """Initialize browser instance"""
        # If already initialized, skip
        if self.browser and self.context:
            return
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--js-flags=--max-old-space-size=256'
            ]
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1366, 'height': 768},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            ignore_https_errors=getattr(self.config, 'IGNORE_HTTPS_ERRORS', True)
        )
    
    async def capture_screenshot(self, url: str) -> Dict:
        """Capture screenshot and page data"""
        result = {
            'url': url,
            'timestamp': datetime.now().isoformat(),
            'screenshot_path': None,
            'page_title': None,
            'page_content': None,
            'error': None
        }
        
        try:
            page = await self.context.new_page()
            # Set navigation timeout from config
            try:
                page.set_default_navigation_timeout(self.config.PLAYWRIGHT_NAV_TIMEOUT_MS)
            except Exception:
                pass
            # Navigate to URL
            response = await page.goto(
                url,
                wait_until=getattr(self.config, 'PLAYWRIGHT_WAIT_UNTIL', 'domcontentloaded'),
                timeout=getattr(self.config, 'PLAYWRIGHT_NAV_TIMEOUT_MS', 20000)
            )
            
            if response:
                result['status_code'] = response.status
                
                # Wait for content to load
                await asyncio.sleep(2)
                
                # Capture screenshot
                timestamp = int(datetime.now().timestamp())
                screenshot_path = os.path.join(
                    self.config.SCREENSHOTS_DIR,
                    f"screenshot_{timestamp}.png"
                )
                await page.screenshot(
                    path=screenshot_path,
                    full_page=getattr(self.config, 'SCREENSHOT_FULL_PAGE', False)
                )
                result['screenshot_path'] = screenshot_path
                
                # Extract page data
                result['page_title'] = await page.title()
                result['page_content'] = await page.content()
                
                # Extract text content
                result['text_content'] = await page.evaluate('''
                    () => document.body.innerText
                ''')
                
                # Extract images
                images = await page.evaluate('''
                    () => Array.from(document.images).map(img => ({
                        src: img.src,
                        alt: img.alt,
                        width: img.width,
                        height: img.height
                    }))
                ''')
                result['images'] = images
                
                # Extract links
                links = await page.evaluate('''
                    () => Array.from(document.links).map(link => ({
                        href: link.href,
                        text: link.innerText
                    }))
                ''')
                result['links'] = links
            
            await page.close()
            
        except Exception as e:
            logger.error(f"Error capturing screenshot for {url}: {e}")
            result['error'] = str(e)
            # If the browser crashed or connection closed, try one retry with a fresh context
            transient_signals = (
                'Connection closed',
                'Target page, context or browser has been closed',
                'out of memory',
            )
            if any(sig.lower() in str(e).lower() for sig in transient_signals):
                try:
                    await self.cleanup()
                    await self.initialize()
                    # Retry once with same settings
                    page = await self.context.new_page()
                    try:
                        page.set_default_navigation_timeout(self.config.PLAYWRIGHT_NAV_TIMEOUT_MS)
                    except Exception:
                        pass
                    response = await page.goto(
                        url,
                        wait_until=getattr(self.config, 'PLAYWRIGHT_WAIT_UNTIL', 'domcontentloaded'),
                        timeout=getattr(self.config, 'PLAYWRIGHT_NAV_TIMEOUT_MS', 20000)
                    )
                    if response:
                        result['status_code'] = response.status
                        await asyncio.sleep(1)
                        timestamp = int(datetime.now().timestamp())
                        screenshot_path = os.path.join(
                            self.config.SCREENSHOTS_DIR,
                            f"screenshot_{timestamp}.png"
                        )
                        await page.screenshot(
                            path=screenshot_path,
                            full_page=getattr(self.config, 'SCREENSHOT_FULL_PAGE', False)
                        )
                        result['screenshot_path'] = screenshot_path
                        result['page_title'] = await page.title()
                        result['page_content'] = await page.content()
                        result['text_content'] = await page.evaluate('''() => document.body.innerText''')
                        images = await page.evaluate('''() => Array.from(document.images).map(img => ({src: img.src, alt: img.alt, width: img.width, height: img.height}))''')
                        result['images'] = images
                        links = await page.evaluate('''() => Array.from(document.links).map(link => ({href: link.href, text: link.innerText}))''')
                        result['links'] = links
                    await page.close()
                except Exception as e2:
                    logger.error(f"Retry failed for {url}: {e2}")
                    result['error'] = f"initial: {result['error']} | retry: {e2}"

        return result
    
    async def cleanup(self):
        """Clean up browser resources"""
        try:
            if self.context:
                await self.context.close()
        finally:
            self.context = None
        try:
            if self.browser:
                await self.browser.close()
        finally:
            self.browser = None
        try:
            if self.playwright:
                await self.playwright.stop()
        finally:
            self.playwright = None
