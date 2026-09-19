import os
import yaml
from typing import Dict, Any, List, Optional
from core.system_tools import get_resource_path

DEFAULT_LANGUAGE = "en"
_current_language = DEFAULT_LANGUAGE
_catalogs: Dict[str, Dict[str, Any]] = {}
_loaded = False


def _load_all_locales():
    """Loads all translation catalogs from the locales directory."""
    global _catalogs, _loaded
    _catalogs.clear()
    
    locales_dir = get_resource_path("locales")
    if not os.path.isdir(locales_dir):
        # Fallback to local locales directory
        local_dir = os.path.abspath("locales")
        if os.path.isdir(local_dir):
            locales_dir = local_dir

    if os.path.isdir(locales_dir):
        for entry in os.listdir(locales_dir):
            if entry.endswith(".yaml") or entry.endswith(".yml"):
                lang_code = os.path.splitext(entry)[0].lower()
                filepath = os.path.join(locales_dir, entry)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                        _catalogs[lang_code] = data
                except Exception:
                    pass

    _loaded = True


def get_available_languages() -> List[str]:
    """Returns list of loaded language codes."""
    if not _loaded:
        _load_all_locales()
    langs = sorted(list(_catalogs.keys()))
    if DEFAULT_LANGUAGE not in langs:
        langs.insert(0, DEFAULT_LANGUAGE)
    return langs


def set_language(lang_code: Optional[str]) -> bool:
    """
    Sets active language code. Defaults to 'en' if code is empty or unsupported.
    """
    global _current_language
    if not _loaded:
        _load_all_locales()

    if not lang_code:
        _current_language = DEFAULT_LANGUAGE
        return True

    clean = lang_code.strip().lower()
    if clean in _catalogs:
        _current_language = clean
        return True
    
    _current_language = DEFAULT_LANGUAGE
    return False


def get_language() -> str:
    """Returns active language code."""
    return _current_language


def _lookup_key(catalog: Dict[str, Any], key: str) -> Optional[str]:
    """Navigates dot-separated key inside a nested dictionary."""
    parts = key.split(".")
    curr = catalog
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return None
    if isinstance(curr, str):
        return curr
    return None


def t(key: str, **kwargs) -> str:
    """
    Translates a dot-notated key into the active language, with fallback to English.
    Interpolates any keyword arguments provided (e.g. t('msg', count=5)).
    """
    if not _loaded:
        _load_all_locales()

    # 1. Try active language
    val = None
    if _current_language in _catalogs:
        val = _lookup_key(_catalogs[_current_language], key)

    # 2. Fallback to default English
    if val is None and DEFAULT_LANGUAGE in _catalogs:
        val = _lookup_key(_catalogs[DEFAULT_LANGUAGE], key)

    # 3. Fallback to raw key if not found in catalogs
    if val is None:
        val = key

    # Format parameters if provided
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val
