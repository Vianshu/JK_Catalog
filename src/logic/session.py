"""
User Session & Permission Guard — In-memory session after login.

Created after successful login, passed through the app.
Provides permission checking via the `can()` method.

Usage:
    session = UserSession(user_id=1, username="admin", ...)
    if session.can("final_data.edit"):
        # allow editing
    if session.can("tab.catalog"):
        # show catalog tab
"""

from datetime import datetime


# ─── COMPLETE PERMISSION REGISTRY ────────────────────────────────────────────
# Every controllable element in the application.
# Company Admin (is_admin=True) bypasses all checks.

PERMISSION_REGISTRY = {
    # ── Main Tab Visibility ──
    "tab.final_data":       "Final Data tab",
    "tab.super_master":     "Super Master tab",
    "tab.catalog":          "Full Catalog tab",
    "tab.godown":           "Godown tab",
    "tab.reports":          "Reports tab",
    "tab.row_data":         "Row Data tab",
    "tab.ledger":           "Ledger Row Data tab",
    "tab.group_test":       "Group Test tab",
    "tab.payment_list":     "Payment List tab",
    "tab.price_list":       "Price List tab",
    "tab.sales_chat":       "Sales Chat tab",
    "tab.cheque_list":      "Cheque List tab",
    "tab.calendar":         "Calendar Mapping tab",

    # ── Final Data ──
    "final_data.view":      "View final data table",
    "final_data.edit":      "Edit True/False toggles and cell values",
    "final_data.sync":      "Press Tally Sync button",
    "final_data.export":    "Export final data",

    # ── Super Master ──
    "super_master.view":    "View super master data",
    "super_master.edit":    "Edit/add/delete super master entries",

    # ── Catalog ──
    "catalog.view":         "View catalog pages",
    "catalog.build":        "Press Build Catalog button",
    "catalog.print":        "Print catalog pages",
    "catalog.edit_assignment": "Drag/reassign products to pages",

    # ── Godown ──
    "godown.view":          "View godown stock data",

    # ── Reports ──
    "reports.view":         "View reports",
    "reports.print":        "Print reports",
    "reports.mark_done":    "Mark pages as done/printed",

    # ── Row Data / Ledger ──
    "row_data.view":        "View raw Tally data",
    "ledger.view":          "View ledger data",
    "ledger.sync":          "Press Sync Ledger button",

    # ── Cheque List ──
    "cheque_list.view":     "View cheque entries",
    "cheque_list.edit":     "Add/edit cheque entries",

    # ── Calendar ──
    "calendar.view":        "View calendar",
    "calendar.edit":        "Edit calendar entries",

    # ── Settings / Admin ──
    "settings.manage_users":    "Create/edit/delete users",
    "settings.manage_roles":    "Create/edit roles and permissions",
    "settings.manage_crm":      "Create/alter CRM names",
    "settings.change_path":     "Change data path",
    "settings.company_config":  "Edit company configuration",
}


# ─── DEFAULT ROLES ────────────────────────────────────────────────────────────
# Auto-created when a new company is registered.
# Admin can modify/delete these later (except 'Full Access').

DEFAULT_ROLES = {
    "Full Access": {
        "description": "All permissions granted (system role)",
        "is_system": True,
        "permissions": list(PERMISSION_REGISTRY.keys()),
    },
    "Data Entry": {
        "description": "Can view and edit final data, view godown and row data",
        "is_system": False,
        "permissions": [
            "tab.final_data", "final_data.view", "final_data.edit",
            "tab.godown", "godown.view",
            "tab.row_data", "row_data.view",
        ],
    },
    "Catalog Viewer": {
        "description": "Can view and print catalog and reports",
        "is_system": False,
        "permissions": [
            "tab.catalog", "catalog.view", "catalog.print",
            "tab.reports", "reports.view", "reports.print",
        ],
    },
    "Accountant": {
        "description": "Access to ledger, cheques, payments, and sales",
        "is_system": False,
        "permissions": [
            "tab.ledger", "ledger.view",
            "tab.cheque_list", "cheque_list.view", "cheque_list.edit",
            "tab.payment_list",
            "tab.sales_chat",
        ],
    },
}


# ─── USER SESSION ─────────────────────────────────────────────────────────────

class UserSession:
    """In-memory session created after successful login.
    
    Holds user info, company context, and resolved permissions.
    Passed from main.py → MainWindow → all pages.
    """

    def __init__(self, user_id, username, is_admin, company_id, company_name,
                 company_path, role_name=None, permissions=None):
        self.user_id = user_id
        self.username = username
        self.is_admin = is_admin
        self.company_id = company_id
        self.company_name = company_name
        self.company_path = company_path
        self.role_name = role_name or ("Admin" if is_admin else "No Role")
        self.permissions = set(permissions) if permissions else set()
        self.login_time = datetime.now()

    def can(self, permission_key):
        """Check if current user has a specific permission.
        
        Args:
            permission_key: e.g., 'final_data.edit', 'tab.catalog'
        
        Returns:
            True if allowed, False if denied.
        """
        # Admin bypasses all permission checks
        if self.is_admin:
            return True
        return permission_key in self.permissions

    def can_view_tab(self, tab_key):
        """Shortcut: check if user can see a main tab.
        
        Args:
            tab_key: e.g., 'final_data', 'catalog', 'reports'
        """
        return self.can(f"tab.{tab_key}")

    def __repr__(self):
        return (f"UserSession(user='{self.username}', admin={self.is_admin}, "
                f"company='{self.company_name}', role='{self.role_name}', "
                f"perms={len(self.permissions)})")
