import json
import os
import re
import time
import traceback
from pathlib import Path
from typing import Optional

from selenium import webdriver
from urllib.parse import urlparse
import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.expected_conditions import presence_of_element_located
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager

logger = logging.getLogger("BibQuery")

# Disable annoying webdriver manager outputs
os.environ["WDM_PROGRESS_BAR"] = "0"


class BibQueryException(Exception):
    pass


class CaptchaEncounteredException(Exception):
    pass


class BibQuery:
    def __init__(self):
        self.__browser: Optional[WebDriver] = None
        self.__res_path = Path(__file__).parent / "res"
        self.__cache_path = Path("~").expanduser() / ".cache" / "bibquery"
        self.__cookie_path = self.__cache_path / "google_cookies.json"
        with (self.__res_path / "urlSpecificAdjusterList.json").open() as f:
            self.__url_specific_adjusters = json.load(f)

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def initialize(self):
        options = Options()
        options.headless = True
        self.__cache_path.mkdir(exist_ok=True, parents=True)
        self.__browser = webdriver.Firefox(executable_path=GeckoDriverManager(
            path=str(self.__cache_path)).install(), options=options, log_path=os.devnull)
        self.__browser.install_addon(self.__res_path / "bibitnow_patched.xpi", temporary=True)
        if self.__cookie_path.exists():
            with self.__cookie_path.open() as f:
                cookies = json.load(f)
            self.__browser.get("https://scholar.google.com/")
            self.__browser.delete_all_cookies()
            for cookie in cookies:
                self.__browser.add_cookie(cookie)

    def close(self):
        self.__browser.close()

    def __wait_and_get(self, driver: WebDriver, by: str, value: Optional[str] = None, timeout: float = 60.0):
        WebDriverWait(driver, timeout).until(presence_of_element_located((by, value)))
        return driver.find_element(by, value)

    def query(self, url: str) -> str:
        """
        Tries to load the BibTeX of the paper behind the URL first using the query_bibitnow method and if that fails,
        falling back to query_google_scholar.
        :param url: URL to get the BibTeX for.
        :return: A string containing the BibTeX for paper in the given URL.
        """
        try:
            return self.query_bibitnow(url)
        except:
            logger.debug(f"Failed to obtain BibTeX using BibItNow with the following "
                         f"exception:\n{traceback.format_exc()}")
            try:
                logger.debug(f"Trying with Google Scholar...")
                return self.query_google_scholar(url)
            except:
                logger.debug(f"Failed to obtain BibTeX using Google Scholar with the following "
                             f"exception:\n{traceback.format_exc()}")
                raise BibQueryException(f"Failed to load BibTeX for URL \"{url}\"")

    def query_bibitnow(self, url: str) -> str:
        """
        Tries to load the BibTeX of the paper behind the URL using the BibItNow! Firefox plugin
        (https://github.com/Langenscheiss/bibitnow)
        :param url: URL to get the BibTeX for.
        :return: A string containing the BibTeX for paper in the given URL.
        """
        if self.__browser is None:
            raise ValueError("BibQuery has not been initialized or was already closed.")

        url_parsed = urlparse(url)
        domain = url_parsed.netloc.lower()
        *rest, top = domain.split(".")
        rest_joined = ".".join(rest)
        path = url_parsed.path[1:]
        for adjuster in self.__url_specific_adjusters:
            if re.match(adjuster["scheme"], rest_joined):
                prefselector = adjuster.get("prefselector")
                if isinstance(adjuster["top"], list):
                    for top_adjuster in adjuster["top"]:
                        if top_adjuster["scheme"] == top:
                            prefselector = adjuster.get("prefselector", prefselector)
                            break
                    else:
                        raise ValueError(f"No valid adjuster found for toplevel {top} of domain {domain}.")
                else:
                    if adjuster["top"] != top:
                        raise ValueError(f"No valid adjuster found for toplevel {top} of domain {domain}.")
                if "path" in adjuster:
                    if isinstance(adjuster["path"], list):
                        for path_adjuster in adjuster["top"]:
                            if re.match(path_adjuster["scheme"], path):
                                prefselector = adjuster.get("prefselector", prefselector)
                                break
                        else:
                            raise ValueError(f"No valid adjuster found for path {path} of url {url}.")
                    else:
                        if not re.match(adjuster["path"], path):
                            raise ValueError(f"No valid adjuster found for path {path} of url {url}.")
                break
        else:
            raise ValueError(f"No valid adjuster found for url {url}.")

        with (self.__res_path / "prefselectors" / f"{prefselector}.js").open() as f:
            prefselector_code = f.read()

        self.__browser.get(url)
        prefselector_code_augmented = f"""
        {prefselector_code}
        window.BINPrefselector = BINPrefselector;
        """
        self.__browser.execute_script(prefselector_code_augmented)

        prefselector_dict = self.__browser.execute_script(f"return BINPrefselector")
        if "getFallbackURL" in prefselector_dict:
            fallback_url = self.__browser.execute_script(
                "return BINPrefselector['getFallbackURL'](arguments[0]);", url)
            if fallback_url is not None:
                self.__browser.get(fallback_url)

        self.__browser.switch_to.frame("bibquery-popup")
        result_element = self.__wait_and_get(self.__browser, By.XPATH, "//textarea[@id='textToCopy']")

        bibtex_result = None
        start_time = time.time()
        while bibtex_result is None or bibtex_result == "Loading page...":
            bibtex_result = result_element.get_attribute("value")
            time.sleep(0.1)
            if time.time() - start_time > 60.0:
                raise TimeoutError("Timed out waiting for BibTeX entry to load.")

        if not bibtex_result.startswith("@"):
            raise ValueError(f"BibItNow returned unexpected string \"{bibtex_result}\"")

        return bibtex_result

    def query_google_scholar(self, url: str) -> str:
        """
        Tries to load the BibTeX of the paper behind the URL using Google Scholar.
        :param url: URL to get the BibTeX for.
        :return: A string containing the BibTeX for paper in the given URL.
        """
        if self.__browser is None:
            raise ValueError("BibQuery has not been initialized or was already closed.")

        try:
            return self.__query_google_scholar(url, self.__browser)
        except CaptchaEncounteredException:
            logger.info("Encountered Captcha. Prompting user to solve it.")
            browser = webdriver.Firefox(executable_path=GeckoDriverManager(
                path=str(self.__cache_path), cache_valid_range=14).install(), log_path=os.devnull)
            try:
                return_value = self.__query_google_scholar(url, browser, cancel_on_captcha=False)

                # This seems to be the only way of obtaining and setting cookies for www.google.com
                browser.get("https://scholar.google.com/")
                cookies = browser.get_cookies()
                with self.__cookie_path.open("w") as f:
                    json.dump(cookies, f)
                self.__browser.get("https://scholar.google.com/")
                self.__browser.delete_all_cookies()
                for cookie in cookies:
                    self.__browser.add_cookie(cookie)
            finally:
                browser.close()
            return return_value

    def __query_google_scholar(self, url: str, browser: WebDriver, cancel_on_captcha: bool = True) -> str:
        browser.get("https://scholar.google.com/")
        browser.find_element(By.NAME, "q").send_keys(url)
        browser.find_element(By.NAME, "btnG").click()

        start_time = time.time()
        citation_element = None
        while (time.time() - start_time < 60.0 or not cancel_on_captcha) and citation_element is None:
            citation_elements = browser.find_elements(By.XPATH, "//a[@aria-controls='gs_cit']")
            if len(citation_elements) > 0:
                citation_element = citation_elements[0]
            else:
                recaptcha_element_present = \
                    len(browser.find_elements(By.XPATH, "//iframe[@title='reCAPTCHA']")) > 0
                if recaptcha_element_present and cancel_on_captcha:
                    raise CaptchaEncounteredException("Encountered Captcha when querying Google Scholar.")
                time.sleep(0.1)
        if citation_element is None:
            raise TimeoutError("Timed out waiting for the citation link to appear on Google Scholar.")
        citation_element.click()

        link = self.__wait_and_get(browser, By.XPATH, "//a[contains(text(), 'BibTeX')]").get_attribute("href")

        browser.get(link)
        return browser.find_element(By.XPATH, "/html/body/pre").text
