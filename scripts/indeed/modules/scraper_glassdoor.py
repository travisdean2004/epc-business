#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""SeleniumBase UC Mode Glassdoor Scraper - Working Version
Based on actual DOM structure analysis:
- Container: ul.JobsList_jobsList__lqjTr
- Cards: li.JobsList_jobListItem__wjTHv
- Title: a[data-test="job-title"]
"""

import re
import os
import time
import random
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus
from modules.cfg import get_base_url
from modules.cloudflare_helpers import ensure_page_ready, ensure_warm_chrome_for_board, load_board_cookies
from modules.sb_utils import (open_url, finalize_job_listing, job_listing_is_usable, is_duplicate_listing, start_board_browser, use_board_attach,)
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_DELAY_MIN = 1
DEFAULT_DELAY_MAX = 3
PAGE_DELAY_MIN = 3
PAGE_DELAY_MAX = 5
NOT_AVAILABLE = "Not Available"
MAX_SNIPPET_LENGTH = 300
MAX_CONSECUTIVE_FAILURES = 3

class GlassdoorScraper:
    """Glassdoor scraper using SeleniumBase UC Mode"""

    def __init__(self, headless=False, incognito=False, window_size="maximized", proxy=None, screenshots=False, artifacts_dir=None, cookie_file=None):
        self.window_size = window_size
        self.screenshots = screenshots
        self.incognito = incognito
        self.headless = headless
        self.proxy = proxy
        self.cookie_file = cookie_file
        self.driver = None
        self.sb = None
        self._context_manager = None
        self.use_attach = False
        self.board = "glassdoor"

        if artifacts_dir:
            self.artifacts_dir = Path(artifacts_dir)
        else:
            self.artifacts_dir = Path(__file__).parents[1] / "artifacts"

        self.screenshots_dir = self.artifacts_dir / "screenshots"
        self.pages_dir = self.screenshots_dir / "pages"
        self.cards_dir = self.screenshots_dir / "cards"

        if self.screenshots:
            self.pages_dir.mkdir(parents=True, exist_ok=True)
            self.cards_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Page screenshots: {self.pages_dir}")
            logger.info(f"Card screenshots: {self.cards_dir}")

        if not use_board_attach(self.board):
            allow_selenium = os.environ.get("GLASSDOOR_ALLOW_SELENIUM", "0").lower() in (
                "1",
                "true",
                "yes",
            )
            if not allow_selenium:
                ensure_warm_chrome_for_board(self.board, logger=logger)

        self._start_browser()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _start_browser(self):
        try:
            session = start_board_browser(
                self.board,
                headless=self.headless,
                incognito=self.incognito,
                proxy=self.proxy,
                window_size=self.window_size,
                logger=logger,
                landing_url=get_base_url("glassdoor"),
            )
            self.sb = session["sb"]
            self.driver = session["driver"]
            self._context_manager = session["context"]
            self.use_attach = session["use_attach"]
            if self.use_attach:
                logger.info("Glassdoor attach mode — use the warmed Chrome window on debug port 9223")
            elif not self.use_attach:
                load_board_cookies(self.driver, self.board, get_base_url("glassdoor"), logger)
            logger.info("Browser started successfully")
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise

    def _build_search_url(self, query, location="", remote_only=False):
        query_encoded = quote_plus(query.strip().replace(' ', '-'))
        query_len = len(query.strip())
        base_url = get_base_url(jb_board="glassdoor") + f"/Job/{query_encoded}-jobs-SRCH_KO0,{query_len}.htm"
        logger.info(f"[*]\tGlassdoor search URL: {base_url}")

        if remote_only:
            base_url += "?remoteWorkType=1"
        return base_url

    def _wait_for_job_listings(self):
        try:
            logger.info("Waiting for job listings ...")
            selectors = [
                'li[data-test="jobListing"]',
                'a[data-test="job-title"]',
                'ul[class*="JobsList"] li',
            ]
            for selector in selectors:
                try:
                    self.sb.wait_for_element(selector, timeout=10)
                    logger.info(f"Job listings found via: {selector}")
                    time.sleep(2)
                    return True
                except TimeoutException:
                    continue

            logger.warning("Could not find job listings ...")
            try:
                self.sb.save_screenshot("debug_no_listings.png")
                logger.info("Screenshot saved: debug_no_listings.png")
            except Exception:
                pass
            return False
        except Exception as e:
            logger.warning(f"Error waiting for listings: {e}")
            return False

    def _extract_jobs_via_javascript(self, max_results):
        """ Extract all job data using JavaScript """
        try:
            extract_script = """
            return (function(maxResults) {
                const cardSelectors = [
                    'li[data-test="jobListing"]',
                    'li[data-test="job-listing"]',
                    'ul[class*="JobsList"] li',
                    '[data-test="jobListing"]',
                ];
                let cards = [];
                for (const sel of cardSelectors) {
                    const found = Array.from(document.querySelectorAll(sel));
                    if (found.length) {
                        cards = found;
                        break;
                    }
                }
                if (!cards.length) return [];

                function decodeHtml(html) {
                    const txt = document.createElement('textarea');
                    txt.innerHTML = html;
                    return txt.value;
                }

                function cleanText(text) {
                    if (!text) return '';
                    text = decodeHtml(text);
                    return text.replace(/\\s+/g, ' ').trim();
                }

                return cards.slice(0, maxResults).map((card) => {
                    const data = {
                        job_id: card.getAttribute('data-jobid')
                            || card.getAttribute('data-id')
                            || card.getAttribute('id')
                            || 'Not Available',
                        title: 'Not Available',
                        url: 'Not Available',
                        company: 'Not Available',
                        job_location: 'Not Available',
                        salary: 'Not Available',
                        company_rating: 'Not Available',
                        description: 'Not Available',
                        posted_date: 'Not Available',
                        easy_apply: false
                    };

                    const titleLink = card.querySelector('a[data-test="job-title"]')
                        || card.querySelector('a[href*="/job-listing/"]')
                        || card.querySelector('a.jobTitle')
                        || card.querySelector('a[href*="jobListingId"]');
                    if (titleLink) {
                        data.title = cleanText(titleLink.textContent)
                            || cleanText(titleLink.getAttribute('aria-label'))
                            || 'Not Available';
                        data.url = titleLink.href || 'Not Available';
                    }

                    if ((!data.url || data.url === 'Not Available')) {
                        const anyLink = card.querySelector('a[href*="/job-listing/"], a[href*="jobListingId"]');
                        if (anyLink) data.url = anyLink.href;
                    }

                    const companyElem = card.querySelector('span[data-test="employer-name"]')
                        || card.querySelector('[data-test="emp-name"]')
                        || card.querySelector('[class*="EmployerName"]');
                    if (companyElem) {
                        let companyText = cleanText(companyElem.textContent);
                        companyText = companyText.replace(/\\d+\\.\\d+★?\\s*$/, '').trim();
                        data.company = companyText;
                    }

                    const ratingElem = card.querySelector('span[class*="RatingText"]')
                        || card.querySelector('[data-test="rating"]');
                    if (ratingElem) {
                        data.company_rating = cleanText(ratingElem.textContent);
                    }

                    const locationElem = card.querySelector('div[data-test="emp-location"]')
                        || card.querySelector('[data-test="location"]');
                    if (locationElem) {
                        data.job_location = cleanText(locationElem.textContent);
                    }

                    const salaryElem = card.querySelector('div[data-test="detailSalary"]')
                        || card.querySelector('[data-test="salary"]');
                    if (salaryElem) {
                        data.salary = cleanText(salaryElem.textContent);
                    }

                    const descElem = card.querySelector('div[data-test="descSnippet"]')
                        || card.querySelector('[class*="JobDescription"]');
                    if (descElem) {
                        data.description = cleanText(descElem.textContent);
                    }

                    const ageElem = card.querySelector('div[data-test="job-age"]')
                        || card.querySelector('[data-test="job-age"]');
                    if (ageElem) {
                        data.posted_date = cleanText(ageElem.textContent);
                    }

                    if (/easy apply/i.test(card.textContent || '')) {
                        data.easy_apply = true;
                    }

                    return data;
                });
            })(arguments[0]);
            """

            jobs_data = self.sb.execute_script(extract_script, max_results)

            if jobs_data and isinstance(jobs_data, list):
                usable = []
                for raw in jobs_data:
                    job = finalize_job_listing(raw, board_label="Glassdoor", id_field="job_id")
                    if job_listing_is_usable(job, id_fields=("job_id",)):
                        usable.append(job)
                logger.info(
                    f"JavaScript extracted {len(usable)} usable listing(s) "
                    f"(raw cards: {len(jobs_data)})"
                )
                return usable
            else:
                logger.warning("JavaScript extraction returned no data:")
                return []

        except Exception as e:
            logger.error(f"Error in JavaScript extraction: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []

    def _take_page_screenshot(self, page_num, query, session_ts):
        """ Take full page screenshot: """
        try:
            filename = f"page_{page_num:02d}_{query.replace(' ', '_')}_{session_ts}.png"
            filepath = self.pages_dir / filename

            # __ get full page height for complete screenshot:
            try:
                # __ method 1: use SeleniumBase's full page screenshot:
                self.sb.save_screenshot(str(filepath), folder="")
                logger.info(f"Full page screenshot saved: {filepath}")
                return filepath
            except:
                # __ fallback: regular screenshot:
                self.driver.save_screenshot(str(filepath))
                logger.debug(f"Page screenshot: {filepath}")
                return filepath

        except Exception as e:
            logger.debug(f"Failed to take page screenshot: {e}")
            return None

    def _take_job_screenshot(self, job_index, page_num, job_num, title, job_id, session_ts):
        """Take screenshot of individual job card"""
        try:
            safe_title = re.sub(r'[^\w\s-]', '', title)[:30].replace(' ', '_')
            filename = f"job_{job_num:03d}_p{page_num:02d}_{safe_title}_{job_id}_{session_ts}.png"
            filepath = self.cards_dir / filename

            # __ get the card element and screenshot it:
            script = f"""
            (function() {{
                const ul = document.querySelector('ul.JobsList_jobsList__lqjTr');
                if (!ul) return null;
                const cards = ul.querySelectorAll('li.JobsList_jobListItem__wjTHv');
                return cards[{job_index}];
            }})();
            """

            card_element = self.sb.execute_script(script)
            if card_element:
                # __ take element screenshot using JavaScript canvas:
                screenshot_script = """return arguments[0].outerHTML.length;"""
                self.sb.execute_script(screenshot_script, card_element)
                logger.debug(f"Job card screenshot attempted: {filepath}")
                return str(filepath)
            else:
                return None

        except Exception as e:
            logger.debug(f"Failed to take job screenshot: {e}")
            return None

    def _scroll_to_load_more(self):
        try:
            self.sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX))
            return True
        except Exception as e:
            logger.warning(f"Error scrolling: {e}")
            return False

    def search_jobs(self, query, location="", remote_only=False, min_salary=None, max_salary=None, date_posted=None, max_results=25):
        """ Search for jobs on Glassdoor """

        search_url = self._build_search_url(query, location, remote_only)
        if remote_only:
            location_display = "Remote"
        else:
            location_display = location or "All Locations"
        logger.info(f"Searching Glassdoor: '{query}' in '{location_display}'")
        logger.info(f"Max results: {max_results}")
        logger.info(f"Search URL: {search_url}")

        try:
            open_url(self.sb, search_url, logger)
            time.sleep(random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX))
            if not ensure_page_ready(
                self.sb,
                logger,
                board=self.board,
                site_name="Glassdoor",
                jobs_hint="Glassdoor job listings",
                use_attach=self.use_attach,
                landing_url=get_base_url("glassdoor"),
            ):
                logger.error("Cloudflare blocked Glassdoor — try warm profile + attach mode")
                return []
        except Exception as e:
            logger.error(f"Failed to load search page: {e}")
            return []

        if not self._wait_for_job_listings():
            logger.warning("No job listings found")
            return []

        session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.screenshots:
            self._take_page_screenshot(1, query, session_ts)

        all_jobs = []
        scroll_attempts = 0
        max_scroll_attempts = 5

        # __ keep scrolling and extracting until we have enough jobs:
        while len(all_jobs) < max_results and scroll_attempts < max_scroll_attempts:
            # __ extract currently visible jobs:
            jobs_data = self._extract_jobs_via_javascript(max_results * 2)  # Get more than needed

            if not jobs_data:
                logger.warning("No jobs extracted from visible listings")
                break

            jobs_added = 0
            for job in jobs_data:
                if len(all_jobs) >= max_results:
                    break

                job = finalize_job_listing(job, board_label="Glassdoor", id_field="job_id")
                if not job_listing_is_usable(job, id_fields=("job_id",)):
                    continue
                if is_duplicate_listing(job, all_jobs, id_fields=("job_id",)):
                    continue

                job_record = {
                    'query': query,
                    'location': location,
                    'page': 1,
                    'scraped_at': datetime.now().isoformat(),
                    'title': job['title'],
                    'company': job['company'],
                    'job_location': job['job_location'],
                    'salary': job['salary'],
                    'posted_date': job['posted_date'],
                    'posted': job['posted_date'],
                    'url': job['url'],
                    'job_id': job['job_id'],
                    'company_rating': job['company_rating'],
                    'easy_apply': job['easy_apply'],
                    'description': job['description'],
                    'snippet': job['description'],
                    'screenshot': NOT_AVAILABLE
                }

                all_jobs.append(job_record)
                jobs_added += 1

                if len(all_jobs) >= max_results:
                    break

            if jobs_added:
                logger.info(
                    f"Collected {jobs_added} listing(s) for '{query}' "
                    f"(total {len(all_jobs)}; board may include related jobs)"
                )

            # __ if we have enough jobs, stop:
            if len(all_jobs) >= max_results:
                break

            # __ scroll to load more jobs:
            logger.info(f"Loaded {len(all_jobs)} jobs so far, scrolling for more... (attempt {scroll_attempts + 1}/{max_scroll_attempts})")
            if self._scroll_to_load_more():
                scroll_attempts += 1
                time.sleep(2)
            else:
                break

        # __ trim to max_results:
        all_jobs = all_jobs[:max_results]

        # __ log final results:
        for idx, job in enumerate(all_jobs, 1):
            title_short = job['title'][:50]
            company_short = job['company'][:30]
            logger.info(f"[{idx}/{max_results}] {title_short} @ {company_short}")

        logger.info(f"\n{'='*80}")
        logger.info(f"Scraping complete: {len(all_jobs)} jobs collected")
        logger.info(f"{'='*80}")
        return all_jobs

    def close(self):
        if getattr(self, "use_attach", False):
            from modules.sb_utils import close_attach_session

            close_attach_session(driver=self.driver, board=self.board, logger=logger)
            return
        if self._context_manager:
            try:
                self._context_manager.__exit__(None, None, None)
                logger.info("Browser closed")
            except Exception as e:
                logger.debug(f"Error closing browser: {e}")