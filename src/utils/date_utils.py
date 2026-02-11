"""
Centralized date utilities for the catalog application.

Provides:
- Footer date calculation (finding max update date from products)
- AD to BS (Nepali) date conversion wrapper
- Date format parsing

Eliminates code duplication between:
- print_export.py
- reports.py
- full_catalog.py
"""

from datetime import datetime


def get_max_update_date(products):
    """
    Find the maximum (latest) update date from a list of product dicts.

    Each product dict has a structure: {"data": {"max_update_date": "DD-MM-YYYY HH:MM:SS"}}

    Args:
        products: List of product dicts from layout_map.

    Returns:
        The raw date string of the latest update, or "" if none found.
    """
    if not products:
        return ""

    max_dt_obj = None
    max_date_str = ""

    for p in products:
        p_data = p.get("data", {})
        p_date = p_data.get("max_update_date", "")
        if p_date:
            try:
                date_part = p_date.split(" ")[0]
                dt = datetime.strptime(date_part, "%d-%m-%Y")
                if max_dt_obj is None or dt > max_dt_obj:
                    max_dt_obj = dt
                    max_date_str = p_date
            except (ValueError, IndexError):
                # Fallback: string comparison if format parsing fails
                if p_date > max_date_str:
                    max_date_str = p_date

    return max_date_str


def get_footer_date(products, logic=None):
    """
    Calculate the footer date string for a catalog page.

    Finds the max update date from products, then converts
    to Nepali date (DD/MM) if a logic object with get_nepali_date is available.

    Args:
        products: List of product dicts from layout_map.
        logic: CatalogLogic instance (optional). If provided,
               converts AD date to BS (Nepali) date.

    Returns:
        Footer date string (Nepali DD/MM format if logic available, else "").
    """
    max_date_str = get_max_update_date(products)

    if not max_date_str:
        return ""

    if logic and hasattr(logic, 'get_nepali_date'):
        try:
            return logic.get_nepali_date(max_date_str)
        except Exception:
            return ""

    return ""
