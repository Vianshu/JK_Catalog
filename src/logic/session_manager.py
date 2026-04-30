"""
SessionManager: Centralizes company session setup logic.

Replaces the lengthy, error-prone handle_login_success method in MainWindow
with a clean, structured approach to initializing all page modules with
company data. Each page registration is declarative, making it easy to add
or remove pages without modifying a monolithic method.

Usage in MainWindow:
    from src.logic.session_manager import SessionManager
    
    self.session = SessionManager()
    self.session.register("final_data", self.final_data_page, 
                          setup_fn=lambda page, path: (
                              page.load_and_sync_data(comp_name, path),
                              page.set_company_path(path)
                          ))
    ...
    self.session.activate(company_name, company_path)
"""

import os
import re
from typing import Callable, Optional, Any
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class PageRegistration:
    """Describes how a page should be initialized when a company is loaded."""
    
    def __init__(self, name: str, page_widget: Any, setup_fn: Callable):
        self.name = name
        self.page_widget = page_widget
        self.setup_fn = setup_fn


class SessionManager:
    """
    Manages company session state and coordinates page initialization.
    
    Instead of a single massive handle_login_success method that manually
    calls each page's setup, this class provides a registry of pages
    with their setup functions. When a company is activated, all registered
    pages are initialized in order.
    """
    
    def __init__(self):
        self._registrations = []
        self._current_company = None
        self._current_path = None
        self._on_error = None
    
    @property
    def company_name(self) -> Optional[str]:
        return self._current_company
    
    @property
    def company_path(self) -> Optional[str]:
        return self._current_path
    
    @property
    def is_active(self) -> bool:
        return self._current_company is not None and self._current_path is not None
    
    def set_error_handler(self, handler: Callable):
        """Set a callback for setup errors: handler(page_name, error)."""
        self._on_error = handler
    
    def register(self, name: str, page_widget: Any, setup_fn: Callable):
        """
        Register a page for company session initialization.
        
        Args:
            name: Human-readable page name (for error reporting).
            page_widget: The page widget instance.
            setup_fn: Callable(page_widget, company_path) that sets up the page.
        """
        self._registrations.append(PageRegistration(name, page_widget, setup_fn))
    
    def activate(self, company_name: str, company_path: str) -> dict:
        """
        Activate a company session, initializing all registered pages.
        
        Args:
            company_name: Display name of the company.
            company_path: Full path to the company data directory.
            
        Returns:
            dict with keys: success (bool), errors (list of (page_name, error_msg))
        """
        if not company_path or not os.path.exists(company_path):
            return {
                "success": False,
                "errors": [("session", f"Company path not found: {company_path}")]
            }
        
        self._current_company = company_name
        self._current_path = company_path
        
        errors = []
        
        for reg in self._registrations:
            try:
                reg.setup_fn(reg.page_widget, company_path)
            except Exception as e:
                error_msg = f"{reg.name}: {str(e)}"
                errors.append((reg.name, str(e)))
                if self._on_error:
                    self._on_error(reg.name, e)
                logger.error(f"Session init failed: {error_msg}", exc_info=True)
        
        return {
            "success": len(errors) == 0,
            "errors": errors
        }
    
    def get_clean_company_name(self) -> str:
        """Get company name without year suffix like (2081/82)."""
        if not self._current_company:
            return ""
        return re.sub(r'\s*\(\d{4}[-/].*?\)', '', self._current_company)
    
    def deactivate(self):
        """Clear the current session."""
        self._current_company = None
        self._current_path = None
