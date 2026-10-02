"""
VAT Working UI Pages.

Re-exports BalanceUI and StockUI implementations.
"""

from src.ui.vat_balance_ui import BalanceUI
from src.ui.vat_stock_ui import StockUI

__all__ = ['BalanceUI', 'StockUI']