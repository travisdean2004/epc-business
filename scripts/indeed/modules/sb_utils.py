#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Shared SeleniumBase launch options.

Indeed + Cloudflare:
- Standard Selenium Chrome is flagged (navigator.webdriver, automation flags).
- Clicks/PyAutoGUI cannot fix a bad fingerprint — Cloudflare loops forever.
- Best fix: warm a persistent Chrome profile in REAL Chrome, then reuse it.
- UC mode helps but may hang on some macOS setups (INDEED_USE_UC=1).
"""

import os
import re
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

NOT_AVAILABLE = "Not Available"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEED_PROFILE = PROJECT_ROOT / "artifacts" / "chrome_profile"
DEFAULT_INDEED_DEBUG_PORT = 9222
DEFAULT_BOARD_DEBUG_PORTS = {
    "indeed": 9222,
    "glassdoor": 9223,
    "dice": 9224,
}
DOCKER_CHROMIUM_ARGS = "--no-sandbox,--disable-dev-shm-usage,--disable-gpu"


def running_in_docker():
    """True when executing inside a container (Docker/Kubernetes)."""
    if Path("/.dockerenv").exists():
        return True
    return os.environ.get("RUNNING_IN_DOCKER", "").strip().lower() in ("1", "true", "yes")


def _merge_chromium_arg(opts, extra):
    """Append comma-separated Chromium flags to SeleniumBase chromium_arg."""
    if not extra:
        return
    current = opts.get("chromium_arg") or ""
    parts = [p.strip() for p in re.split(r",|\s+", current) if p.strip()]
    for flag in extra.split(","):
        flag = flag.strip()
        if flag and flag not in parts:
            parts.append(flag)
    opts["chromium_arg"] = ",".join(parts)

STEALTH_CDP_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def use_indeed_uc_mode():
    """Return True only when user explicitly opts into UC mode."""
    return os.environ.get("INDEED_USE_UC", "0").lower() in ("1", "true", "yes")


def use_indeed_profile():
    """Use persistent Chrome profile (recommended for Indeed Cloudflare)."""
    if use_indeed_attach():
        return False
    if os.environ.get("INDEED_NO_PROFILE", "0").lower() in ("1", "true", "yes"):
        return False
    return True


def indeed_debug_port():
    """Remote debugging port for attach mode (default 9222)."""
    raw = os.environ.get("INDEED_DEBUG_PORT", str(DEFAULT_INDEED_DEBUG_PORT)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_INDEED_DEBUG_PORT


def board_debug_port(board="indeed"):
    """Per-board debug port so Glassdoor/Dice do not attach to Indeed's Chrome."""
    board = (board or "indeed").lower()
    env_key = f"{board.upper()}_DEBUG_PORT"
    if os.environ.get(env_key):
        try:
            return int(os.environ.get(env_key).strip())
        except ValueError:
            pass
    if board == "indeed":
        return indeed_debug_port()
    return DEFAULT_BOARD_DEBUG_PORTS.get(board, DEFAULT_INDEED_DEBUG_PORT)


def _debug_json(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None


def chrome_debug_targets(port=None):
    port = port if port is not None else indeed_debug_port()
    data = _debug_json(f"http://127.0.0.1:{port}/json/list")
    return data if isinstance(data, list) else []


def chrome_debug_page_targets(port=None):
    return [t for t in chrome_debug_targets(port) if t.get("type") == "page"]


def is_chrome_debug_port_open(port=None):
    """Return True if something responds on the Chrome debug port."""
    port = port if port is not None else indeed_debug_port()
    data = _debug_json(f"http://127.0.0.1:{port}/json/version")
    return isinstance(data, dict) and bool(data.get("Browser"))


def is_chrome_attachable(port=None):
    """True when debug port is open AND at least one page tab exists for Selenium attach."""
    port = port if port is not None else indeed_debug_port()
    if not is_chrome_debug_port_open(port):
        return False
    return len(chrome_debug_page_targets(port)) > 0


def ensure_chrome_debug_page(port=None, url="about:blank", logger=None):
    """Open a tab via CDP when Chrome is listening but has no attachable pages."""
    port = port if port is not None else indeed_debug_port()
    if chrome_debug_page_targets(port):
        return True
    target_url = url if url.startswith(("http://", "https://", "about:")) else f"https://{url}"
    open_url = f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(target_url, safe='')}"
    try:
        data = _debug_json(open_url, timeout=8)
        if isinstance(data, dict) and data.get("id"):
            if logger:
                logger.info(f"Opened debug tab on port {port}")
            time.sleep(1.5)
            return bool(chrome_debug_page_targets(port))
    except Exception as exc:
        if logger:
            logger.debug(f"Could not open debug tab: {exc}")
    return bool(chrome_debug_page_targets(port))


def use_board_attach(board="indeed"):
    """Attach to real Chrome when enabled and the board's debug port is attachable."""
    env = os.environ.get("INDEED_ATTACH", os.environ.get("SCRAPER_ATTACH", "")).strip().lower()
    if env in ("0", "false", "no"):
        return False
    if env in ("1", "true", "yes"):
        return True
    port = board_debug_port(board)
    return is_chrome_attachable(port)


def use_indeed_attach():
    """Attach to an already-open Chrome instead of launching Selenium Chrome.

    INDEED_ATTACH=1  -> force attach
    INDEED_ATTACH=0  -> never attach
    unset            -> auto-attach when Indeed debug port has attachable pages
    """
    return use_board_attach("indeed")


def indeed_profile_dir():
    """Directory for Indeed-dedicated Chrome profile."""
    custom = os.environ.get("INDEED_CHROME_PROFILE")
    if custom:
        return Path(custom).expanduser().resolve()
    return DEFAULT_INDEED_PROFILE


def apply_cdp_stealth(driver, logger=None):
    """Reduce obvious automation signals (helps slightly; profile warmup is the real fix)."""
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_CDP_SCRIPT})
        if logger:
            logger.debug("Applied CDP stealth patches")
    except Exception as e:
        if logger:
            logger.debug(f"CDP stealth skipped: {e}")


def build_sb_options(headless=False, incognito=False, proxy=None, use_uc=False, use_profile=False, profile_dir=None,):
    """Build SeleniumBase kwargs. Default is standard Chrome (use_uc=False)."""
    opts = {
        "headed": not headless,
        "incognito": incognito,
        "locale_code": "en",
    }

    if use_uc:
        opts.update(
            uc=True,
            uc_cdp_events=False,
            uc_subprocess=True,
            disable_csp=True,
        )
    else:
        opts["chromium_arg"] = "--disable-blink-features=AutomationControlled"

    if use_profile and not use_uc:
        pd = Path(profile_dir) if profile_dir else indeed_profile_dir()
        pd.mkdir(parents=True, exist_ok=True)
        opts["user_data_dir"] = str(pd)
        opts["incognito"] = False

    if headless:
        opts["headless"] = True
        opts["xvfb"] = True

    if proxy:
        proxy_str = proxy.get("server", "")
        if proxy.get("username"):
            auth = f"{proxy['username']}:{proxy.get('password', '')}"
            server = proxy_str.replace("http://", "").replace("https://", "")
            proxy_str = f"{auth}@{server}"
        opts["proxy"] = proxy_str

    if running_in_docker():
        _merge_chromium_arg(opts, DOCKER_CHROMIUM_ARGS)

    return opts


def open_url(sb, url, logger=None):
    """Navigate with driver.get(); sb.open() can leave Chrome on data:, on some setups."""
    url = str(url).strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid navigation URL: {url!r}")

    if logger:
        logger.info(f"Navigating to: {url}")

    sb.driver.get(url)
    time.sleep(0.5)

    current = sb.driver.current_url
    if current.startswith("data:") or current in ("about:blank", ""):
        if logger:
            logger.warning(f"Navigation stuck on {current!r}; retrying...")
        sb.driver.get(url)
        time.sleep(1.5)
        current = sb.driver.current_url

    if logger:
        logger.info(f"Current URL: {current}")

    if current.startswith("data:"):
        raise RuntimeError(f"Navigation failed — browser stayed on {current!r}")

    return current


def wait_for_chrome_debug_port(port=None, timeout=120, logger=None, landing_url=None):
    """Wait until Chrome remote debugging has at least one attachable page."""
    port = port if port is not None else indeed_debug_port()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_chrome_attachable(port):
            return port
        if is_chrome_debug_port_open(port) and landing_url:
            ensure_chrome_debug_page(port, landing_url, logger)
            if is_chrome_attachable(port):
                return port
        if logger:
            logger.info(f"Waiting for Chrome on debug port {port}...")
        time.sleep(2)
    raise RuntimeError(
        f"Chrome not ready on port {port}. "
        f"Run: python modules/warm_indeed_profile.py --board ...  (keep Chrome open)"
    )


def attach_chrome_driver(port=None, landing_url=None, logger=None):
    """Connect Selenium to an existing Chrome started with --remote-debugging-port."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import SessionNotCreatedException

    port = port if port is not None else indeed_debug_port()
    if not is_chrome_attachable(port):
        if is_chrome_debug_port_open(port):
            ensure_chrome_debug_page(port, landing_url or "about:blank", logger)
        if not is_chrome_attachable(port):
            wait_for_chrome_debug_port(port, timeout=30, logger=logger, landing_url=landing_url)

    address = f"127.0.0.1:{port}"
    options = Options()
    options.add_experimental_option("debuggerAddress", address)

    try:
        return webdriver.Chrome(options=options)
    except SessionNotCreatedException as exc:
        msg = str(exc).lower()
        if "unable to discover open pages" in msg or "cannot connect to chrome" in msg:
            if logger:
                logger.warning("Attach failed — opening a new tab and retrying once...")
            ensure_chrome_debug_page(port, landing_url or "about:blank", logger)
            time.sleep(2)
            return webdriver.Chrome(options=options)
        raise


def indeed_cookie_pickle_path(cookie_file=None):
    """Path to saved Indeed session pickle (project root by default)."""
    from modules.cookies_age import cookie_artifact

    name = cookie_file or cookie_artifact
    path = Path(name)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def inject_pickle_cookies(driver, cookie_path=None, landing_url="https://www.indeed.com"):
    """Seed an open browser from indeed_cookies.pkl via WebDriver add_cookie."""
    import pickle
    from selenium.common.exceptions import WebDriverException

    path = indeed_cookie_pickle_path(cookie_path)
    if not path.exists():
        return 0, 0

    try:
        with open(path, "rb") as f:
            cookies = pickle.load(f)
    except (OSError, pickle.UnpicklingError):
        return 0, 0

    driver.get(landing_url)
    time.sleep(1)

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

    return added, len(cookies)


def warm_inject_saved_cookies(port=None, cookie_path=None, jobs_url="https://www.indeed.com/jobs"):
    """Attach to warm Chrome and load pickle cookies into the profile (Chrome stays open)."""
    port = port if port is not None else indeed_debug_port()
    path = indeed_cookie_pickle_path(cookie_path)
    if not path.exists():
        print(f"No saved cookies at {path} — log in manually in Chrome if needed")
        return False

    print(f"Injecting saved cookies from {path.name} into Chrome profile...")
    driver = attach_chrome_driver(port)
    try:
        added, total = inject_pickle_cookies(driver, path)
        driver.get(jobs_url)
        time.sleep(1)
        print(f"Injected {added}/{total} cookies into profile")
        if added < total:
            print("Some cookies were skipped (expired domain or Cloudflare-only tokens)")
        print("If Cloudflare appears, complete it once in Chrome — clearance stays in the profile")
        return added > 0
    finally:
        # Do not driver.quit() — that can close the user's real Chrome window.
        pass


def find_chrome_pid_for_debug_port(port=None, profile_dir=None):
    """Return PID of the Chrome instance listening on the scraper debug port."""
    import subprocess

    port = port if port is not None else indeed_debug_port()
    profile_dir = profile_dir or indeed_profile_dir()
    profile_arg = str(profile_dir)

    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    except (FileNotFoundError, OSError, ValueError):
        pass

    patterns = (
        f"[c]hrome.*remote-debugging-port={port}.*user-data-dir={profile_arg}",
        f"[c]hrome.*user-data-dir={profile_arg}.*remote-debugging-port={port}",
        f"[c]hrome.*remote-debugging-port={port}",
    )
    for pattern in patterns:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
        except (FileNotFoundError, OSError, ValueError):
            continue
    return None


def kill_process_tree(pid, logger=None):
    """Terminate one process (and children on macOS). Does not quit all Chrome."""
    import signal
    import subprocess

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False

    if pid <= 1:
        return False

    try:
        import platform as _platform

        if _platform.system() == "Darwin":
            subprocess.run(["pkill", "-P", str(pid)], check=False, capture_output=True)
    except (FileNotFoundError, OSError):
        pass

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError as exc:
            if logger:
                logger.warning(f"Could not signal Chrome PID {pid}: {exc}")
            return False
        if sig == signal.SIGTERM:
            time.sleep(1.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
    return True


def kill_chrome_session(pid=None, port=None, driver=None, logger=None):
    """Close only the scraper Chrome (debug port / tracked PID), not every Chrome window."""
    port = port if port is not None else indeed_debug_port()
    target_pid = pid
    if target_pid is not None:
        try:
            target_pid = int(target_pid)
        except (TypeError, ValueError):
            target_pid = None
    if not target_pid:
        target_pid = find_chrome_pid_for_debug_port(port)

    if driver:
        try:
            driver.quit()
        except Exception as exc:
            if logger:
                logger.debug(f"driver.quit() during attach teardown: {exc}")

    if target_pid and kill_process_tree(target_pid, logger=logger):
        if logger:
            logger.info(f"Stopped scraper Chrome (PID {target_pid}, port {port})")
        return True

    if logger:
        logger.warning(f"No scraper Chrome PID found for debug port {port}")
    return False


def close_attach_session(driver=None, board="indeed", logger=None):
    """Detach from or quit the board's warmed Chrome (orchestrator sets INDEED_QUIT_CHROME)."""
    quit_chrome = os.environ.get("INDEED_QUIT_CHROME", "").strip().lower() in ("1", "true", "yes")
    if quit_chrome:
        pid_env = os.environ.get("INDEED_CHROME_PID", "").strip()
        pid = int(pid_env) if pid_env.isdigit() else None
        kill_chrome_session(pid=pid, port=board_debug_port(board), driver=driver, logger=logger,)
        if logger:
            logger.info("Closed attached Chrome session")
        return True
    if logger:
        logger.info("Detached from Chrome (browser left open)")
    return False


class AttachedBrowserSession:
    """Minimal SeleniumBase-compatible wrapper for attach mode (no setUp() required)."""

    def __init__(self, driver):
        self.driver = driver

    def get_current_url(self):
        return self.driver.current_url

    def get_page_source(self):
        return self.driver.page_source

    def get_title(self):
        return self.driver.title

    def refresh(self):
        self.driver.refresh()

    def execute_script(self, script, *args, **kwargs):
        return self.driver.execute_script(script, *args, **kwargs)

    def find_elements(self, selector, by="css selector", limit=0):
        from selenium.webdriver.common.by import By

        by_map = {"css selector": By.CSS_SELECTOR, "xpath": By.XPATH, "id": By.ID, "name": By.NAME, "link text": By.LINK_TEXT,}
        selenium_by = by_map.get(by, by)
        elements = self.driver.find_elements(by=selenium_by, value=selector)
        if limit and limit > 0:
            return elements[:limit]
        return elements

    def find_element(self, selector, by="css selector", timeout=None, visible=True):
        from selenium.webdriver.common.by import By
        from seleniumbase.fixtures import page_actions

        by_map = {"css selector": By.CSS_SELECTOR, "xpath": By.XPATH, "id": By.ID, "name": By.NAME, "link text": By.LINK_TEXT,}
        selenium_by = by_map.get(by, by)
        wait = page_actions.wait_for_element_visible if visible else page_actions.wait_for_element_present
        return wait(self.driver, selector, selenium_by, timeout or 10)

    def wait_for_element(self, selector, by="css selector", timeout=None, visible=False):
        """Wait for element in DOM (default: present, not visible — safer for attach/split views)."""
        return self.find_element(selector, by=by, timeout=timeout, visible=visible)

    def wait_for_element_present(self, selector, by="css selector", timeout=None):
        return self.find_element(selector, by=by, timeout=timeout, visible=False)

    def switch_to_frame(self, frame, timeout=None, invisible=False):
        self.driver.switch_to.frame(frame)

    def switch_to_default_content(self):
        self.driver.switch_to.default_content()

    def save_screenshot(self, name, folder=None, selector=None, by="css selector"):
        target = Path(name)
        if folder and not target.is_absolute():
            target = Path(folder) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        self.driver.save_screenshot(str(target))

    def maximize_window(self):
        self.driver.maximize_window()

    def set_window_size(self, width, height):
        self.driver.set_window_size(width, height)


def create_attached_sb(port=None, logger=None, landing_url=None):
    """Return an SB-compatible session wired to an existing Chrome window."""
    port = port if port is not None else indeed_debug_port()
    if logger:
        logger.info(f"Attaching to Chrome on debug port {port} (your real browser session)")
    driver = attach_chrome_driver(port, landing_url=landing_url, logger=logger)
    return AttachedBrowserSession(driver)


def board_profile_dir(board="indeed"):
    """Persistent Chrome profile directory per job board."""
    if board == "indeed":
        return indeed_profile_dir()
    env = os.environ.get(f"{board.upper()}_CHROME_PROFILE") or os.environ.get("SCRAPER_CHROME_PROFILE")
    if env:
        return Path(env).expanduser().resolve()
    return PROJECT_ROOT / "artifacts" / f"chrome_profile_{board}"


def use_scraper_uc():
    default = "1" if running_in_docker() else "0"
    raw = os.environ.get("SCRAPER_USE_UC", os.environ.get("INDEED_USE_UC", default))
    return raw.lower() in ("1", "true", "yes")


def use_scraper_profile(board="indeed"):
    if running_in_docker():
        return False
    if use_board_attach(board) or use_scraper_uc():
        return False
    no_profile = os.environ.get("SCRAPER_NO_PROFILE", os.environ.get("INDEED_NO_PROFILE", "0"))
    if no_profile.lower() in ("1", "true", "yes"):
        return False
    return True


def _launch_profile_browser(board, *, headless, incognito, proxy, window_size, logger,):
    """Launch SeleniumBase with a persistent board profile."""
    from seleniumbase import SB

    use_uc = use_scraper_uc()
    use_profile = use_scraper_profile(board) and not use_uc and not incognito
    if logger:
        logger.info("Starting browser...")
        logger.info("(First launch may take 30-60s while Chrome/driver initializes)")
        if running_in_docker():
            logger.info("Docker mode — UC browser, no persistent profile")
        if use_profile:
            logger.info(f"Using Chrome profile: {board_profile_dir(board)}")
            logger.info(
                f"If Cloudflare loops, run: python modules/warm_indeed_profile.py --board {board}"
            )
        elif not use_uc:
            logger.info("Standard Selenium Chrome — Cloudflare may loop")
            logger.info(
                f"Recommended: python modules/warm_indeed_profile.py --board {board}  (keep Chrome open)"
            )

    sb_options = build_sb_options(headless=headless, incognito=incognito, proxy=proxy, use_uc=use_uc, use_profile=use_profile, profile_dir=board_profile_dir(board) if use_profile else None,)
    context = SB(**sb_options)
    sb = context.__enter__()
    driver = sb.driver
    apply_cdp_stealth(driver, logger)

    if window_size == "maximized":
        sb.maximize_window()
    elif "x" in str(window_size):
        width, height = map(int, window_size.split("x"))
        sb.set_window_size(width, height)

    return {"sb": sb, "driver": driver, "context": context, "use_attach": False, "use_uc": use_uc,}


def start_board_browser(board, *, headless=False, incognito=False, proxy=None, window_size="maximized", logger=None, landing_url=None,):
    """Launch Selenium Chrome, or attach to real Chrome when debug port is ready."""
    board = (board or "indeed").lower()
    port = board_debug_port(board)
    use_attach = use_board_attach(board) and not incognito and not headless

    if use_attach:
        if logger:
            logger.info("Attach mode — reusing your open Chrome (not launching Selenium Chrome)")
            logger.info(f"If Chrome is not open yet: python modules/warm_indeed_profile.py --board {board}")
            logger.info(f"Debug port for {board}: {port}")
        try:
            wait_for_chrome_debug_port(port, logger=logger, landing_url=landing_url)
            sb = create_attached_sb(port, logger=logger, landing_url=landing_url)
            if window_size == "maximized":
                try:
                    sb.maximize_window()
                except Exception:
                    pass
            return {
                "sb": sb,
                "driver": sb.driver,
                "context": None,
                "use_attach": True,
                "use_uc": False,
            }
        except Exception as exc:
            if logger:
                logger.warning(f"Attach to port {port} failed: {exc}")
                logger.warning("Falling back to launching Chrome with saved profile...")
            if os.environ.get("INDEED_ATTACH", "").lower() in ("1", "true", "yes"):
                raise

    return _launch_profile_browser(board, headless=headless, incognito=incognito, proxy=proxy, window_size=window_size, logger=logger,)


def finalize_job_listing(job, *, board_label, id_field="job_id", url_field="url", title_field="title", build_url=None,):
    """Fill missing title/URL from job id; keep any listing the board returned."""
    job_id = job.get(id_field)
    url = job.get(url_field)

    if (not job_id or job_id == NOT_AVAILABLE) and url and url != NOT_AVAILABLE:
        for pattern in (
            r"job-detail/([a-f0-9-]+)",
            r"job-listing/[^/?#]*-JV_[^/_]+_(\d+)",
            r"[?&]jobListingId=(\d+)",
        ):
            match = re.search(pattern, url, re.I)
            if match:
                job[id_field] = match.group(1)
                job_id = job[id_field]
                break

    if build_url and job_id and job_id != NOT_AVAILABLE:
        if not url or url == NOT_AVAILABLE:
            job[url_field] = build_url(job_id)

    title = (job.get(title_field) or "").strip()
    if not title or title == NOT_AVAILABLE:
        if job_id and job_id != NOT_AVAILABLE:
            job[title_field] = f"{board_label} job {job_id}"
        elif url and url != NOT_AVAILABLE:
            job[title_field] = f"{board_label} listing"
        else:
            job[title_field] = NOT_AVAILABLE
    return job


def job_listing_is_usable(job, id_fields=("job_id", "job_key"), url_field="url", title_field="title"):
    """Accept any listing with an id, URL, or parsed title (no query match required)."""
    for field in id_fields:
        value = job.get(field)
        if value and value != NOT_AVAILABLE:
            return True
    for field in (url_field, title_field):
        value = job.get(field)
        if value and value != NOT_AVAILABLE:
            return True
    return False


def is_duplicate_listing(job, all_jobs, id_fields=("job_id", "job_key"), url_field="url"):
    """Dedupe by stable id or URL."""
    for id_field in id_fields:
        job_id = job.get(id_field)
        if job_id and job_id != NOT_AVAILABLE:
            return any(
                existing.get(id_field) == job_id
                for existing in all_jobs
                if existing.get(id_field) not in (None, NOT_AVAILABLE)
            )
    url = job.get(url_field)
    if url and url != NOT_AVAILABLE:
        return any(
            existing.get(url_field) == url
            for existing in all_jobs
            if existing.get(url_field) not in (None, NOT_AVAILABLE)
        )
    return False
