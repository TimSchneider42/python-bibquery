import json
import re
import time
from pathlib import Path
from selenium import webdriver
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.expected_conditions import presence_of_element_located
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager


class BibQuery:
    def __init__(self):
        self.__browser = None
        self.__res_path = Path(__file__).parent / "res"
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
        self.__browser = webdriver.Firefox(executable_path=GeckoDriverManager().install(), options=options)
        self.__browser.install_addon(self.__res_path / "bibitnow_patched.xpi", temporary=True)

    def close(self):
        self.__browser.close()

    def query(self, url: str) -> str:
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
        WebDriverWait(self.__browser, 60.0).until(
            presence_of_element_located((By.XPATH, "//textarea[@id='textToCopy']")))
        result_element = self.__browser.find_element(By.XPATH, "//textarea[@id='textToCopy']")

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
