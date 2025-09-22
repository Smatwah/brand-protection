"""

Discovery Watchers: Monitors various channels for potential brand impersonation

"""

import asyncio

import json

import time

import re

from datetime import datetime

from typing import List, Dict, Any, Optional

from playwright.async_api import async_playwright

import requests

from requests.auth import HTTPBasicAuth

from bs4 import BeautifulSoup

from pathlib import Path

import logging

from urllib.parse import urlparse, quote_plus, unquote





logger = logging.getLogger(__name__)



DEFAULT_HEADERS = {

    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36',

    'Accept-Language': 'en-US,en;q=0.9',

}



class DiscoveryWatcher:

    def __init__(self, config):

        self.config = config

        self.discovered_items = []

        self.logger = logging.getLogger('bpp.discovery')

        self.logger.setLevel(logging.INFO)

        self.discovery_log_path = Path(getattr(self.config, 'DISCOVERY_LOG_PATH', 'data/logs/discovery_watchers.log'))

        self.error_export_path = Path(getattr(self.config, 'DISCOVERY_ERROR_EXPORT', 'data/logs/watcher_errors.jsonl'))

        self.discovery_log_path.parent.mkdir(parents=True, exist_ok=True)

        self.error_export_path.parent.mkdir(parents=True, exist_ok=True)

        self._maybe_attach_file_handler()

        self._twitter_bearer: Optional[str] = getattr(self.config, 'TWITTER_BEARER_TOKEN', None)

        self._last_twitter_refresh: Optional[float] = None



    def _maybe_attach_file_handler(self) -> None:

        existing_handlers = [

            handler for handler in self.logger.handlers

            if isinstance(handler, logging.FileHandler) and getattr(handler, 'baseFilename', None) == str(self.discovery_log_path)

        ]

        if existing_handlers:

            return

        handler = logging.FileHandler(self.discovery_log_path, encoding='utf-8')

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        handler.setFormatter(formatter)

        self.logger.addHandler(handler)

    def _record_error(self, summary: str, **context: Any) -> None:

        event = {

            'timestamp': datetime.now().isoformat(),

            'summary': summary,

            'context': context,

        }

        try:

            with self.error_export_path.open('a', encoding='utf-8') as fh:

                fh.write(json.dumps(event, ensure_ascii=False) + '\n')

        except Exception as exc:

            self.logger.error('Failed to write discovery error log: %s', exc)

    def _certificate_transparency_url(self) -> str:

        base = getattr(self.config, 'CERTIFICATE_TRANSPARENCY_URL', 'https://crt.sh/')

        if not base.endswith('/'):

            base += '/'

        return base



    def _resolve_twitter_bearer(self) -> Optional[str]:

        if self._twitter_bearer and (self._last_twitter_refresh is None or time.time() - self._last_twitter_refresh < 3300):

            return self._twitter_bearer

        token = getattr(self.config, 'TWITTER_BEARER_TOKEN', None)

        if token:

            self._twitter_bearer = token

            self._last_twitter_refresh = time.time()

            return token

        token = self._exchange_twitter_credentials()

        if token:

            self._twitter_bearer = token

            self._last_twitter_refresh = time.time()

        return self._twitter_bearer



    def _exchange_twitter_credentials(self) -> Optional[str]:

        client_id = getattr(self.config, 'TWITTER_CLIENT_ID', None)

        client_secret = getattr(self.config, 'TWITTER_CLIENT_SECRET', None)

        refresh_token = getattr(self.config, 'TWITTER_REFRESH_TOKEN', None)

        api_key = getattr(self.config, 'TWITTER_API_KEY', None)

        api_secret = getattr(self.config, 'TWITTER_API_SECRET', None)

        if client_id and refresh_token:

            try:

                payload = {

                    'client_id': client_id,

                    'grant_type': 'refresh_token',

                    'refresh_token': refresh_token,

                }

                scope = getattr(self.config, 'TWITTER_SCOPE', None)

                if scope:

                    payload['scope'] = scope

                response = requests.post('https://api.twitter.com/2/oauth2/token', data=payload, timeout=20)

                if response.status_code == 200:

                    data = response.json()

                    token = data.get('access_token')

                    if token:

                        self.logger.info('Refreshed Twitter OAuth2 access token via client refresh flow.')

                        return token

                else:

                    self._record_error('twitter_oauth_refresh_failed', status=response.status_code, body=response.text[:120])

            except Exception as exc:

                self._record_error('twitter_oauth_refresh_exception', error=str(exc))

        if api_key and api_secret:

            try:

                response = requests.post(

                    'https://api.twitter.com/oauth2/token',

                    data={'grant_type': 'client_credentials'},

                    auth=(api_key, api_secret),

                    timeout=15,

                )

                if response.status_code == 200:

                    data = response.json()

                    token = data.get('access_token')

                    if token:

                        self.logger.info('Obtained Twitter bearer token via app-only auth.')

                        return token

                else:

                    self._record_error('twitter_client_credentials_failed', status=response.status_code, body=response.text[:120])

            except Exception as exc:

                self._record_error('twitter_client_credentials_exception', error=str(exc))

        return None



    def _is_valid_url(self, url: str) -> bool:

        """Validate if URL is properly formatted and doesn't contain invalid characters"""

        try:

            parsed = urlparse(url)

            # Must have scheme and netloc

            if not parsed.scheme or not parsed.netloc:

                return False

            # Domain should not contain '@' or other invalid chars

            domain = parsed.netloc

            if '@' in domain or ' ' in domain:

                return False

            # Basic check for valid domain format

            return len(domain.split('.')) >= 2

        except:

            return False





    async def watch_transparency_reports(self) -> List[Dict]:

        """Monitor certificate transparency logs"""

        discovered: List[Dict] = []

        ct_url: Optional[str] = None

        try:

            brand_query = quote_plus(self.config.BRAND_NAME)

            ct_url = f"{self._certificate_transparency_url()}?q=%25{brand_query}%25&output=json"

            timeout = getattr(self.config, 'DISCOVERY_REQUEST_TIMEOUT_SECONDS', 30)

            response = requests.get(ct_url, timeout=timeout)



            if response.status_code == 200:

                certs = response.json()

                for cert in certs:

                    domain = cert.get('name_value', '')

                    if self._is_suspicious_domain(domain):

                        url = f"https://{domain}"

                        if self._is_valid_url(url):

                            discovered.append({

                                'source': 'certificate_transparency',

                                'type': 'domain',

                                'url': url,

                                'timestamp': datetime.now().isoformat(),

                                'risk_indicators': self._analyze_domain_risk(domain),

                            })

                        else:

                            self.logger.warning('Skipping invalid URL from CT: %s', url)

            else:

                self._record_error('ct_watch_http_error', status=response.status_code, url=ct_url)

        except Exception as exc:

            self._record_error('ct_watch_exception', error=str(exc), url=ct_url)

            self.logger.error('Error monitoring CT logs: %s', exc)



        return discovered



    async def watch_typosquatting(self) -> List[Dict]:

        """Generate and check typosquatting variants"""

        discovered = []

        variants = self._generate_typo_variants(self.config.BRAND_NAME)

        

        for variant in variants:

            domains_to_check = [f"{variant}.com", f"{variant}.org", f"{variant}.net"]

            for domain in domains_to_check:

                if self._check_domain_exists(domain):

                    url = f"https://{domain}"

                    if self._is_valid_url(url):

                        discovered.append({

                            'source': 'typosquatting',

                            'type': 'domain',

                            'url': url,

                            'timestamp': datetime.now().isoformat(),

                            'variant_type': 'typosquatting'

                        })

                    else:

                        self.logger.warning(f"Skipping invalid URL from typosquatting: {url}")

        

        return discovered

    

    async def watch_web_mentions(self) -> List[Dict]:

        """Scrape the open web for brand mentions."""

        discovered: List[Dict] = []

        if not getattr(self.config, 'ENABLE_WEB_DISCOVERY', True):

            self.logger.info("Web discovery watcher disabled. Set ENABLE_WEB_DISCOVERY=1 to enable.")

            return discovered



        queries = self._build_brand_queries()

        engines = getattr(self.config, 'WEB_DISCOVERY_ENGINES', ['duckduckgo', 'bing', 'google_news'])

        tasks = [asyncio.to_thread(self._run_web_search, engine, query) for engine in engines for query in queries]



        seen_urls = set()

        for result in await asyncio.gather(*tasks, return_exceptions=True):

            if isinstance(result, Exception):

                self._record_error('web_discovery_exception', error=str(result))

                self.logger.error('Web discovery error: %s', result)

                continue

            for item in result:

                url = item.get('url')

                if not url or url in seen_urls:

                    continue

                if self._is_official_domain(url) or not self._is_valid_url(url):

                    continue

                seen_urls.add(url)

                discovered.append(item)



        return discovered



    async def watch_visual_mentions(self) -> List[Dict]:

        """Scrape image-focused sources for potential logo usage."""

        discovered: List[Dict] = []

        if not getattr(self.config, 'ENABLE_SOCIAL_IMAGE_DISCOVERY', True):

            self.logger.info("Visual discovery watcher disabled. Set ENABLE_SOCIAL_IMAGE_DISCOVERY=1 to enable.")

            return discovered



        queries = self._build_brand_queries(include_logo_variants=True)

        engines = getattr(self.config, 'IMAGE_DISCOVERY_ENGINES', ['bing_images', 'duckduckgo_images'])

        tasks = [asyncio.to_thread(self._run_image_search, engine, query) for engine in engines for query in queries]



        seen_pairs = set()

        for result in await asyncio.gather(*tasks, return_exceptions=True):

            if isinstance(result, Exception):

                self._record_error('image_discovery_exception', error=str(result))

                self.logger.error('Visual discovery error: %s', result)

                continue

            for item in result:

                primary_key = (item.get('url'), item.get('media_url'))

                if not primary_key[0] or primary_key in seen_pairs:

                    continue

                if self._is_official_domain(item.get('url', '')):

                    continue

                seen_pairs.add(primary_key)

                discovered.append(item)



        # Optional platform-specific scrapes (e.g., Reddit, Pinterest)

        platforms = getattr(self.config, 'SOCIAL_IMAGE_PLATFORMS', ['reddit', 'pinterest'])

        for platform in platforms:

            for query in queries:

                try:

                    platform_results = await asyncio.to_thread(self._scrape_social_images, platform, query)

                    for item in platform_results:

                        key = (item.get('url'), item.get('media_url'))

                        if not key[0] or key in seen_pairs:

                            continue

                        seen_pairs.add(key)

                        discovered.append(item)

                except Exception as platform_err:

                    self._record_error('image_platform_exception', platform=platform, error=str(platform_err))

                    self.logger.error('Image discovery error for %s: %s', platform, platform_err)



        return discovered



    async def watch_social_media(self) -> List[Dict]:

        """Monitor social media for brand mentions"""

        discovered = []

        if not getattr(self.config, 'ENABLE_SOCIAL_MEDIA', False):

            self.logger.info("Social media monitoring disabled. Set ENABLE_SOCIAL_MEDIA=1 to enable.")

            return discovered

        platforms = ['twitter', 'facebook', 'instagram', 'linkedin']

        

        async with async_playwright() as p:

            # Launch hardened browser once; we will recreate it if it crashes

            browser = await p.chromium.launch(

                headless=True,

                args=[

                    '--no-sandbox',

                    '--disable-setuid-sandbox',

                    '--disable-dev-shm-usage',

                    '--disable-gpu',

                    '--js-flags=--max-old-space-size=256'

                ]

            )

            for platform in platforms:

                # Allow one retry if the browser/context closes unexpectedly

                for attempt in (1, 2):

                    context = None

                    page = None

                    try:

                        search_url = self._get_social_search_url(platform)

                        if not search_url:

                            break

                        # Isolate each platform in its own context

                        context = await browser.new_context(

                            viewport={'width': 1366, 'height': 768},

                            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',

                            ignore_https_errors=getattr(self.config, 'IGNORE_HTTPS_ERRORS', True)

                        )

                        page = await context.new_page()

                        # Respect configured timeouts and wait conditions

                        try:

                            page.set_default_navigation_timeout(self.config.PLAYWRIGHT_NAV_TIMEOUT_MS)

                        except Exception:

                            pass

                        await page.goto(

                            search_url,

                            wait_until=getattr(self.config, 'PLAYWRIGHT_WAIT_UNTIL', 'domcontentloaded'),

                            timeout=getattr(self.config, 'PLAYWRIGHT_NAV_TIMEOUT_MS', 20000)

                        )

                        await asyncio.sleep(2)



                        # Take screenshot for analysis

                        screenshot_path = f"{self.config.SCREENSHOTS_DIR}/{platform}_{int(time.time())}.png"

                        await page.screenshot(path=screenshot_path)



                        # Extract potential impersonation accounts

                        content = await page.content()

                        suspicious_accounts = self._extract_suspicious_accounts(content, platform)



                        for account in suspicious_accounts:

                            discovered.append({

                                'source': 'social_media',

                                'platform': platform,

                                'type': 'account',

                                'url': account['url'],

                                'username': account['username'],

                                'screenshot': screenshot_path,

                                'timestamp': datetime.now().isoformat()

                            })

                        # Success; don't retry

                        break

                    except Exception as e:

                        self._record_error('social_platform_exception', platform=platform, error=str(e), attempt=attempt)

                        self.logger.error('Error monitoring %s: %s', platform, e)

                        # If browser/context/page closed, try to relaunch once

                        transient = (

                            'Target page, context or browser has been closed',

                            'Connection closed',

                        )

                        if attempt == 1 and any(sig.lower() in str(e).lower() for sig in transient):

                            # Clean up and recreate browser before retry

                            try:

                                if page:

                                    await page.close()

                            except Exception:

                                pass

                            try:

                                if context:

                                    await context.close()

                            except Exception:

                                pass

                            try:

                                await browser.close()

                            except Exception:

                                pass

                            browser = await p.chromium.launch(

                                headless=True,

                                args=[

                                    '--no-sandbox',

                                    '--disable-setuid-sandbox',

                                    '--disable-dev-shm-usage',

                                    '--disable-gpu',

                                    '--js-flags=--max-old-space-size=256'

                                ]

                            )

                            continue  # retry

                        else:

                            break  # don't retry for non-transient errors

                    finally:

                        try:

                            if page:

                                await page.close()

                        except Exception:

                            pass

                        try:

                            if context:

                                await context.close()

                        except Exception:

                            pass

            try:

                await browser.close()

            except Exception:

                pass

        

        return discovered

    

    def _is_official_domain(self, url: str) -> bool:

        """Return True if the URL belongs to an official brand domain."""

        try:

            netloc = urlparse(url).netloc.lower()

            if not netloc:

                return False

            if ':' in netloc:

                netloc = netloc.split(':', 1)[0]

            if netloc.startswith('www.'):

                netloc = netloc[4:]

            official_domains = [d.lower() for d in getattr(self.config, 'BRAND_DOMAINS', [])]

            return any(netloc == domain or netloc.endswith(f".{domain}") for domain in official_domains)

        except Exception:

            return False



    def _build_brand_queries(self, include_logo_variants: bool = False) -> List[str]:

        """Generate search queries using brand keywords and optional logo modifiers."""

        keywords = {self.config.BRAND_NAME}

        keywords.update(getattr(self.config, 'BRAND_KEYWORDS', []))

        queries = set()



        suffixes = ['']

        if include_logo_variants:

            suffixes.extend(['logo', 'brand logo', 'official logo', 'profile picture', 'avatar'])

        else:

            suffixes.extend(['review', 'login', 'promotion', 'giveaway', 'signup'])



        for keyword in keywords:

            keyword = keyword.strip()

            if not keyword:

                continue

            queries.add(keyword)

            for suffix in suffixes[1:]:

                queries.add(f"{keyword} {suffix}".strip())

            hashtag = keyword.replace(' ', '')

            if include_logo_variants:

                queries.add(f"#{hashtag}")



        return sorted(queries)



    def _run_web_search(self, engine: str, query: str) -> List[Dict]:

        """Run a single web search synchronously and return discovered URLs."""

        items: List[Dict] = []

        try:

            if engine == 'google_news':

                search_url = (

                    f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"

                )

                response = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=20)

                if response.status_code != 200:

                    return items

                soup = BeautifulSoup(response.text, 'xml')

                for entry in soup.find_all('item')[:20]:

                    link_tag = entry.find('link')

                    link = link_tag.get_text(strip=True) if link_tag else ''

                    if not link:

                        continue

                    title_tag = entry.find('title')

                    description_tag = entry.find('description')

                    items.append({

                        'source': 'web_google_news',

                        'type': 'web_mention',

                        'url': link,

                        'timestamp': datetime.now().isoformat(),

                        'title': title_tag.get_text(strip=True) if title_tag else query,

                        'snippet': description_tag.get_text(strip=True) if description_tag else '',

                        'query': query,

                        'risk_indicators': ['brand_mention']

                    })

                return items



            if engine == 'duckduckgo':

                search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

                response = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=20)

                if response.status_code != 200:

                    return items

                soup = BeautifulSoup(response.text, 'html.parser')

                for result in soup.select('div.result'):

                    link_tag = result.find('a', class_='result__a')

                    if not link_tag:

                        continue

                    href = link_tag.get('href')

                    if href and 'uddg=' in href:

                        href = href.split('uddg=')[-1]

                        href = unquote(href)

                    snippet_tag = result.find('a', class_='result__snippet') or result.find('div', class_='result__snippet')

                    items.append({

                        'source': 'web_duckduckgo',

                        'type': 'web_mention',

                        'url': href,

                        'timestamp': datetime.now().isoformat(),

                        'title': link_tag.get_text(strip=True),

                        'snippet': snippet_tag.get_text(strip=True) if snippet_tag else '',

                        'query': query,

                        'risk_indicators': ['brand_mention']

                    })

                return items



            # Default or Bing

            search_url = f"https://www.bing.com/search?q={quote_plus(query)}"

            response = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=20)

            if response.status_code != 200:

                return items

            soup = BeautifulSoup(response.text, 'html.parser')

            for result in soup.select('li.b_algo'):

                link_tag = result.find('a')

                if not link_tag:

                    continue

                href = link_tag.get('href')

                snippet_tag = result.find('p')

                items.append({

                    'source': f'web_{engine}',

                    'type': 'web_mention',

                    'url': href,

                    'timestamp': datetime.now().isoformat(),

                    'title': link_tag.get_text(strip=True),

                    'snippet': snippet_tag.get_text(strip=True) if snippet_tag else '',

                    'query': query,

                    'risk_indicators': ['brand_mention']

                })

        except Exception as exc:

            self._record_error('web_search_exception', engine=engine, error=str(exc))

            self.logger.error('Web search failure (%s): %s', engine, exc)

        return items



    def _run_image_search(self, engine: str, query: str) -> List[Dict]:

        """Run an image search synchronously and return candidate image posts."""

        items: List[Dict] = []

        try:

            if engine == 'duckduckgo_images':

                search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&iar=images&iax=images&ia=images"

                response = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=20)

                if response.status_code != 200:

                    return items

                soup = BeautifulSoup(response.text, 'html.parser')

                for tile in soup.select('div.tile--img__img'):

                    data_link = tile.get('data-id') or tile.get('href')

                    if not data_link:

                        continue

                    link = tile.get('data-href') or data_link

                    img_tag = tile.find('img') if hasattr(tile, 'find') else None

                    media_url = img_tag.get('data-src') if img_tag else None

                    if not media_url:

                        continue

                    items.append({

                        'source': 'image_duckduckgo',

                        'type': 'visual_mention',

                        'url': link,

                        'media_url': media_url,

                        'timestamp': datetime.now().isoformat(),

                        'query': query,

                        'risk_indicators': ['potential_logo_usage']

                    })

                return items



            # Default to Bing Images

            search_url = f"https://www.bing.com/images/search?q={quote_plus(query)}"

            response = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=20)

            if response.status_code != 200:

                return items

            soup = BeautifulSoup(response.text, 'html.parser')

            for anchor in soup.select('a.iusc'):

                metadata_raw = anchor.get('m')

                if not metadata_raw:

                    continue

                try:

                    metadata = json.loads(metadata_raw)

                except Exception:

                    continue

                media_url = metadata.get('murl')

                page_url = metadata.get('purl') or anchor.get('href')

                if not media_url or not page_url:

                    continue

                items.append({

                    'source': f'image_{engine}',

                    'type': 'visual_mention',

                    'url': page_url,

                    'media_url': media_url,

                    'thumbnail_url': metadata.get('turl'),

                    'timestamp': datetime.now().isoformat(),

                    'query': query,

                    'risk_indicators': ['potential_logo_usage']

                })

        except Exception as exc:

            self._record_error('image_search_exception', engine=engine, error=str(exc))

            self.logger.error('Image search failure (%s): %s', engine, exc)

        return items



    def _scrape_social_images(self, platform: str, query: str) -> List[Dict]:

        """Scrape social/image platforms for brand-related visuals."""

        platform = platform.lower().strip()

        if platform in ('reddit', 'reddit_anon'):

            return self._scrape_reddit_images(query)

        if platform in ('reddit_auth', 'reddit_api'):

            return self._scrape_reddit_images_authenticated(query)

        if platform == 'twitter':

            return self._scrape_twitter_images(query)

        if platform == 'instagram':

            return self._scrape_instagram_images(query)

        if platform == 'pinterest':

            return self._scrape_pinterest_images(query)

        return []







    def _scrape_reddit_images_authenticated(self, query: str) -> List[Dict]:

        items: List[Dict] = []

        token = self._reddit_get_access_token()

        if not token:

            return items



        headers = {**DEFAULT_HEADERS, 'Authorization': f'Bearer {token}', 'User-Agent': 'BrandProtectionBot/1.0'}

        params = {

            'q': query,

            'sort': 'new',

            'limit': '25',

            'type': 'link',

            'include_over_18': 'on'

        }

        try:

            response = requests.get('https://oauth.reddit.com/search', headers=headers, params=params, timeout=20)

            if response.status_code != 200:

                self._record_error('reddit_api_error', status=response.status_code, body=response.text[:120])

                self.logger.error('Reddit authenticated search failed (%s): %s', response.status_code, response.text[:120])

                return items

            payload = response.json()

            for child in payload.get('data', {}).get('children', []):

                data = child.get('data', {})

                media_url = None

                if data.get('preview', {}).get('images'):

                    media_url = data['preview']['images'][0]['source'].get('url')

                elif data.get('url_overridden_by_dest') and data['url_overridden_by_dest'].startswith('http'):

                    media_url = data['url_overridden_by_dest']

                if not media_url:

                    continue

                items.append({

                    'source': 'social_reddit_api',

                    'type': 'visual_mention',

                    'url': f"https://www.reddit.com{data.get('permalink', '')}",

                    'media_url': media_url,

                    'timestamp': datetime.now().isoformat(),

                    'title': data.get('title'),

                    'query': query,

                    'risk_indicators': ['potential_logo_usage', 'social_media']

                })

        except Exception as exc:

            self._record_error('reddit_authenticated_exception', error=str(exc))

            self.logger.error('Reddit authenticated scrape failed: %s', exc)

        return items



    def _reddit_get_access_token(self) -> Optional[str]:

        client_id = getattr(self.config, 'REDDIT_CLIENT_ID', None)

        client_secret = getattr(self.config, 'REDDIT_CLIENT_SECRET', None)

        if not client_id or not client_secret:

            self.logger.info('Reddit API credentials not configured; skipping authenticated Reddit scrape.')

            return None

        try:

            auth = HTTPBasicAuth(client_id, client_secret)

            data = {'grant_type': 'client_credentials'}

            headers = {**DEFAULT_HEADERS, 'User-Agent': 'BrandProtectionBot/1.0'}

            response = requests.post('https://www.reddit.com/api/v1/access_token', auth=auth, data=data, headers=headers, timeout=15)

            if response.status_code != 200:

                self._record_error('reddit_token_error', status=response.status_code, body=response.text[:120])

                self.logger.error('Reddit token request failed (%s): %s', response.status_code, response.text[:120])

                return None

            return response.json().get('access_token')

        except Exception as exc:

            self._record_error('reddit_token_exception', error=str(exc))

            self.logger.error('Reddit token request error: %s', exc)

            return None



    def _scrape_reddit_images(self, query: str) -> List[Dict]:

        items: List[Dict] = []

        api_url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&type=link&limit=15"

        try:

            response = requests.get(api_url, headers={**DEFAULT_HEADERS, 'User-Agent': 'BrandProtectionBot/1.0'}, timeout=15)

            if response.status_code != 200:

                return items

            payload = response.json()

            for child in payload.get('data', {}).get('children', []):

                data = child.get('data', {})

                media_url = None

                if data.get('preview', {}).get('images'):

                    media_url = data['preview']['images'][0]['source'].get('url')

                elif data.get('thumbnail') and data['thumbnail'].startswith('http'):

                    media_url = data['thumbnail']

                if not media_url:

                    continue

                permalink = data.get('permalink') or ''

                items.append({

                    'source': 'social_reddit',

                    'type': 'visual_mention',

                    'url': f"https://www.reddit.com{permalink}",

                    'media_url': media_url,

                    'timestamp': datetime.now().isoformat(),

                    'title': data.get('title'),

                    'query': query,

                    'risk_indicators': ['potential_logo_usage']

                })

        except Exception as exc:

            self._record_error('reddit_scrape_exception', error=str(exc))

            self.logger.error('Reddit image scrape failed: %s', exc)

        return items









def _scrape_twitter_images(self, query: str) -> List[Dict]:

    items: List[Dict] = []

    token = self._resolve_twitter_bearer()

    if not token:

        self.logger.info('Twitter API token not configured; skipping Twitter scrape.')

        return items



    params = {

        'query': f"{query} has:images -is:retweet",

        'expansions': 'attachments.media_keys,author_id',

        'media.fields': 'url,preview_image_url,type',

        'tweet.fields': 'created_at,lang',

        'user.fields': 'username,name',

        'max_results': '50',

    }

    headers = {

        'Authorization': f'Bearer {token}',

        'User-Agent': 'BrandProtectionBot/1.0',

    }

    try:

        timeout = getattr(self.config, 'DISCOVERY_REQUEST_TIMEOUT_SECONDS', 30)

        response = requests.get('https://api.twitter.com/2/tweets/search/recent', params=params, headers=headers, timeout=timeout)

        if response.status_code != 200:

            self._record_error('twitter_api_error', status=response.status_code, body=response.text[:120])

            self.logger.error('Twitter API error (%s): %s', response.status_code, response.text[:120])

            return items

        payload = response.json()

        tweets = payload.get('data', [])

        media_index = {m['media_key']: m for m in payload.get('includes', {}).get('media', []) if isinstance(m, dict)}

        user_index = {u['id']: u for u in payload.get('includes', {}).get('users', []) if isinstance(u, dict)}

        for tweet in tweets:

            media_keys = tweet.get('attachments', {}).get('media_keys', [])

            author = user_index.get(tweet.get('author_id'))

            for key in media_keys:

                media = media_index.get(key)

                if not media:

                    continue

                media_url = media.get('url') or media.get('preview_image_url')

                if not media_url:

                    continue

                username = author.get('username') if author else None

                tweet_url = f"https://twitter.com/{username}/status/{tweet['id']}" if username else f"https://twitter.com/i/web/status/{tweet['id']}"

                items.append({

                    'source': 'social_twitter',

                    'type': 'visual_mention',

                    'url': tweet_url,

                    'media_url': media_url,

                    'timestamp': datetime.now().isoformat(),

                    'title': tweet.get('text'),

                    'query': query,

                    'risk_indicators': ['potential_logo_usage', 'social_media'],

                })

    except Exception as exc:

        self._record_error('twitter_scrape_exception', error=str(exc))

        self.logger.error('Twitter scrape failed: %s', exc)

    return items



def _scrape_instagram_images(self, query: str) -> List[Dict]:

        items: List[Dict] = []

        access_token = getattr(self.config, 'INSTAGRAM_ACCESS_TOKEN', None)

        user_id = getattr(self.config, 'INSTAGRAM_GRAPH_USER_ID', None)

        if not access_token or not user_id:

            self.logger.info('Instagram Graph credentials not configured; skipping Instagram scrape.')

            return items



        hashtag = self._sanitize_hashtag(query)

        if not hashtag:

            return items



        try:

            search_params = {'user_id': user_id, 'q': hashtag, 'access_token': access_token}

            search_resp = requests.get('https://graph.facebook.com/v19.0/ig_hashtag_search', params=search_params, timeout=20)

            if search_resp.status_code != 200:

                self._record_error('instagram_hashtag_error', status=search_resp.status_code, body=search_resp.text[:120])

                self.logger.error('Instagram hashtag search failed (%s): %s', search_resp.status_code, search_resp.text[:120])

                return items

            data = search_resp.json().get('data', [])

            if not data:

                return items

            hashtag_id = data[0].get('id')

            if not hashtag_id:

                return items

            media_params = {

                'user_id': user_id,

                'fields': 'id,caption,media_type,media_url,permalink,timestamp',

                'access_token': access_token

            }

            media_resp = requests.get(f'https://graph.facebook.com/v19.0/{hashtag_id}/recent_media', params=media_params, timeout=20)

            if media_resp.status_code != 200:

                self._record_error('instagram_media_error', status=media_resp.status_code, body=media_resp.text[:120])

                self.logger.error('Instagram media fetch failed (%s): %s', media_resp.status_code, media_resp.text[:120])

                return items

            for media in media_resp.json().get('data', [])[:25]:

                if media.get('media_type') not in ('IMAGE', 'CAROUSEL_ALBUM', 'VIDEO'):

                    continue

                media_url = media.get('media_url')

                if not media_url:

                    continue

                items.append({

                    'source': 'social_instagram',

                    'type': 'visual_mention',

                    'url': media.get('permalink'),

                    'media_url': media_url,

                    'timestamp': media.get('timestamp') or datetime.now().isoformat(),

                    'title': media.get('caption'),

                    'query': query,

                    'risk_indicators': ['potential_logo_usage', 'social_media']

                })

        except Exception as exc:

            self._record_error('instagram_scrape_exception', error=str(exc))

            self.logger.error('Instagram scrape failed: %s', exc)

        return items



def _sanitize_hashtag(self, query: str) -> Optional[str]:

        if not query:

            return None

        candidate = query.strip().lstrip('#')

        candidate = re.sub(r'[^0-9A-Za-z_]', '', candidate)

        return candidate or None



def _scrape_pinterest_images(self, query: str) -> List[Dict]:

        items: List[Dict] = []

        search_url = f"https://www.pinterest.com/search/pins/?q={quote_plus(query)}"

        try:

            response = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=20)

            if response.status_code != 200:

                return items

            soup = BeautifulSoup(response.text, 'html.parser')

            for link in soup.select('a[href*="pin/"]'):

                img = link.find('img')

                media_url = None

                if img:

                    media_url = img.get('src') or img.get('data-src')

                if not media_url:

                    continue

                href = link.get('href')

                if href and not href.startswith('http'):

                    href = f"https://www.pinterest.com{href}"

                items.append({

                    'source': 'social_pinterest',

                    'type': 'visual_mention',

                    'url': href,

                    'media_url': media_url,

                    'timestamp': datetime.now().isoformat(),

                    'query': query,

                    'risk_indicators': ['potential_logo_usage']

                })

        except Exception as exc:

            self._record_error('pinterest_scrape_exception', error=str(exc))

            self.logger.error('Pinterest image scrape failed: %s', exc)

        return items



def _is_suspicious_domain(self, domain: str) -> bool:

        """Check if domain is suspicious"""

        brand_lower = self.config.BRAND_NAME.lower()

        domain_lower = domain.lower()

        

        # Check for brand name variations

        if brand_lower in domain_lower and domain not in self.config.BRAND_DOMAINS:

            return True

        

        # Check for common phishing patterns

        phishing_patterns = ['secure-', '-verify', '-official', 'support-', '-login']

        return any(pattern in domain_lower for pattern in phishing_patterns)

    

def _analyze_domain_risk(self, domain: str) -> Dict:

        """Analyze domain risk indicators"""

        indicators = {

            'contains_brand_name': self.config.BRAND_NAME.lower() in domain.lower(),

            'uses_hyphen': '-' in domain,

            'unusual_tld': not domain.endswith(('.com', '.org', '.net')),

            'length_similarity': abs(len(domain) - len(self.config.BRAND_NAME)) < 5

        }

        return indicators
def _generate_typo_variants(self, brand: str) -> List[str]:

        """Generate common typosquatting variants"""

        variants = []

        brand_lower = brand.lower()

        

        # Character substitution

        substitutions = {'o': '0', 'i': '1', 'l': '1', 'e': '3', 'a': '@'}

        for old, new in substitutions.items():

            if old in brand_lower:

                variants.append(brand_lower.replace(old, new))

        

        # Character omission

        for i in range(len(brand_lower)):

            variants.append(brand_lower[:i] + brand_lower[i+1:])

        

        # Character duplication

        for i in range(len(brand_lower)):

            variants.append(brand_lower[:i] + brand_lower[i] + brand_lower[i:])

        

        # Common misspellings

        variants.extend([

            brand_lower + 's',

            brand_lower + '-official',

            'official-' + brand_lower,

            brand_lower + '-support'

        ])

        

        return list(set(variants))[:20]  # Limit to 20 variants

    

def _check_domain_exists(self, domain: str) -> bool:

        """Check if a domain exists"""

        try:

            response = requests.head(f"http://{domain}", timeout=5)

            return response.status_code < 500

        except:

            return False

    

def _get_social_search_url(self, platform: str) -> str:

        """Get search URL for social media platform"""

        brand = self.config.BRAND_NAME

        urls = {

            'twitter': f"https://twitter.com/search?q={brand}",

            'facebook': f"https://www.facebook.com/search/top?q={brand}",

            'instagram': f"https://www.instagram.com/explore/tags/{brand}",

            'linkedin': f"https://www.linkedin.com/search/results/all/?keywords={brand}"

        }

        return urls.get(platform)

    

def _extract_suspicious_accounts(self, html: str, platform: str) -> List[Dict]:

        """Extract potentially suspicious accounts from HTML"""

        suspicious = []

        soup = BeautifulSoup(html, 'html.parser')

        brand_lower = self.config.BRAND_NAME.lower()

        

        # Platform-specific extraction logic

        if platform == 'twitter':

            usernames = soup.find_all('span', class_='username')

            for username in usernames:

                text = username.get_text().lower()

                if brand_lower in text and text not in self.config.BRAND_DOMAINS:

                    suspicious.append({

                        'username': text,

                        'url': f"https://twitter.com/{text.replace('@', '')}"

                    })

        

        return suspicious[:10]  # Limit results



class QueueManager:

    def __init__(self):

        self.queue = asyncio.Queue()

        self.processed_items = set()

    

    async def add_items(self, items: List[Dict]):

        """Add items to processing queue"""

        for item in items:

            item_id = f"{item['source']}_{item['url']}"

            if item_id not in self.processed_items:

                await self.queue.put(item)

                self.processed_items.add(item_id)

    

    async def get_next_item(self) -> Dict:

        """Get next item from queue"""

        return await self.queue.get()

    

    def is_empty(self) -> bool:

        """Check if queue is empty"""

        return self.queue.empty()

















