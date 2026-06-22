"""Botasaurus tasks registered once and imported lazily by the fetch layer."""

from typing import Dict

from botasaurus.browser import Driver, browser
from botasaurus.request import Request, request

from parser_app.runtime import MAX_RETRIES, REQUEST_TIMEOUT


@request(
    max_retry=MAX_RETRIES,
    output=None,
    close_on_crash=True,
    raise_exception=True,
    create_error_logs=False,
)
def request_html(request_client: Request, target_url: str):
    response = request_client.get(target_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return {
        "content_type": response.headers.get("content-type", ""),
        "text": response.text,
    }


@browser(
    headless=True,
    add_arguments=[
        "--headless=new",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-sync",
        "--blink-settings=imagesEnabled=false",
    ],
    window_size=[1280, 720],
    block_images_and_css=True,
    wait_for_complete_page_load=False,
    max_retry=1,
    output=None,
    close_on_crash=True,
    raise_exception=True,
    create_error_logs=False,
)
def browser_html(driver: Driver, payload: Dict[str, str]):
    target_url = str(payload.get("url") or "")
    navigation = str(payload.get("navigation") or "direct")
    if navigation == "direct":
        driver.get(target_url)
    else:
        driver.google_get(target_url)
    driver.sleep(2)
    for _ in range(4):
        try:
            driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            break
        driver.sleep(0.8)
    return driver.page_html


@browser(
    headless=False,
    profile="protected_sites_debug_visible",
    window_size=[1280, 720],
    add_arguments=["--window-position=40,40"],
    block_images_and_css=False,
    wait_for_complete_page_load=True,
    reuse_driver=False,
    output=None,
    close_on_crash=True,
    raise_exception=True,
    create_error_logs=False,
    max_retry=1,
)
def visible_browser_html(driver: Driver, target_url: str):
    driver.get(target_url)
    driver.sleep(8)
    for _ in range(3):
        try:
            driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            break
        driver.sleep(0.8)
    return driver.page_html
