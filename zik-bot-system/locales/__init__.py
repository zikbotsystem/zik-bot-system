from __future__ import annotations

import json
import os
from typing import Dict


class LocaleManager:
    """Loads simple JSON locale dictionaries from ./locales."""

    def __init__(self, locales_dir: str = "locales"):
        self.locales_dir = locales_dir
        self._locales: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isdir(self.locales_dir):
            return
        for filename in os.listdir(self.locales_dir):
            if not filename.endswith(".json"):
                continue
            lang = filename.split(".")[0]
            path = os.path.join(self.locales_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                self._locales[lang] = json.load(f)

    def t(self, key: str, lang: str = "az") -> str:
        # fallback order: requested lang -> az -> ru -> key
        if lang in self._locales and key in self._locales[lang]:
            return self._locales[lang][key]
        if "az" in self._locales and key in self._locales["az"]:
            return self._locales["az"][key]
        if "ru" in self._locales and key in self._locales["ru"]:
            return self._locales["ru"][key]
        return f"[{key}]"


_lm = LocaleManager()


def get_text(key: str, language: str = "az") -> str:
    return _lm.t(key, language)
