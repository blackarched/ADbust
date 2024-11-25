
import time
import random
import logging
import configparser
import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    WebDriverException,
)


# Load and validate configuration
def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists("config.ini"):
        raise FileNotFoundError("config.ini not found. Please create it before running the script.")

    config.read("config.ini")
    settings = config["SETTINGS"]
    advanced = config["ADVANCED"]

    # Validate and parse settings
    try:
        url = settings.get("url", "").strip()
        ad_video_selector = settings.get("ad_video_selector", "").strip()
        task_selector = settings.get("completion_task_selector", "").strip()
        cookie_selector = settings.get("cookie_consent_selector", "").strip()
        ad_duration = max(1, int(settings.get("ad_duration", 30)))
        headless_mode = settings.getboolean("headless_mode", True)
        task_retry_count = max(1, int(settings.get("task_retry_count", 3)))
        log_level = settings.get("log_level", "INFO").upper()
        log_file = settings.get("log_file", "automation_log.log").strip()

        # Parse and validate delay range
        delay_range = settings.get("delay_between_tasks", "2-5")
        delay_min, delay_max = map(int, delay_range.split("-"))
        delay_min, delay_max = min(delay_min, delay_max), max(delay_min, delay_max)

        # Advanced settings
        chromedriver_path = advanced.get("chromedriver_path", "chromedriver").strip()
        window_size = advanced.get("window_size", "1920x1080").strip()

    except Exception as e:
        raise ValueError(f"Error in config.ini: {e}")

    return {
        "url": url,
        "ad_video_selector": ad_video_selector,
        "task_selector": task_selector,
        "cookie_selector": cookie_selector,
        "ad_duration": ad_duration,
        "headless_mode": headless_mode,
        "task_retry_count": task_retry_count,
        "delay_min": delay_min,
        "delay_max": delay_max,
        "log_level": log_level,
        "log_file": log_file,
        "chromedriver_path": chromedriver_path,
        "window_size": window_size,
    }


# Set up logging
def setup_logging(log_file, log_level):
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, mode="w")],
    )


# Initialize Selenium WebDriver
def setup_driver(headless_mode, chromedriver_path, window_size):
    options = webdriver.ChromeOptions()
    if headless_mode:
        options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={window_size}")

    return webdriver.Chrome(executable_path=chromedriver_path, options=options)


# Wait for an element to appear
def wait_for_element(driver, by, value, timeout=10):
    try:
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
    except TimeoutException:
        logging.error(f"Timeout while waiting for element: {value}")
        return None


# Handle cookie consent pop-up
def handle_cookie_consent(driver, cookie_selector):
    try:
        cookie_button = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, cookie_selector)))
        cookie_button.click()
        logging.info("Cookie consent handled.")
    except TimeoutException:
        logging.info("No cookie consent pop-up found.")
    except Exception as e:
        logging.error(f"Error handling cookie consent: {e}")


# Handle task automation
def handle_tasks(driver, task_selector, retries, delay_min, delay_max):
    tasks = driver.find_elements(By.CSS_SELECTOR, task_selector)
    if not tasks:
        logging.warning("No tasks found using selector: %s", task_selector)
        return

    logging.info("Found %d tasks. Beginning task automation.", len(tasks))

    for index, task in enumerate(tasks):
        success = False
        for attempt in range(retries):
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", task)
                task.click()
                logging.info("Task %d completed successfully.", index + 1)
                success = True
                break
            except (ElementNotInteractableException, StaleElementReferenceException) as e:
                logging.warning("Retry %d for task %d due to error: %s", attempt + 1, index + 1, str(e))
                time.sleep(2 ** (attempt + 1))  # Exponential backoff

        if not success:
            logging.error("Task %d failed after %d retries.", index + 1, retries)

        time.sleep(random.uniform(delay_min, delay_max))  # Random delay between tasks


# Parallel task handling
def execute_task(driver, task):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", task)
        task.click()
        logging.info("Task executed successfully.")
    except Exception as e:
        logging.error(f"Error executing task: {e}")


def handle_tasks_parallel(driver, task_selector, max_threads=4):
    tasks = driver.find_elements(By.CSS_SELECTOR, task_selector)
    if not tasks:
        logging.warning("No tasks found using selector: %s", task_selector)
        return

    logging.info("Executing %d tasks in parallel with %d threads.", len(tasks), max_threads)
    with ThreadPoolExecutor(max_threads) as executor:
        executor.map(lambda task: execute_task(driver, task), tasks)


# Main function
def main():
    try:
        # Load configuration
        config = load_config()
        setup_logging(config["log_file"], config["log_level"])

        # Parse command-line arguments
        parser = argparse.ArgumentParser(description="Selenium Automation Script")
        parser.add_argument("--url", help="Override the URL from config.ini")
        parser.add_argument("--parallel", action="store_true", help="Enable parallel task handling")
        args = parser.parse_args()
        config["url"] = args.url or config["url"]

        if not config["url"]:
            logging.error("No URL provided. Please specify it in config.ini or use the --url argument.")
            return

        # Initialize WebDriver
        driver = setup_driver(config["headless_mode"], config["chromedriver_path"], config["window_size"])
        driver.get(config["url"])
        logging.info(f"Opened URL: {config['url']}")

        # Handle cookie consent
        handle_cookie_consent(driver, config["cookie_selector"])

        # Handle ad playback
        ad_video = wait_for_element(driver, By.CSS_SELECTOR, config["ad_video_selector"])
        if ad_video:
            ad_video.click()
            logging.info("Ad started. Waiting for playback to complete...")
            time.sleep(config["ad_duration"])

        # Handle tasks
        if args.parallel:
            handle_tasks_parallel(driver, config["task_selector"])
        else:
            handle_tasks(driver, config["task_selector"], config["task_retry_count"], config["delay_min"], config["delay_max"])

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
    finally:
        driver.quit()
        logging.info("Browser closed.")


if __name__ == "__main__":
    main()
