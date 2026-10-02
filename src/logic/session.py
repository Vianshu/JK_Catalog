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
    "tab.cat_price_list":   "Catalog Price List tab",
    "tab.vat_balance":      "Vat Balance tab",
    "tab.vat_stock":        "Vat Stock tab",
    "tab.catalog_on_account": "Catalog On Account tab",
    "tab.supp_payment":     "Supplier Payment tab",
    "tab.pur_import":       "Purchase Import tab",
    "tab.int_cost_sheet":   "Internal Cost Sheet tab",
    "tab.for_branch":       "Branch Submenu",

    # ── Vat Working ──
    "vat_balance.edit":     "Edit Vat Balance and Conf data",
    "vat_balance.sync":     "Sync Vat Ledger from Tally",
    "vat_stock.edit":       "Edit Vat Stock data",
    "vat.export_print":     "Export or Print Vat Working tables",

    # ── Final Data ──
    "final_data.edit":      "Edit True/False toggles and cell values",
    "final_data.sync":      "Press Tally Sync button",
    "final_data.export":    "Export final data",

    # ── Super Master ──
    "super_master.edit":    "Edit/add/delete super master entries",

    # ── Catalog ──
    "catalog.build":            "Build catalog via button click",
    "catalog.build_auto":       "Auto-build catalog on tab switch",
    "catalog.reshuffle":        "Reshuffle product assignments",
    "catalog.page_management":  "Add/remove catalog pages",

    # ── Godown ──
    # (View only, controlled by tab.godown)

    # ── Reports ──
    "reports.print":        "Print reports",
    "reports.mark_done":    "Mark pages as done/printed",

    # ── Row Data / Ledger ──
    "ledger.sync":          "Press Sync Ledger button",

    # ── Cheque List ──
    "cheque_list.edit":     "Add/edit cheque entries",

    # ── Calendar ──
    "calendar.edit":        "Edit calendar entries",

    # ── Settings / Admin ──
    "settings.manage_users":    "Create/edit/delete users",
    "settings.manage_roles":    "Create/edit roles and permissions",
    "settings.manage_crm":      "Create/alter CRM names",
    "settings.change_path":     "Change data path",
    "settings.company_config":  "Edit company configuration",
    "settings.year_end":        "Perform Year End (create new company with carried-forward data)",

    # ── Data Transfer ──
    "data.export":              "Export data backup (.jkbackup)",
    "data.import":              "Import data backup (.jkbackup)",
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
            "tab.final_data", "final_data.edit",
            "tab.godown",
            "tab.row_data",
        ],
    },
    "Catalog Viewer": {
        "description": "Can view and print catalog and reports",
        "is_system": False,
        "permissions": [
            "tab.catalog", 
            "tab.reports", "reports.print",
            "catalog.build", "catalog.build_auto",
        ],
    },
    "Accountant": {
        "description": "Access to ledger, cheques, payments, and sales",
        "is_system": False,
        "permissions": [
            "tab.ledger",
            "tab.cheque_list", "cheque_list.edit",
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
        self.role_name = "Admin (Owner)" if is_admin else (role_name or "No Role")
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
