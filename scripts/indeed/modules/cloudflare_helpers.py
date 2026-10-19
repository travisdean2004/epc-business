#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Shared Cloudflare challenge handling for job board scrapers.

Selenium-controlled Chrome is often flagged — clearance does not stick and the
challenge keeps returning. Prefer real Chrome attach mode:

    python modules/warm_indeed_profile.py --board dice
    python src/main.py --auto --board dice ...
"""

import pickle
import platform
import random
import time
from pathlib import Path

try:
    import pyautogui

    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

from selenium.common.exceptions import NoSuchElementException, WebDriverException

CF_DELAY = 3
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIE_DIR = PROJECT_ROOT / "artifacts" / "cookies"

TURNSTILE_CLICK_JS = """
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

DICE_CONTENT_JS = 'return document.querySelectorAll(\'a[href*="/job-detail/"]\').length;'
GLASSDOOR_CONTENT_JS = ('return document.querySelectorAll(\'a[data-test="job-title"], li[data-test="jobListing"]\').length;')
INDEED_CONTENT_JS = 'return document.querySelectorAll(\'a[data-jk], .job_seen_beacon\').length;'


def ensure_warm_chrome_for_board(board, logger=None, timeout=180):
    """Block until warmed real Chrome is attachable, or raise with instructions."""
    from modules.sb_utils import board_debug_port, is_chrome_attachable, wait_for_chrome_debug_port
    from modules.cfg import get_base_url

    board = (board or "indeed").lower()
    port = board_debug_port(board)
    if is_chrome_attachable(port):
        return port

    landing = get_base_url(board) if board in ("indeed", "glassdoor", "dice") else "about:blank"
    msg = (
        f"\n{'=' * 72}\n"
        f"{board.upper()} requires REAL Chrome (not Selenium automation).\n"
        f"Glassdoor shows a 'Humans only' page that loops forever in Selenium Chrome.\n\n"
        f"  Terminal 1:  python modules/warm_indeed_profile.py --board {board}\n"
        f"               Pass the checkbox, confirm job listings load, KEEP Chrome OPEN.\n"
        f"               (debug port {port})\n\n"
        f"  Terminal 2:  python src/main.py\n"
        f"{'=' * 72}\n"
        f"Waiting up to {timeout}s for Chrome on port {port} ..."
    )
    if logger:
        logger.warning(msg)
    else:
        print(msg)

    wait_for_chrome_debug_port(port, timeout=timeout, logger=logger, landing_url=landing)
    return port


def board_cookie_path(board):
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    return COOKIE_DIR / f"{board}_session.pkl"


def load_board_cookies(driver, board, landing_url, logger=None):
    """Restore saved session cookies (incl. cf_clearance) before scraping."""
    path = board_cookie_path(board)
    if not path.exists():
        return 0
    try:
        with open(path, "rb") as handle:
            cookies = pickle.load(handle)
    except (OSError, pickle.UnpicklingError):
        return 0

    try:
        driver.get(landing_url)
        time.sleep(1)
    except WebDriverException:
        return 0

    added = 0
    for cookie in cookies:
        try:
            item = dict(cookie)
            if "expiry" in item:
                item["expiry"] = int(item["expiry"])
            item.pop("sameSite", None)
            driver.add_cookie(item)
            added += 1
        except (WebDriverException, ValueError, TypeError):
            continue

    if logger and added:
        logger.info(f"Loaded {added} saved cookies for {board} (incl. Cloudflare clearance if present)")
    return added


def persist_board_cookies(driver, board, logger=None):
    """Save browser cookies after manual Cloudflare clearance."""
    try:
        cookies = driver.get_cookies()
        if not cookies:
            return False
        path = board_cookie_path(board)
        with open(path, "wb") as handle:
            pickle.dump(cookies, handle)
        if logger:
            logger.info(f"Saved session cookies for {board}: {path.name}")
        return True
    except Exception as exc:
        if logger:
            logger.debug(f"Could not persist cookies for {board}: {exc}")
        return False


def _content_count(sb, script):
    try:
        return int(sb.execute_script(script) or 0)
    except Exception:
        return 0


def content_ready_for_board(sb, board):
    board = (board or "").lower()
    if board == "glassdoor" and is_board_blocked(sb, board):
        return False
    if board == "dice":
        return _content_count(sb, DICE_CONTENT_JS) > 0
    if board == "glassdoor":
        return _content_count(sb, GLASSDOOR_CONTENT_JS) > 0
    if board == "indeed":
        return _content_count(sb, INDEED_CONTENT_JS) > 0
    return False


def is_board_blocked(sb, board=None):
    """Board-specific bot/challenge pages (Glassdoor 'Humans only', CF tokens in URL)."""
    try:
        url = sb.get_current_url().lower()
        title = sb.get_title().lower()
        snippet = sb.get_page_source().lower()[:15000]
    except WebDriverException:
        return False

    board = (board or "").lower()
    if board == "glassdoor" or "glassdoor.com" in url:
        if "__cf_chl" in url or "cf_chl_rt" in url:
            return True
        if "humans only" in title or "humans only" in snippet:
            return True
        if "security service to protect glassdoor" in snippet:
            return True
        if "verify you are human" in snippet and "glassdoor.com" in url:
            return True
    return False


def is_cloudflare_challenge(sb, content_ready_fn=None, board=None):
    """Return True only when the page is blocked — not normal pages with CF CDN assets."""
    if content_ready_fn and content_ready_fn():
        return False
    if board and is_board_blocked(sb, board):
        return True
    if is_board_blocked(sb):
        return True

    try:
        title = sb.get_title().lower()
        page_source = sb.get_page_source().lower()
    except WebDriverException:
        return False

    blocking_title = (
        "just a moment" in title
        or "humans only" in title
        or "attention required" in title
        or "additional verification" in title
        or title.strip() in ("", "cloudflare")
    )
    blocking_body = (
        "verify you are human" in page_source
        or "humans only" in page_source
        or "additional verification required" in page_source
        or "checking your browser before accessing" in page_source
        or "security service to protect glassdoor" in page_source
        or "challenges.cloudflare.com" in page_source
        or "cf-turnstile" in page_source
        or "__cf_chl" in page_source
        or ("checking your browser" in page_source and "just a moment" in title)
    )

    if blocking_body and ("glassdoor.com" in page_source or "humans only" in title):
        return True
    if blocking_title and ("cloudflare" in title or "just a moment" in title):
        return True
    if "challenges.cloudflare.com" in page_source and not (content_ready_fn and content_ready_fn()):
        return True
    return False


def wait_for_manual_solve(sb, logger, site_name="site", jobs_hint="job listings", content_ready_fn=None, timeout_sec=600, board=None, use_attach=False,):
    """Poll until the user clears Cloudflare in the browser (no Enter required)."""
    
    board_key = (board or site_name.split()[0]).lower()
    logger.warning("\n" + "=" * 60)
    logger.warning("MANUAL CLOUDFLARE VERIFICATION REQUIRED")
    logger.warning("=" * 60)
    logger.warning(f"Site: {site_name}")
    if not use_attach and board_key in ("glassdoor", "dice"):
        logger.warning("You are in SELENIUM Chrome — Glassdoor 'Humans only' usually LOOPS here.")
        logger.warning("Stop (Ctrl+C), then use real Chrome attach mode:")
        logger.warning(f"  python modules/warm_indeed_profile.py --board {board_key}")
        logger.warning("  Keep that window open, re-run the scraper.")
    else:
        logger.warning("Complete verification in the Chrome window the scraper is using.")
    try:
        logger.warning(f"Browser URL:  {sb.get_current_url()}")
        logger.warning(f"Page title:   {sb.get_title()}")
    except WebDriverException:
        pass
    logger.warning(f"Waiting until {jobs_hint} appear — up to {timeout_sec // 60} minutes.")
    logger.warning("=" * 60)

    deadline = time.time() + timeout_sec
    last_log = 0.0
    selenium_warned = False
    while time.time() < deadline:
        if content_ready_fn and content_ready_fn():
            logger.info("Job content detected — page is ready!")
            return True
        if not is_cloudflare_challenge(sb, content_ready_fn, board=board_key):
            if content_ready_fn and content_ready_fn():
                logger.info("Cloudflare challenge cleared!")
                return True

        now = time.time()
        elapsed = int(now - (deadline - timeout_sec))
        if (
            not use_attach
            and board_key == "glassdoor"
            and elapsed >= 45
            and not selenium_warned
        ):
            selenium_warned = True
            logger.error(
                "Still blocked after 45s in Selenium Chrome — this will not clear. "
                "Use warm profile attach mode (see instructions above)."
            )
        if now - last_log >= 15:
            logger.info(f"Still waiting for you to verify in browser... ({elapsed}s)")
            last_log = now
        time.sleep(2)

    logger.error(
        f"Cloudflare still blocking {site_name}. Use warm profile + attach mode "
        f"(python modules/warm_indeed_profile.py --board {board_key})"
    )
    return False


def try_pyautogui_captcha(sb, logger, max_attempts=3):
    """Real mouse click on Turnstile — works in standard Chrome."""
    if not PYAUTOGUI_AVAILABLE:
        logger.info("PyAutoGUI not installed — pip install pyautogui for auto Cloudflare click")
        return False

    logger.info("Attempting PyAutoGUI Turnstile click (keep browser window visible)...")
    time.sleep(random.uniform(2, 4))
    browser_chrome_height = 85 if platform.system() == "Darwin" else 75

    for attempt in range(max_attempts):
        try:
            window_info = sb.execute_script("return {screenX: window.screenX, screenY: window.screenY};") or {}
            checkbox_info = sb.execute_script(TURNSTILE_CLICK_JS) or {}
            if not checkbox_info.get("found"):
                logger.debug(f"Turnstile target not found (attempt {attempt + 1})")
                time.sleep(random.uniform(2, 3))
                continue

            screen_x = window_info.get("screenX", 0) + checkbox_info["x"]
            screen_y = window_info.get("screenY", 0) + browser_chrome_height + checkbox_info["y"]
            target_x = screen_x + random.randint(-3, 3)
            target_y = screen_y + random.randint(-3, 3)

            logger.info(f"Clicking Turnstile at screen ({target_x:.0f}, {target_y:.0f})")
            pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.4, 0.8), tween=pyautogui.easeOutQuad,)
            time.sleep(random.uniform(0.15, 0.35))
            pyautogui.click()
            time.sleep(random.uniform(4, 6))

            if not is_cloudflare_challenge(sb):
                logger.info("Cloudflare challenge solved via PyAutoGUI!")
                return True
        except Exception as exc:
            logger.debug(f"PyAutoGUI attempt {attempt + 1} failed: {exc}")

    return False


def try_iframe_checkbox(sb, logger):
    """Try clicking the checkbox inside a Cloudflare/Turnstile iframe."""
    try:
        iframes = sb.find_elements("iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if "challenges.cloudflare.com" in src or "turnstile" in src:
                sb.switch_to_frame(iframe)
                try:
                    checkbox = sb.find_element('input[type="checkbox"]')
                    if checkbox:
                        sb.execute_script("arguments[0].click();", checkbox)
                        logger.info("Clicked Turnstile checkbox in iframe")
                        time.sleep(CF_DELAY)
                except NoSuchElementException:
                    pass
                finally:
                    sb.switch_to_default_content()

        if not is_cloudflare_challenge(sb):
            logger.info("Cloudflare challenge solved!")
            return True
    except WebDriverException as exc:
        logger.debug(f"Iframe method failed: {exc}")

    return False


def handle_cloudflare(sb, logger, *, site_name="site", jobs_hint="job listings", board=None, content_ready_fn=None, persist_cookies=None, try_automation=True, use_attach=False,):
    """Detect and handle Cloudflare. Returns True if challenge was cleared."""
    if not is_cloudflare_challenge(sb, content_ready_fn, board=board):
        return False

    logger.info(f"Cloudflare challenge detected on {site_name} — attempting bypass ...")

    if use_attach:
        logger.info("Attach mode — complete verification in your Chrome window (automation skipped)")
        solved = wait_for_manual_solve(sb, logger, site_name=site_name, jobs_hint=jobs_hint, content_ready_fn=content_ready_fn, board=board, use_attach=use_attach,)
        if solved and board:
            persist_board_cookies(sb.driver, board, logger)
        elif solved and persist_cookies:
            persist_cookies()
        return solved

    if try_automation and board not in ("glassdoor",):
        if try_pyautogui_captcha(sb, logger):
            if board:
                persist_board_cookies(sb.driver, board, logger)
            elif persist_cookies:
                persist_cookies()
            return True
        if try_iframe_checkbox(sb, logger):
            if board:
                persist_board_cookies(sb.driver, board, logger)
            elif persist_cookies:
                persist_cookies()
            return True

    solved = wait_for_manual_solve(sb, logger, site_name=site_name, jobs_hint=jobs_hint, content_ready_fn=content_ready_fn, board=board, use_attach=use_attach,)
    if solved:
        if board:
            persist_board_cookies(sb.driver, board, logger)
        elif persist_cookies:
            persist_cookies()
    return solved


def ensure_page_ready(sb, logger, *, board, site_name=None, jobs_hint="job listings", use_attach=False, landing_url=None, max_rounds=4,):
    """After navigation, wait out Cloudflare loops until listings load or we give up."""
    board = (board or "indeed").lower()
    site = site_name or board.title()
    content_fn = lambda: content_ready_for_board(sb, board)

    if content_fn():
        return True

    if landing_url and not use_attach:
        load_board_cookies(sb.driver, board, landing_url, logger)

    if not is_cloudflare_challenge(sb, content_fn, board=board) and not content_fn():
        return True

    for round_num in range(1, max_rounds + 1):
        if content_fn():
            return True
        if not is_cloudflare_challenge(sb, content_fn, board=board) and round_num > 1:
            return True

        logger.warning(f"Cloudflare still blocking {site} (round {round_num}/{max_rounds})")
        if not use_attach and board == "glassdoor":
            logger.error(
                "Glassdoor 'Humans only' cannot be cleared in Selenium Chrome. "
                "Stop and run: python modules/warm_indeed_profile.py --board glassdoor"
            )
        cleared = handle_cloudflare(sb, logger, site_name=site, jobs_hint=jobs_hint, board=board, content_ready_fn=content_fn, use_attach=use_attach, try_automation=not use_attach,)
        if cleared and content_fn():
            return True

        deadline = time.time() + 90
        while time.time() < deadline:
            if content_fn():
                persist_board_cookies(sb.driver, board, logger)
                return True
            if not is_cloudflare_challenge(sb, content_fn, board=board):
                persist_board_cookies(sb.driver, board, logger)
                return True
            time.sleep(2)

    if content_fn():
        return True
    logger.error(
        f"Could not reach {site} listings after {max_rounds} Cloudflare rounds. "
        f"Run: python modules/warm_indeed_profile.py --board {board}"
    )
    return False
