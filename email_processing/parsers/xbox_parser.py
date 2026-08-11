import json
import logging
import os
import re
from typing import Dict, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"^[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}$", re.IGNORECASE)
XBOX_KEYWORDS = ("xbox", "game pass")
REJECT_KEYWORDS = ("norton",)


class XboxParser:
    def __init__(self):
        config_path = os.path.join(os.path.dirname(__file__), "html_selectors.json")
        with open(config_path, "r") as f:
            self.selectors = json.load(f)["xbox_parsing"]

    def _find_element_by_selector(self, soup: BeautifulSoup, selector_config: dict):
        tag = selector_config.get("tag")
        attributes = selector_config.get("attributes", {})
        text_contains = selector_config.get("text_contains")

        elements = soup.find_all(tag)

        for element in elements:
            if text_contains and text_contains not in element.get_text():
                continue

            style = element.get("style", "")
            if "style_contains_all" in attributes:
                if not all(attr in style for attr in attributes["style_contains_all"]):
                    continue
            elif "style_contains" in attributes:
                if attributes["style_contains"] not in style:
                    continue

            return element

        return None

    def _is_xbox_email(self, html_content: str) -> bool:
        text = html_content.lower()
        if any(keyword in text for keyword in REJECT_KEYWORDS):
            logger.info("Skipping non-Xbox perk email (reject keyword matched)")
            return False
        if not any(keyword in text for keyword in XBOX_KEYWORDS):
            logger.info("Skipping email without Xbox/Game Pass context")
            return False
        return True

    def _normalize_code(self, code: str) -> Optional[str]:
        if not code:
            return None
        normalized = re.sub(r"\s+", "", code.strip().upper())
        if not CODE_PATTERN.match(normalized):
            logger.info("Rejecting code with invalid format: %s", normalized)
            return None
        if not normalized.endswith("Z"):
            logger.info("Rejecting code that does not end with Z: %s", normalized)
            return None
        return normalized

    def extract_xbox_code(self, html_content: str) -> Optional[Dict[str, str]]:
        if not html_content or not self._is_xbox_email(html_content):
            return None

        soup = BeautifulSoup(html_content, "lxml")

        title_element = self._find_element_by_selector(soup, self.selectors["title"])
        title = title_element.get_text().strip() if title_element else None

        code_container = self._find_element_by_selector(
            soup, self.selectors["code_extraction"]["container"]
        )
        if not code_container:
            logger.info("Xbox code container not found")
            return None

        code_element = code_container.find_next_sibling("strong")
        if not code_element:
            logger.info("Xbox code element not found after container")
            return None

        code = self._normalize_code(code_element.get_text())
        if not code:
            return None

        logger.info("Extracted Xbox code: %s", code)

        result = {"code": code}
        if title:
            result["title"] = title

        return result
