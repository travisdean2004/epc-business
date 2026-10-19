#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Cookie Setup Script - Manual login with automatic cookie capture (REFACTORED): """

import sys
import time
import pickle
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seleniumbase import SB
from selenium.common.exceptions import WebDriverException, TimeoutException
from modules.sb_utils import build_sb_options, open_url

# ___ configure logging:
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def normalize_indeed_cookies(raw_cookies):
    """Normalize Indeed cookies to use the correct domain."""
    indeed_cookies = []
    for cookie in raw_cookies:
        if "indeed" in cookie.get("domain", ""):
            cookie["domain"] = ".indeed.com"
            indeed_cookies.append(cookie)
    return indeed_cookies


def save_cookies_to_file(cookies, cookie_file):
    """ Save cookies to a pickle file:
        Args:   cookies (list):     <-- List of cookie dictionaries:
                cookie_file (str):  <-- Path to save the cookies:
        Returns: bool:              <-- True if successful, False otherwise: """
    
    cookie_path = Path(cookie_file)
    try:
        with open(cookie_path, 'wb') as f:
            pickle.dump(cookies, f)
        logger.info(f"SUCCESS! Cookies saved to: {cookie_path.absolute()}")
        logger.info(f"Saved {len(cookies)} cookies")
        return True
    except (IOError, OSError) as e:
        logger.error(f"Error saving cookies: {e}")
        return False


def get_cookies_from_driver(sb):
    """ Retrieve cookies from the Selenium driver:
        Args: sb:       <-- SeleniumBase driver instance:
        Returns: list:  <-- List of cookie dictionaries, or empty list on failure:"""
    
    try:
        cookies = sb.driver.get_cookies()
        logger.info(f"Retrieved {len(cookies)} cookies")
        return cookies
    except WebDriverException as e:
        logger.warning(f"Error getting cookies via driver.get_cookies(): {e}")
        logger.info("Trying alternative method using document.cookie...")
        
        try:
            cookie_string = sb.execute_script("return document.cookie")
            logger.info(f"Got cookie string: {cookie_string[:100]}...")
            
            cookies = []
            for cookie_pair in cookie_string.split('; '):
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name,
                        'value': value,
                        'domain': '.indeed.com',
                        'path': '/',
                    })
            
            logger.info(f"Parsed {len(cookies)} cookies from document.cookie")
            return cookies
        except WebDriverException as e2:
            logger.error(f"Alternative method failed: {e2}")
            return []


def wait_for_manual_login(sb):
    """ Wait for user to complete manual login:
        Args: sb:       <-- SeleniumBase driver instance:        
        Returns: bool:  <-- True if login successful, False otherwise:"""
    
    logger.info("=" * 70)
    logger.info("LOGIN IN THE BROWSER")
    logger.info("=" * 70)
    logger.info("Steps:")
    logger.info("1. Enter your email")
    logger.info("2. Choose 'Sign in with code' or 'Continue with Google'")
    logger.info("3. Complete authentication")
    logger.info("4. Click 'Not now' for passkey prompt")
    logger.info("5. Wait until redirected to Indeed homepage")
    logger.info("=" * 70)
    logger.info("DON'T close browser - let script do it")
    logger.info("=" * 70)
    
    input("\n>>> Press ENTER when login complete and you see Indeed homepage ... ")
    
    logger.info("Checking login status...")
    current_url = sb.get_current_url()
    logger.info(f"Current URL: {current_url}")
    
    if 'indeed.com' in current_url and 'auth' not in current_url:
        logger.info("Login successful!")
        return True
    else:
        logger.warning("WARNING: Still on auth page")
        logger.warning(f"URL: {current_url}")
        retry = input("Continue anyway? (y/n): ")
        return retry.lower() == 'y'


def wait_for_auto_login(sb, max_wait=300):
    """ Automatically detect when user completes login:
        Args: sb:       <-- SeleniumBase driver instance:
        max_wait (int): <-- Maximum seconds to wait for login:
        Returns: bool:  <-- True if login detected, False if timeout:"""
    
    logger.info("=" * 70)
    logger.info("LOGIN IN THE BROWSER")
    logger.info("=" * 70)
    logger.info("Complete login process:")
    logger.info("1. Enter email")
    logger.info("2. Complete authentication (code or Google)")
    logger.info("3. Click 'Not now' on passkey")
    logger.info("4. Wait until redirected to Indeed")
    logger.info("\nScript will detect automatically - no need to press Enter.")
    logger.info("=" * 70)
    logger.info("Waiting for login...")
    logger.info("(Auto-detection in progress)")
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            current_url = sb.get_current_url()
            if 'indeed.com' in current_url and 'auth' not in current_url:
                logger.info(f"Login detected! Page: {current_url}")
                return True
            
            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0 and elapsed > 0:
                logger.info(f"Still waiting... ({elapsed}s)")
            
            time.sleep(2)
        except WebDriverException as e:
            logger.debug(f"Exception during URL check: {e}")
            time.sleep(2)
    
    logger.error("Timeout waiting for login:")
    return False


def manual_login_and_save_cookies(cookie_file="indeed_cookies.pkl"):
    """ Login manually and save cookies (manual Enter press method):
        Args: cookie_file (str):    <-- Path to save cookies:
        Returns: bool:              <-- True if successful, False otherwise: """
    
    logger.info("\n" + "=" * 70)
    logger.info("INDEED MANUAL LOGIN - COOKIE SETUP")
    logger.info("=" * 70)
    logger.info("Browser will open to Indeed login page.")
    logger.info("Login manually, then press Enter when complete.")
    logger.info("=" * 70)
    
    cookie_path = Path(__file__).parent.parent / cookie_file
    logger.info("Launching Chrome for login (standard mode)...")
    logger.info("(First launch may take 30-60s while Chrome/driver initializes)")
    sb_opts = build_sb_options(use_uc=False)
    with SB(**sb_opts) as sb:
        logger.info("Opening Indeed login page...")
        open_url(sb, "https://secure.indeed.com/auth", logger)
        time.sleep(3)
        
        if not wait_for_manual_login(sb):
            logger.error("Setup cancelled")
            return False
        
        logger.info("Saving cookies...")
        cookies = get_cookies_from_driver(sb)
        
        if not cookies:
            logger.error("No cookies to save")
            return False
        
        # ___ normalize Indeed cookies:
        normalized_cookies = normalize_indeed_cookies(cookies)
        if normalized_cookies:
            logger.info(f"Found {len(normalized_cookies)} Indeed cookies")
        else:
            logger.warning("No Indeed cookies found, saving all cookies")
            normalized_cookies = cookies
        
        if not save_cookies_to_file(normalized_cookies, str(cookie_path)):
            return False
        
        logger.info("Cookies will last 7-30 days")
        logger.info("You can now run scraper without logging in!")
        logger.info("=" * 70)
        logger.info("Browser will close in 2 seconds...")
        time.sleep(2)
    return True


def auto_detect_login_and_save_cookies(cookie_file="indeed_cookies.pkl"):
    """ Login manually with automatic detection (recommended method):
        Args: cookie_file (str): <-- Path to save cookies:
        Returns: bool:           <-- True if successful, False otherwise: """
    
    logger.info("\n" + "=" * 70)
    logger.info("INDEED AUTOMATIC LOGIN DETECTION")
    logger.info("=" * 70)
    logger.info("Browser will open. Login manually.")
    logger.info("Script will automatically detect when you're logged in.")
    logger.info("=" * 70)
    
    cookie_path = Path(__file__).parent.parent / cookie_file
    logger.info("Launching Chrome for login (standard mode)...")
    logger.info("(First launch may take 30-60s while Chrome/driver initializes)")
    sb_opts = build_sb_options(use_uc=False)
    with SB(**sb_opts) as sb:
        logger.info("Opening Indeed login page...")
        open_url(sb, "https://secure.indeed.com/auth", logger)
        time.sleep(3)
        
        if not wait_for_auto_login(sb):
            return False
        
        logger.info("Saving cookies ...")
        time.sleep(2)
        
        cookies = get_cookies_from_driver(sb)
        if not cookies:
            logger.error("No cookies retrieved")
            return False
        
        # ___ normalize Indeed cookies:
        normalized_cookies = normalize_indeed_cookies(cookies)
        if normalized_cookies:
            logger.info(f"Found {len(normalized_cookies)} Indeed cookies")
        else:
            logger.warning("No Indeed cookies found, saving all cookies")
            normalized_cookies = cookies
        
        if not save_cookies_to_file(normalized_cookies, str(cookie_path)):
            return False
        
        logger.info("=" * 70)
        time.sleep(2)
    
    return True


def save_cookies_from_warm_chrome(port=None, cookie_file="indeed_cookies.pkl", jobs_url="https://www.indeed.com/jobs"):
    """Export cookies from real warm Chrome (debug attach) to indeed_cookies.pkl.

    Use this after logging in via maintance/run_*_attach.sh — avoids Selenium auth + Cloudflare loops.
    """
    from modules.sb_utils import attach_chrome_driver, indeed_debug_port, is_chrome_debug_port_open

    port = port if port is not None else indeed_debug_port()
    cookie_path = Path(__file__).parent.parent / cookie_file

    if not is_chrome_debug_port_open(port):
        logger.error(f"Chrome not open on debug port {port}")
        logger.info("Run attach first and keep Chrome open, or use: maintance/run_indeed_attach.sh")
        return False

    logger.info(f"Reading Indeed cookies from warm Chrome on port {port}...")
    driver = attach_chrome_driver(port, landing_url=jobs_url)
    try:
        try:
            if "indeed.com" not in (driver.current_url or ""):
                driver.get(jobs_url)
                time.sleep(1)
        except WebDriverException:
            driver.get(jobs_url)
            time.sleep(1)

        cookies = driver.get_cookies()
        if not cookies:
            logger.error("No cookies found — log in to Indeed in the warm Chrome window first")
            return False

        normalized = normalize_indeed_cookies(cookies)
        if not normalized:
            logger.warning("No Indeed-domain cookies — saving all cookies from browser")
            normalized = cookies

        if not save_cookies_to_file(normalized, str(cookie_path)):
            return False

        logger.info("Cookies exported from warm Chrome (includes Cloudflare clearance when present)")
        return True
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


def main():
    """ Main entry point for the script: """
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--from-warm":
            from modules.sb_utils import indeed_debug_port

            port = indeed_debug_port()
            if len(sys.argv) > 2:
                try:
                    port = int(sys.argv[2])
                except ValueError:
                    logger.error(f"Invalid port: {sys.argv[2]!r}")
                    sys.exit(1)
            success = save_cookies_from_warm_chrome(port=port)
        elif len(sys.argv) > 1 and sys.argv[1] == "--auto":
            logger.warning(
                "Note: --auto uses Selenium on secure.indeed.com/auth and often hits Cloudflare."
            )
            logger.warning(
                "Recommended: bash maintance/run_indeed_attach.sh — log in in real Chrome, "
                "then save cookies at end of run (or: python3 modules/get_cookies.py --from-warm)"
            )
            logger.info("Using AUTOMATIC detection method ...")
            logger.info("=" * 70)
            success = auto_detect_login_and_save_cookies()
        else:
            logger.info("Using MANUAL method (press Enter when ready) ...")
            logger.info("=" * 70)
            success = manual_login_and_save_cookies()
        
        if success:
            logger.info("\n" + "=" * 70)
            logger.info("SETUP COMPLETE!")
            logger.info("=" * 70)
            logger.info("Cookies saved successfully.")
            logger.info("\nRe-run Scraper:")
            logger.info('  python3 main.py --auto --query "Engineer" --max 25')
            logger.info("=" * 70)
        else:
            logger.error("\nSetup failed.")
            logger.info("\nTry alternative method:")
            if "--from-warm" in sys.argv:
                logger.info("  bash maintance/run_indeed_attach.sh  # log in in real Chrome first")
                logger.info("  python3 modules/get_cookies.py --from-warm 9222  # while Chrome still open")
            elif "--auto" in sys.argv:
                logger.info("  bash maintance/run_indeed_attach.sh  # recommended")
                logger.info("  python3 modules/get_cookies.py --from-warm 9222")
            else:
                logger.info("  python3 modules/get_cookies.py --from-warm 9222  # after attach login")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
