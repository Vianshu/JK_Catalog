"""
Centralized text cleaning and similarity utilities for product name clustering.

This module provides the single source of truth for:
- Product name cleaning (bracket removal, digit stripping, etc.)
- Fuzzy similarity matching between cleaned names
- Clustering products into groups based on name similarity

Used by: catalog_logic.py, group_test_tab.py
"""

import re
import os
import json
from difflib import SequenceMatcher


# --- Load config from JSON (with hardcoded fallback) ---
from src.utils.path_utils import get_base_path
_CONFIG_PATH = os.path.join(
    get_base_path(),
    "config", "cleaning_rules.json"
)

_DEFAULT_RULES = [
    {"pattern": r"chain\s*saw", "replacement": "chainsaw"},
    {"pattern": r"\(.*?\)", "replacement": ""},
    {"pattern": r"\[.*?\]", "replacement": ""},
    {"pattern": r"\d+", "replacement": ""},
    {"pattern": r"[^\w\s]", "replacement": " "},
]

_DEFAULT_IGNORE_WORDS = {'black', 'white', 'heavy', 'super', 'power', 'auto', 'manual'}
_DEFAULT_MIN_WORD_LEN = 5
_DEFAULT_THRESHOLD = 0.85

try:
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as _f:
        _config = json.load(_f)
    NAME_CLEANING_RULES = _config.get("name_cleaning_rules", _DEFAULT_RULES)
    _sim_config = _config.get("similarity", {})
    COMMON_IGNORE_WORDS = set(_sim_config.get("common_ignore_words", _DEFAULT_IGNORE_WORDS))
    MIN_LONG_WORD_LENGTH = _sim_config.get("min_long_word_length", _DEFAULT_MIN_WORD_LEN)
    SIMILARITY_THRESHOLD = _sim_config.get("threshold", _DEFAULT_THRESHOLD)
except (FileNotFoundError, json.JSONDecodeError):
    # Fallback to hardcoded defaults (safe for EXE or missing config)
    NAME_CLEANING_RULES = _DEFAULT_RULES
    COMMON_IGNORE_WORDS = _DEFAULT_IGNORE_WORDS
    MIN_LONG_WORD_LENGTH = _DEFAULT_MIN_WORD_LEN
    SIMILARITY_THRESHOLD = _DEFAULT_THRESHOLD


def clean_cat_name(n):
    """
    Clean a product name for similarity comparison.
    
    Applies all rules from config/cleaning_rules.json in order.
    Fallback to hardcoded rules if config is unavailable.
    """
    n = str(n).lower()
    for rule in NAME_CLEANING_RULES:
        n = re.sub(rule["pattern"], rule["replacement"], n)
    return " ".join(n.split())


def has_long_common_word(n1, n2, min_len=None):
    """
    Check if two cleaned names share a long common word.
    
    This catches cases like "Chainsaw" (8 chars) or "Hammer" (6 chars)
    while avoiding short common words like "Cock" (4) or "Sink" (4).
    """
    if min_len is None:
        min_len = MIN_LONG_WORD_LENGTH
    w1 = set(n1.split())
    w2 = set(n2.split())
    common = w1.intersection(w2)
    for w in common:
        if len(w) >= min_len and w not in COMMON_IGNORE_WORDS:
            return True
    return False


def is_similar(clean_a, clean_b):
    """
    Determine if two cleaned product names refer to the same product group.
    
    Three-tier check:
    1. Exact match after cleaning (fast path for bracket variants)
    2. Long common word heuristic (catches "Chainsaw", "Hammer", etc.)
    3. Fuzzy ratio >= 85% (fallback for typos/small differences)
    """
    if not clean_a or not clean_b:
        return False

    # 1. Exact Match
    if clean_a == clean_b:
        return True

    # 2. Long Common Word
    if has_long_common_word(clean_a, clean_b):
        return True

    # 3. High Fuzzy Match
    ratio = SequenceMatcher(None, clean_a, clean_b).ratio()
    return ratio >= SIMILARITY_THRESHOLD


def cluster_products(items, get_name_fn=None, get_price_fn=None, get_id_fn=None):
    """
    Cluster a list of product items by name similarity and sort by price.
    
    Args:
        items: List of product dicts or tuples.
        get_name_fn: Function to extract product name from an item.
                     Defaults to item.get("product_name", "").
        get_price_fn: Function to extract sort price from an item.
                      Defaults to item.get("sort_price", 0).
        get_id_fn: Function to extract product ID from an item.
                   Defaults to item.get("min_id", "ZZZZZZ").
    
    Returns:
        List of clusters, where each cluster is a list of items
        sorted by ID (ASC). Clusters are sorted by their minimum price.
    """
    if get_name_fn is None:
        def get_name_fn(x):
            if isinstance(x, dict):
                return x.get("product_name", "") or x.get("name", "")
            return x[0] if x else ""

    if get_price_fn is None:
        def get_price_fn(x):
            if isinstance(x, dict):
                return x.get("sort_price", 0)
            try:
                return float(str(x[4]).replace(",", "").strip()) if len(x) > 4 else 0
            except:
                return 0

    if get_id_fn is None:
        def get_id_fn(x):
            if isinstance(x, dict):
                return x.get("min_id", "ZZZZZZ")
            try:
                return str(x[11]) if len(x) > 11 and x[11] else "ZZZZZZ"
            except:
                return "ZZZZZZ"

    clusters = []
    for item in items:
        name = get_name_fn(item)
        clean_n = clean_cat_name(name)

        added = False
        for cluster in clusters:
            rep_name = get_name_fn(cluster[0])
            rep_clean = clean_cat_name(rep_name)
            if is_similar(clean_n, rep_clean):
                cluster.append(item)
                added = True
                break

        if not added:
            clusters.append([item])

    # Sort items within clusters by price (ASC)
    for cluster in clusters:
        cluster.sort(key=get_price_fn)

    # Sort clusters by minimum price across all items in the cluster
    clusters.sort(key=lambda c: min(get_price_fn(x) for x in c) if c else 0)

    return clusters
