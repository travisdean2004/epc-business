#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SeleniumBase UC Mode Scraper - Cloudflare bypass with cookie authentication (REFACTORED)

This refactored version addresses the following issues:
    1. Replaced all bare except clauses with specific exception handling
    2. Implemented proper logging instead of print statements
    3. Improved separation of concerns
    4. Ensured consistent return types across all functions
    5. Moved error handling to outer layers
    6. Fixed commented out imports and used specific exceptions
    7. Improved code modularity and testability

Features:
    - UC Mode: Undetected ChromeDriver evading bot detection
    - CDP Events: Low-level Chrome DevTools Protocol control
    - Auto CAPTCHA: Turnstile/Cloudflare challenge solving
    - Reconnection: Evade fingerprinting after actions
    - Screenshots: Page and job card capture for verification
"""

import re
import os
import time
import pickle
import random
import logging
import platform
from pathlib import Path
from seleniumbase import SB
from datetime import datetime
from urllib.parse import quote_plus
from modules.cfg import get_base_url
from modules.sb_utils import (
    build_sb_options, use_indeed_uc_mode, use_indeed_profile, 
    use_indeed_attach, indeed_debug_port, open_url, apply_cdp_stealth, 
    indeed_profile_dir, create_attached_sb, wait_for_chrome_debug_port,)
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (TimeoutException, NoSuchElementException, WebDriverException)

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

# __ configure logging:
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# __ global vars:
DEFAULT_DELAY_MIN = 1
DEFAULT_DELAY_MAX = 3
PAGE_DELAY_MIN = 2
PAGE_DELAY_MAX = 4
CLOUDFLARE_DELAY = 3
RECONNECT_TIMEOUT = 3
NOT_AVAILABLE = "Not Available"
MAX_SNIPPET_LENGTH = 300
MAX_CONSECUTIVE_FAILURES = 2
BASE_URL = get_base_url(jb_board="indeed")

EXTRACT_JOBS_JS = """
return (function() {
    const jobs = [];
    const cardSelectors = [
        'div.job_seen_beacon',
        'div[data-jk]',
        '#mosaic-provider-jobcards li',
        '.resultContent',
    ];
    let cards = [];
    for (const selector of cardSelectors) {
        const found = document.querySelectorAll(selector);
        if (found && found.length > 0) {
            cards = Array.from(found);
            break;
        }
    }

    function cleanKey(key) {
        if (!key) return null;
        key = String(key).trim();
        if (!/^[a-f0-9]{8,24}$/i.test(key)) return null;
        if (/^1234567890?abcdef/i.test(key)) return null;
        return key;
    }

    const seenKeys = new Set();
    const seenUrls = new Set();

    for (const card of cards) {
        try {
            const job = { sponsored: false };
            job.job_key = cleanKey(card.getAttribute('data-jk'))
                || cleanKey(card.querySelector('[data-jk]')?.getAttribute('data-jk'))
                || cleanKey(card.querySelector('a[data-jk]')?.getAttribute('data-jk'));

            const titleEl = card.querySelector('h2.jobTitle span[title]')
                || card.querySelector('h2.jobTitle a')
                || card.querySelector('a.jcs-JobTitle')
                || card.querySelector('[data-testid="jobTitle"]')
                || card.querySelector('h2.jobTitle');
            job.title = titleEl?.getAttribute('title')
                || titleEl?.innerText?.trim()
                || titleEl?.getAttribute('aria-label')
                || null;

            const link = card.querySelector('a.jcs-JobTitle')
                || card.querySelector('h2.jobTitle a')
                || card.querySelector('a[href*="viewjob"]')
                || card.querySelector('a[href*="jk="]')
                || titleEl;
            let href = link?.href || link?.getAttribute('href') || '';
            if (href && !href.startsWith('http')) href = 'https://www.indeed.com' + href;
            job.url = href || null;

            if (!job.job_key && href) {
                const match = href.match(/[?&]jk=([a-f0-9]{8,24})/i);
                if (match) job.job_key = cleanKey(match[1]);
            }

            if (job.url && /pagead\\/clk|\\/aclk\\?/i.test(job.url)) {
                job.sponsored = true;
            }

            const dedupeKey = job.job_key || job.url;
            if (!dedupeKey) continue;
            if (job.job_key && seenKeys.has(job.job_key)) continue;
            if (job.url && seenUrls.has(job.url)) continue;
            if (job.job_key) seenKeys.add(job.job_key);
            if (job.url) seenUrls.add(job.url);

            const companyEl = card.querySelector('[data-testid="company-name"]')
                || card.querySelector('.companyName');
            job.company = companyEl?.innerText?.trim() || null;

            const locationEl = card.querySelector('[data-testid="text-location"]')
                || card.querySelector('.companyLocation');
            job.location = locationEl?.innerText?.trim() || null;

            const salaryEl = card.querySelector('[data-testid="attribute_snippet_testid"]')
                || card.querySelector('.salary-snippet-container');
            job.salary = salaryEl?.innerText?.trim()?.split('\\n')[0] || null;

            const snippetEl = card.querySelector('.job-snippet')
                || card.querySelector('[data-testid="jobsnippet"]');
            job.snippet = snippetEl?.innerText?.trim()?.substring(0, 500) || null;

            job.posted = extractPosted(card);

            if (job.title || job.job_key || job.url) jobs.push(job);
        } catch (e) {}
    }

    function looksLikePosted(text) {
        if (!text) return false;
        const lower = String(text).toLowerCase().trim();
        if (!lower) return false;
        if (/\\$|€|£|per\\s+(year|hour|month|annum)/i.test(lower) && !/ago|posted|just|today|active/i.test(lower)) {
            return false;
        }
        return ['posted', 'ago', 'day', 'hour', 'week', 'month', 'just', 'today', 'active', 'employer']
            .some((kw) => lower.includes(kw));
    }

    function extractPosted(card) {
        const selectors = [
            'span[data-testid="myJobsStateDate"]',
            'span.date',
            '.jobMetaDataGroup span',
            'div.metadata span',
            '[class*="underShelfFooter"] span',
            'span[class*="date"]',
            '[data-testid="attribute_snippet_testid"]',
            '[data-testid="attribute_snippet_testid"] li',
        ];
        for (const selector of selectors) {
            const elems = card.querySelectorAll(selector);
            for (const el of elems) {
                const text = (el.innerText || el.textContent || '').trim();
                if (looksLikePosted(text)) {
                    return text.split('\\n')[0].trim();
                }
            }
        }
        const cardText = (card.innerText || card.textContent || '').toLowerCase();
        const patterns = [
            /posted\\s+\\d+\\s+(?:day|hour|week|month)s?\\s+ago/i,
            /just\\s+posted/i,
            /active\\s+\\d+\\s+(?:day|hour|week|month)s?\\s+ago/i,
            /\\d+\\s+(?:day|hour|week|month)s?\\s+ago/i,
            /today/i,
        ];
        for (const pattern of patterns) {
            const match = cardText.match(pattern);
            if (match) return match[0];
        }
        return null;
    }

    return jobs;
})();
"""

class SeleniumBaseIndeedScraper:
    """Indeed scraper using SeleniumBase UC Mode for Cloudflare bypass:
        UC Mode advantages:
            - Runtime ChromeDriver patching to avoid detection:
            - Removes automation flags Cloudflare checks:
            - Built-in CAPTCHA solver for Turnstile challenges:
            - Reconnection strategy to evade fingerprinting: """
    
    def __init__(self, headless=False, incognito=False, window_size="maximized", proxy=None, screenshots=False, artifacts_dir=None, cookie_file=None):
        """Initialize SeleniumBase scraper in UC Mode:
            Args:
                headless (bool):        <-- Run headless (uses xvfb on Linux)
                incognito (bool):       <-- Use incognito mode:
                window_size (str):      <-- "maximized" or "WIDTHxHEIGHT"
                proxy (dict):           <-- Proxy config {'server': '...', 'username': '...', 'password': '...'}
                screenshots (bool):     <-- Enable screenshot capture:
                artifacts_dir (Path):   <-- Base artifacts directory:
                cookie_file (str):      <-- Path to cookie file: """
        
        self.window_size = window_size
        self.screenshots = screenshots
        self.cookie_file = cookie_file
        self.incognito = incognito
        self.headless = headless
        self.proxy = proxy
        self.driver = None
        self.sb = None
        self.use_uc = False
        self.use_attach = False
        self._sb_context = None
        
        # __ setup screenshot directories:
        if artifacts_dir:
            self.artifacts_dir = Path(artifacts_dir)
        else:
            self.artifacts_dir = Path(__file__).parent.parent / "artifacts"

        self.screenshots_dir = self.artifacts_dir / "screenshots"
        self.pages_dir = self.screenshots_dir / "pages"
        self.cards_dir = self.screenshots_dir / "cards"
        
        if self.screenshots:
            self.pages_dir.mkdir(parents=True, exist_ok=True)
            self.cards_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Page screenshots: {self.pages_dir}")
            logger.info(f"Card screenshots: {self.cards_dir}")
        
        self._start_browser()
        
        # __ auth: attach mode uses the open Chrome session; else profile/cookies:
        if self.use_attach:
            self._ensure_indeed_tab()
            current = self.sb.get_current_url()
            logger.info(f"Attached session URL: {current}")
            if self._is_cloudflare_challenge():
                logger.warning("Cloudflare still showing — complete verification in the Chrome window")
                self._handle_cloudflare()
            elif self._is_logged_in():
                logger.info("Authenticated via attached Chrome session")
            else:
                logger.info("Using attached Chrome session (pass Cloudflare in that window if needed)")
        elif use_indeed_profile() and not self.use_uc and not self.incognito:
            self._open_url(BASE_URL, reconnect_time=3)
            time.sleep(2)
            if self._is_logged_in():
                logger.info("Authenticated via Chrome profile")
            elif self.cookie_file:
                self._load_cookies_from_file(skip_home_open=True)
        elif self.cookie_file:
            self._load_cookies_from_file()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def _start_browser(self):
        """Start browser — attach to real Chrome, UC mode, or standard Selenium."""
        use_attach = use_indeed_attach() and not self.incognito
        use_uc = use_indeed_uc_mode() and not use_attach
        use_profile = use_indeed_profile() and not use_uc and not self.incognito and not use_attach
        self.use_attach = use_attach
        self.use_uc = use_uc

        if use_attach:
            port = indeed_debug_port()
            logger.info("Indeed attach mode — reusing your open Chrome (not launching Selenium Chrome)")
            logger.info("If Chrome is not open yet, run: python modules/warm_indeed_profile.py")
            wait_for_chrome_debug_port(port, logger=logger)
            self.sb = create_attached_sb(port, logger=logger)
            self.driver = self.sb.driver
            self._sb_context = None
            logger.info("Attached to Chrome — manual Cloudflare clicks work in that window")
            return

        logger.info("Starting SeleniumBase browser...")
        logger.info("(First launch may take 30-60s while Chrome/driver initializes)")
        
        if use_uc:
            logger.info("UC Mode enabled (INDEED_USE_UC=1) for Cloudflare bypass")
        elif use_profile:
            logger.info(f"Using Chrome profile: {indeed_profile_dir()}")
            logger.info("If Cloudflare loops, run: python modules/warm_indeed_profile.py")
        else:
            logger.info("Standard Chrome (no profile) — Cloudflare may block Selenium")
            logger.info("Recommended: python modules/warm_indeed_profile.py first")
        
        # __ build SB options:
        sb_options = build_sb_options(
            headless=self.headless,
            incognito=self.incognito,
            proxy=self.proxy,
            use_uc=use_uc,
            use_profile=use_profile,
        )
        if use_uc:
            sb_options['block_images'] = False
        self._sb_context = SB(**sb_options)
        self.sb = self._sb_context.__enter__()
        self.driver = self.sb.driver
        apply_cdp_stealth(self.driver, logger)
        
        # __ set window size:
        if self.window_size == "maximized":
            self.sb.maximize_window()
        else:
            try:
                width, height = map(int, self.window_size.split('x'))
                self.sb.set_window_size(width, height)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Invalid window size format '{self.window_size}': {e}")
                logger.info("Falling back to maximized window")
                self.sb.maximize_window()
        
        logger.info("SeleniumBase browser started")

    def _open_url(self, url, reconnect_time=3):
        """Open URL with UC reconnect when enabled, otherwise standard navigation."""
        if self.use_uc:
            self.sb.uc_open_with_reconnect(url, reconnect_time=reconnect_time)
        else:
            open_url(self.sb, url, logger)

    def _reconnect(self, timeout=2):
        """UC reconnect for fingerprint evasion; no-op-ish fallback in standard mode."""
        if self.use_uc and hasattr(self.sb, "reconnect"):
            self.sb.reconnect(timeout=timeout)
        else:
            time.sleep(min(timeout, 2))

    def _load_cookies_from_file(self, skip_home_open=False):
        """ Load cookies from file to bypass login:
            Returns: bool:              <-- True if successful, False otherwise:
            Raises: FileNotFoundError:  <-- If cookie file doesn't exist: """
        
        cookie_path = Path(self.cookie_file)
        if not cookie_path.is_absolute():
            cookie_path = Path(__file__).parent.parent / cookie_path
        if not cookie_path.exists():
            logger.error(f"Cookie file not found: {cookie_path}")
            logger.info("Run cookie setup first:")
            logger.info("    python3 modules/get_cookies.py --auto")
            raise FileNotFoundError(f"Cookie file not found: {cookie_path}")
        
        logger.info(f"Loading cookies from: {cookie_path}")
        
        if not skip_home_open:
            self._open_url(BASE_URL, reconnect_time=3)
            time.sleep(2)
        
        # __ load cookies:
        try:
            with open(cookie_path, 'rb') as f:
                cookies = pickle.load(f)
        except (IOError, OSError, pickle.UnpicklingError) as e:
            logger.error(f"Failed to load cookies from file: {e}")
            return False
        
        logger.info(f"Adding {len(cookies)} cookies ...")
        
        # __ add cookies:
        added = 0
        for cookie in cookies:
            try:
                if 'expiry' in cookie:
                    cookie['expiry'] = int(cookie['expiry'])
                cookie.pop('sameSite', None)
                self.driver.add_cookie(cookie)
                added += 1
            except (WebDriverException, ValueError, TypeError) as e:
                logger.debug(f"Failed to add cookie {cookie.get('name', 'unknown')}: {e}")
                continue
        
        logger.info(f"Added {added}/{len(cookies)} cookies")
        
        # __ refresh to apply:
        self.sb.refresh()
        time.sleep(2)
        
        if self._is_cloudflare_challenge():
            logger.info("Cloudflare on homepage — solve once to save clearance cookies")
            if not self._handle_cloudflare():
                logger.warning("Could not pass Cloudflare on homepage")
                return False
        
        # __ verify login:
        if self._is_logged_in():
            logger.info("Successfully logged in via cookies!")
            return True
        else:
            logger.warning("Cookies may be expired - refresh them")
            return False
    
    def _is_logged_in(self):
        """ Check if logged in:
            Returns: bool: <-- True if logged in: """
        try:
            page_source = self.sb.get_page_source().lower()
            current_url = self.sb.get_current_url()
            return 'sign out' in page_source or ('account' in page_source and 'auth' not in current_url)
        except WebDriverException as e:
            logger.debug(f"Error checking login status: {e}")
            return False

    def search_jobs(self, query, location="", remote_only=False, min_salary=None, max_salary=None, date_posted=None, max_results=25):
        """ Search Indeed jobs with UC Mode Cloudflare bypass:
            Args:
                query (str):        <-- Job search query:
                location (str):     <-- Job location
                remote_only (bool): <-- Filter remote jobs only
                min_salary (int):   <-- Minimum salary
                max_salary (int):   <-- Maximum salary
                date_posted (int):  <-- Days filter (1, 3, 7, 14)
                max_results (int):  <-- Maximum results to return
            Returns: list:          <-- Job dictionaries, or empty list if no jobs found: """
        
        base_url = self._build_search_url(query, location, remote_only, min_salary, max_salary, date_posted)
        all_jobs = []
        page_num = 0
        consecutive_failures = 0
        session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        while len(all_jobs) < max_results and consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            url = f"{base_url}&start={page_num * 10}" if page_num > 0 else base_url
            logger.info(f"\nPage {page_num + 1}: {url}")
            try:
                # __ navigate:
                self._open_url(url, reconnect_time=5)
                self._human_delay(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
                
                # __ handle Cloudflare if present:
                if self._handle_cloudflare():
                    logger.info("Cloudflare challenge handled")
                    self._reconnect(timeout=RECONNECT_TIMEOUT)
                    self._human_delay(PAGE_DELAY_MIN, CLOUDFLARE_DELAY)
                elif self._is_cloudflare_challenge():
                    logger.error("Still blocked by Cloudflare — refresh cookies or retry")
                    consecutive_failures += 1
                    self._human_delay(5, 10)
                    continue
                
                # __ wait for job cards:
                if not self._wait_for_job_listings():
                    consecutive_failures += 1
                    if self._is_cloudflare_challenge():
                        logger.warning("Still blocked by Cloudflare - retrying...")
                        self._handle_cloudflare()
                    self._human_delay(5, 10)
                    continue

                self._scroll_job_results_page()

                # __ take page screenshot:
                if self.screenshots:
                    self._take_page_screenshot(page_num + 1, query, session_ts)
                
                # __ extract jobs from page:
                # page_jobs = self._extract_jobs_from_page(all_jobs, max_results, query, location, page_num, session_ts)
                page_jobs, total_cards = self._extract_jobs_from_page(all_jobs, max_results, query, location, page_num, session_ts)
                
                if page_jobs == 0:
                    logger.warning("No new jobs on this page")
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                
                # __ stop if mostly duplicates (only when we did extract some jobs):
                if total_cards > 0 and page_jobs > 0:
                    duplicate_rate = (total_cards - page_jobs) / total_cards
                    if duplicate_rate > 0.8 and page_jobs < 3:
                        logger.info(f"High duplicate rate ({duplicate_rate:.0%}) - likely end of results")
                        consecutive_failures += 1
                
                if len(all_jobs) >= max_results:
                    break
                
                # __ reconnect before pagination:
                if not self.use_attach:
                    logger.info("Reconnecting before next page...")
                    self._reconnect(timeout=2)
                else:
                    logger.info("Loading next page in your Chrome window...")
                self._human_delay(4, 8)
                page_num += 1
                
            except WebDriverException as e:
                logger.error(f"WebDriver error on page {page_num + 1}: {e}")
                consecutive_failures += 1
                self._human_delay(5, 10)
            except Exception as e:
                logger.error(f"Unexpected error on page {page_num + 1}: {e}")
                consecutive_failures += 1
                self._human_delay(5, 10)
        
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(f"Stopped after {MAX_CONSECUTIVE_FAILURES} consecutive failures")
        
        return all_jobs
    
    def _build_search_url(self, query, location, remote_only, min_salary, max_salary, date_posted):
        """ Build Indeed search url with parameters:
            Args:
                query (str):        <-- Job search query:
                location (str):     <-- Job location:
                remote_only (bool): <-- Filter remote jobs only:
                min_salary (int):   <-- Minimum salary:
                max_salary (int):   <-- Maximum salary:
                date_posted (int):  <-- Days filter:
            Returns: str:           <-- Complete search url: """
        
        params = []
        if query:
            params.append(f"q={quote_plus(query)}")
        if location:
            params.append(f"l={quote_plus(location)}")
        if remote_only:
            params.append("sc=0kf%3Aattr%28DSQF7%29%3B")
        if min_salary and max_salary:
            params.append(f"salary={min_salary}-{max_salary}")
        if date_posted:
            params.append(f"fromage={date_posted}")
        
        return f"{BASE_URL}/jobs?{'&'.join(params)}"

    def _ensure_indeed_tab(self):
        """In attach mode, switch to an open Indeed tab (not chrome:// internal pages)."""
        try:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                url = (self.driver.current_url or "").lower()
                if "indeed.com" in url:
                    logger.info(f"Using Indeed tab: {self.driver.current_url}")
                    return True
            logger.warning(
                "No Indeed tab in attached Chrome — open https://www.indeed.com/jobs in warmed Chrome"
            )
        except WebDriverException as e:
            logger.debug(f"Tab switch failed: {e}")
        return False

    def _scroll_job_results_page(self):
        """Scroll through result cards so lazy-loaded jobs appear (visible in attach mode)."""
        count, _ = self._count_job_cards_js()
        if count <= 0:
            return
        logger.info(f"Scrolling {min(count, 20)} job card(s) into view...")
        try:
            for index in range(min(count, 20)):
                self.sb.execute_script(
                    """
                    const cards = document.querySelectorAll(
                        'div.job_seen_beacon, div[data-jk], #mosaic-provider-jobcards li'
                    );
                    if (arguments[0] < cards.length) {
                        cards[arguments[0]].scrollIntoView({behavior: 'smooth', block: 'center'});
                    }
                    """,
                    index,
                )
                time.sleep(0.4)
            self.sb.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
            time.sleep(0.6)
        except WebDriverException as e:
            logger.debug(f"Scroll step failed: {e}")
    
    def _count_job_cards_js(self):
        """Count job cards in DOM (presence only — does not require visibility)."""
        script = """
        return (function() {
            const selectors = [
                'div.job_seen_beacon',
                'div[data-jk]',
                '#mosaic-provider-jobcards li',
                '.resultContent',
                'a[data-jk]',
            ];
            for (const sel of selectors) {
                const n = document.querySelectorAll(sel).length;
                if (n > 0) return {count: n, selector: sel};
            }
            return {count: 0, selector: null};
        })();
        """
        try:
            result = self.sb.execute_script(script) or {}
            return int(result.get("count") or 0), result.get("selector")
        except WebDriverException:
            return 0, None

    def _wait_for_job_listings(self):
        """Wait for job listings in DOM (not strict visibility — attach/split view safe)."""
        try:
            self.sb.execute_script("window.scrollTo(0, 0);")
        except WebDriverException:
            pass

        for attempt in range(20):
            count, selector = self._count_job_cards_js()
            if count > 0:
                logger.info(f"Job listings found via JS: {count} card(s) ({selector})")
                return True
            time.sleep(0.5)

        selectors = [
            'div.job_seen_beacon',
            '[data-jk]',
            '#mosaic-provider-jobcards li',
            '.resultContent',
            '[class*="jobCard"]',
            '[data-testid="jobsearch-ResultsList"]',
        ]
        for selector in selectors:
            try:
                if hasattr(self.sb, "wait_for_element_present"):
                    self.sb.wait_for_element_present(selector, timeout=3)
                else:
                    self.sb.wait_for_element(selector, timeout=3)
                logger.info(f"Job listings found via: {selector}")
                return True
            except (TimeoutException, NoSuchElementException, WebDriverException) as e:
                logger.debug(f"Selector wait failed for {selector}: {e}")
                continue

        logger.warning("Could not find job listings with any known selector")
        return False
    
    def _collect_job_cards(self):
        """Find job card elements, preferring stable data-jk containers."""
        selectors = [
            'div.job_seen_beacon',
            'div[data-jk]',
            '#mosaic-provider-jobcards li',
            '.resultContent',
            'div.jobsearch-ResultsList > div',
        ]
        for selector in selectors:
            cards = self.sb.find_elements(selector)
            if cards:
                return cards
        return []

    def _finalize_job_record(self, job_data):
        """Fill missing title/url from job_key; keep any listing Indeed returned."""
        job_key = job_data.get('job_key')
        if job_key and job_key != NOT_AVAILABLE and not self._valid_indeed_job_key(job_key):
            job_data['job_key'] = NOT_AVAILABLE
            job_key = NOT_AVAILABLE
        if job_key and job_key != NOT_AVAILABLE:
            if not job_data.get('url') or job_data.get('url') == NOT_AVAILABLE:
                job_data['url'] = f"{BASE_URL}/viewjob?jk={job_key}"

        title = (job_data.get('title') or '').strip()
        if not title or title == NOT_AVAILABLE:
            if job_key and job_key != NOT_AVAILABLE:
                job_data['title'] = f"Indeed job {job_key}"
            elif job_data.get('url') and job_data.get('url') != NOT_AVAILABLE:
                job_data['title'] = "Indeed listing"
            else:
                job_data['title'] = NOT_AVAILABLE
        return job_data

    def _job_record_is_usable(self, job_data):
        """Accept any listing with a key, URL, or parsed title (no query match required)."""
        for field in ('job_key', 'url', 'title'):
            value = job_data.get(field)
            if value and value != NOT_AVAILABLE:
                return True
        return False

    def _append_job_record(self, job_data, all_jobs, max_results, page_num, session_ts, card=None):
        """Normalize, dedupe, and append one job if usable."""
        if len(all_jobs) >= max_results:
            return False

        job_data = self._finalize_job_record(job_data)
        if not self._job_record_is_usable(job_data):
            return False
        if self._is_duplicate_job(job_data, all_jobs):
            return False

        if self.screenshots and card is not None and not self.use_attach:
            screenshot_path = self._take_job_screenshot(
                card, page_num + 1, len(all_jobs) + 1, job_data['title'], job_data['job_key'], session_ts)
            job_data['screenshot'] = str(screenshot_path) if screenshot_path else NOT_AVAILABLE
        elif self.screenshots and self.use_attach:
            job_data['screenshot'] = NOT_AVAILABLE

        all_jobs.append(job_data)
        title_short = job_data['title'][:50]
        url_short = job_data['url'][:60] if job_data['url'] != NOT_AVAILABLE else 'No URL'
        logger.info(f"  [{len(all_jobs)}] {title_short} | {url_short}")
        return True

    def _extract_jobs_via_js(self, query, location, page_num):
        """JS fallback when Selenium element parsing misses titles on current Indeed DOM."""
        try:
            raw_jobs = self.sb.execute_script(EXTRACT_JOBS_JS) or []
        except WebDriverException as e:
            logger.debug(f"JS job extraction failed: {e}")
            return []

        jobs = []
        for raw in raw_jobs:
            job_key = raw.get('job_key')
            url = raw.get('url')
            if job_key and not self._valid_indeed_job_key(job_key):
                job_key = None
            if not url and job_key:
                url = f"{BASE_URL}/viewjob?jk={job_key}"
            jobs.append({
                'scraped_at': datetime.now().isoformat(),
                'search_query': query,
                'search_location': location,
                'page_number': page_num + 1,
                'job_key': job_key or NOT_AVAILABLE,
                'url': url or NOT_AVAILABLE,
                'title': raw.get('title') or NOT_AVAILABLE,
                'company': raw.get('company') or NOT_AVAILABLE,
                'location': raw.get('location') or NOT_AVAILABLE,
                'salary': raw.get('salary') or NOT_AVAILABLE,
                'snippet': raw.get('snippet') or NOT_AVAILABLE,
                'posted': raw.get('posted') or NOT_AVAILABLE,
                'sponsored': bool(raw.get('sponsored')),
            })
        return jobs

    def _valid_indeed_job_key(self, job_key):
        """Reject placeholder / malformed Indeed job keys."""
        if not job_key or job_key == NOT_AVAILABLE:
            return False
        if not re.match(r'^[a-f0-9]{8,24}$', str(job_key), re.I):
            return False
        if re.match(r'^1234567890?abcdef', str(job_key), re.I):
            return False
        return True

    def _normalize_job_url(self, url):
        if not url or url == NOT_AVAILABLE:
            return ""
        return url.split("#")[0].strip()

    def _extract_jobs_from_page(self, all_jobs, max_results, query, location, page_num, session_ts):
        """Extract all jobs from current page (including similar/sponsored listings Indeed shows)."""
        job_cards = self._collect_job_cards()
        logger.info(f"Found {len(job_cards)} job cards")

        page_jobs = 0
        for index, card in enumerate(job_cards):
            if len(all_jobs) >= max_results:
                break
            try:
                if self.use_attach or self.screenshots:
                    self.sb.execute_script(
                        "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", card
                    )
                    time.sleep(0.25)
                job_data = self._extract_job_from_element(card, query, location, page_num + 1)
                if self._append_job_record(job_data, all_jobs, max_results, page_num, session_ts, card=card):
                    page_jobs += 1
            except (NoSuchElementException, WebDriverException) as e:
                logger.debug(f"Error parsing job card: {e}")
                continue

        if page_jobs == 0 and len(job_cards) > 0:
            logger.info("DOM parsing found cards but no jobs — trying JS fallback")
            for job_data in self._extract_jobs_via_js(query, location, page_num):
                if self._append_job_record(job_data, all_jobs, max_results, page_num, session_ts):
                    page_jobs += 1

        if page_jobs > 0 and query:
            logger.info(
                f"Collected {page_jobs} listing(s) from page "
                f"(Indeed may include similar/sponsored jobs beyond '{query}')"
            )

        return page_jobs, len(job_cards)
    
    def _is_duplicate_job(self, job_data, all_jobs):
        """Check duplicate by job_key, normalized URL, or same title+company."""
        job_key = job_data.get('job_key')
        if job_key and job_key != NOT_AVAILABLE and self._valid_indeed_job_key(job_key):
            if any(j.get('job_key') == job_key for j in all_jobs):
                return True

        url = self._normalize_job_url(job_data.get('url'))
        if url:
            if any(self._normalize_job_url(j.get('url')) == url for j in all_jobs):
                return True

        title = (job_data.get('title') or '').strip().lower()
        company = (job_data.get('company') or '').strip().lower()
        if title and title != NOT_AVAILABLE.lower() and company and company != NOT_AVAILABLE.lower():
            if any(
                (j.get('title') or '').strip().lower() == title
                and (j.get('company') or '').strip().lower() == company
                for j in all_jobs
            ):
                return True
        return False

    def _handle_cloudflare(self):
        """ Handle Cloudflare challenge using UC Mode:
            Returns: bool: <-- True if challenge was detected and handled: """
        
        if not self._is_cloudflare_challenge():
            return False
        
        logger.info("Cloudflare challenge detected - attempting bypass ...")

        if self.use_attach:
            logger.info("Attach mode — complete verification in your Chrome window (PyAutoGUI skipped)")
            solved = self._wait_for_manual_solve()
            if solved:
                self._persist_browser_cookies()
            return solved

        if self._try_pyautogui_captcha():
            self._persist_browser_cookies()
            return True
        
        # __ method - 1: Built-in CAPTCHA clicker (UC mode only):
        if self._try_auto_click_captcha():
            self._persist_browser_cookies()
            return True
        
        # __ method - 2: Manual iframe checkbox:
        if self._try_iframe_checkbox():
            self._persist_browser_cookies()
            return True
        
        # __ method - 3: Wait for manual intervention:
        solved = self._wait_for_manual_solve()
        if solved:
            self._persist_browser_cookies()
        return solved
    
    def _try_auto_click_captcha(self):
        """ Try to auto-click Cloudflare CAPTCHA:
            Returns: bool: <-- True if successful: """
        if not self.use_uc:
            return False
        try:
            self.sb.uc_gui_click_captcha()
            logger.info("Clicked Cloudflare checkbox")
            self._human_delay(CLOUDFLARE_DELAY, 5)
            
            if not self._is_cloudflare_challenge():
                logger.info("Cloudflare challenge solved!")
                return True
        except WebDriverException as e:
            logger.debug(f"Auto-click failed: {e}")
        
        return False
    
    def _try_iframe_checkbox(self):
        """ Try to click checkbox in Cloudflare iframe:
            Returns: bool: <-- True if successful:"""
        
        try:
            iframes = self.sb.find_elements('iframe')
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                if 'challenges.cloudflare.com' in src or 'turnstile' in src:
                    self.sb.switch_to_frame(iframe)
                    try:
                        checkbox = self.sb.find_element('input[type="checkbox"]')
                        if checkbox:
                            self.sb.execute_script("arguments[0].click();", checkbox)
                            logger.info("Clicked Turnstile checkbox in iframe")
                            self._human_delay(CLOUDFLARE_DELAY, 5)
                    except NoSuchElementException:
                        pass
                    finally:
                        self.sb.switch_to_default_content()
            
            if not self._is_cloudflare_challenge():
                logger.info("Cloudflare challenge solved!")
                return True
        except WebDriverException as e:
            logger.debug(f"Iframe method failed: {e}")
        
        return False
    
    def _wait_for_manual_solve(self):
        """ Wait for manual Cloudflare challenge solution:
            Returns: bool: <-- True if solved within timeout:"""
        
        logger.warning("\n" + "=" * 60)
        logger.warning("MANUAL CLOUDFLARE VERIFICATION REQUIRED")
        logger.warning("=" * 60)
        if self.use_attach:
            logger.warning("Use the SAME Chrome window that warm_indeed_profile.py opened.")
            logger.warning("Click verify there — Selenium is not controlling a separate browser.")
        else:
            logger.warning("1. Click the 'Verify you are human' checkbox in the browser")
            logger.warning("2. Wait until Indeed search results load (not this black page)")
        logger.warning("3. Press ENTER here in the terminal when jobs load")
        logger.warning("=" * 60)
        
        try:
            input("\n>>> Press ENTER after Cloudflare clears and jobs page loads ... ")
        except EOFError:
            pass
        
        for wait_iteration in range(24):
            if not self._is_cloudflare_challenge():
                logger.info("Cloudflare challenge cleared!")
                return True
            logger.info(f"Still on Cloudflare page... ({(wait_iteration + 1) * 5}s)")
            time.sleep(5)
        
        logger.error("Cloudflare still blocking — try attach mode with real Chrome:")
        logger.error("  Terminal 1: python modules/warm_indeed_profile.py  (keep Chrome open)")
        logger.error("  Terminal 2: python src/main.py")
        return False
    
    def _find_turnstile_click_point_js(self):
        """Return viewport x/y for Turnstile checkbox via in-page JS."""
        script = """
        return (function() {
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                const src = (iframe.src || '').toLowerCase();
                const id = (iframe.id || '').toLowerCase();
                if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenge') || id.includes('cf-')) {
                    const rect = iframe.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return {found: true, x: rect.x + 30, y: rect.y + rect.height / 2};
                    }
                }
            }
            const text = document.body ? document.body.innerText : '';
            if (/verify you are human|additional verification required/i.test(text)) {
                return {found: true, x: 120, y: 280};
            }
            return {found: false};
        })();
        """
        try:
            return self.sb.execute_script(script) or {}
        except WebDriverException:
            return {}

    def _try_pyautogui_captcha(self, max_attempts=3):
        """Real mouse click on Turnstile — works in standard Chrome (not just UC)."""
        if not PYAUTOGUI_AVAILABLE:
            logger.info("PyAutoGUI not installed — pip install pyautogui for auto Cloudflare click")
            return False
        
        logger.info("Attempting PyAutoGUI Turnstile click (keep browser window visible)...")
        self._human_delay(2, 4)
        browser_chrome_height = 85 if platform.system() == 'Darwin' else 75
        
        for attempt in range(max_attempts):
            try:
                window_info = self.sb.execute_script(
                    "return {screenX: window.screenX, screenY: window.screenY};"
                ) or {}
                checkbox_info = self._find_turnstile_click_point_js()
                if not checkbox_info.get('found'):
                    logger.debug(f"Turnstile target not found (attempt {attempt + 1})")
                    self._human_delay(2, 3)
                    continue
                
                screen_x = window_info.get('screenX', 0) + checkbox_info['x']
                screen_y = window_info.get('screenY', 0) + browser_chrome_height + checkbox_info['y']
                target_x = screen_x + random.randint(-3, 3)
                target_y = screen_y + random.randint(-3, 3)
                
                logger.info(f"Clicking Turnstile at screen ({target_x:.0f}, {target_y:.0f})")
                pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.4, 0.8), tween=pyautogui.easeOutQuad)
                time.sleep(random.uniform(0.15, 0.35))
                pyautogui.click()
                self._human_delay(4, 6)
                
                if not self._is_cloudflare_challenge():
                    logger.info("Cloudflare challenge solved via PyAutoGUI!")
                    return True
            except Exception as e:
                logger.debug(f"PyAutoGUI attempt {attempt + 1} failed: {e}")
        
        return False

    def _persist_browser_cookies(self):
        """Save browser cookies (incl. cf_clearance) back to pickle for next run."""
        if not self.cookie_file:
            return
        try:
            cookie_path = Path(self.cookie_file)
            if not cookie_path.is_absolute():
                cookie_path = Path(__file__).parent.parent / cookie_path
            cookies = self.driver.get_cookies()
            if not cookies:
                return
            with open(cookie_path, 'wb') as f:
                pickle.dump(cookies, f)
            logger.info(f"Updated session cookies (incl. Cloudflare): {cookie_path.name}")
        except Exception as e:
            logger.debug(f"Could not persist cookies: {e}")

    def _is_cloudflare_challenge(self):
        """ Check if current page is Cloudflare challenge:
            Returns: bool: <-- True if Cloudflare challenge detected:"""
        
        try:
            title = self.sb.get_title().lower()
            page_source = self.sb.get_page_source().lower()
            
            indicators = [
                'just a moment' in title,
                'additional verification' in title,
                'cloudflare' in title,
                'verify you are human' in page_source,
                'additional verification required' in page_source,
                'checking your browser' in page_source,
                'challenges.cloudflare.com' in page_source,
                'cf-turnstile' in page_source,
                'ray id' in page_source,
            ]
            
            return any(indicators)
        except WebDriverException as e:
            logger.debug(f"Error checking Cloudflare challenge: {e}")
            return False

    def _extract_job_from_element(self, element, query, location, page_num):
        """ Extract job data from Selenium element:
            Args:
                element:        <-- Selenium WebElement of job card:
                query (str):    <-- Search query:
                location (str): <-- Search location:
                page_num (int): <-- Page number:
            Returns: dict:      <-- Job data: """
        
        job_data = {
            'scraped_at': datetime.now().isoformat(),
            'search_query': query,
            'search_location': location,
            'page_number': page_num,
        }
        
        # __ extract job key and url:
        job_key, job_url = self._extract_job_key_and_url(element)
        job_data['job_key'] = job_key if job_key else NOT_AVAILABLE
        
        # __ build url:
        if job_key:
            job_data['url'] = f"{BASE_URL}/viewjob?jk={job_key}"
        elif job_url:
            job_data['url'] = job_url
        else:
            job_data['url'] = NOT_AVAILABLE
        
        # __ extract other fields:
        job_data['title'] = self._extract_title(element)
        job_data['company'] = self._extract_company(element)
        job_data['location'] = self._extract_location(element)
        job_data['salary'] = self._extract_salary(element)
        job_data['snippet'] = self._extract_snippet(element)
        job_data['posted'] = self._extract_posted_date(element)
        
        return job_data
    
    def _extract_job_key_and_url(self, element):
        """ Extract job key and URL from element:
            Args: element:  <-- Selenium WebElement:
            Returns: tuple: <-- (job_key, job_url) or (None, None):"""
        
        job_key = None
        job_url = None
        
        # __ try multiple extraction methods:
        extraction_methods = [
            lambda: element.get_attribute('data-jk'),
            lambda: element.find_element(By.CSS_SELECTOR, 'a[data-jk]').get_attribute('data-jk'),
            lambda: element.find_element(By.CSS_SELECTOR, 'h2.jobTitle a').get_attribute('data-jk'),
            lambda: element.find_element(By.CSS_SELECTOR, 'a.jcs-JobTitle').get_attribute('data-jk'),
        ]
        
        for method in extraction_methods:
            try:
                job_key = method()
                if job_key:
                    return job_key, None
            except (NoSuchElementException, WebDriverException):
                continue
        
        # __ extract from href:
        href_selectors = [
            'a[href*="jk="]',
            'a[href*="viewjob"]',
            'a.jcs-JobTitle',
            'h2.jobTitle a',
        ]
        
        for selector in href_selectors:
            try:
                link = element.find_element(By.CSS_SELECTOR, selector)
                href = link.get_attribute('href')
                if href:
                    job_url = href
                    if 'jk=' in href:
                        job_key = href.split('jk=')[1].split('&')[0]
                        return job_key, job_url
            except (NoSuchElementException, WebDriverException):
                continue
        
        # __ try alternative attributes:
        try:
            job_key = element.get_attribute('data-mobtk') or element.get_attribute('id')
            if job_key and job_key.startswith('job_'):
                job_key = job_key.replace('job_', '')
        except WebDriverException:
            pass
        
        return job_key, job_url
    
    def _extract_title(self, element):
        """ Extract job title:
            Args: element:  <-- Selenium WebElement:
            Returns: str:   <-- Job title or NOT_AVAILABLE: """
        
        selectors = [
            ('h2.jobTitle span[title]', 'title'),
            ('[data-testid="jobTitle"]', 'text'),
            ('a.jcs-JobTitle', 'text'),
            ('h2.jobTitle a', 'text'),
            ('h2.jobTitle', 'text'),
            ('a[data-jk]', 'aria'),
            ('.jobTitle', 'text'),
        ]

        for selector, mode in selectors:
            try:
                elem = element.find_element(By.CSS_SELECTOR, selector)
                if mode == 'title':
                    value = elem.get_attribute('title')
                elif mode == 'aria':
                    value = elem.get_attribute('aria-label') or elem.text
                else:
                    value = elem.text
                value = (value or '').strip()
                if value:
                    return value
            except (NoSuchElementException, WebDriverException):
                continue
        return NOT_AVAILABLE
    
    def _extract_company(self, element):
        """ Extract company name:
            Args: element:  <-- Selenium WebElement:
            Returns: str:   <-- Company name or NOT_AVAILABLE: """
        
        selectors = [
            'span[data-testid="company-name"]',
            '.companyName',
            '[data-testid="company-name"]'
        ]
        
        for selector in selectors:
            try:
                elem = element.find_element(By.CSS_SELECTOR, selector)
                return elem.text.strip()
            except (NoSuchElementException, WebDriverException):
                continue
        return NOT_AVAILABLE
    
    def _extract_location(self, element):
        """ Extract job location:
            Args: element:  <-- Selenium WebElement:
            Returns: str:   <-- Job location or NOT_AVAILABLE: """
        
        selectors = [
            'div[data-testid="text-location"]',
            '.companyLocation'
        ]
        
        for selector in selectors:
            try:
                elem = element.find_element(By.CSS_SELECTOR, selector)
                return elem.text.strip()
            except (NoSuchElementException, WebDriverException):
                continue
        return NOT_AVAILABLE
    
    def _extract_salary(self, element):
        """ Extract salary from job card:
            Args: element:  <-- Selenium WebElement:
            Returns: str:   <-- Salary text or NOT_AVAILABLE:"""
        
        salary_selectors = [
            'div[data-testid="attribute_snippet_testid"]',
            'div.salary-snippet-container',
            'div.salaryOnly',
            '.salary-snippet',
            '.salaryText',
            'div.metadata',
            'div[class*="salary"]',
        ]
        
        for selector in salary_selectors:
            try:
                elems = element.find_elements(By.CSS_SELECTOR, selector)
                for elem in elems:
                    text = elem.text.strip()
                    if text and self._looks_like_salary(text):
                        return text.split('\n')[0].strip()
            except (NoSuchElementException, WebDriverException):
                continue
        
        # __ Regex fallback:
        try:
            salary = self._extract_salary_regex(element.text)
            if salary:
                return salary
        except WebDriverException:
            pass
        
        return NOT_AVAILABLE
    
    def _looks_like_salary(self, text):
        """ Check if text looks like salary:
            Args: text (str):   <-- Text to check:
            Returns: bool:      <-- True if appears to be salary: """
        
        if not text:
            return False
        
        text_lower = text.lower()
        has_dollar = '$' in text
        has_salary_keyword = any(kw in text_lower for kw in ['year', 'hour', 'month', 'week', '/yr', '/hr', 'annually', 'per '])
        exclude_patterns = ['posted', 'ago', 'apply', 'easily', 'active', 'hiring']
        has_exclude = any(ex in text_lower for ex in exclude_patterns)
        return (has_dollar or has_salary_keyword) and not has_exclude
    
    def _extract_salary_regex(self, text):
        """ Extract salary using regex patterns:
            Args: text (str):   <-- Full text to search:            
            Returns: str:       <-- Extracted salary or None: """
        
        patterns = [
            r'\$[\d,]+(?:\.\d{2})?\s*-\s*\$[\d,]+(?:\.\d{2})?\s*(?:a|an|per)?\s*(?:year|hour|month|week)',
            r'\$[\d,]+(?:\.\d{2})?\s*(?:a|an|per)?\s*(?:year|hour|month|week)',
            r'\$[\d,]+(?:\.\d{2})?\s*-\s*\$[\d,]+(?:\.\d{2})?',
            r'\$[\d,]+(?:K)?\s*-\s*\$[\d,]+(?:K)?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None
    
    def _extract_snippet(self, element):
        """ Extract job description snippet:
            Args: element:  <-- Selenium WebElement:
            Returns: str:   <-- Snippet text or NOT_AVAILABLE:"""
        
        selectors = [
            'div.job-snippet',
            'div[class*="job-snippet"]',
            'div.jobsearch-JobComponent-description',
            'ul.css-kyg8or',
            'table.jobCardShelfContainer td',
        ]
        
        for selector in selectors:
            try:
                elems = element.find_elements(By.CSS_SELECTOR, selector)
                for elem in elems:
                    text = elem.text.strip()
                    if text and len(text) > 20:
                        if not self._looks_like_salary(text) and 'posted' not in text.lower():
                            return text[:MAX_SNIPPET_LENGTH]
            except (NoSuchElementException, WebDriverException):
                continue
        return NOT_AVAILABLE
    
    def _extract_posted_date(self, element):
        """ Extract posted date:
            Args: element:  <-- Selenium WebElement:
            Returns: str:   <-- Posted date or NOT_AVAILABLE:"""
        
        selectors = [
            'span[data-testid="myJobsStateDate"]',
            'span.date',
            '.jobMetaDataGroup span',
            'span.css-qvloho',
            'span[class*="date"]',
            'div.metadata span',
            '[class*="underShelfFooter"] span',
            '[data-testid="attribute_snippet_testid"]',
            '[data-testid="attribute_snippet_testid"] li',
        ]
        
        for selector in selectors:
            try:
                elems = element.find_elements(By.CSS_SELECTOR, selector)
                for elem in elems:
                    text = elem.text.strip()
                    if not text:
                        continue
                    lower = text.lower()
                    if self._looks_like_salary(text) and not any(
                        kw in lower for kw in ('ago', 'posted', 'just', 'today', 'active')
                    ):
                        continue
                    if any(kw in lower for kw in ['posted', 'ago', 'day', 'hour', 'week', 'month', 'just', 'today', 'active', 'employer']):
                        return text.split('\n')[0].strip()
            except (NoSuchElementException, WebDriverException):
                continue
        
        # __ Regex fallback:
        try:
            card_text = element.text.lower()
            patterns = [
                r'posted\s+\d+\s+(?:day|hour|week|month)s?\s+ago',
                r'just\s+posted',
                r'active\s+\d+\s+(?:day|hour|week|month)s?\s+ago',
                r'today',
                r'\d+\s+(?:day|hour|week|month)s?\s+ago',
            ]
            for pattern in patterns:
                match = re.search(pattern, card_text)
                if match:
                    return match.group(0).title()
        except WebDriverException:
            pass
        
        return NOT_AVAILABLE

    def _take_page_screenshot(self, page_num, query, session_ts):
        """ Take screenshot of entire page:
            Args: page_num (int):   <-- Page number:
                  query (str):      <-- Search query:
                  session_ts (str): <-- Session timestamp:
            Returns: Path:          <-- Screenshot file path or None:"""
        
        try:
            safe_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')[:30]
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"page{page_num:02d}_{safe_query}_{session_ts}_{timestamp}.png"
            filepath = self.pages_dir / filename

            if self.use_attach:
                # Full-page capture can hang on attached Chrome — viewport only, best-effort.
                self.driver.save_screenshot(str(filepath))
            else:
                self.sb.save_screenshot(str(filepath))
            logger.info(f"  [Screenshot] Page: {filename}")
            return filepath
        except WebDriverException as e:
            if self.use_attach:
                logger.debug(f"Attach mode page screenshot skipped: {e}")
            else:
                logger.warning(f"Screenshot error: {e}")
            return None
        except Exception as e:
            logger.debug(f"Screenshot skipped: {e}")
            return None
    
    def _take_job_screenshot(self, element, page_num, job_num, title, job_key, session_ts):
        """ Take screenshot of job card:
            Args:
                element:            <-- Selenium WebElement:
                page_num (int):     <-- Page number:
                job_num (int):      <-- Job number:
                title (str):        <-- Job title:
                job_key (str):      <-- Job key:
                session_ts (str):   <-- Session timestamp:
            Returns: Path:          <-- Screenshot file path or None: """
        try:
            # __ scroll into view:
            self.sb.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            self._human_delay(0.3, 0.5)
            
            # __ build filename:
            safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:25]
            safe_key = job_key if job_key not in [NOT_AVAILABLE, "N/A"] else "nokey"
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"page{page_num:02d}_job{job_num:03d}_{safe_title}_{safe_key}_{timestamp}.png"
            filepath = self.cards_dir / filename
            
            # __ take screenshot:
            element.screenshot(str(filepath))
            return filepath
        except WebDriverException as e:
            logger.debug(f"Element screenshot failed: {e}")
            
            # __ fallback to full page:
            try:
                safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:25]
                timestamp = datetime.now().strftime("%H%M%S")
                filename = f"page{page_num:02d}_job{job_num:03d}_{safe_title}_full_{timestamp}.png"
                filepath = self.cards_dir / filename
                self.sb.save_screenshot(str(filepath))
                return filepath
            except WebDriverException as e2:
                logger.warning(f"Fallback screenshot failed: {e2}")
                return None
    
    def _human_delay(self, min_seconds=DEFAULT_DELAY_MIN, max_seconds=DEFAULT_DELAY_MAX):
        """ Random human-like delay:
            Args:
                min_seconds (float): <-- Minimum delay
                max_seconds (float): <-- Maximum delay: """
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
    
    def _quit_attached_chrome(self):
        """Close only the scraper Chrome instance (never quit all Chrome on macOS)."""
        from modules.sb_utils import close_attach_session

        close_attach_session(driver=self.driver, board="indeed", logger=logger)

    def close(self):
        """ Close browser and cleanup: """
        try:
            if self.use_attach:
                if os.environ.get("INDEED_QUIT_CHROME", "").strip().lower() in ("1", "true", "yes"):
                    self._quit_attached_chrome()
                    logger.info("Closed attached Chrome session")
                else:
                    logger.info("Detached from Chrome (your browser was left open)")
                return
            if self._sb_context:
                self._sb_context.__exit__(None, None, None)
                logger.info("SeleniumBase browser closed")
        except Exception as e:
            logger.error(f"Error closing browser: {e}")


if __name__ == "__main__":
    pass
