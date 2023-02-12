#!/usr/bin/env python3
import json
import re
import shutil
from distutils.command.build_py import build_py as _build_py
from distutils.core import setup
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
import zipfile

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()


class build_py(_build_py):
    def run(self):
        super().run()

        if not self.dry_run:
            with TemporaryDirectory() as temp:
                temp_path = Path(temp)
                build_lib_path = Path(self.build_lib)
                res_path = build_lib_path / self.packages[0] / "res"
                res_path.mkdir(parents=True, exist_ok=True)
                bibitnow_zip_path = temp_path / "bibitnow.xpi"
                bibitnow_zip_output_path = res_path / "bibitnow_patched.xpi"
                bibitnow_path = temp_path / "bibitnow"
                urlretrieve(
                    "https://addons.mozilla.org/firefox/downloads/file/3916050/bibitnow-0.908.xpi", bibitnow_zip_path)
                with zipfile.ZipFile(bibitnow_zip_path, "r") as zip_file:
                    zip_file.extractall(bibitnow_path)

                with (bibitnow_path / "manifest.json").open() as f:
                    manifest = json.load(f)

                manifest["permissions"].remove("activeTab")
                manifest["permissions"].append("<all_urls>")

                if "content_scripts" not in manifest:
                    manifest["content_scripts"] = []

                manifest["content_scripts"].append({
                    "matches": ["<all_urls>"],
                    "js": [
                        str(p.relative_to(bibitnow_path))
                        for p in chain(
                            bibitnow_path.glob("popup/parser/*.js"),
                            [
                                bibitnow_path / "popup" / "popup_interaction.js",
                                bibitnow_path / "popup" / "popup_load.js",
                            ]
                        )
                    ]
                })

                with (bibitnow_path / "manifest.json").open("w") as f:
                    json.dump(manifest, f)

                with (bibitnow_path / "popup" / "popup_interaction.js").open() as f:
                    popup_interaction = f.read()

                # A bit of a yolo approach, but it works for 9.0.8
                popup_interaction = popup_interaction.replace("document", "new_document")

                with (bibitnow_path / "popup" / "popup_interaction.js").open("w") as f:
                    f.write(popup_interaction)

                with (bibitnow_path / "popup" / "popup_load.js").open() as f:
                    popup_load = f.read()

                # A bit of a yolo approach, but it works for 9.0.8
                popup_load = popup_load.replace(
                    "BINPopup.retreiveContent({name: \"first\" , message: \"\"});", "")

                with (bibitnow_path / "popup" / "popup.html").open() as f:
                    popup_html = f.read()
                body_content = re.findall(r"^[\s\S]*<body[^\>]*>([\s\S]*)<\/body>[\s\S]*", popup_html)[0]

                body_content_sanitized = body_content.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "")

                popup_load += f"\nconst html_code = \"{body_content_sanitized}\";"

                popup_load += """
                    iframe_element = document.createElement("iframe");
                    iframe_element.setAttribute("id", "bibquery-popup");
                    iframe_element.onload = () => {
                        iframe_element.contentDocument.body.innerHTML = html_code;
                        window.new_document = iframe_element.contentDocument;
                        BINPopup.retreiveContent({name: "first" , message: ""});
                    }
                    document.body.appendChild(iframe_element);
                    
                    iframe_element.contentWindow.browser = browser;
                    iframe_element.contentWindow.browser.permissions = {
                        contains: (...args) => new Promise((res, rej) => {return true;})
                    }
                """

                with (bibitnow_path / "popup" / "popup_load.js").open("w") as f:
                    f.write(popup_load)

                with (bibitnow_path / "background" / "background_interaction.js").open() as f:
                    background_interaction = f.read()

                background_interaction = background_interaction.replace(
                    "sendMsg(parsedData, doNothing);",
                    "sendMsg(parsedData, doNothing, parseInt(parsedData[\"tab_id\"].slice(4)));")

                with (bibitnow_path / "background" / "background_interaction.js").open("w") as f:
                    f.write(background_interaction)

                with zipfile.ZipFile(bibitnow_zip_output_path.resolve(), "w") as zip_file:
                    for path in bibitnow_path.rglob("*"):
                        zip_file.write(path.resolve(), path.relative_to(bibitnow_path))

                shutil.copytree(bibitnow_path / "extractors" / "prefselectors", res_path / "prefselectors")
                shutil.copy(bibitnow_path / "nameResources" / "urlSpecificAdjusterList.json",
                            res_path / "urlSpecificAdjusterList.json")


setup(name="bibquery",
      version="1.2.4",
      description="Creates BibTeX entries from links using BibItNow (https://github.com/Langenscheiss/bibitnow), "
                  "Google Scholar and Selenium.",
      author="Tim Schneider",
      author_email="tim@robot-learning.de",
      url="https://github.com/TimSchneider42/python-bibquery",
      packages=["bibquery"],
      cmdclass={"build_py": build_py},
      install_requires=[
          "selenium == 4.7.2",
          "webdriver-manager == 3.8.5"
      ],
      long_description=long_description,
      long_description_content_type='text/markdown',
      scripts=["bin/bibquery"]
      )
