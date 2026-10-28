"""
VAT Working — Balance Screen.

Contains 4 views switchable via sidebar Left Panel:
1. Int. Ledger (Sundry Debtors from Internal Company row_ledger_data)
2. Vat Ledger (Sundry Debtors from configured VAT company) + VAT Company config bar
3. Mapping (VAT Ledger <-> Internal Ledger match with autocomplete, unmatched shown at top in red)
4. Vat Conf. (Debtor & Creditor tabs with 10 compact columns, editable cartoon numbers, flexible Yes/No input)
"""

import os
import re
import math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTabWidget, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QProgressDialog,
    QMessageBox, QLineEdit, QStyledItemDelegate, QAbstractItemView, QTabBar,
    QDialog, QCheckBox, QScrollArea, QSplitter, QListWidget, QListWidgetItem, QMenu,
    QComboBox, QStyle, QStyleOptionViewItem, QStyleOptionHeader
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QSettings, QEvent, QRect, QPoint
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QBrush, QCursor, QKeySequence, QShortcut

from src.logic.db_manager import get_db_manager, build_logical_name
from src.logic.vat_manager import (
    get_active_vat_company, load_internal_debtors, load_vat_debtors,
    load_vat_mappings, save_manual_mapping, get_internal_debtor_names,
    get_vat_debtor_names, load_vat_conf_table_data, save_vat_conf_field,
    check_amount_match, ensure_vat_tables, normalize_yes_no, validate_cartoon_number,
    _EXCLUDED_CNS,
    get_unassigned_internal_debtors, assign_internal_ledger_to_group,
    remove_internal_ledger_from_group, unmap_vat_group, merge_mapping_groups,
    demerge_mapping_group, set_group_internal_ledgers, set_group_vat_ledgers,
    set_group_manual_name, update_group_internal_ledger, update_group_vat_ledger,
    merge_vat_ledger_into_group, remove_vat_ledger_from_group,
    set_mapping_classification, set_unassigned_classification, run_auto_mapping_on_sync,
    calculate_need_print, get_unique_vat_creditor_subgroups, save_mapping_narration
)
from src.services.tally_sync import fetch_tally_vat_internal_data, fetch_tally_vat_ledger_data, TallyService
from src.ui.vat_company_dialog import VatCompanyDialog
from src.ui.vat_crm_mapping_dialog import VatSubgroupCrmMappingDialog
from src.ui.table_nav_mixin import UniversalCellDelegate, UNIVERSAL_TABLE_STYLE, _TallyCompleter, _norm
from src.ui.settings import load_crm_list
import difflib
from src.utils.app_logger import get_logger
from src.utils.path_utils import get_icon

logger = get_logger(__name__)


def round_nearest_1000(val: float) -> int:
    """Round value to the nearest 1,000 following Excel-style rounding (=ROUND(val, -3)).
    - Values below 500 round to 0 (e.g. 499 -> 0, 1499 -> 1000).
    - Values of 500 or above round to 1,000 (e.g. 500 -> 1000, 1500 -> 2000).
    """
    if not val:
        return 0
    sign = 1 if val >= 0 else -1
    return int(math.floor(abs(float(val)) / 1000.0 + 0.5) * 1000) * sign


def extract_company_year(name: str) -> str:
    """Extract fiscal year or year string from company name (e.g. '2083/84', '2024-25', '082/083')."""
    if not name:
        return ""
    s = str(name).strip()

    # 1. Look inside parentheses for year / fiscal year pattern
    paren_matches = re.findall(r'\(([^)]+)\)', s)
    for cand in reversed(paren_matches):
        cand = cand.strip()
        # Look for range like 2081/82, 081/082, 2024-25, 2024-2025
        m = re.search(r'\b((?:20)?\d{2}\s*[/_-]\s*(?:20)?\d{2,4})\b', cand)
        if m:
            return m.group(1).strip()
        # Look for 4-digit year like 2024 or 2081
        m = re.search(r'\b(20\d{2})\b', cand)
        if m:
            return m.group(1).strip()
        # Look for 6-digit fiscal like 082083
        m = re.search(r'\b(0\d{2})(0\d{2})\b', cand)
        if m:
            return f"{m.group(1)}/{m.group(2)}"

    # 2. Year range pattern in full string (e.g. 2081/82, 081/082, 2024-25)
    m = re.search(r'\b((?:20)?\d{2}\s*[/_-]\s*(?:20)?\d{2,4})\b', s)
    if m:
        return m.group(1).strip()

    # 3. 6-digit fiscal pattern like 082083 -> 082/083
    m = re.search(r'\b(0\d{2})(0\d{2})\b', s)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # 4. 4-digit year like 2082 or 2024
    m = re.search(r'\b(20\d{2})\b', s)
    if m:
        return m.group(1).strip()

    return ""

_GENERIC_BUSINESS_WORDS = {
    "traders", "trader", "enterprise", "enterprises", "corporation", "corp",
    "industries", "industry", "brothers", "bros", "co", "company", "limited",
    "ltd", "pvt", "private", "holdings", "agency", "agencies", "stores", "store",
    "mart", "bazaar", "bazar", "depot", "shop", "centre", "center", "house",
    "point", "hub", "associates", "associate", "and", "sons", "son", "services",
    "service", "works", "work", "steel", "steels", "metals", "metal", "sales"
}

def _extract_core_tokens(cleaned_name: str) -> list[str]:
    tokens = cleaned_name.split()
    core = [t for t in tokens if t not in _GENERIC_BUSINESS_WORDS]
    return core if core else tokens


def _clean_party_name_for_similarity(name: str) -> str:
    """Normalize a ledger party name for similarity comparison.
    Strips parenthetical/bracketed content (e.g. city, branch, GSTIN),
    standardizes legal prefixes/suffixes and common business words,
    removes punctuation, and collapses whitespace.
    """
    if not name:
        return ""
    s = str(name).strip().lower()
    # 1. Remove bracketed / parenthetical annotations: (Delhi), [Old], (07AAAA...), (Branch-1)
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'\[.*?\]', ' ', s)
    # 2. Normalize prefixes: m/s, m/s., ms, messrs, shri, shree
    s = re.sub(r'\bm/s\.?\b', ' ', s)
    s = re.sub(r'\bm/s\b', ' ', s)
    s = re.sub(r'\bms\.?\b', ' ', s)
    s = re.sub(r'\bmessrs\b', ' ', s)
    s = re.sub(r'\bshree\b', ' shri ', s)
    # 3. Standardize common business terms & abbreviations
    s = re.sub(r'\b&\b', ' and ', s)
    s = re.sub(r'\bpvt\.?\s*ltd\.?\b', ' pvt ltd ', s)
    s = re.sub(r'\bprivate\s+limited\b', ' pvt ltd ', s)
    s = re.sub(r'\bltd\.?\b', ' ltd ', s)
    s = re.sub(r'\blimited\b', ' ltd ', s)
    s = re.sub(r'\bco\.?\b', ' co ', s)
    s = re.sub(r'\bcompany\b', ' co ', s)
    s = re.sub(r'\bbros\.?\b', ' brothers ', s)
    s = re.sub(r'\bcorp\.?\b', ' corporation ', s)
    s = re.sub(r'\benterprises\b', ' enterprise ', s)
    s = re.sub(r'\btrading\s+co\.?\b', ' traders ', s)
    s = re.sub(r'\btrading\s+company\b', ' traders ', s)
    # 4. Strip all remaining punctuation
    s = re.sub(r'[^\w\s]', ' ', s)
    # 5. Collapse spaces
    return " ".join(s.split())


def _are_single_names_similar(vname: str, iname: str, v_aliases: list = None, i_aliases: list = None) -> bool:
    """Check if a VAT ledger name and an Internal ledger name are sufficiently similar
    or almost identical, taking into account aliases and business variations.
    """
    v_raw = (vname or "").strip()
    i_raw = (iname or "").strip()
    if not v_raw or not i_raw:
        return False

    v_lower = v_raw.lower()
    i_lower = i_raw.lower()

    # Rule 0: Placeholders (Cash Sales, Old Party) are NEVER considered similar
    # unless the VAT ledger itself is actually named Cash Sales / Old Party
    if i_lower in ("cash sales", "old party"):
        return i_lower in v_lower

    if v_lower in ("cash sales", "old party"):
        return v_lower in i_lower

    # Rule 1: Case-insensitive exact match
    if v_lower == i_lower:
        return True

    # Rule 2: Cleaned names match
    v_clean = _clean_party_name_for_similarity(v_raw)
    i_clean = _clean_party_name_for_similarity(i_raw)
    if not v_clean or not i_clean:
        return False

    if v_clean == i_clean:
        return True

    # Rule 3: Compressed match (ignoring whitespace differences like "j k" vs "jk")
    if v_clean.replace(" ", "") == i_clean.replace(" ", ""):
        return True

    # Rule 4: Token re-ordering (e.g. "KUMAR RAMESH" vs "RAMESH KUMAR")
    v_tokens = set(v_clean.split())
    i_tokens = set(i_clean.split())
    if v_tokens == i_tokens:
        return True

    # Rule 5: Check aliases if provided
    # If VAT name/alias matches internal alias/name
    candidates_v = [v_raw, v_clean]
    if v_aliases:
        for a in v_aliases:
            if a:
                candidates_v.extend([a.strip(), _clean_party_name_for_similarity(a)])

    candidates_i = [i_raw, i_clean]
    if i_aliases:
        for a in i_aliases:
            if a:
                candidates_i.extend([a.strip(), _clean_party_name_for_similarity(a)])

    for cv in candidates_v:
        cv_s = cv.strip().lower()
        if not cv_s or cv_s in ("none", "nan", "null"):
            continue
        for ci in candidates_i:
            ci_s = ci.strip().lower()
            if not ci_s or ci_s in ("none", "nan", "null"):
                continue
            if cv_s == ci_s or cv_s.replace(" ", "") == ci_s.replace(" ", ""):
                return True

    # Rule 6: Core entity tokens analysis (eliminates false positives like "RAMESH TRADERS" vs "SURESH TRADERS")
    v_core = _extract_core_tokens(v_clean)
    i_core = _extract_core_tokens(i_clean)

    # 6a. Core tokens exact match or re-ordered
    # e.g. "BHARAT HARDWARE" (core: bharat hardware) vs "BHARAT HARDWARE STORES" (core: bharat hardware)
    if set(v_core) == set(i_core):
        return True

    # 6b. Core tokens typo tolerance via SequenceMatcher on joined core names
    # e.g. "AGARWAL" vs "AGRAWAL" ratio is 0.86 >= 0.85; "KHANDELWAL" vs "KHANDALWAL" ratio is 0.90 >= 0.85
    v_core_str = " ".join(sorted(v_core))
    i_core_str = " ".join(sorted(i_core))
    core_ratio = difflib.SequenceMatcher(None, v_core_str, i_core_str).ratio()
    if core_ratio >= 0.85:
        return True

    # 6c. High overall cleaned ratio ONLY IF core tokens have significant overlap
    full_ratio = difflib.SequenceMatcher(None, v_clean, i_clean).ratio()
    common_core = set(v_core).intersection(set(i_core))
    if common_core and full_ratio >= 0.90:
        return True

    return False


def _are_group_names_sufficiently_similar(vat_items: list, internal_items: list, m: dict) -> bool:
    """Determine if all mapped ledgers in a group have almost identical / sufficiently similar names.
    Returns False if any ledger was mapped to a completely different party or to Cash Sales / Old Party.
    """
    if not vat_items or not internal_items:
        return False

    # Check for placeholder assignment (Cash Sales, Old Party)
    for ii in internal_items:
        iname = str(ii.get("name", "")).strip().lower()
        if iname in ("cash sales", "old party"):
            if not any(iname in str(vi.get("name", "")).strip().lower() for vi in vat_items):
                return False

    cls = str(m.get("classification", "")).strip().lower()
    if cls in ("cash sales", "old party"):
        if not any(cls in str(vi.get("name", "")).strip().lower() for vi in vat_items):
            return False

    # Extract all names and aliases
    v_names = [str(v.get("name", "")).strip() for v in vat_items if v.get("name")]
    if not v_names and m.get("vat_ledger"):
        v_names = [str(m.get("vat_ledger")).strip()]

    i_names = [str(i.get("name", "")).strip() for i in internal_items if i.get("name")]
    if not i_names and m.get("internal_ledger"):
        i_names = [str(m.get("internal_ledger")).strip()]

    if not v_names or not i_names:
        return False

    v_aliases = [str(v.get("alias", "")).strip() for v in vat_items if v.get("alias")]
    if not v_aliases and m.get("vat_aliases"):
        v_aliases = [str(a).strip() for a in m.get("vat_aliases") if a]

    i_aliases = [str(i.get("alias", "")).strip() for i in internal_items if i.get("alias")]
    if not i_aliases and m.get("internal_aliases"):
        i_aliases = [str(a).strip() for a in m.get("internal_aliases") if a]

    # Check every internal ledger matches at least one VAT ledger
    for iname in i_names:
        matched = False
        for vname in v_names:
            if _are_single_names_similar(vname, iname, v_aliases, i_aliases):
                matched = True
                break
        if not matched:
            return False

    # Check every VAT ledger matches at least one internal ledger
    for vname in v_names:
        matched = False
        for iname in i_names:
            if _are_single_names_similar(vname, iname, v_aliases, i_aliases):
                matched = True
                break
        if not matched:
            return False

    return True


# ── Background Worker for non-blocking data load ─────────────────────
class _VatBalanceLoadWorker(QThread):
    """Fetches all VAT Balance data off the main thread.

    Emits `finished` with a dict of results when done, or `error` with the
    exception message on failure.  The UI thread picks up the signal and
    populates tables — keeping the window responsive throughout.
    """
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db_name: str, vat_company: str, parent=None):
        super().__init__(parent)
        self._db_name = db_name
        self._vat_company = vat_company

    def run(self):
        try:
            int_debtors = load_internal_debtors(self._db_name)
            vat_debtors = load_vat_debtors(self._db_name, self._vat_company) if self._vat_company else []
            mappings = load_vat_mappings(self._db_name, self._vat_company) if self._vat_company else []
            if not mappings and self._vat_company:
                run_auto_mapping_on_sync(self._db_name, self._vat_company)
                mappings = load_vat_mappings(self._db_name, self._vat_company)
            unassigned_int = get_unassigned_internal_debtors(self._db_name, self._vat_company) if self._vat_company else []
            debtor_conf = load_vat_conf_table_data(self._db_name, self._vat_company, "Debtor") if self._vat_company else []
            creditor_conf = load_vat_conf_table_data(self._db_name, self._vat_company, "Creditor") if self._vat_company else []

            self.finished.emit({
                "int_debtors": int_debtors,
                "vat_debtors": vat_debtors,
                "mappings": mappings,
                "unassigned_int": unassigned_int,
                "debtor_conf": debtor_conf,
                "creditor_conf": creditor_conf,
            })
        except Exception as e:
            logger.error(f"[_VatBalanceLoadWorker] error: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            get_db_manager().close_thread_connections()


class _MappingRefreshWorker(QThread):
    """Background worker to fetch mappings and unassigned internal debtors without blocking UI."""
    finished = pyqtSignal(list, list, int)
    error = pyqtSignal(str)

    def __init__(self, db_name: str, vat_company: str, select_group_id: int = 0, parent=None):
        super().__init__(parent)
        self.db_name = db_name
        self.vat_company = vat_company
        safe_select_gid = 0
        if select_group_id is not None:
            try:
                safe_select_gid = int(select_group_id)
            except (ValueError, TypeError):
                safe_select_gid = 0
        self.select_group_id = safe_select_gid

    def run(self):
        try:
            mappings = load_vat_mappings(self.db_name, self.vat_company)
            unassigned_int = get_unassigned_internal_debtors(self.db_name, self.vat_company)
            self.finished.emit(mappings, unassigned_int, self.select_group_id)
        except Exception as e:
            logger.error(f"[_MappingRefreshWorker] error: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            get_db_manager().close_thread_connections()


# Authentic columns directly from Tally Ledger
TALLY_LEDGER_COLUMNS = [
    ("Name", "Ledger Name", 250, False),
    ("Group", "Group", 130, False),
    ("Opening_Balance", "Opening Balance", 120, True),
    ("Debit_Totals", "Debit Total", 120, True),
    ("Credit_Totals", "Credit Total", 120, True),
    ("Closing_Balance", "Closing Balance", 120, True),
    ("CashOutFlow", "Cash Outflow", 130, True),
    ("CashInFlow", "Cash Inflow", 120, True),
    ("Pan_No.", "Pan No.", 120, False),
    ("Phone", "Phone", 110, False),
    ("Mobile", "Mobile", 110, False),
    ("Address", "Address", 220, False),
    ("Alias", "Alias", 130, False),
    ("Contact_Person", "Contact Person", 140, False),
    ("Sub_Group", "Sub Group", 150, False),
    ("Credit_Limit", "Credit Limit", 110, True),
    ("Overdue_Bills", "Overdue Bills", 110, True),
    ("On_Account_Value", "On Account Value", 120, True),
    ("Performance", "Performance", 100, True),
    ("This_Qtr_Balance", "This Qtr Balance", 120, True),
    ("Prev_Qtr_Balance", "Prev Qtr Balance", 120, True),
    ("BillwiseOn", "Billwise On", 90, True),
]


class LedgerColumnSettingsDialog(QDialog):
    """Allows user to select which columns to display in Int. and VAT Ledger tables."""

    DEFAULT_COLUMNS = {
        "Name", "Alias", "Group", "Opening_Balance",
        "Debit_Totals", "Credit_Totals",
        "Closing_Balance"
    }

    def __init__(self, current_visible: set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Visible Columns")
        self.setMinimumWidth(380)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { font-size: 13px; color: #0f172a; }
            QCheckBox { font-size: 12px; color: #334155; padding: 4px 0; }
            QCheckBox:hover { color: #059669; }
            QPushButton {
                font-size: 12px; font-weight: 600; border-radius: 4px; padding: 6px 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Select Columns to Display:")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")
        layout.addWidget(title)

        # Quick preset buttons
        preset_bar = QHBoxLayout()
        btn_preset_def = QPushButton("Default View")
        btn_preset_def.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        btn_preset_all = QPushButton("Show All")
        btn_preset_all.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        preset_bar.addWidget(btn_preset_def)
        preset_bar.addWidget(btn_preset_all)
        preset_bar.addStretch()
        layout.addLayout(preset_bar)

        # Scroll area with checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 4px; }")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(6)

        self.checkboxes = {}
        for col_key, col_title, _, _ in TALLY_LEDGER_COLUMNS:
            cb = QCheckBox(col_title)
            cb.setChecked(col_key in current_visible)
            if col_key == "Name":
                cb.setChecked(True)
                cb.setEnabled(False)
            self.checkboxes[col_key] = cb
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        btn_preset_def.clicked.connect(self._select_default)
        btn_preset_all.clicked.connect(self._select_all)

        # Bottom buttons: Save / Cancel
        btn_box = QHBoxLayout()
        btn_save = QPushButton("Save & Apply")
        btn_save.setStyleSheet("background: #059669; color: #ffffff; border: none;")
        btn_save.clicked.connect(self.accept)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1;")
        btn_cancel.clicked.connect(self.reject)

        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    def _select_default(self):
        for k, cb in self.checkboxes.items():
            if k == "Name":
                continue
            cb.setChecked(k in self.DEFAULT_COLUMNS)

    def _select_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def get_selected_columns(self) -> set:
        selected = {"Name"}
        for k, cb in self.checkboxes.items():
            if cb.isChecked():
                selected.add(k)
        return selected


VAT_CONF_DEBTOR_COLUMNS = [
    ("sn", "SN.", True),
    ("name", "Name", True),
    ("pan_no", "Pan No.", True),
    ("alias", "Alias", True),
    ("opening_amount", "Opening Amount", True),
    ("debit_totals", "Debit Total", False),
    ("credit_totals", "Credit Total", False),
    ("cash_in", "Cash Inflow", False),
    ("cash_out", "Cash Outflow", False),
    ("closing_amount", "Closing Amount", True),
    ("need_print", "Need Print ?", True),
    ("did_you_print", "Did You Print", True),
    ("sub_group", "Sub Group", True),
    ("crm", "CRM", True),
    ("get_back", "Get Back", True),
    ("expected_opening", "Opening ?", True),
    ("expected_closing", "Closing ?", True),
]


class VatConfColumnSettingsDialog(QDialog):
    """Allows user to select which columns to display in the VAT Conf Debtor table."""

    def __init__(self, current_visible: set, on_autofit_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Visible Columns")
        self.setMinimumWidth(380)
        self.on_autofit_callback = on_autofit_callback
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { font-size: 13px; color: #0f172a; }
            QCheckBox { font-size: 12px; color: #334155; padding: 4px 0; }
            QCheckBox:hover { color: #059669; }
            QPushButton {
                font-size: 12px; font-weight: 600; border-radius: 4px; padding: 6px 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Select Columns to Display:")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")
        layout.addWidget(title)

        # Quick preset buttons
        preset_bar = QHBoxLayout()
        btn_preset_def = QPushButton("Default View")
        btn_preset_def.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        btn_preset_fin = QPushButton("Show Financials")
        btn_preset_fin.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        btn_preset_all = QPushButton("Show All")
        btn_preset_all.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        preset_bar.addWidget(btn_preset_def)
        preset_bar.addWidget(btn_preset_fin)
        preset_bar.addWidget(btn_preset_all)
        preset_bar.addStretch()
        layout.addLayout(preset_bar)

        # Scroll area with checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 4px; }")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(6)

        self.checkboxes = {}
        for col_key, col_title, _ in VAT_CONF_DEBTOR_COLUMNS:
            cb = QCheckBox(col_title)
            cb.setChecked(col_key in current_visible)
            if col_key == "name":
                cb.setChecked(True)
                cb.setEnabled(False)
            self.checkboxes[col_key] = cb
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        # Bottom buttons: Auto-fit, Cancel, Save
        btn_box = QHBoxLayout()
        btn_autofit = QPushButton("Auto-Fit Widths")
        btn_autofit.setStyleSheet("background: #f8fafc; color: #0284c7; border: 1px solid #bae6fd;")
        btn_autofit.clicked.connect(self._do_autofit)
        btn_box.addWidget(btn_autofit)
        btn_box.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_save = QPushButton("Apply")
        btn_save.setStyleSheet("background: #059669; color: white; border: none;")
        btn_save.clicked.connect(self.accept)
        btn_box.addWidget(btn_save)

        layout.addLayout(btn_box)

        btn_preset_def.clicked.connect(self._select_default)
        btn_preset_fin.clicked.connect(self._select_financials)
        btn_preset_all.clicked.connect(self._select_all)

    def _select_default(self):
        for col_key, _, def_vis in VAT_CONF_DEBTOR_COLUMNS:
            if col_key in self.checkboxes:
                self.checkboxes[col_key].setChecked(def_vis)
        self.checkboxes["name"].setChecked(True)

    def _select_financials(self):
        fin_keys = {"opening_amount", "debit_totals", "credit_totals", "cash_in", "cash_out", "closing_amount"}
        for col_key, cb in self.checkboxes.items():
            if col_key in fin_keys or col_key in ("sn", "name", "need_print"):
                cb.setChecked(True)

    def _select_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def _do_autofit(self):
        if callable(self.on_autofit_callback):
            self.on_autofit_callback()

    def get_selected_columns(self) -> set:
        selected = {k for k, cb in self.checkboxes.items() if cb.isChecked()}
        selected.add("name")
        return selected


class CreditorSubgroupDialog(QDialog):
    """Clean multi-select dialog for Creditor Sub Groups with live search, checkboxes, and extra addition."""

    def __init__(self, available_subgroups: list[str], selected_subgroups: set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Creditor Sub Groups")
        self.resize(440, 500)
        self.setMinimumSize(380, 420)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { font-size: 13px; color: #0f172a; }
            QLineEdit {
                border: 1px solid #cbd5e1; border-radius: 4px; background: #ffffff;
                padding: 6px 10px; font-size: 12px; color: #0f172a;
            }
            QLineEdit:focus { border: 1px solid #059669; }
            QCheckBox { font-size: 12px; color: #334155; padding: 4px 0; }
            QCheckBox:hover { color: #059669; }
            QPushButton {
                font-size: 12px; font-weight: 600; border-radius: 4px; padding: 6px 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Filter Creditor Ledgers by Sub Group:")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")
        layout.addWidget(title)

        # Search Bar
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search sub groups...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_box)

        # Quick preset buttons
        preset_bar = QHBoxLayout()
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        btn_clear = QPushButton("Clear All")
        btn_clear.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        preset_bar.addWidget(btn_sel_all)
        preset_bar.addWidget(btn_clear)
        preset_bar.addStretch()
        layout.addLayout(preset_bar)

        # Scroll Area for checkable sub groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 4px; }")
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(4)
        self.scroll_layout.setContentsMargins(8, 8, 8, 8)

        self.checkboxes = {}
        all_sgs = list(available_subgroups)
        for s in selected_subgroups:
            if s and s not in all_sgs:
                all_sgs.append(s)
        all_sgs.sort(key=lambda x: x.lower())

        sel_lower = {x.lower() for x in selected_subgroups if x}
        for sg in all_sgs:
            self._add_checkbox(sg, checked=(sg.lower() in sel_lower))

        self.scroll_layout.addStretch()
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, stretch=1)

        # Add Extra Custom Sub Group
        extra_layout = QHBoxLayout()
        self.extra_input = QLineEdit()
        self.extra_input.setPlaceholderText("Add extra sub group name...")
        btn_add = QPushButton("Add")
        btn_add.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600; padding: 6px 14px; border: none;
            }
            QPushButton:hover { background: #047857; }
        """)
        btn_add.clicked.connect(self._add_custom_subgroup)
        self.extra_input.returnPressed.connect(self._add_custom_subgroup)
        extra_layout.addWidget(self.extra_input, stretch=1)
        extra_layout.addWidget(btn_add)
        layout.addLayout(extra_layout)

        # Bottom Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_apply = QPushButton("Apply Filter")
        btn_apply.setStyleSheet("background: #059669; color: white; border: none;")
        btn_apply.clicked.connect(self.accept)
        btn_box.addWidget(btn_apply)

        layout.addLayout(btn_box)

        btn_sel_all.clicked.connect(self._select_all)
        btn_clear.clicked.connect(self._clear_all)

    def _add_checkbox(self, sg: str, checked: bool = False):
        if sg in self.checkboxes:
            self.checkboxes[sg].setChecked(checked)
            return
        cb = QCheckBox(sg)
        cb.setChecked(checked)
        self.checkboxes[sg] = cb
        idx = max(0, self.scroll_layout.count() - 1)
        self.scroll_layout.insertWidget(idx, cb)

    def _add_custom_subgroup(self):
        text = self.extra_input.text().strip()
        if not text:
            return
        self._add_checkbox(text, checked=True)
        self.extra_input.clear()

    def _filter_items(self, text: str):
        q = (text or "").strip().lower()
        for sg, cb in self.checkboxes.items():
            match = not q or q in sg.lower()
            cb.setVisible(match)

    def _select_all(self):
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.setChecked(True)

    def _clear_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def get_selected_subgroups(self) -> set:
        return {sg for sg, cb in self.checkboxes.items() if cb.isChecked()}

    def accept(self):
        # Auto-commit any text typed into extra_input before applying
        text = self.extra_input.text().strip()
        if text:
            self._add_checkbox(text, checked=True)
            self.extra_input.clear()
        super().accept()


class AdminPasswordConfirmDialog(QDialog):
    """Confirmation dialog requiring admin password before proceeding with sensitive actions like Clear Mapping."""

    def __init__(self, title: str = "Confirm Action", prompt: str = "Enter Admin Password to confirm:",
                 security_mgr=None, company_path: str = "", company_name: str = "", parent=None):
        super().__init__(parent)
        self.security_mgr = security_mgr
        self.company_path = company_path
        self.company_name = company_name
        self.setWindowTitle(title)
        self.setFixedWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background: #ffffff;
            }
            QLabel {
                font-family: 'Noto Sans Devanagari', 'Segoe UI', system-ui, sans-serif;
            }
            QLineEdit {
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 12px;
                font-size: 13px;
                background: #f8fafc;
                color: #0f172a;
            }
            QLineEdit:focus {
                border-color: #ef4444;
                background: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header with warning prompt
        hdr_lay = QHBoxLayout()
        hdr_lay.setSpacing(12)
        lbl_icon = QLabel("⚠️")
        lbl_icon.setStyleSheet("font-size: 26px;")
        hdr_lay.addWidget(lbl_icon)

        lbl_prompt = QLabel(prompt)
        lbl_prompt.setStyleSheet("font-size: 13px; font-weight: 600; color: #0f172a;")
        lbl_prompt.setWordWrap(True)
        hdr_lay.addWidget(lbl_prompt, 1)
        layout.addLayout(hdr_lay)

        # Password input
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("Enter Admin Password...")
        self.txt_password.returnPressed.connect(self._on_confirm)
        layout.addWidget(self.txt_password)

        # Error label
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 600;")
        self.lbl_error.setVisible(False)
        layout.addWidget(self.lbl_error)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #475569; font-weight: 600; font-size: 12px;
                padding: 7px 16px; border-radius: 5px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; color: #1e293b; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("Confirm Clear")
        self.btn_confirm.setStyleSheet("""
            QPushButton {
                background: #ef4444; color: #ffffff; font-weight: 700; font-size: 12px;
                padding: 7px 18px; border-radius: 5px; border: none;
            }
            QPushButton:hover { background: #dc2626; }
            QPushButton:pressed { background: #b91c1c; }
        """)
        self.btn_confirm.clicked.connect(self._on_confirm)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)
        self.txt_password.setFocus()

    def _on_confirm(self):
        pw = self.txt_password.text().strip()
        if not pw:
            self.lbl_error.setText("Please enter the admin password.")
            self.lbl_error.setVisible(True)
            self.txt_password.setFocus()
            return

        mgr = self.security_mgr
        if not mgr:
            from src.logic.security_manager import SecurityManager
            data_path = os.path.dirname(self.company_path) if self.company_path else ""
            mgr = SecurityManager(data_path)

        is_valid = mgr.verify_admin_password(
            password=pw,
            folder_path=self.company_path,
            company_name=self.company_name
        )
        if is_valid:
            self.accept()
        else:
            self.lbl_error.setText("Incorrect admin password.")
            self.lbl_error.setVisible(True)
            self.txt_password.selectAll()
            self.txt_password.setFocus()


# ─── WORKER THREADS ──────────────────────────────────────────────────────────

class _InternalLedgerWorker(QThread):
    finished = pyqtSignal(int, str)

    def __init__(self, company_name, path, service):
        super().__init__()
        self.company_name = company_name
        self.path = path
        self.service = service

    def run(self):
        try:
            rc, err = fetch_tally_vat_internal_data(
                company_name=self.company_name,
                company_path=self.path,
                service=self.service
            )
            self.finished.emit(rc or 0, err or "")
        except Exception as e:
            self.finished.emit(0, str(e))
        finally:
            get_db_manager().close_thread_connections()


class _VatLedgerWorker(QThread):
    finished = pyqtSignal(int, str)

    def __init__(self, vat_company, company_name, path, service):
        super().__init__()
        self.vat_company = vat_company
        self.company_name = company_name
        self.path = path
        self.service = service

    def run(self):
        try:
            rc, err = fetch_tally_vat_ledger_data(
                vat_company_name=self.vat_company,
                company_name=self.company_name,
                company_path=self.path,
                service=self.service
            )
            self.finished.emit(rc or 0, err or "")
        except Exception as e:
            self.finished.emit(0, str(e))
        finally:
            get_db_manager().close_thread_connections()


# ─── CUSTOM DELEGATES & CONTROLS ─────────────────────────────────────────────

class MappingItemDelegate(UniversalCellDelegate):
    """Delegate for Mapping table: provides seamless in-cell QLineEdit editing with
    searchable _TallyCompleter for both VAT Ledger (Col 1) and Internal Ledger (Col 3),
    and editable text for Manual Name (Col 5). Strictly validates ledger selections
    against configured options and paints unmapped rows in red.
    """
    def __init__(self, get_vat_options_callback, get_int_options_callback,
                 resolve_vat_callback=None, resolve_int_callback=None,
                 parent_table=None, parent=None):
        super().__init__(parent=parent)
        self.get_vat_options_callback = get_vat_options_callback
        self.get_int_options_callback = get_int_options_callback
        self.resolve_vat_callback = resolve_vat_callback
        self.resolve_int_callback = resolve_int_callback
        self.parent_table = parent_table

    def paint(self, painter, option, index):
        # Unmapped VAT rows are painted in light red (#fecaca)
        table = self.parent_table or (self.parent() if isinstance(self.parent(), QAbstractItemView) else None)
        if table:
            it0 = table.item(index.row(), 0)
            mapping_data = getattr(it0, '_mapping_group', {}) if it0 else {}
            if mapping_data.get("is_unmapped", False):
                painter.save()
                painter.fillRect(option.rect, QColor("#fecaca"))
                painter.restore()

        super().paint(painter, option, index)

    def _commit_and_close(self, editor):
        table = self.parent_table or self.parent()
        if not table or not hasattr(table, 'state'):
            p = editor.parent() if editor else None
            table = p if hasattr(p, 'state') else (getattr(p, 'parent', lambda: None)() if p else None)

        if table and hasattr(table, 'state') and table.state() != QAbstractItemView.State.EditingState:
            return

        try:
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
        except RuntimeError:
            pass

    def createEditor(self, parent, option, index):
        table = self.parent_table or (self.parent() if isinstance(self.parent(), QAbstractItemView) else None)
        if table and hasattr(table, '_can_edit') and not table._can_edit:
            return None

        col = index.column()
        if col in (0, 2, 4):  # #, VAT Alias, Internal Alias are read-only
            return None

        if col == 1:  # VAT Ledger (editable with completer)
            ed = QLineEdit(parent)
            ed._initial_text = index.data() or ""
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)

            callback = self.get_vat_options_callback
            options = callback() if callable(callback) else []
            completer = _TallyCompleter(options or [], ed)
            completer.setMaxVisibleItems(12)
            completer.popup().setMinimumWidth(420)
            ed.setCompleter(completer)
            ed.textEdited.connect(completer.update_prefix)

            def _on_vat_activated(selected, e=ed, c=completer):
                c._typed_text = selected
                e.setText(selected)
                QTimer.singleShot(0, lambda: self._commit_and_close(e))

            completer.activated.connect(_on_vat_activated)
            return ed

        elif col in (2, 3):  # Internal Ledger (editable with completer)
            ed = QLineEdit(parent)
            ed._initial_text = index.data() or ""
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)

            callback = self.get_int_options_callback
            options = callback() if callable(callback) else []
            completer = _TallyCompleter(options or [], ed)
            completer.setMaxVisibleItems(12)
            completer.popup().setMinimumWidth(420)
            ed.setCompleter(completer)
            ed.textEdited.connect(completer.update_prefix)

            def _on_activated(selected, e=ed, c=completer):
                c._typed_text = selected
                e.setText(selected)
                QTimer.singleShot(0, lambda: self._commit_and_close(e))

            completer.activated.connect(_on_activated)
            return ed

        elif col == 5:  # Manual Name column
            ed = QLineEdit(parent)
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)
            return ed

        return super().createEditor(parent, option, index)

    def updateEditorGeometry(self, editor, option, index):
        view = option.widget if option else None
        if not view:
            p = self.parent()
            if isinstance(p, QAbstractItemView):
                view = p
        if view is not None and isinstance(editor, QLineEdit):
            editor.setGeometry(view.visualRect(index))
            return
        super().updateEditorGeometry(editor, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QLineEdit):
            val = index.data() or ""
            editor.setText(val)
            editor._initial_text = val
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            col = index.column()
            val = editor.text().strip()
            init_val = getattr(editor, '_initial_text', index.data() or "")

            if col in (2, 3):  # Internal Ledger: strictly validate against options
                if not val:
                    # User cleared cell -> unassign/clear
                    model.setData(index, "", Qt.ItemDataRole.EditRole)
                    return

                resolved = None
                if callable(self.resolve_int_callback):
                    resolved = self.resolve_int_callback(val)
                elif callable(self.get_int_options_callback):
                    opts = self.get_int_options_callback()
                    for opt in (opts or []):
                        if opt.strip().lower() == val.lower():
                            resolved = opt
                            break

                if resolved:
                    model.setData(index, resolved, Qt.ItemDataRole.EditRole)
                else:
                    # Not in the list! REJECT! Revert back to original value
                    editor.setText(init_val)
                    return

            elif col == 1:  # VAT Ledger: strictly validate against options
                if not val:
                    # VAT ledger cannot be empty
                    editor.setText(init_val)
                    return

                resolved = None
                if callable(self.resolve_vat_callback):
                    resolved = self.resolve_vat_callback(val)
                elif callable(self.get_vat_options_callback):
                    opts = self.get_vat_options_callback()
                    for opt in (opts or []):
                        if opt.strip().lower() == val.lower():
                            resolved = opt
                            break

                if resolved:
                    model.setData(index, resolved, Qt.ItemDataRole.EditRole)
                else:
                    # Not in the list! REJECT! Revert back to original value
                    editor.setText(init_val)
                    return

            else:
                model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class VatConfDelegate(UniversalCellDelegate):
    """Delegate for Vat Conf table:
    - Dynamic column resolution based on horizontal header labels
    - SN.: seamless centered QLineEdit
    - Did You Print / Get Back: seamless centered QLineEdit normalizing 1/0, Y/N, T/F
    - CRM: seamless QLineEdit with _TallyCompleter
    - Opening ? / Closing ?: right-aligned numeric QLineEdit
    """
    def __init__(self, get_crm_callback, parent=None):
        super().__init__(parent=parent)
        self.get_crm_callback = get_crm_callback

    def _commit_and_close(self, editor):
        table = self.parent()
        if not table or not hasattr(table, 'state'):
            p = editor.parent() if editor else None
            table = p if hasattr(p, 'state') else (getattr(p, 'parent', lambda: None)() if p else None)

        if table and hasattr(table, 'state') and table.state() != QAbstractItemView.State.EditingState:
            return

        try:
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
        except RuntimeError:
            pass

    def createEditor(self, parent, option, index):
        table = self.parent()
        if table and hasattr(table, '_can_edit') and not table._can_edit:
            return None

        col = index.column()
        header_text = ""
        if table:
            hi = table.horizontalHeaderItem(col)
            if hi:
                header_text = hi.text().strip().lower()

        ed = QLineEdit(parent)
        ed.setFrame(False)
        ed.setAutoFillBackground(True)
        ed.setStyleSheet(
            "QLineEdit { background: #ffffff; border: 1px solid #059669; "
            "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
        )
        ed.setTextMargins(0, 0, 0, 0)
        ed.setContentsMargins(0, 0, 0, 0)

        if header_text in ("sn.", "pan no.", "need print ?", "did you print", "get back", "need confirmation", "get confirmation"):
            ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif header_text in ("opening amount", "closing amount", "opening ?", "closing ?", "opening", "closing", "his opening", "his closing"):
            ed.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            ed.setAlignment(Qt.AlignmentFlag.AlignLeft)

        if header_text == "sn." and table:
            it = table.item(index.row(), col)
            if it:
                it._prev_sn = it.text().strip()

        if header_text in ("did you print", "get back", "get confirmation"):
            ed.setPlaceholderText("Y/N or 1/0")
        elif header_text == "crm":
            crms = self.get_crm_callback() or []
            completer = _TallyCompleter(crms, ed)
            completer.setMaxVisibleItems(10)
            completer.popup().setMinimumWidth(240)
            ed.setCompleter(completer)
            ed.textEdited.connect(completer.update_prefix)

            def _on_crm_activated(selected, e=ed, c=completer):
                c._typed_text = selected
                e.setText(selected)
                QTimer.singleShot(0, lambda: self._commit_and_close(e))

            completer.activated.connect(_on_crm_activated)

        return ed

    def updateEditorGeometry(self, editor, option, index):
        view = option.widget if option else None
        if not view:
            p = self.parent()
            if isinstance(p, QAbstractItemView):
                view = p
        if view is not None and isinstance(editor, QLineEdit):
            editor.setGeometry(view.visualRect(index))
            return
        super().updateEditorGeometry(editor, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QLineEdit):
            val = index.data() or ""
            editor.setText(val)
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            col = index.column()
            val = editor.text().strip()
            table = self.parent()
            header_text = ""
            if table:
                hi = table.horizontalHeaderItem(col)
                if hi:
                    header_text = hi.text().strip().lower()
            if header_text in ("did you print", "get back", "get confirmation"):
                val = normalize_yes_no(val)
            model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class WordWrapHeaderView(QHeaderView):
    """Header view with automatic text wrapping and centered bold text."""
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        opt.rect = rect
        opt.section = logicalIndex
        opt.text = ""  # We paint text ourselves with word wrap
        self.style().drawControl(QStyle.ControlElement.CE_Header, opt, painter, self)

        model = self.model()
        if model:
            val = model.headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole)
            if val:
                text_rect = rect.adjusted(4, 2, -4, -2)
                painter.setPen(QColor("#ffffff"))
                font = self.font()
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(
                    text_rect,
                    int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                    str(val)
                )
        painter.restore()

    def sizeHint(self):
        sz = super().sizeHint()
        return QSize(sz.width(), max(sz.height(), 46))


class VatConfTableWidget(QTableWidget):
    """QTableWidget with spacebar toggle for Did You Print, Get Back, and Get Confirmation."""
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.state() != QTableWidget.State.EditingState:
            col = self.currentColumn()
            row = self.currentRow()
            hi = self.horizontalHeaderItem(col) if col >= 0 else None
            header_text = hi.text().strip().lower() if hi else ""
            if header_text in ("did you print", "get back", "get confirmation") and row >= 0:
                item = self.item(row, col)
                if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    cur_val = (item.text() or "").strip()
                    new_val = "No" if cur_val.lower() in ("yes", "y", "1", "t", "true") else "Yes"
                    item.setText(new_val)
                    return
        super().keyPressEvent(event)


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically for balances and integer amounts."""
    def __init__(self, text: str = "", num_value: float = None):
        super().__init__(text)
        if num_value is not None:
            self.num_value = float(num_value)
        else:
            try:
                self.num_value = float(text.replace(",", "").strip())
            except Exception:
                self.num_value = 0.0

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.num_value < other.num_value
        try:
            val_other = float(other.text().replace(",", "").strip())
            return self.num_value < val_other
        except Exception:
            return super().__lt__(other)


class SnTableWidgetItem(NumericTableWidgetItem):
    """SN item that sorts numerically for cartoon numbers, preserving text and _prev_sn."""
    def __init__(self, text: str = ""):
        s = (text or "").strip()
        try:
            val = float(int(s)) if s.isdigit() else 999999999.0
        except Exception:
            val = 999999999.0
        super().__init__(s, val)
        self._prev_sn = s


class YesNoTableWidgetItem(QTableWidgetItem):
    """Sorts 'Yes' before 'No' (or blanks) in Ascending order."""
    def __init__(self, text: str = ""):
        super().__init__(text)

    def __lt__(self, other):
        def _rank(txt):
            t = (txt or "").strip().lower()
            if t == "yes":
                return 0
            if t == "no":
                return 1
            if t == "no need":
                return 2
            if t == "n/a":
                return 3
            return 4
        val_self = _rank(self.text())
        val_other = _rank(other.text() if other else "")
        if val_self != val_other:
            return val_self < val_other
        return super().__lt__(other)


class ExpAmountTableWidgetItem(NumericTableWidgetItem):
    """Editable numeric item for expected opening/closing that sorts by numeric value."""
    def __init__(self, text: str = ""):
        s = (text or "").strip()
        try:
            val = float(s.replace(",", ""))
        except Exception:
            val = 0.0
        super().__init__(s, val)


class _LedgerCellWidget(QWidget):
    """Cell container widget displaying ledger name, optional classification badge, and small '+' button."""
    def __init__(self, name: str, has_plus: bool = True, badge: str = "", placeholder: str = "", on_plus = None, can_edit: bool = True, text_color: str = "", parent=None):
        super().__init__(parent)
        self.can_edit = can_edit
        self._name = name or ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        display_name = name or placeholder
        self.lbl_name = QLabel(display_name)
        if placeholder and not name:
            self.lbl_name.setStyleSheet("color: #94a3b8; font-style: italic; font-size: 11px;")
        else:
            c_str = text_color or "#0f172a"
            self.lbl_name.setStyleSheet(f"color: {c_str}; font-size: 12px; font-weight: 500;")
        layout.addWidget(self.lbl_name, stretch=1)

        if badge:
            badge_color = "#4338ca" if badge.lower() == "cash sales" else "#b45309"
            badge_bg = "#e0e7ff" if badge.lower() == "cash sales" else "#fef3c7"
            lbl_badge = QLabel(f"[{badge}]")
            lbl_badge.setStyleSheet(f"""
                QLabel {{
                    background: {badge_bg};
                    color: {badge_color};
                    font-size: 10px;
                    font-weight: 700;
                    padding: 1px 5px;
                    border-radius: 3px;
                }}
            """)
            layout.addWidget(lbl_badge)

        if has_plus:
            self.btn_plus = QPushButton("+")
            self.btn_plus.setFixedSize(18, 18)
            self.btn_plus.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_plus.setStyleSheet("""
                QPushButton {
                    background: #f1f5f9;
                    color: #475569;
                    font-weight: bold;
                    font-size: 12px;
                    border: 1px solid #cbd5e1;
                    border-radius: 3px;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton:hover {
                    background: #059669;
                    color: #ffffff;
                    border-color: #059669;
                }
            """)
            if callable(on_plus):
                self.btn_plus.clicked.connect(on_plus)
            self.btn_plus.setEnabled(can_edit)
            self.btn_plus.setVisible(can_edit)
            layout.addWidget(self.btn_plus)

    def text(self) -> str:
        """Return the ledger name for export, printing, and clipboard."""
        return self._name or ""

    def set_editable(self, can_edit: bool):
        self.can_edit = can_edit
        if hasattr(self, 'btn_plus'):
            self.btn_plus.setEnabled(can_edit)
            self.btn_plus.setVisible(can_edit)


class MappingCellDelegate(QStyledItemDelegate):
    """Ultra-fast, zero-allocation delegate for Mapping table columns 1 & 2.
    Paints ledger names, classification badges, and interactive [+] buttons directly
    on the viewport canvas with 0 child QWidgets, eliminating UI thrash and flicker.
    """
    def __init__(self, on_plus_callback=None, parent=None):
        super().__init__(parent)
        self.on_plus_callback = on_plus_callback
        self.can_edit: bool = True
        self._hovered_row = -1
        self._hovered_col = -1

    def _get_plus_rect(self, option: QStyleOptionViewItem) -> QRect:
        btn_size = 18
        margin = 6
        x = option.rect.right() - btn_size - margin
        y = option.rect.top() + (option.rect.height() - btn_size) // 2
        return QRect(x, y, btn_size, btn_size)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        if option.widget and hasattr(option.widget, 'cellWidget'):
            if option.widget.cellWidget(index.row(), index.column()):
                return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 1. Background
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        is_selectable = bool(index.flags() & Qt.ItemFlag.ItemIsSelectable)
        is_selected = is_selectable and bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            painter.fillRect(option.rect, QColor("#e0f2fe"))
        elif bg:
            if isinstance(bg, QBrush):
                painter.fillRect(option.rect, bg)
            elif isinstance(bg, QColor):
                painter.fillRect(option.rect, bg)
            else:
                painter.fillRect(option.rect, QColor(bg))
        elif index.row() % 2 == 1:
            painter.fillRect(option.rect, QColor("#f8fafc"))
        else:
            painter.fillRect(option.rect, QColor("#ffffff"))

        # Selection border
        if is_selected:
            sel_pen = QPen(QColor("#059669"), 1.5)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(option.rect.adjusted(1, 1, -1, -1))

        # Data retrieval
        name = str(index.data(Qt.ItemDataRole.UserRole + 2) or index.data(Qt.ItemDataRole.DisplayRole) or "").strip()
        badge = str(index.data(Qt.ItemDataRole.UserRole + 3) or "").strip()
        has_plus = bool(index.data(Qt.ItemDataRole.UserRole + 4))
        placeholder = str(index.data(Qt.ItemDataRole.UserRole + 5) or "").strip()
        is_merged = bool(index.data(Qt.ItemDataRole.UserRole + 6))

        # 2. Draw '+' Button if editable and cell has_plus
        plus_rect = self._get_plus_rect(option)
        show_plus = self.can_edit and has_plus
        if show_plus:
            is_hover = (index.row() == self._hovered_row and index.column() == self._hovered_col)
            btn_bg = QColor("#059669") if is_hover else QColor("#f1f5f9")
            btn_border = QColor("#047857") if is_hover else QColor("#cbd5e1")
            plus_color = QColor("#ffffff") if is_hover else QColor("#475569")

            painter.setPen(QPen(btn_border, 1))
            painter.setBrush(QBrush(btn_bg))
            painter.drawRoundedRect(plus_rect, 3, 3)

            # Draw '+' symbol
            painter.setPen(QPen(plus_color, 2))
            cx = plus_rect.center().x()
            cy = plus_rect.center().y()
            painter.drawLine(cx - 4, cy, cx + 4, cy)
            painter.drawLine(cx, cy - 4, cx, cy + 4)

        # 3. Draw Badges (Classification) - never tag in Column 1 (VAT Ledger Name), and no badges for Cash Sales / Old Party
        badge_right = plus_rect.left() - 6 if show_plus else option.rect.right() - 6
        badges_to_draw = []
        if badge and index.column() != 1 and badge.lower() not in ("cash sales", "old party"):
            b_fg = "#4338ca"
            b_bg = "#e0e7ff"
            badges_to_draw.append((f"[{badge}]", b_fg, b_bg))

        if badges_to_draw:
            b_font = QFont(option.font)
            b_font.setPointSize(9)
            b_font.setBold(True)
            painter.setFont(b_font)
            fm = painter.fontMetrics()

            for badge_text, fg_col, bg_col in badges_to_draw:
                bw = fm.horizontalAdvance(badge_text) + 10
                bh = 18
                bx = badge_right - bw
                by = option.rect.top() + (option.rect.height() - bh) // 2
                b_rect = QRect(bx, by, bw, bh)

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(bg_col)))
                painter.drawRoundedRect(b_rect, 3, 3)
                painter.setPen(QPen(QColor(fg_col)))
                painter.drawText(b_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
                badge_right = bx - 4

        text_max_right = badge_right - 2

        # 4. Draw Name / Placeholder Text
        text_rect = QRect(
            option.rect.left() + 8,
            option.rect.top(),
            max(text_max_right - (option.rect.left() + 8), 10),
            option.rect.height()
        )

        if not name and placeholder:
            p_font = QFont(option.font)
            p_font.setPointSize(9)
            p_font.setItalic(True)
            painter.setFont(p_font)
            painter.setPen(QPen(QColor("#94a3b8")))
            elided = painter.fontMetrics().elidedText(placeholder, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        elif name:
            t_font = QFont(option.font)
            t_font.setPointSize(9)
            t_font.setBold(False)
            painter.setFont(t_font)
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            if is_selected:
                painter.setPen(QPen(QColor("#0f172a")))
            elif fg:
                if isinstance(fg, QColor):
                    painter.setPen(QPen(fg))
                elif isinstance(fg, QBrush):
                    painter.setPen(QPen(fg.color()))
                else:
                    painter.setPen(QPen(QColor(fg)))
            else:
                painter.setPen(QPen(QColor("#0f172a")))

            elided = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not self.can_edit:
            return super().editorEvent(event, model, option, index)

        has_plus = bool(index.data(Qt.ItemDataRole.UserRole + 4))
        if not has_plus:
            return super().editorEvent(event, model, option, index)

        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            pos = event.position().toPoint()
            plus_rect = self._get_plus_rect(option)
            if plus_rect.contains(pos):
                if self._hovered_row != index.row() or self._hovered_col != index.column():
                    self._hovered_row = index.row()
                    self._hovered_col = index.column()
                    if option.widget:
                        option.widget.setCursor(Qt.CursorShape.PointingHandCursor)
                        option.widget.viewport().update()
            else:
                if self._hovered_row == index.row() and self._hovered_col == index.column():
                    self._hovered_row = -1
                    self._hovered_col = -1
                    if option.widget:
                        option.widget.unsetCursor()
                        option.widget.viewport().update()

        elif event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                plus_rect = self._get_plus_rect(option)
                if plus_rect.contains(pos):
                    if option.widget:
                        option.widget.clearSelection()
                        option.widget.setCurrentItem(None)
                    return True

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                plus_rect = self._get_plus_rect(option)
                if plus_rect.contains(pos):
                    if option.widget:
                        option.widget.clearSelection()
                        option.widget.setCurrentItem(None)
                    if callable(self.on_plus_callback):
                        group_id = index.data(Qt.ItemDataRole.UserRole)
                        cb = self.on_plus_callback
                        r, c = index.row(), index.column()
                        QTimer.singleShot(0, lambda: cb(r, c, group_id))
                    return True

        return super().editorEvent(event, model, option, index)


class MappingTableWidget(QTableWidget):
    """QTableWidget with keyboard shortcuts and visual grouping for Mapping table:
    - Delete / Backspace on Col 2 (Internal Ledger): removes that internal ledger from group
    - Delete / Backspace on Col 1 (VAT Ledger): if merged, removes VAT ledger from group
    - Delete / Backspace on Col 0 / row selection: unmaps the entire group
    - Renders combined VAT ledger names inside a unified box with dark borders
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._combined_group_ranges = []

    def paintEvent(self, event):
        super().paintEvent(event)
        if hasattr(self, '_combined_group_ranges') and self._combined_group_ranges:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            v_rect = self.viewport().rect()
            col_count = self.columnCount()

            for item in self._combined_group_ranges:
                if len(item) == 5:
                    start_row, n_rows, bg_col, border_col, accent_col = item
                else:
                    start_row, n_rows, bg_col, border_col = item
                    accent_col = border_col

                if n_rows <= 1 or self.isRowHidden(start_row) or col_count == 0:
                    continue

                # 1. Geometry of the entire group card spanning Column 0 to Column col_count - 1
                top_rect_c0 = self.visualRect(self.model().index(start_row, 0))
                bot_rect_last = self.visualRect(self.model().index(start_row + n_rows - 1, col_count - 1))
                if not top_rect_c0.isValid() or not bot_rect_last.isValid():
                    continue
                if top_rect_c0.width() == 0 or bot_rect_last.width() == 0:
                    continue

                group_left = top_rect_c0.left()
                group_top = top_rect_c0.top()
                group_right = bot_rect_last.right()
                group_bottom = bot_rect_last.bottom()
                group_rect = QRect(group_left, group_top, group_right - group_left + 1, group_bottom - group_top + 1)

                if not group_rect.intersects(v_rect):
                    continue

                # 2. Inner Dividers:
                # - Shared columns (0: S.No, 5: Balance, 6: Negative, 7: Narration):
                #   Erase inner horizontal dividers so these fields seamlessly span the full group height
                # - Split columns (1: VAT Ledger, 2: Int Ledger, 3: Vat Closing, 4: Int Closing):
                #   Draw subtle, clean 1px divider in #cbd5e1 so itemized lines are easy to read
                shared_cols = (0, 5, 6, 7)
                split_cols = (1, 2, 3, 4)

                for k in range(n_rows - 1):
                    r = start_row + k
                    next_r = r + 1

                    is_r_sel = self.selectionModel().isRowSelected(r, self.rootIndex()) if self.selectionModel() else False
                    is_next_sel = self.selectionModel().isRowSelected(next_r, self.rootIndex()) if self.selectionModel() else False

                    if is_r_sel and is_next_sel:
                        erase_fill = QColor("#e0f2fe")
                    elif not is_r_sel and not is_next_sel:
                        erase_fill = bg_col
                    else:
                        erase_fill = None

                    # Erase on shared columns
                    if erase_fill:
                        for c in shared_cols:
                            if c < col_count:
                                r_rect = self.visualRect(self.model().index(r, c))
                                if r_rect.isValid() and r_rect.width() > 0 and r_rect.intersects(v_rect):
                                    erase_rect = QRect(r_rect.left(), r_rect.bottom() - 1, r_rect.width(), 2)
                                    painter.fillRect(erase_rect, erase_fill)

                    # Subtle clean divider on split columns
                    divider_col = QColor("#bae6fd") if (is_r_sel and is_next_sel) else QColor("#cbd5e1")
                    for c in split_cols:
                        if c < col_count:
                            r_rect = self.visualRect(self.model().index(r, c))
                            if r_rect.isValid() and r_rect.width() > 0 and r_rect.intersects(v_rect):
                                divider_rect = QRect(r_rect.left() + 1, r_rect.bottom(), r_rect.width() - 2, 1)
                                painter.fillRect(divider_rect, divider_col)

                # 3. Draw Full-Width Group Outer Perimeter Frame across all columns (2.5px solid dark border)
                pen = QPen(border_col, 2.5)
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(group_rect.adjusted(1, 1, -1, -1))

                # 4. Draw 5px Left Accent Bar on Column 0
                accent_rect = QRect(group_rect.left() + 1, group_rect.top() + 1, 5, group_rect.height() - 2)
                if accent_rect.intersects(v_rect):
                    painter.fillRect(accent_rect, accent_col)

            painter.end()

    def mousePressEvent(self, event):
        parent_ui = getattr(self, '_parent_ui', None)
        staged_gid = getattr(parent_ui, '_staged_group_id', None) if parent_ui else None
        if staged_gid is not None:
            pos = event.position().toPoint()
            idx = self.indexAt(pos)
            if idx.isValid():
                it = self.item(idx.row(), 0)
                clicked_gid = it.data(Qt.ItemDataRole.UserRole) if it else None
                try:
                    is_diff = (clicked_gid is not None) and (int(clicked_gid) != int(staged_gid))
                except (ValueError, TypeError):
                    is_diff = (clicked_gid != staged_gid)

                if is_diff and parent_ui and hasattr(parent_ui, 'destage_and_select'):
                    parent_ui.destage_and_select(clicked_gid, idx.column())
                    return
            else:
                if parent_ui and hasattr(parent_ui, 'destage_and_select'):
                    parent_ui.destage_and_select(None)
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        parent_ui = getattr(self, '_parent_ui', None)
        staged_gid = getattr(parent_ui, '_staged_group_id', None) if parent_ui else None

        if staged_gid is not None and event.key() in (
            Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
            Qt.Key.Key_Home, Qt.Key.Key_End
        ):
            cur_r = self.currentRow()
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                target_r = cur_r + step
                while 0 <= target_r < self.rowCount() and self.isRowHidden(target_r):
                    target_r += step

                target_gid = None
                if 0 <= target_r < self.rowCount():
                    it = self.item(target_r, 0)
                    target_gid = it.data(Qt.ItemDataRole.UserRole) if it else None

                try:
                    is_same_group = (target_gid is not None) and (int(target_gid) == int(staged_gid))
                except (ValueError, TypeError):
                    is_same_group = (target_gid == staged_gid)

                # If moving inside the same multi-row group, allow normal row movement
                if is_same_group:
                    super().keyPressEvent(event)
                    return

                # Navigating outside the staged group: commit move to permanent sorted position
                if parent_ui and hasattr(parent_ui, 'destage_and_select'):
                    parent_ui.destage_and_select(target_gid)
                    return
            else:
                # PageUp / PageDown / Home / End navigates away from the staged group
                if parent_ui and hasattr(parent_ui, 'destage_and_select'):
                    parent_ui.destage_and_select(None)
                    super().keyPressEvent(event)
                    return

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state() != QTableWidget.State.EditingState:
            if parent_ui and getattr(self, '_can_edit', True):
                cur_r = self.currentRow()
                cur_c = self.currentColumn()
                if cur_r >= 0 and cur_c != 7:
                    it0 = self.item(cur_r, 0)
                    gid = it0.data(Qt.ItemDataRole.UserRole) if it0 else 0
                    if gid:
                        col_to_open = 1 if cur_c == 1 else 2
                        parent_ui._on_mapping_plus_clicked(cur_r, col_to_open, gid)
                        return

        if event.key() == Qt.Key.Key_Escape and staged_gid is not None:
            if parent_ui and hasattr(parent_ui, 'destage_and_select'):
                parent_ui.destage_and_select(None)
                return

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.state() != QTableWidget.State.EditingState:
            if getattr(self, '_can_edit', True):
                selected_indexes = self.selectedIndexes()
                if selected_indexes:
                    selected_rows = sorted(list({idx.row() for idx in selected_indexes}))
                    selected_cols = {idx.column() for idx in selected_indexes}
                    parent_ui = getattr(self, '_parent_ui', None)
                    if selected_cols == {2} and parent_ui:
                        # Col 2 is Internal Ledger
                        for r in selected_rows:
                            it2 = self.item(r, 2)
                            i_name = str(it2.data(Qt.ItemDataRole.UserRole + 2) or it2.text()).strip() if it2 else ""
                            it0 = self.item(r, 0)
                            gid = it0.data(Qt.ItemDataRole.UserRole) if it0 else 0
                            if i_name and gid:
                                remove_internal_ledger_from_group(parent_ui.db_name, parent_ui.active_vat_company, gid, i_name)
                        parent_ui.refresh_mapping_table()
                        return
                    elif selected_cols == {1} and parent_ui:
                        # Col 1 is VAT Ledger
                        for r in selected_rows:
                            it1 = self.item(r, 1)
                            v_name = str(it1.data(Qt.ItemDataRole.UserRole + 2) or it1.text()).strip() if it1 else ""
                            if v_name.startswith("↳ "):
                                v_name = v_name[2:].strip()
                            it0 = self.item(r, 0)
                            gid = it0.data(Qt.ItemDataRole.UserRole) if it0 else 0
                            if v_name and gid:
                                remove_vat_ledger_from_group(parent_ui.db_name, parent_ui.active_vat_company, gid, v_name)
                        parent_ui.refresh_mapping_table()
                        return
                    else:
                        if parent_ui and hasattr(parent_ui, '_unmap_selected_mapping'):
                            parent_ui._unmap_selected_mapping()
                            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self.currentRow() < 0 and self.rowCount() > 0:
                self.selectRow(0)
                self.setCurrentCell(0, 0)
        super().keyPressEvent(event)


TABLE_WITH_FOOTER_STYLE = UNIVERSAL_TABLE_STYLE + """
QTableWidget {
    border-bottom: none;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
"""

FOOTER_TABLE_STYLE = """
QTableWidget {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-top: 2px solid #059669;
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 0px;
    gridline-color: #64748b;
    font-family: 'Noto Sans Devanagari', 'Segoe UI', sans-serif;
    font-size: 10pt;
}
QTableWidget::item {
    padding: 2px 4px;
    font-weight: bold;
    color: #0f172a;
}
"""


class TableFooterWidget(QTableWidget):
    """Pinned single-row footer table displaying column-aligned grand totals."""

    def __init__(self, main_table: QTableWidget, parent=None):
        super().__init__(1, main_table.columnCount(), parent)
        self.main_table = main_table
        self.setStyleSheet(FOOTER_TABLE_STYLE)
        self.setFixedHeight(30)
        self.setRowHeight(0, 28)
        self.horizontalHeader().setVisible(False)
        self.verticalHeader().setVisible(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        # Synchronize horizontal scrolling
        self.main_table.horizontalScrollBar().valueChanged.connect(
            self.horizontalScrollBar().setValue
        )
        self.main_table.horizontalScrollBar().rangeChanged.connect(
            lambda min_v, max_v: self.horizontalScrollBar().setRange(min_v, max_v)
        )

        # Synchronize column resize
        self.main_table.horizontalHeader().sectionResized.connect(
            self._on_section_resized
        )

        # Synchronize column movement if applicable
        self.main_table.horizontalHeader().sectionMoved.connect(
            self._on_section_moved
        )

        self.sync_columns()

    def _on_section_resized(self, logical_index: int, old_size: int, new_size: int):
        self.setColumnWidth(logical_index, new_size)

    def _on_section_moved(self, logical_index: int, old_visual: int, new_visual: int):
        self.horizontalHeader().moveSection(old_visual, new_visual)

    def sync_columns(self):
        self.blockSignals(True)
        col_count = self.main_table.columnCount()
        self.setColumnCount(col_count)
        for c in range(col_count):
            self.setColumnWidth(c, self.main_table.columnWidth(c))
            self.setColumnHidden(c, self.main_table.isColumnHidden(c))
        self.horizontalScrollBar().setValue(self.main_table.horizontalScrollBar().value())
        self.blockSignals(False)

    def wheelEvent(self, event):
        self.main_table.wheelEvent(event)

    def update_totals(self, col_values: dict[int, str], label_col: int = 0, label_text: str = "Grand Total"):
        """Populate column totals.

        col_values: {col_index: formatted_string}
        """
        self.blockSignals(True)
        col_count = self.columnCount()
        for c in range(col_count):
            item = self.item(0, c)
            if not item:
                item = QTableWidgetItem()
                self.setItem(0, c, item)

            item.setFont(QFont("Noto Sans Devanagari", 9, QFont.Weight.Bold))

            if c == label_col:
                item.setText(label_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor("#0f172a"))
            elif c in col_values:
                item.setText(col_values[c])
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor("#047857"))
            else:
                item.setText("")
        self.blockSignals(False)


class TableFooterContainer(QWidget):
    """Container holding TableFooterWidget with a right-hand spacer that dynamically
    matches the width of the main table's vertical scrollbar to guarantee exact
    column alignment.
    """

    def __init__(self, main_table: QTableWidget, footer: TableFooterWidget, parent=None):
        super().__init__(parent)
        self.main_table = main_table
        self.footer = footer

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(footer, stretch=1)

        self.spacer = QWidget()
        self.spacer.setFixedWidth(0)
        self.spacer.setFixedHeight(30)
        self.spacer.setStyleSheet("""
            background-color: #f8fafc;
            border-top: 2px solid #059669;
            border-bottom: 1px solid #cbd5e1;
            border-right: 1px solid #cbd5e1;
            border-bottom-right-radius: 6px;
        """)
        self.spacer.hide()
        layout.addWidget(self.spacer)

        # Connect vertical scrollbar changes
        main_table.verticalScrollBar().rangeChanged.connect(self._sync_spacer)
        main_table.installEventFilter(self)

    def _sync_spacer(self, *args):
        sb = self.main_table.verticalScrollBar()
        if sb.isVisible() and sb.maximum() > 0:
            w = sb.width()
            if w <= 0:
                w = sb.sizeHint().width()
            self.spacer.setFixedWidth(max(w, 0))
            self.spacer.show()
        else:
            self.spacer.setFixedWidth(0)
            self.spacer.hide()

    def eventFilter(self, obj, event):
        if obj == self.main_table:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                QTimer.singleShot(0, self._sync_spacer)
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_spacer()
        if hasattr(self, 'footer'):
            self.footer.sync_columns()


# ─── MAIN BALANCE SCREEN ─────────────────────────────────────────────────────

class BalanceUI(QWidget):
    """Main Balance page for VAT Working.

    The 4 views (Int. Ledger, Vat Ledger, Mapping, Vat Conf.) are switched
    directly via the left panel sidebar menu.
    """
    def __init__(self):
        super().__init__()
        self.setObjectName("BalanceContainer")
        self.db = get_db_manager()
        self.current_company_path = ""
        self.current_company_name = ""
        self.db_name = ""
        self.active_vat_company = ""
        self._can_edit = True
        self._can_clear_mapping = True
        self._security_mgr = None
        self._load_worker = None          # background data fetch thread
        self._last_loaded_path = None     # dedup guard: skip reload if path unchanged
        self._loading_path = None         # tracks path currently being fetched
        self._cached_data = {}            # cached data for lazy tab rendering
        self._rendered_tabs = set()       # set of tab keys that have been rendered
        self._int_lookup = {}             # norm_key -> canonical_name
        self._int_alias_map = {}          # norm_name_key -> alias
        self._int_options = []            # list of names and aliases for completer
        self._vat_lookup = {}             # norm_key -> canonical_name
        self._vat_alias_map = {}          # norm_name_key -> alias
        self._vat_options = []            # list of names and aliases for completer
        self._mapping_refresh_worker = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── Main Tabs (inside screen) ──────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("BalanceTabs")
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cbd5e1;
                background: #ffffff;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background: #f1f5f9;
                color: #475569;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #cbd5e1;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f172a;
                font-weight: 700;
                border-bottom: 2px solid #059669;
            }
            QTabBar::tab:hover:!selected {
                background: #e2e8f0;
                color: #1e293b;
            }
        """)

        # Tab 0: Int. Ledger
        self.int_ledger_widget = self._create_int_ledger_tab()
        self.tabs.addTab(self.int_ledger_widget, "Int. Ledger")

        # Sync button logo to the right of Int. Ledger tab
        self.btn_tab_sync_int = QPushButton()
        self.btn_tab_sync_int.setObjectName("TabSyncIntBtn")
        self.btn_tab_sync_int.setIcon(get_icon("sync.svg"))
        self.btn_tab_sync_int.setIconSize(QSize(15, 15))
        self.btn_tab_sync_int.setFixedSize(22, 22)
        self.btn_tab_sync_int.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_sync_int.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                padding: 0px;
                margin-left: 2px;
                margin-right: 4px;
            }
            QPushButton:hover {
                background: #e2e8f0;
                border-radius: 11px;
            }
        """)
        self.btn_tab_sync_int.clicked.connect(self.sync_int_ledger)
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, self.btn_tab_sync_int)

        # Tab 1: Vat Ledger (includes active VAT company config)
        self.vat_ledger_widget = self._create_vat_ledger_tab()
        self.tabs.addTab(self.vat_ledger_widget, "Vat Ledger")

        # Sync button logo to the right of Vat Ledger tab
        self.btn_tab_sync_vat = QPushButton()
        self.btn_tab_sync_vat.setObjectName("TabSyncVatBtn")
        self.btn_tab_sync_vat.setIcon(get_icon("sync.svg"))
        self.btn_tab_sync_vat.setIconSize(QSize(15, 15))
        self.btn_tab_sync_vat.setFixedSize(22, 22)
        self.btn_tab_sync_vat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_sync_vat.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                padding: 0px;
                margin-left: 2px;
                margin-right: 4px;
            }
            QPushButton:hover {
                background: #e2e8f0;
                border-radius: 11px;
            }
        """)
        self.btn_tab_sync_vat.clicked.connect(self.sync_vat_ledger)
        self.tabs.tabBar().setTabButton(1, QTabBar.ButtonPosition.RightSide, self.btn_tab_sync_vat)

        # Tab 2: Mapping (clean, uncluttered, unmatched in red at top)
        self.mapping_widget = self._create_mapping_tab()
        self.tabs.addTab(self.mapping_widget, "Mapping")

        # Tab 3: Vat Conf. (with Debtor and Creditor sub-tabs)
        self.vat_conf_widget = self._create_vat_conf_tab()
        self.tabs.addTab(self.vat_conf_widget, "Vat Conf.")

        # Tab 4: Empty Ledger (to the right of Vat Conf.)
        self.empty_ledger_widget = self._create_empty_ledger_tab()
        self.tabs.addTab(self.empty_ledger_widget, "Empty Ledger")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, stretch=1)

    def _create_vat_conf_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(6)

        self.conf_tabs = QTabWidget()
        self.conf_tabs.setObjectName("VatConfTabs")
        self.conf_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #e2e8f0;
                background: #ffffff;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background: #f8fafc;
                color: #64748b;
                font-weight: 600;
                font-size: 12px;
                padding: 6px 16px;
                margin-right: 3px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                border: 1px solid #e2e8f0;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f172a;
                font-weight: 700;
                border-bottom: 2px solid #059669;
            }
            QTabBar::tab:hover:!selected {
                background: #f1f5f9;
                color: #334155;
            }
        """)

        self.debtor_widget = self._create_debtor_tab()
        self.conf_tabs.addTab(self.debtor_widget, "Debtor")

        self.creditor_widget = self._create_creditor_tab()
        self.conf_tabs.addTab(self.creditor_widget, "Creditor")

        self.conf_tabs.currentChanged.connect(self._on_conf_tab_changed)
        vbox.addWidget(self.conf_tabs, stretch=1)
        return widget

    def set_current_view(self, index: int):
        """Switch active tab (0: Int, 1: Vat, 2: Mapping, 3: Debtor, 4: Creditor, 5: Empty Ledger)."""
        if index in (0, 1, 2):
            self.tabs.setCurrentIndex(index)
        elif index == 3:
            self.tabs.setCurrentIndex(3)
            if hasattr(self, 'conf_tabs'):
                self.conf_tabs.setCurrentIndex(0)
        elif index == 4:
            self.tabs.setCurrentIndex(3)
            if hasattr(self, 'conf_tabs'):
                self.conf_tabs.setCurrentIndex(1)
        elif index == 5:
            self.tabs.setCurrentIndex(4)
        self._render_current_tab()

    def _update_options_cache(self, int_debtors: list = None, vat_debtors: list = None):
        """Pre-cache autocomplete options and canonical lookup maps in memory for fast UI interaction."""
        if int_debtors is not None:
            self._int_lookup.clear()
            self._int_alias_map.clear()
            opts = set()
            for d in int_debtors:
                name = str(d.get("Name") or "").strip()
                alias = str(d.get("Alias") or "").strip()
                if name.lower() in ("none", "nan", "null"):
                    name = ""
                if alias.lower() in ("none", "nan", "null"):
                    alias = ""
                if name:
                    nk = " ".join(name.split()).lower()
                    self._int_lookup[nk] = name
                    self._int_lookup[_norm(name)] = name
                    opts.add(name)
                    if alias and alias.lower() != name.lower():
                        ak = " ".join(alias.split()).lower()
                        self._int_lookup[ak] = name
                        self._int_lookup[_norm(alias)] = name
                        self._int_alias_map[nk] = alias
                        combo = f"{name} ({alias})"
                        opts.add(combo)
                        opts.add(alias)
                        self._int_lookup[" ".join(combo.split()).lower()] = name
                        self._int_lookup[_norm(combo)] = name
                        self._int_lookup[" ".join(f"{name} [{alias}]".split()).lower()] = name
                        self._int_lookup[" ".join(f"{alias} - {name}".split()).lower()] = name
                        self._int_lookup[" ".join(f"{name} - {alias}".split()).lower()] = name
                        self._int_lookup[" ".join(f"{alias} ({name})".split()).lower()] = name
            self._int_options = sorted(list(opts), key=lambda x: x.lower())

        if vat_debtors is not None:
            self._vat_lookup.clear()
            self._vat_alias_map.clear()
            opts = set()
            for d in vat_debtors:
                name = str(d.get("Name") or "").strip()
                alias = str(d.get("Alias") or "").strip()
                if name.lower() in ("none", "nan", "null"):
                    name = ""
                if alias.lower() in ("none", "nan", "null"):
                    alias = ""
                if name:
                    nk = " ".join(name.split()).lower()
                    self._vat_lookup[nk] = name
                    self._vat_lookup[_norm(name)] = name
                    opts.add(name)
                    if alias and alias.lower() != name.lower():
                        ak = " ".join(alias.split()).lower()
                        self._vat_lookup[ak] = name
                        self._vat_lookup[_norm(alias)] = name
                        self._vat_alias_map[nk] = alias
                        combo = f"{name} ({alias})"
                        opts.add(combo)
                        opts.add(alias)
                        self._vat_lookup[" ".join(combo.split()).lower()] = name
                        self._vat_lookup[_norm(combo)] = name
                        self._vat_lookup[" ".join(f"{name} [{alias}]".split()).lower()] = name
                        self._vat_lookup[" ".join(f"{alias} - {name}".split()).lower()] = name
                        self._vat_lookup[" ".join(f"{name} - {alias}".split()).lower()] = name
                        self._vat_lookup[" ".join(f"{alias} ({name})".split()).lower()] = name
            self._vat_options = sorted(list(opts), key=lambda x: x.lower())

    def resolve_int_ledger(self, text: str) -> str | None:
        """Resolve typed text (name, alias, or combination) to canonical internal debtor Name."""
        if not text:
            return None
        t_clean = text.strip()
        t_lower = t_clean.lower()
        if t_lower in ("cash sales", "old party"):
            return "Cash Sales" if t_lower == "cash sales" else "Old Party"
        if not self._int_lookup and self.db_name:
            self._get_internal_ledger_options()

        k = " ".join(t_clean.split()).lower()
        if k in self._int_lookup:
            return self._int_lookup[k]

        kn = _norm(t_clean)
        if kn in self._int_lookup:
            return self._int_lookup[kn]

        # Handle 'Name (Alias)' or 'Alias (Name)'
        if '(' in t_clean and ')' in t_clean:
            before = t_clean[:t_clean.rfind('(')].strip()
            inside = t_clean[t_clean.rfind('(')+1:t_clean.rfind(')')].strip()
            for cand in (before, inside):
                ck = " ".join(cand.split()).lower()
                if ck in self._int_lookup:
                    return self._int_lookup[ck]
                if _norm(cand) in self._int_lookup:
                    return self._int_lookup[_norm(cand)]

        # Handle 'Name [Alias]' or 'Alias [Name]'
        if '[' in t_clean and ']' in t_clean:
            before = t_clean[:t_clean.rfind('[')].strip()
            inside = t_clean[t_clean.rfind('[')+1:t_clean.rfind(']')].strip()
            for cand in (before, inside):
                ck = " ".join(cand.split()).lower()
                if ck in self._int_lookup:
                    return self._int_lookup[ck]
                if _norm(cand) in self._int_lookup:
                    return self._int_lookup[_norm(cand)]

        # Handle 'Name - Alias' or 'Alias - Name'
        if ' - ' in t_clean:
            parts = [p.strip() for p in t_clean.split(' - ') if p.strip()]
            for cand in parts:
                ck = " ".join(cand.split()).lower()
                if ck in self._int_lookup:
                    return self._int_lookup[ck]
                if _norm(cand) in self._int_lookup:
                    return self._int_lookup[_norm(cand)]

        return None

    def resolve_vat_ledger(self, text: str) -> str | None:
        """Resolve typed text (name, alias, or combination) to canonical VAT debtor Name."""
        if not text:
            return None
        t_clean = text.strip()
        if t_clean.startswith("↳ "):
            t_clean = t_clean[2:].strip()
        if not self._vat_lookup and self.db_name and self.active_vat_company:
            self._get_vat_ledger_options()

        k = " ".join(t_clean.split()).lower()
        if k in self._vat_lookup:
            return self._vat_lookup[k]

        kn = _norm(t_clean)
        if kn in self._vat_lookup:
            return self._vat_lookup[kn]

        # Handle 'Name (Alias)' or 'Alias (Name)'
        if '(' in t_clean and ')' in t_clean:
            before = t_clean[:t_clean.rfind('(')].strip()
            inside = t_clean[t_clean.rfind('(')+1:t_clean.rfind(')')].strip()
            for cand in (before, inside):
                ck = " ".join(cand.split()).lower()
                if ck in self._vat_lookup:
                    return self._vat_lookup[ck]
                if _norm(cand) in self._vat_lookup:
                    return self._vat_lookup[_norm(cand)]

        # Handle 'Name [Alias]' or 'Alias [Name]'
        if '[' in t_clean and ']' in t_clean:
            before = t_clean[:t_clean.rfind('[')].strip()
            inside = t_clean[t_clean.rfind('[')+1:t_clean.rfind(']')].strip()
            for cand in (before, inside):
                ck = " ".join(cand.split()).lower()
                if ck in self._vat_lookup:
                    return self._vat_lookup[ck]
                if _norm(cand) in self._vat_lookup:
                    return self._vat_lookup[_norm(cand)]

        # Handle 'Name - Alias' or 'Alias - Name'
        if ' - ' in t_clean:
            parts = [p.strip() for p in t_clean.split(' - ') if p.strip()]
            for cand in parts:
                ck = " ".join(cand.split()).lower()
                if ck in self._vat_lookup:
                    return self._vat_lookup[ck]
                if _norm(cand) in self._vat_lookup:
                    return self._vat_lookup[_norm(cand)]

        return None

    def _get_internal_ledger_options(self) -> list[str]:
        """Return cached list of internal debtor names and aliases for mapping autocomplete."""
        if self._int_options:
            return self._int_options
        if not self.db_name:
            return []
        try:
            debtors = load_internal_debtors(self.db_name)
            self._update_options_cache(int_debtors=debtors)
            return self._int_options
        except Exception:
            return []

    def _get_vat_ledger_options(self) -> list[str]:
        """Return cached list of VAT debtor names and aliases for mapping autocomplete."""
        if self._vat_options:
            return self._vat_options
        if not self.db_name or not self.active_vat_company:
            return []
        try:
            debtors = load_vat_debtors(self.db_name, self.active_vat_company)
            self._update_options_cache(vat_debtors=debtors)
            return self._vat_options
        except Exception:
            return []

    # ── TAB / VIEW CREATION HELPERS ──────────────────────────────────

    def _create_int_ledger_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Search + Sync
        # Top Bar: Search + Sync + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("Internal Ledger")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_int_count = QLabel("")
        self.lbl_int_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.int_search = QLineEdit()
        self.int_search.setPlaceholderText("Search name or alias...")
        self.int_search.setFixedWidth(220)
        self.int_search.textChanged.connect(self._filter_int_table)

        self.btn_sync_int = QPushButton("Sync Int. Ledger")
        self.btn_sync_int.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600;
                border: none; border-radius: 4px; padding: 6px 14px;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_sync_int.clicked.connect(self.sync_int_ledger)

        self.btn_cols_int = QPushButton("Columns ⚙")
        self.btn_cols_int.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_cols_int.clicked.connect(self.open_column_settings_dialog)

        self.btn_toggle_int_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_int_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_int_alias.clicked.connect(self._toggle_ledger_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_int_count)
        top_bar.addStretch()
        top_bar.addWidget(self.int_search)
        top_bar.addWidget(self.btn_toggle_int_alias)
        top_bar.addWidget(self.btn_cols_int)
        top_bar.addWidget(self.btn_sync_int)
        vbox.addLayout(top_bar)

        # Table with all authentic columns from Tally Ledger Rows
        self.int_table = QTableWidget()
        self.int_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.int_table.setAlternatingRowColors(True)
        self.int_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.int_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.int_table.verticalHeader().setVisible(False)
        self.int_table.setItemDelegate(UniversalCellDelegate(self.int_table))
        self.int_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.int_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        headers = [c[1] for c in TALLY_LEDGER_COLUMNS]
        self.int_table.setColumnCount(len(headers))
        self.int_table.setHorizontalHeaderLabels(headers)

        header = self.int_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionDoubleClicked.connect(
            lambda idx: self._on_generic_header_double_clicked(self.int_table, idx, self._update_int_totals)
        )
        for idx, col in enumerate(TALLY_LEDGER_COLUMNS):
            self.int_table.setColumnWidth(idx, col[2])

        self.int_footer = TableFooterWidget(self.int_table)
        self.int_footer_container = TableFooterContainer(self.int_table, self.int_footer)

        self.apply_column_visibility()

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.int_table, stretch=1)
        table_layout.addWidget(self.int_footer_container)

        vbox.addWidget(table_container, stretch=1)
        return widget

    def _create_vat_ledger_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Search + Sync + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("VAT Ledger")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_vat_count = QLabel("")
        self.lbl_vat_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.vat_search = QLineEdit()
        self.vat_search.setPlaceholderText("Search name or alias...")
        self.vat_search.setFixedWidth(220)
        self.vat_search.textChanged.connect(self._filter_vat_table)

        self.btn_sync_vat = QPushButton("Sync Vat Ledger")
        self.btn_sync_vat.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600;
                border: none; border-radius: 4px; padding: 6px 14px;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_sync_vat.clicked.connect(self.sync_vat_ledger)

        self.btn_cols_vat = QPushButton("Columns ⚙")
        self.btn_cols_vat.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_cols_vat.clicked.connect(self.open_column_settings_dialog)

        self.btn_toggle_vat_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_vat_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_vat_alias.clicked.connect(self._toggle_ledger_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_vat_count)
        top_bar.addStretch()
        top_bar.addWidget(self.vat_search)
        top_bar.addWidget(self.btn_toggle_vat_alias)
        top_bar.addWidget(self.btn_cols_vat)
        top_bar.addWidget(self.btn_sync_vat)
        vbox.addLayout(top_bar)

        # Table with all authentic columns from Tally Ledger Rows
        self.vat_table = QTableWidget()
        self.vat_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.vat_table.setAlternatingRowColors(True)
        self.vat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.vat_table.verticalHeader().setVisible(False)
        self.vat_table.setItemDelegate(UniversalCellDelegate(self.vat_table))
        self.vat_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.vat_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        headers = ["VAT Ledger Name" if idx == 0 else c[1] for idx, c in enumerate(TALLY_LEDGER_COLUMNS)]
        self.vat_table.setColumnCount(len(headers))
        self.vat_table.setHorizontalHeaderLabels(headers)

        header = self.vat_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionDoubleClicked.connect(
            lambda idx: self._on_generic_header_double_clicked(self.vat_table, idx, self._update_vat_totals)
        )
        for idx, col in enumerate(TALLY_LEDGER_COLUMNS):
            self.vat_table.setColumnWidth(idx, col[2])

        self.vat_footer = TableFooterWidget(self.vat_table)
        self.vat_footer_container = TableFooterContainer(self.vat_table, self.vat_footer)

        self.apply_column_visibility()

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.vat_table, stretch=1)
        table_layout.addWidget(self.vat_footer_container)

        vbox.addWidget(table_container, stretch=1)

        # ── VAT Company Configuration: Exclusively in Vat Ledger View ──
        vat_comp_bar = QHBoxLayout()
        vat_comp_bar.setContentsMargins(4, 6, 4, 4)

        self.lbl_active_vat = QLabel("Active VAT Company: None")
        self.lbl_active_vat.setStyleSheet("font-weight: 600; color: #1e293b; font-size: 13px;")

        self.btn_vat_company = QPushButton("VAT Company")
        self.btn_vat_company.setStyleSheet("""
            QPushButton {
                background: #059669;
                color: white;
                font-weight: 600;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #047857;
            }
        """)
        self.btn_vat_company.clicked.connect(self.open_vat_company_dialog)

        vat_comp_bar.addWidget(self.lbl_active_vat)
        vat_comp_bar.addStretch()
        vat_comp_bar.addWidget(self.btn_vat_company)

        vbox.addLayout(vat_comp_bar)
        return widget

    def _create_mapping_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Search filter, Unmapped badge, Show 'None' VAT checkbox, Clear mapping, Toggle unassigned panel
        top_bar = QHBoxLayout()
        self.mapping_search = QLineEdit()
        self.mapping_search.setPlaceholderText("Search any cell, name, S.No, amount, narration...")
        self.mapping_search.setClearButtonEnabled(True)
        self.mapping_search.setFixedWidth(280)
        self.mapping_search.textChanged.connect(self._filter_mapping_table)
        self.mapping_search.textEdited.connect(self._on_mapping_search_user_edited)

        # Operational hotkey: Esc clears search and returns focus to table
        orig_search_kpe = self.mapping_search.keyPressEvent
        def _search_kpe(event):
            if event.key() == Qt.Key.Key_Escape:
                if self.mapping_search.text():
                    self.mapping_search.clear()
                self.mapping_table.setFocus()
                return
            orig_search_kpe(event)
        self.mapping_search.keyPressEvent = _search_kpe

        top_bar.addWidget(self.mapping_search)

        # Operational shortcut: Ctrl+F focuses the mapping search
        QShortcut(QKeySequence("Ctrl+F"), widget, activated=self._focus_mapping_search)

        self.lbl_unmapped_badge = QLabel("")
        self.lbl_unmapped_badge.setStyleSheet(
            "background: #fee2e2; color: #991b1b; font-size: 11px; font-weight: 700; "
            "padding: 3px 8px; border-radius: 10px; border: 1px solid #fca5a5;"
        )
        self.lbl_unmapped_badge.setVisible(False)
        top_bar.addWidget(self.lbl_unmapped_badge)

        top_bar.addStretch()

        self.btn_unmap_mapping = QPushButton("Clear Mapping")
        self.btn_unmap_mapping.setEnabled(False)
        self.btn_unmap_mapping.setStyleSheet("""
            QPushButton {
                background: #ef4444; color: white; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #dc2626; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        self.btn_unmap_mapping.clicked.connect(self._unmap_selected_mapping)
        top_bar.addWidget(self.btn_unmap_mapping)

        self.btn_toggle_unassigned = QPushButton("📋 Unassigned (0) ❯")
        self.btn_toggle_unassigned.setStyleSheet("""
            QPushButton {
                background: #f8fafc; color: #334155; font-weight: 600; font-size: 11px;
                padding: 4px 10px; border-radius: 4px; border: 1px solid #e2e8f0;
            }
            QPushButton:hover { background: #f1f5f9; border-color: #cbd5e1; }
        """)
        self.btn_toggle_unassigned.clicked.connect(self._toggle_unassigned_panel)
        top_bar.addWidget(self.btn_toggle_unassigned)

        # Toggle button for Pending Chq. column (User can hide if needed)
        _chq_settings = QSettings("JKCatalog", "VatBalanceMappingColumns")
        self._hide_pending_chq = _chq_settings.value("hide_pending_chq", False, type=bool)
        chq_btn_label = "👁️ Show Pending Chq." if self._hide_pending_chq else "👁️ Hide Pending Chq."
        self.btn_toggle_pending_chq = QPushButton(chq_btn_label)
        self.btn_toggle_pending_chq.setStyleSheet("""
            QPushButton {
                background: #f8fafc; color: #334155; font-weight: 600; font-size: 11px;
                padding: 4px 10px; border-radius: 4px; border: 1px solid #e2e8f0;
            }
            QPushButton:hover { background: #f1f5f9; border-color: #cbd5e1; }
        """)
        self.btn_toggle_pending_chq.clicked.connect(self._toggle_pending_chq_visibility)
        top_bar.addWidget(self.btn_toggle_pending_chq)

        vbox.addLayout(top_bar)

        # Splitter: Left is Main Mapping Table, Right is Minimizable Unassigned Internal List
        self.mapping_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Container (Main Mapping Table)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.mapping_table = MappingTableWidget()
        self.mapping_table._parent_ui = self
        self.mapping_table._can_edit = self._can_edit
        self.mapping_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.mapping_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mapping_table.verticalHeader().setVisible(False)

        headers = ["S.no", "VAT Ledger Name", "Internal Ledger Name", "Vat Closing", "Int. Closing", "Pending Chq.", "Balance", "Negative", "Narration"]
        self.mapping_table.setColumnCount(9)
        self.mapping_table.setHorizontalHeaderLabels(headers)

        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.mapping_table.setColumnWidth(0, 60)   # S.no
        self.mapping_table.setColumnWidth(1, 240)  # VAT Ledger Name
        self.mapping_table.setColumnWidth(2, 240)  # Internal Ledger Name
        self.mapping_table.setColumnWidth(3, 110)  # Vat Closing
        self.mapping_table.setColumnWidth(4, 110)  # Int. Closing
        self.mapping_table.setColumnWidth(5, 110)  # Pending Chq.
        self.mapping_table.setColumnWidth(6, 110)  # Balance
        self.mapping_table.setColumnWidth(7, 110)  # Negative
        self.mapping_table.setColumnWidth(8, 200)  # Narration (stretches to fill available width)

        # Apply saved column 5 visibility
        if self._hide_pending_chq:
            self.mapping_table.setColumnHidden(5, True)

        # Double clicking column header sorts that column (Requirement 15)
        header.sectionDoubleClicked.connect(self._on_mapping_header_double_clicked)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_mapping_header_context_menu)

        # Zero-allocation high-FPS delegate for columns 1 & 2 (VAT & Internal Ledgers)
        self._mapping_delegate = MappingCellDelegate(
            on_plus_callback=self._on_mapping_plus_clicked,
            parent=self.mapping_table
        )
        self._mapping_delegate.can_edit = self._can_edit
        self.mapping_table.setItemDelegateForColumn(1, self._mapping_delegate)
        self.mapping_table.setItemDelegateForColumn(2, self._mapping_delegate)
        self.mapping_table.setMouseTracking(True)
        self.mapping_table.viewport().setMouseTracking(True)
        self.mapping_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.mapping_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self.mapping_table.itemSelectionChanged.connect(self._on_mapping_selection_changed)
        self.mapping_table.itemChanged.connect(self._on_mapping_item_changed)
        self.mapping_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mapping_table.customContextMenuRequested.connect(self._show_mapping_context_menu)

        # Pinned Footer / Total Row (Requirement 13)
        self.mapping_footer = TableFooterWidget(self.mapping_table)
        self.mapping_footer_container = TableFooterContainer(self.mapping_table, self.mapping_footer)

        left_layout.addWidget(self.mapping_table, stretch=1)
        left_layout.addWidget(self.mapping_footer_container)
        self.mapping_splitter.addWidget(left_widget)

        # Right Container (Unassigned Internal Ledgers Panel - Compact & Minimalist)
        self.unassigned_panel = QWidget()
        self.unassigned_panel.setStyleSheet("""
            QWidget {
                background: #fbfcfe;
                border-left: 1px solid #e2e8f0;
            }
        """)
        self.unassigned_panel.setMinimumWidth(180)
        self.unassigned_panel.setMaximumWidth(235)
        panel_layout = QVBoxLayout(self.unassigned_panel)
        panel_layout.setContentsMargins(6, 6, 6, 6)
        panel_layout.setSpacing(5)

        # Panel Header
        p_hdr = QHBoxLayout()
        p_hdr.setContentsMargins(0, 0, 0, 0)
        p_hdr.setSpacing(4)
        p_lbl = QLabel("UNASSIGNED")
        p_lbl.setStyleSheet("font-weight: 700; font-size: 10px; color: #64748b; letter-spacing: 0.5px;")
        self.lbl_unassigned_count = QLabel("0")
        self.lbl_unassigned_count.setStyleSheet(
            "background: #f1f5f9; color: #475569; font-size: 10px; font-weight: 700; "
            "padding: 1px 6px; border-radius: 8px; border: 1px solid #e2e8f0;"
        )
        p_hdr.addWidget(p_lbl)
        p_hdr.addWidget(self.lbl_unassigned_count)
        p_hdr.addStretch()

        self.btn_collapse_unassigned = QPushButton("⮞")
        self.btn_collapse_unassigned.setFixedSize(20, 20)
        self.btn_collapse_unassigned.setStyleSheet("""
            QPushButton {
                background: transparent; color: #94a3b8; font-size: 11px; border: none; border-radius: 3px;
            }
            QPushButton:hover { background: #f1f5f9; color: #0f172a; }
        """)
        self.btn_collapse_unassigned.clicked.connect(self._collapse_unassigned_panel)
        p_hdr.addWidget(self.btn_collapse_unassigned)
        panel_layout.addLayout(p_hdr)

        # Panel Search
        self.unassigned_search = QLineEdit()
        self.unassigned_search.setPlaceholderText("Filter name or alias...")
        self.unassigned_search.setStyleSheet("""
            QLineEdit {
                background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px;
                padding: 3px 6px; font-size: 11px; color: #0f172a;
            }
            QLineEdit:focus {
                border: 1px solid #059669; background: #ffffff;
            }
        """)
        self.unassigned_search.textChanged.connect(self._filter_unassigned_list)
        panel_layout.addWidget(self.unassigned_search)

        # Panel Action: Assign button
        self.btn_assign_internal = QPushButton("← Assign to VAT")
        self.btn_assign_internal.setEnabled(False)
        self.btn_assign_internal.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600; font-size: 11px;
                padding: 4px 8px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #047857; }
            QPushButton:disabled { background: #f1f5f9; color: #94a3b8; border: 1px solid #e2e8f0; }
        """)
        self.btn_assign_internal.clicked.connect(self._assign_selected_internal_ledger)
        panel_layout.addWidget(self.btn_assign_internal)

        # Panel List
        self.unassigned_list = QListWidget()
        self.unassigned_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.unassigned_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #e2e8f0; border-radius: 4px; background: #ffffff;
                font-size: 11px; color: #0f172a; padding: 2px; outline: none;
            }
            QListWidget::item {
                padding: 3px 6px; border-radius: 3px; min-height: 20px;
                border-bottom: 1px solid #f8fafc;
            }
            QListWidget::item:hover {
                background: #f8fafc;
            }
            QListWidget::item:selected {
                background: #ecfdf5; color: #065f46; font-weight: 600;
            }
        """)
        self.unassigned_list.itemDoubleClicked.connect(self._on_unassigned_item_double_clicked)
        self.unassigned_list.itemClicked.connect(self._on_unassigned_item_user_clicked)
        self.unassigned_list.itemSelectionChanged.connect(self._on_unassigned_selection_changed)
        self.unassigned_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.unassigned_list.customContextMenuRequested.connect(self._show_unassigned_context_menu)
        panel_layout.addWidget(self.unassigned_list, stretch=1)

        self.mapping_splitter.addWidget(self.unassigned_panel)
        self.mapping_splitter.setStretchFactor(0, 1)
        self.mapping_splitter.setStretchFactor(1, 0)
        self.mapping_splitter.setSizes([950, 210])

        vbox.addWidget(self.mapping_splitter, stretch=1)
        return widget

    def _create_debtor_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Title + Search + Count + CRM Mapping + Hide Alias
        top_bar = QHBoxLayout()
        lbl = QLabel("Debtor")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_debtor_count = QLabel("")
        self.lbl_debtor_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.debtor_search = QLineEdit()
        self.debtor_search.setPlaceholderText("Search all columns...")
        self.debtor_search.setFixedWidth(240)
        self.debtor_search.textChanged.connect(lambda txt: self._filter_conf_table(self.debtor_table, txt))

        self.btn_crm_mapping = QPushButton("CRM Mapping")
        self.btn_crm_mapping.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600; font-size: 11px;
                padding: 5px 14px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_crm_mapping.clicked.connect(self._open_crm_mapping_dialog)

        self.btn_debtor_columns = QPushButton("Columns")
        self.btn_debtor_columns.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_debtor_columns.clicked.connect(self._open_debtor_columns_dialog)

        self.btn_toggle_debtor_alias = QPushButton("Hide Alias")
        self.btn_toggle_debtor_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_debtor_alias.clicked.connect(self._toggle_conf_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_debtor_count)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_crm_mapping)
        top_bar.addWidget(self.btn_debtor_columns)
        top_bar.addWidget(self.debtor_search)
        top_bar.addWidget(self.btn_toggle_debtor_alias)
        vbox.addLayout(top_bar)

        self.debtor_table = self._build_vat_conf_table("Debtor")
        self.debtor_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.debtor_footer = TableFooterWidget(self.debtor_table)
        self.debtor_footer_container = TableFooterContainer(self.debtor_table, self.debtor_footer)

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.debtor_table, stretch=1)
        table_layout.addWidget(self.debtor_footer_container)

        vbox.addWidget(table_container, stretch=1)
        return widget

    def _open_crm_mapping_dialog(self):
        """Open CRM Mapping popup dialog for Debtor Sub Groups."""
        if not self.db_name or not self.active_vat_company:
            QMessageBox.warning(self, "No Active VAT Company", "Please configure and select an active VAT Company first.")
            return
        dlg = VatSubgroupCrmMappingDialog(
            db_name=self.db_name,
            vat_company=self.active_vat_company,
            company_path=self.current_company_path,
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Reload debtor conf table so new mappings appear immediately
            d_rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, "debtor", self.current_company_path)
            if not hasattr(self, '_cached_data') or self._cached_data is None:
                self._cached_data = {}
            self._cached_data["debtor_conf"] = d_rows
            self._populate_vat_conf_table_from_data(self.debtor_table, "Debtor", d_rows)
            if hasattr(self, 'debtor_search') and self.debtor_search.text():
                self._filter_conf_table(self.debtor_table, self.debtor_search.text())

    def _create_creditor_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Title + Sub Group Filter + Search + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("Creditor")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_creditor_count = QLabel("")
        self.lbl_creditor_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.btn_creditor_subgroups = QPushButton("Select Sub Groups")
        self.btn_creditor_subgroups.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                padding: 5px 14px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_creditor_subgroups.clicked.connect(self._open_creditor_subgroups_dialog)

        self.lbl_creditor_subgroup_summary = QLabel("No Sub Group Selected")
        self.lbl_creditor_subgroup_summary.setStyleSheet(
            "font-size: 11px; color: #059669; font-weight: 600; padding: 2px 6px;"
        )

        self.btn_clear_creditor_subgroups = QPushButton("Clear")
        self.btn_clear_creditor_subgroups.setStyleSheet("""
            QPushButton {
                background: transparent; color: #ef4444; font-size: 11px; font-weight: 600;
                padding: 2px 6px; border: none; text-decoration: underline;
            }
            QPushButton:hover { color: #dc2626; }
        """)
        self.btn_clear_creditor_subgroups.clicked.connect(self._clear_creditor_subgroups)
        self.btn_clear_creditor_subgroups.setVisible(False)

        self.creditor_search = QLineEdit()
        self.creditor_search.setPlaceholderText("Search all columns...")
        self.creditor_search.setClearButtonEnabled(True)
        self.creditor_search.setFixedWidth(220)
        self.creditor_search.textChanged.connect(lambda _t: self._apply_creditor_filters())

        top_bar.addWidget(lbl)
        top_bar.addSpacing(6)
        top_bar.addWidget(self.lbl_creditor_count)
        top_bar.addSpacing(12)
        top_bar.addWidget(self.btn_creditor_subgroups)
        top_bar.addWidget(self.lbl_creditor_subgroup_summary)
        top_bar.addWidget(self.btn_clear_creditor_subgroups)
        top_bar.addStretch()
        top_bar.addWidget(self.creditor_search)
        vbox.addLayout(top_bar)

        self._update_creditor_subgroup_button()

        self.creditor_table = self._build_creditor_table()

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.creditor_table, stretch=1)

        # Overlay label for "No Creditor Fund" when empty
        self.lbl_creditor_empty = QLabel("No Creditor Fund", self.creditor_table)
        self.lbl_creditor_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_creditor_empty.setStyleSheet(
            "color: #64748b; font-size: 15px; font-weight: bold; background: transparent;"
        )
        self.lbl_creditor_empty.setVisible(False)

        def _on_creditor_table_resize(event):
            QTableWidget.resizeEvent(self.creditor_table, event)
            if hasattr(self, 'lbl_creditor_empty'):
                self.lbl_creditor_empty.setGeometry(0, 46, self.creditor_table.width(), max(self.creditor_table.height() - 46, 100))

        self.creditor_table.resizeEvent = _on_creditor_table_resize

        vbox.addWidget(table_container, stretch=1)
        return widget

    def _build_creditor_table(self) -> QTableWidget:
        tbl = VatConfTableWidget()
        tbl.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        tbl.verticalHeader().setVisible(False)

        wrap_header = WordWrapHeaderView(Qt.Orientation.Horizontal, tbl)
        wrap_header.setMinimumHeight(38)
        tbl.setHorizontalHeader(wrap_header)

        headers = [
            "Ledger Name",
            "Opening",
            "Closing",
            "Need Confirmation",
            "Get Confirmation",
            "His Opening",
            "His Closing"
        ]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)

        header = tbl.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionDoubleClicked.connect(
            lambda idx, t=tbl: self._on_generic_header_double_clicked(t, idx)
        )

        tbl.setColumnWidth(0, 240)  # Ledger Name
        tbl.setColumnWidth(1, 120)  # Opening
        tbl.setColumnWidth(2, 120)  # Closing
        tbl.setColumnWidth(3, 115)  # Need Confirmation
        tbl.setColumnWidth(4, 115)  # Get Confirmation
        tbl.setColumnWidth(5, 120)  # His Opening
        tbl.setColumnWidth(6, 120)  # His Closing

        tbl.setItemDelegate(
            VatConfDelegate(lambda: load_crm_list(self.current_company_path), tbl)
        )
        tbl.itemChanged.connect(lambda item, t=tbl: self._on_creditor_item_changed(item, t))
        return tbl

    def get_creditor_selected_subgroups(self) -> set:
        comp = getattr(self, 'active_vat_company', '') or ""
        s = QSettings("JKCatalog", "VatConfCreditorSubgroups")
        val = s.value(f"subgroups_{comp}", None) if comp else None
        if val is None:
            val = s.value("subgroups", "")
        if not val:
            return set()
        if isinstance(val, str):
            # Support both old comma-separated and new ||-separated format
            parts = val.split("||") if "||" in val else val.split(",")
            return {x.strip() for x in parts if x.strip()}
        if isinstance(val, (list, set)):
            return {str(x).strip() for x in val if str(x).strip()}
        return set()

    def save_creditor_selected_subgroups(self, sgs: set):
        comp = getattr(self, 'active_vat_company', '') or ""
        s = QSettings("JKCatalog", "VatConfCreditorSubgroups")
        val_str = "||".join(sorted(sgs))
        s.setValue("subgroups", val_str)
        if comp:
            s.setValue(f"subgroups_{comp}", val_str)

    def _update_creditor_subgroup_button(self):
        selected = self.get_creditor_selected_subgroups()
        if hasattr(self, 'btn_creditor_subgroups'):
            if selected:
                cnt = len(selected)
                self.btn_creditor_subgroups.setText(f"Sub Groups ({cnt})")
                names_preview = ", ".join(sorted(selected))
                if len(names_preview) > 35:
                    names_preview = names_preview[:32] + "..."
                if hasattr(self, 'lbl_creditor_subgroup_summary'):
                    self.lbl_creditor_subgroup_summary.setText(f"Active: {names_preview}")
                if hasattr(self, 'btn_clear_creditor_subgroups'):
                    self.btn_clear_creditor_subgroups.setVisible(True)
            else:
                self.btn_creditor_subgroups.setText("Select Sub Groups")
                if hasattr(self, 'lbl_creditor_subgroup_summary'):
                    self.lbl_creditor_subgroup_summary.setText("No Sub Group Selected")
                if hasattr(self, 'btn_clear_creditor_subgroups'):
                    self.btn_clear_creditor_subgroups.setVisible(False)

    def _clear_creditor_subgroups(self):
        self.save_creditor_selected_subgroups(set())
        self._update_creditor_subgroup_button()
        self._apply_creditor_filters()

    def _open_creditor_subgroups_dialog(self):
        if not self.db_name or not self.active_vat_company:
            QMessageBox.information(self, "No Active VAT Company", "Please select an active VAT Company first.")
            return

        available_subgroups = get_unique_vat_creditor_subgroups(self.db_name, self.active_vat_company)
        current_selected = self.get_creditor_selected_subgroups()

        dlg = CreditorSubgroupDialog(
            available_subgroups=available_subgroups,
            selected_subgroups=current_selected,
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_selected = dlg.get_selected_subgroups()
            self.save_creditor_selected_subgroups(new_selected)
            self._update_creditor_subgroup_button()
            self._apply_creditor_filters()

    def _apply_creditor_filters(self):
        """Filter Creditor table by selected Sub Groups and search query."""
        tbl = getattr(self, 'creditor_table', None)
        if not tbl:
            return

        selected_sgs = self.get_creditor_selected_subgroups()
        sg_tokens = [s.strip().lower() for s in selected_sgs if s.strip()]

        def _clean_alnum(s: str) -> str:
            return re.sub(r'[^a-z0-9]', '', (s or "").lower())

        search_query = self.creditor_search.text().strip().lower() if hasattr(self, 'creditor_search') else ""
        search_tokens = search_query.split() if search_query else []
        norm_search_q = _clean_alnum(search_query)
        norm_search_tokens = [_clean_alnum(t) for t in search_tokens if _clean_alnum(t)]

        total_rows = tbl.rowCount()
        visible_count = 0

        # If no sub groups are selected, show "No Creditor Fund" (hide all ledgers)
        if not sg_tokens:
            tbl.blockSignals(True)
            tbl.setUpdatesEnabled(False)
            try:
                for r in range(total_rows):
                    tbl.setRowHidden(r, True)
            finally:
                tbl.setUpdatesEnabled(True)
                tbl.blockSignals(False)

            if hasattr(self, 'lbl_creditor_count'):
                self.lbl_creditor_count.setText("No Creditor Fund")
            if hasattr(self, 'lbl_creditor_empty'):
                self.lbl_creditor_empty.setVisible(True)
                self.lbl_creditor_empty.setGeometry(0, 46, tbl.width(), max(tbl.height() - 46, 100))
            return

        tbl.blockSignals(True)
        tbl.setUpdatesEnabled(False)
        try:
            for r in range(total_rows):
                # 1. Sub Group filtering: ONLY matching ledgers appear
                item_name = tbl.item(r, 0)
                row_sg = str(item_name.data(Qt.ItemDataRole.UserRole + 1) or "").strip().lower() if item_name else ""
                matches_sg = any(tok == row_sg or tok in row_sg or (row_sg and row_sg in tok) for tok in sg_tokens)
                if not matches_sg:
                    tbl.setRowHidden(r, True)
                    continue

                # 2. Search query filtering
                if not search_tokens:
                    tbl.setRowHidden(r, False)
                    visible_count += 1
                    continue

                row_words = []
                full_cell_strings = []
                for c in range(tbl.columnCount()):
                    it = tbl.item(r, c)
                    if it:
                        txt = it.text().strip()
                        if txt:
                            txt_low = txt.lower()
                            full_cell_strings.append(txt_low)
                            row_words.extend(txt_low.split())
                        urole = it.data(Qt.ItemDataRole.UserRole)
                        if urole and str(urole).strip():
                            u_str = str(urole).strip().lower()
                            if u_str not in full_cell_strings:
                                full_cell_strings.append(u_str)
                                row_words.extend(u_str.split())

                full_row_str = " ".join(full_cell_strings)
                norm_full_row = _clean_alnum(full_row_str)

                # Tier 1: Substring match (raw or normalized alphanumeric)
                if search_query in full_row_str or (norm_search_q and norm_search_q in norm_full_row):
                    tbl.setRowHidden(r, False)
                    visible_count += 1
                    continue

                # Tier 2: All tokens present in row (raw or normalized alphanumeric)
                if all(tok in full_row_str for tok in search_tokens) or (
                    norm_search_tokens and all(nt in norm_full_row for nt in norm_search_tokens)
                ):
                    tbl.setRowHidden(r, False)
                    visible_count += 1
                    continue

                # Tier 3: Fuzzy / closest match
                is_fuzzy_match = True
                for tok in search_tokens:
                    tok_len = len(tok)
                    tok_alnum = _clean_alnum(tok)
                    token_matched = False
                    for w in row_words:
                        if tok in w or (tok_alnum and tok_alnum in _clean_alnum(w)):
                            token_matched = True
                            break
                        if tok_len >= 3 and abs(tok_len - len(w)) <= 3:
                            ratio = difflib.SequenceMatcher(None, tok, w).ratio()
                            if ratio >= 0.70:
                                token_matched = True
                                break
                    if not token_matched:
                        is_fuzzy_match = False
                        break

                if is_fuzzy_match:
                    tbl.setRowHidden(r, False)
                    visible_count += 1
                else:
                    tbl.setRowHidden(r, True)

        finally:
            tbl.setUpdatesEnabled(True)
            tbl.blockSignals(False)

        # Update counter & empty overlay
        if visible_count == 0:
            if hasattr(self, 'lbl_creditor_count'):
                self.lbl_creditor_count.setText("No Creditor Fund")
            if hasattr(self, 'lbl_creditor_empty'):
                self.lbl_creditor_empty.setVisible(True)
                self.lbl_creditor_empty.setGeometry(0, 46, tbl.width(), max(tbl.height() - 46, 100))
        else:
            if hasattr(self, 'lbl_creditor_empty'):
                self.lbl_creditor_empty.setVisible(False)
            if hasattr(self, 'lbl_creditor_count'):
                if visible_count < total_rows:
                    self.lbl_creditor_count.setText(f"<b>{visible_count}</b> / {total_rows} records")
                else:
                    self.lbl_creditor_count.setText(f"<b>{visible_count}</b> records")

    def _populate_creditor_table_from_data(self, rows: list):
        """Populate Creditor tab table (7 columns) from pre-fetched rows."""
        tbl = self.creditor_table
        tbl.blockSignals(True)
        tbl.setUpdatesEnabled(False)
        try:
            tbl.setRowCount(len(rows))

            for r_idx, r in enumerate(rows):
                # 0: Ledger Name (Read-only, left-aligned)
                raw_name = (r.get("name") or "").strip()
                if raw_name.lower() in ("none", "nan", "null"):
                    raw_name = ""
                it_name = QTableWidgetItem(raw_name)
                it_name.setData(Qt.ItemDataRole.UserRole, raw_name)
                # Store sub_group in UserRole + 1 for filtering
                raw_sg = (r.get("sub_group") or "").strip()
                it_name.setData(Qt.ItemDataRole.UserRole + 1, raw_sg)
                it_name.setFlags(it_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 0, it_name)

                # 1: Opening (Read-only, right-aligned numeric item)
                op_amt = r.get("opening_amount")
                is_op_blank = (
                    op_amt is None
                    or (isinstance(op_amt, float) and op_amt != op_amt)
                    or str(op_amt).strip().lower() in ("", "nan", "none", "null")
                )
                if is_op_blank:
                    it_op = NumericTableWidgetItem("", 0.0)
                else:
                    f_op = 0.0 if abs(float(op_amt)) < 1e-9 else float(op_amt)
                    it_op = NumericTableWidgetItem(f"{f_op:,.2f}", f_op)
                it_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_op.setFlags(it_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 1, it_op)

                # 2: Closing (Read-only, right-aligned numeric item)
                cl_amt = r.get("closing_amount")
                is_cl_blank = (
                    cl_amt is None
                    or (isinstance(cl_amt, float) and cl_amt != cl_amt)
                    or str(cl_amt).strip().lower() in ("", "nan", "none", "null")
                )
                if is_cl_blank:
                    it_cl = NumericTableWidgetItem("", 0.0)
                else:
                    f_cl = 0.0 if abs(float(cl_amt)) < 1e-9 else float(cl_amt)
                    it_cl = NumericTableWidgetItem(f"{f_cl:,.2f}", f_cl)
                it_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_cl.setFlags(it_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 2, it_cl)

                # 3: Need Confirmation (Read-only, centered)
                # If any transaction or balance exceeds ₹1,00,000 -> Yes, else No
                need_conf = r.get("need_confirmation") or r.get("need_print")
                if not need_conf:
                    need_conf = calculate_need_print(
                        opening=f_op if not is_op_blank else 0.0,
                        closing=f_cl if not is_cl_blank else 0.0,
                        cash_in=r.get("cash_in", 0.0),
                        cash_out=r.get("cash_out", 0.0),
                        debit_totals=r.get("debit_totals", 0.0),
                        credit_totals=r.get("credit_totals", 0.0),
                    )
                it_nc = YesNoTableWidgetItem(need_conf)
                it_nc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if need_conf == "Yes":
                    it_nc.setForeground(QColor("#059669"))
                    font = it_nc.font()
                    font.setBold(True)
                    it_nc.setFont(font)
                it_nc.setFlags(it_nc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 3, it_nc)

                # 4: Get Confirmation (Editable, centered)
                # If exceeds 1 lakh -> blank by default; if not -> N/A by default; unless saved by user
                saved_get_back = (r.get("get_back") or "").strip()
                if saved_get_back:
                    get_conf = saved_get_back
                else:
                    get_conf = "" if need_conf == "Yes" else "N/A"
                it_gc = YesNoTableWidgetItem(get_conf)
                it_gc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not self._can_edit:
                    it_gc.setFlags(it_gc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 4, it_gc)

                # 5: His Opening (Editable numeric, compared against Opening)
                it_exp_op = ExpAmountTableWidgetItem(r.get("expected_opening", ""))
                it_exp_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not self._can_edit:
                    it_exp_op.setFlags(it_exp_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 5, it_exp_op)

                # 6: His Closing (Editable numeric, compared against Closing)
                it_exp_cl = ExpAmountTableWidgetItem(r.get("expected_closing", ""))
                it_exp_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not self._can_edit:
                    it_exp_cl.setFlags(it_exp_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 6, it_exp_cl)

                # Apply row styling (mismatch check between Opening vs His Opening, Closing vs His Closing)
                self._update_creditor_row_style(tbl, r_idx)

        finally:
            tbl.setUpdatesEnabled(True)
            tbl.blockSignals(False)

        # Apply active filters (subgroups & search query)
        self._apply_creditor_filters()

    def _update_creditor_row_style(self, tbl: QTableWidget, row: int):
        """Paint row in soft red if His Opening != Opening or His Closing != Closing."""
        # Col 1: Opening, Col 2: Closing, Col 5: His Opening, Col 6: His Closing
        act_op_item = tbl.item(row, 1)
        act_cl_item = tbl.item(row, 2)
        exp_op_item = tbl.item(row, 5)
        exp_cl_item = tbl.item(row, 6)

        try:
            act_op_val = float(act_op_item.text().replace(",", "").strip()) if act_op_item and act_op_item.text().strip() else 0.0
        except ValueError:
            act_op_val = 0.0

        try:
            act_cl_val = float(act_cl_item.text().replace(",", "").strip()) if act_cl_item and act_cl_item.text().strip() else 0.0
        except ValueError:
            act_cl_val = 0.0

        exp_op_text = exp_op_item.text().strip() if exp_op_item else ""
        exp_cl_text = exp_cl_item.text().strip() if exp_cl_item else ""

        # Empty expected fields are NOT mismatches
        op_matches = check_amount_match(act_op_val, exp_op_text)
        cl_matches = check_amount_match(act_cl_val, exp_cl_text)
        is_mismatch = not (op_matches and cl_matches)

        red_bg = QColor("#fecaca")
        red_fg = QColor("#991b1b")
        normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
        normal_fg = QColor("#0f172a")

        for c in range(tbl.columnCount()):
            it = tbl.item(row, c)
            if not it:
                continue
            if is_mismatch:
                it.setBackground(red_bg)
                it.setForeground(red_fg)
            else:
                it.setBackground(normal_bg)
                if c == 3 and it.text().strip() == "Yes":
                    it.setForeground(QColor("#059669"))
                else:
                    it.setForeground(normal_fg)

    def _on_creditor_item_changed(self, item: QTableWidgetItem, tbl: QTableWidget):
        """User modified an editable cell in Creditor tab (Get Confirmation, His Opening, His Closing)."""
        if not getattr(self, '_can_edit', True):
            return
        col = item.column()
        row = item.row()
        name_item = tbl.item(row, 0)
        if not name_item:
            return
        ledger_name = str(name_item.data(Qt.ItemDataRole.UserRole) or name_item.text()).strip()
        val = item.text().strip()

        active_comp = self.active_vat_company
        if not active_comp and self.db_name:
            active_comp = get_active_vat_company(self.db_name)
            self.active_vat_company = active_comp
        if not active_comp:
            return

        # Col 4: Get Confirmation
        if col == 4:
            val = normalize_yes_no(val)
            tbl.blockSignals(True)
            item.setText(val)
            tbl.blockSignals(False)
            try:
                save_vat_conf_field(self.db_name, active_comp, "creditor", ledger_name, "get_back", val)
            except Exception as e:
                logger.error(f"Failed to save creditor get_back: {e}")

        # Col 5: His Opening
        elif col == 5:
            try:
                save_vat_conf_field(self.db_name, active_comp, "creditor", ledger_name, "expected_opening", val)
            except Exception as e:
                logger.error(f"Failed to save creditor expected_opening: {e}")
            self._update_creditor_row_style(tbl, row)

        # Col 6: His Closing
        elif col == 6:
            try:
                save_vat_conf_field(self.db_name, active_comp, "creditor", ledger_name, "expected_closing", val)
            except Exception as e:
                logger.error(f"Failed to save creditor expected_closing: {e}")
            self._update_creditor_row_style(tbl, row)

    def _filter_conf_table(self, tbl: QTableWidget, query: str):
        """Multi-column search across all columns with multi-token, alphanumeric normalization, and fuzzy matching."""
        q = (query or "").strip().lower()
        if not q:
            for r in range(tbl.rowCount()):
                tbl.setRowHidden(r, False)
        else:
            tokens = q.split()
            def _clean_alnum(s: str) -> str:
                return re.sub(r'[^a-z0-9]', '', (s or "").lower())

            norm_q = _clean_alnum(q)
            norm_tokens = [_clean_alnum(t) for t in tokens if _clean_alnum(t)]

            for r in range(tbl.rowCount()):
                row_words = []
                full_cell_strings = []
                for c in range(tbl.columnCount()):
                    if tbl.isColumnHidden(c):
                        continue
                    it = tbl.item(r, c)
                    if it:
                        txt = it.text().strip()
                        if txt:
                            txt_low = txt.lower()
                            full_cell_strings.append(txt_low)
                            row_words.extend(txt_low.split())
                        urole = it.data(Qt.ItemDataRole.UserRole)
                        if urole and str(urole).strip():
                            u_str = str(urole).strip().lower()
                            if u_str not in full_cell_strings:
                                full_cell_strings.append(u_str)
                                row_words.extend(u_str.split())

                full_row_str = " ".join(full_cell_strings)
                norm_full_row = _clean_alnum(full_row_str)

                # Tier 1: Substring match (raw or normalized alphanumeric)
                if q in full_row_str or (norm_q and norm_q in norm_full_row):
                    tbl.setRowHidden(r, False)
                    continue

                # Tier 2: All tokens present in row (raw or normalized alphanumeric)
                if all(tok in full_row_str for tok in tokens) or (
                    norm_tokens and all(nt in norm_full_row for nt in norm_tokens)
                ):
                    tbl.setRowHidden(r, False)
                    continue

                # Tier 3: Fuzzy / closest match
                is_fuzzy_match = True
                for tok in tokens:
                    tok_len = len(tok)
                    tok_alnum = _clean_alnum(tok)
                    token_matched = False
                    for w in row_words:
                        if tok in w:
                            token_matched = True
                            break
                        if tok_alnum and tok_alnum in _clean_alnum(w):
                            token_matched = True
                            break
                        if tok_len >= 3 and abs(tok_len - len(w)) <= 3:
                            ratio = difflib.SequenceMatcher(None, tok, w).ratio()
                            if ratio >= 0.70:
                                token_matched = True
                                break
                    if not token_matched:
                        is_fuzzy_match = False
                        break

                tbl.setRowHidden(r, not is_fuzzy_match)

        if tbl == getattr(self, 'debtor_table', None) and hasattr(self, 'debtor_footer'):
            self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))

    MAX_CONF_COLUMN_WIDTHS = {
        "sn.": 70,
        "name": 420,
        "pan no.": 130,
        "alias": 240,
        "opening amount": 150,
        "debit total": 150,
        "credit total": 150,
        "cash inflow": 150,
        "cash outflow": 150,
        "closing amount": 150,
        "need print ?": 115,
        "did you print": 115,
        "sub group": 260,
        "crm": 200,
        "get back": 100,
        "opening ?": 130,
        "closing ?": 130,
        "ledger name": 300,
        "opening": 150,
        "closing": 150,
        "need confirmation": 130,
        "get confirmation": 130,
        "his opening": 150,
        "his closing": 150,
    }

    def _auto_fit_conf_columns(self, tbl: QTableWidget, force: bool = False):
        """Real content-aware auto-fit with column header name minimum width and safe maximums."""
        if not tbl or tbl.columnCount() == 0:
            return

        # Check for user-persisted widths in QSettings
        saved_widths = {}
        s = QSettings("JKCatalog", "VatConfDebtorColumnWidths")
        if not force:
            saved_str = str(s.value("widths", "") or "")
            if saved_str:
                try:
                    for part in saved_str.split(";"):
                        if ":" in part:
                            k, w = part.split(":", 1)
                            saved_widths[k.strip().lower()] = int(w.strip())
                except Exception:
                    saved_widths = {}

        header = tbl.horizontalHeader()
        header_fm = header.fontMetrics() if header else tbl.fontMetrics()
        tbl_fm = tbl.fontMetrics()

        self._is_programmatic_col_resize = True
        new_widths_to_save = {}

        try:
            row_limit = min(tbl.rowCount(), 300)
            for c in range(tbl.columnCount()):
                hi = tbl.horizontalHeaderItem(c)
                if not hi:
                    continue
                h_text = hi.text().strip()
                h_key = h_text.lower()

                # Minimum width is width of column name + padding so text never clips
                header_text_w = header_fm.horizontalAdvance(h_text) + 28
                min_w = max(header_text_w, 55)

                # Maximum width threshold
                max_w = self.MAX_CONF_COLUMN_WIDTHS.get(h_key, 280)
                if max_w < min_w:
                    max_w = min_w + 40

                if h_key in saved_widths and saved_widths[h_key] > 0:
                    final_w = max(saved_widths[h_key], min_w)
                else:
                    max_content_w = min_w
                    for r in range(row_limit):
                        it = tbl.item(r, c)
                        if it and it.text():
                            txt = it.text().strip()
                            txt_w = tbl_fm.horizontalAdvance(txt) + 24
                            if txt_w > max_content_w:
                                max_content_w = txt_w

                    final_w = max(min_w, min(max_content_w, max_w))

                tbl.setColumnWidth(c, final_w)
                new_widths_to_save[h_key] = final_w

            serialized = ";".join(f"{k}:{w}" for k, w in new_widths_to_save.items())
            s.setValue("widths", serialized)

        finally:
            self._is_programmatic_col_resize = False

    def _build_vat_conf_table(self, group_type: str) -> QTableWidget:
        tbl = VatConfTableWidget()
        tbl.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        tbl.verticalHeader().setVisible(False)

        wrap_header = WordWrapHeaderView(Qt.Orientation.Horizontal, tbl)
        tbl.setHorizontalHeader(wrap_header)

        headers = [
            "SN.", "Name", "Pan No.", "Alias",
            "Opening Amount", "Debit Total", "Credit Total", "Cash Inflow", "Cash Outflow", "Closing Amount",
            "Need Print ?", "Did You Print", "Sub Group", "CRM", "Get Back",
            "Opening ?", "Closing ?"
        ]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)

        header = tbl.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionDoubleClicked.connect(
            lambda idx, t=tbl, gt=group_type: self._on_generic_header_double_clicked(
                t, idx,
                lambda: self._update_conf_totals(
                    t,
                    self.debtor_footer if gt == "Debtor" else self.creditor_footer,
                    getattr(self, 'lbl_debtor_count' if gt == "Debtor" else 'lbl_creditor_count', None)
                )
            )
        )
        if group_type == "Debtor":
            header.sectionResized.connect(self._on_debtor_header_resized)

        # Baseline starting column widths
        default_widths = [
            55, 230, 110, 110, 120, 120, 120, 120, 120, 120,
            95, 95, 140, 130, 85, 105, 105
        ]
        for c, w in enumerate(default_widths):
            if c < tbl.columnCount():
                tbl.setColumnWidth(c, w)

        tbl.setItemDelegate(
            VatConfDelegate(lambda: load_crm_list(self.current_company_path), tbl)
        )
        tbl.itemChanged.connect(lambda item, gt=group_type, t=tbl: self._on_vat_conf_item_changed(item, gt, t))
        return tbl

    # ── EMPTY LEDGER TAB ──────────────────────────────────────────────

    def _create_empty_ledger_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Title + Count + Search
        top_bar = QHBoxLayout()
        lbl = QLabel("Empty Ledger")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_empty_count = QLabel("")
        self.lbl_empty_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.empty_search = QLineEdit()
        self.empty_search.setPlaceholderText("Search empty ledger...")
        self.empty_search.setFixedWidth(240)
        self.empty_search.textChanged.connect(self._filter_empty_ledger_table)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_empty_count)
        top_bar.addStretch()
        top_bar.addWidget(self.empty_search)
        vbox.addLayout(top_bar)

        self.empty_ledger_table = QTableWidget()
        self.empty_ledger_table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.empty_ledger_table.setAlternatingRowColors(True)
        self.empty_ledger_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.empty_ledger_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.empty_ledger_table.verticalHeader().setVisible(False)
        self.empty_ledger_table.setItemDelegate(UniversalCellDelegate(self.empty_ledger_table))
        self.empty_ledger_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.empty_ledger_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        headers = ["Vat Ledger", "From", "To"]
        self.empty_ledger_table.setColumnCount(len(headers))
        self.empty_ledger_table.setHorizontalHeaderLabels(headers)

        header = self.empty_ledger_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionDoubleClicked.connect(
            lambda idx: self._on_generic_header_double_clicked(self.empty_ledger_table, idx)
        )
        self.empty_ledger_table.setColumnWidth(0, 320)
        self.empty_ledger_table.setColumnWidth(1, 160)
        self.empty_ledger_table.setColumnWidth(2, 160)

        vbox.addWidget(self.empty_ledger_table, stretch=1)
        return widget

    def _populate_empty_ledger_table(self, debtors: list[dict] = None):
        """Populate Empty Ledger tab with sundry debtors where all transaction and balance amounts never came."""
        if debtors is None:
            if hasattr(self, '_cached_data') and "vat_debtors" in self._cached_data:
                debtors = self._cached_data["vat_debtors"]
            elif self.db_name and self.active_vat_company:
                debtors = load_vat_debtors(self.db_name, self.active_vat_company)
            else:
                debtors = []

        # Extract year from current company name or active vat company
        year_str = extract_company_year(getattr(self, 'current_company_name', ''))
        if not year_str and getattr(self, 'active_vat_company', None):
            year_str = extract_company_year(self.active_vat_company)

        # Fields to check: Opening, sales (debit), purchase (credit), receipt (cash inflow), payment (cash outflow), closing, overdue, on-account, quarters
        check_fields = [
            "Opening_Balance", "Debit_Totals", "Credit_Totals",
            "CashInFlow", "CashOutFlow", "Closing_Balance",
            "Overdue_Bills", "On_Account_Value", "This_Qtr_Balance", "Prev_Qtr_Balance"
        ]

        def _is_empty_debtor(d: dict) -> bool:
            name = str(d.get("Name") or "").strip()
            if not name or name.lower() in ("none", "nan", "null"):
                return False

            # Ensure it is a sundry debtor and not 'other account'
            grp = str(d.get("Group") or "").strip().lower()
            sub_grp = str(d.get("Sub_Group") or "").strip().lower()
            if any(x in sub_grp for x in ("other account", "othere account")):
                return False
            if grp and not ("debtor" in grp or "debtor" in sub_grp):
                return False

            for field in check_fields:
                val = d.get(field)
                if val is None:
                    continue
                if isinstance(val, float) and val != val:  # NaN
                    continue
                s_val = str(val).strip().lower()
                if s_val in ("", "none", "nan", "null"):
                    continue
                try:
                    s_clean = s_val.replace(",", "").replace("₹", "").strip()
                    num = float(s_clean)
                    if abs(num) > 1e-6:
                        return False
                except Exception:
                    return False
            return True

        empty_debtors = [d for d in debtors if _is_empty_debtor(d)]

        self.empty_ledger_table.blockSignals(True)
        self.empty_ledger_table.setUpdatesEnabled(False)
        self.empty_ledger_table.setRowCount(len(empty_debtors))

        for row, d in enumerate(empty_debtors):
            v_name = str(d.get("Name") or "").strip()
            v_alias = str(d.get("Alias") or "").strip()

            # Col 0: Vat Ledger
            item_name = QTableWidgetItem(v_name)
            item_name.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_name.setData(Qt.ItemDataRole.UserRole, v_name)
            item_name.setData(Qt.ItemDataRole.UserRole + 1, v_alias)
            self.empty_ledger_table.setItem(row, 0, item_name)

            # Col 1: From (Placeholder for future year end logic)
            item_from = QTableWidgetItem("")
            item_from.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_from.setFlags(item_from.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.empty_ledger_table.setItem(row, 1, item_from)

            # Col 2: To (Taken from current company open in Tally)
            item_to = QTableWidgetItem(year_str)
            item_to.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_to.setFlags(item_to.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.empty_ledger_table.setItem(row, 2, item_to)

        self.empty_ledger_table.setUpdatesEnabled(True)
        self.empty_ledger_table.blockSignals(False)

        count = len(empty_debtors)
        if hasattr(self, 'lbl_empty_count'):
            self.lbl_empty_count.setText(f"{count} Ledgers" if count > 0 else "0 Ledgers")

        if hasattr(self, 'empty_search') and self.empty_search.text().strip():
            self._filter_empty_ledger_table(self.empty_search.text())

    def _filter_empty_ledger_table(self, query: str = ""):
        """Filter Empty Ledger table rows based on search query."""
        if not hasattr(self, 'empty_ledger_table'):
            return
        q = (query or "").strip().lower()
        visible_count = 0
        total_rows = self.empty_ledger_table.rowCount()

        self.empty_ledger_table.blockSignals(True)
        self.empty_ledger_table.setUpdatesEnabled(False)
        for r in range(total_rows):
            if not q:
                self.empty_ledger_table.setRowHidden(r, False)
                visible_count += 1
            else:
                name_item = self.empty_ledger_table.item(r, 0)
                from_item = self.empty_ledger_table.item(r, 1)
                to_item = self.empty_ledger_table.item(r, 2)

                name_txt = (name_item.text() if name_item else "").lower()
                alias_txt = str(name_item.data(Qt.ItemDataRole.UserRole + 1) or "").lower() if name_item else ""
                from_txt = (from_item.text() if from_item else "").lower()
                to_txt = (to_item.text() if to_item else "").lower()

                match = (q in name_txt) or (q in alias_txt) or (q in from_txt) or (q in to_txt)
                self.empty_ledger_table.setRowHidden(r, not match)
                if match:
                    visible_count += 1
        self.empty_ledger_table.setUpdatesEnabled(True)
        self.empty_ledger_table.blockSignals(False)

        if hasattr(self, 'lbl_empty_count'):
            if q and visible_count != total_rows:
                self.lbl_empty_count.setText(f"{visible_count} of {total_rows} Ledgers")
            else:
                self.lbl_empty_count.setText(f"{total_rows} Ledgers" if total_rows > 0 else "0 Ledgers")

    # ── DATA LOADING ─────────────────────────────────────────────────

    def load_data(self, company_path: str, company_name: str = None, force: bool = False):
        """Called by MainWindow when company changes or tab opens.

        Uses a dedup guard to avoid redundant reloads when the path hasn't
        changed (e.g. repeated tab switches).  Pass force=True to bypass
        (used after Tally sync or VAT Company reconfigure).

        Heavy DB queries run on a background thread; the page shows instantly.
        """
        company_path = company_path or ""
        # ── Dedup guard: skip if already loaded or currently loading for this path ──
        if not force and company_path and (
            company_path == self._last_loaded_path
            or (self._load_worker is not None and self._load_worker.isRunning() and getattr(self, '_loading_path', None) == company_path)
        ):
            return

        self.current_company_path = company_path
        self.current_company_name = company_name or (os.path.basename(os.path.normpath(company_path)) if company_path else "")
        self.db_name = build_logical_name(self.current_company_name, company_path=self.current_company_path) if company_path else ""

        if not self.db_name or not self.db.database_exists(self.db_name):
            return

        # Fast metadata queries (< 5 ms each) — safe on UI thread
        ensure_vat_tables(self.db, self.db_name)
        self.active_vat_company = get_active_vat_company(self.db_name)
        self.lbl_active_vat.setText(f"Active VAT Company: {self.active_vat_company or 'None (Click Configure)'}")
        # Reset transient mapping staging state across company switch/reload
        self._staged_group_id = None
        self._staged_prior_index = None

        # ── Cancel any in-flight worker for previous company or forced reload ──
        if self._load_worker is not None and self._load_worker.isRunning():
            try:
                self._load_worker.finished.disconnect()
                self._load_worker.error.disconnect()
            except Exception:
                pass
            self._load_worker.quit()
            self._load_worker.wait(300)
            self._load_worker = None

        self._loading_path = company_path

        # ── Kick off background data fetch ──
        self._load_worker = _VatBalanceLoadWorker(self.db_name, self.active_vat_company, parent=self)
        self._load_worker.finished.connect(self._on_data_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    # ── Async callbacks ──────────────────────────────────────────────

    def _on_data_loaded(self, data: dict):
        """Cache data and lazily render only the currently visible tab (runs on UI thread)."""
        self._last_loaded_path = self.current_company_path
        self._loading_path = None
        self._load_worker = None
        self._cached_data = data or {}
        self._update_options_cache(
            int_debtors=self._cached_data.get("int_debtors", []),
            vat_debtors=self._cached_data.get("vat_debtors", [])
        )
        self._rendered_tabs.clear()
        self._render_current_tab()

    def _render_current_tab(self):
        """Lazily populate only the currently active tab from cached data."""
        if not getattr(self, '_cached_data', None):
            return

        current_idx = self.tabs.currentIndex()

        if current_idx == 0:
            if "int_ledger" not in self._rendered_tabs:
                self._populate_ledger_table(self.int_table, self._cached_data.get("int_debtors", []))
                self.apply_column_visibility()
                self._update_int_totals()
                self._rendered_tabs.add("int_ledger")

        elif current_idx == 1:
            if "vat_ledger" not in self._rendered_tabs:
                self._populate_ledger_table(self.vat_table, self._cached_data.get("vat_debtors", []))
                self.apply_column_visibility()
                self._update_vat_totals()
                self._rendered_tabs.add("vat_ledger")

        elif current_idx == 2:
            if "mapping" not in self._rendered_tabs:
                self._populate_mapping_from_data(self._cached_data.get("mappings", []))
                self._populate_unassigned_list(self._cached_data.get("unassigned_int", []))
                self._rendered_tabs.add("mapping")

        elif current_idx == 3:
            conf_idx = self.conf_tabs.currentIndex() if hasattr(self, 'conf_tabs') else 0
            if conf_idx == 0:
                if "debtor_conf" not in self._rendered_tabs:
                    self._populate_vat_conf_table_from_data(
                        self.debtor_table, "Debtor", self._cached_data.get("debtor_conf", [])
                    )
                    self._rendered_tabs.add("debtor_conf")
                QTimer.singleShot(0, lambda: self._auto_fit_conf_columns(self.debtor_table, force=False))
            elif conf_idx == 1:
                if "creditor_conf" not in self._rendered_tabs:
                    self._populate_creditor_table_from_data(
                        self._cached_data.get("creditor_conf", [])
                    )
                    self._rendered_tabs.add("creditor_conf")

        elif current_idx == 4:
            if "empty_ledger" not in self._rendered_tabs:
                self._populate_empty_ledger_table(self._cached_data.get("vat_debtors", []))
                self._rendered_tabs.add("empty_ledger")

    def _on_tab_changed(self, index: int):
        if getattr(self, '_staged_group_id', None) is not None and not getattr(self, '_is_destaging', False):
            self.destage_and_select()
        self._render_current_tab()

    def _on_conf_tab_changed(self, index: int):
        self._render_current_tab()
        if index == 0 and hasattr(self, 'debtor_table'):
            QTimer.singleShot(0, lambda: self._auto_fit_conf_columns(self.debtor_table, force=False))

    def _on_load_error(self, msg: str):
        """Handle background load failure gracefully."""
        self._loading_path = None
        self._load_worker = None
        logger.error(f"[BalanceUI._on_load_error] {msg}")

    def _populate_ledger_table(self, table: QTableWidget, debtors: list[dict]):
        """Fill table with only the authentic fields from Tally ledger data."""
        table.blockSignals(True)
        table.setUpdatesEnabled(False)
        table.setRowCount(len(debtors))

        for row, d in enumerate(debtors):
            for col_idx, (field_key, _, _, is_numeric) in enumerate(TALLY_LEDGER_COLUMNS):
                raw_val = d.get(field_key)
                if is_numeric:
                    is_blank = (
                        raw_val is None
                        or (isinstance(raw_val, float) and raw_val != raw_val)
                        or str(raw_val).strip().lower() in ("", "nan", "none", "null")
                    )
                    if is_blank:
                        val_str = ""
                        n_val = 0.0
                    elif field_key == "BillwiseOn":
                        try:
                            n_val = float(raw_val)
                            val_str = str(int(n_val))
                        except Exception:
                            val_str = str(raw_val)
                            n_val = 0.0
                    else:
                        try:
                            v = float(raw_val)
                            if abs(v) < 1e-9:
                                v = 0.0
                                val_str = "0.00"
                            else:
                                val_str = f"{v:,.2f}"
                            n_val = v
                        except Exception:
                            val_str = str(raw_val)
                            n_val = 0.0
                else:
                    val_str = str(raw_val or "") if raw_val is not None else ""
                    if val_str.lower() in ("none", "nan", "null"):
                        val_str = ""
                    if field_key == "Name":
                        raw_name = str(d.get("Name", "") or "").strip()
                        if raw_name.lower() in ("none", "nan", "null"):
                            raw_name = ""
                        val_str = raw_name
                    elif field_key == "Alias":
                        raw_alias = str(d.get("Alias", "") or "").strip()
                        if raw_alias.lower() in ("none", "nan", "null"):
                            raw_alias = ""
                        val_str = raw_alias

                if is_numeric:
                    item = NumericTableWidgetItem(val_str, n_val)
                else:
                    item = QTableWidgetItem(val_str)
                if field_key == "Name":
                    item.setData(Qt.ItemDataRole.UserRole, str(d.get("Name", "") or "").strip())
                    item.setData(Qt.ItemDataRole.UserRole + 1, str(d.get("Alias", "") or "").strip())

                if is_numeric:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                table.setItem(row, col_idx, item)

        table.setUpdatesEnabled(True)
        table.blockSignals(False)

        # Re-apply active search filter if present
        if table is getattr(self, 'vat_table', None):
            q = self.vat_search.text().strip() if hasattr(self, 'vat_search') else ""
            if q:
                self._filter_vat_table(q)
        elif table is getattr(self, 'int_table', None):
            q = self.int_search.text().strip() if hasattr(self, 'int_search') else ""
            if q:
                self._filter_int_table(q)

    # ── COLUMN VISIBILITY SETTINGS ───────────────────────────────────

    def get_visible_column_keys(self) -> set:
        s = QSettings("JKCatalog", "VatBalanceLedgerColumns")
        val = s.value("visible_columns", None)
        if val is None:
            return set(LedgerColumnSettingsDialog.DEFAULT_COLUMNS)
        if isinstance(val, str):
            res = set(x.strip() for x in val.split(",") if x.strip())
        elif isinstance(val, (list, set)):
            res = set(val)
        else:
            res = {c[0] for c in TALLY_LEDGER_COLUMNS}
        res.add("Name")

        # Auto-migrate old commercial columns to Debit_Totals and Credit_Totals
        old_cols = {"Sales_Amount", "Purchase_Amount", "Receipt_Amount", "Payment_Amount", "Sales_Plus_Purchase"}
        if res.intersection(old_cols):
            res.difference_update(old_cols)
            res.add("Debit_Totals")
            res.add("Credit_Totals")
            self.save_visible_column_keys(res)

        return res

    def save_visible_column_keys(self, cols: set):
        s = QSettings("JKCatalog", "VatBalanceLedgerColumns")
        s.setValue("visible_columns", ",".join(sorted(cols)))

    def apply_column_visibility(self):
        visible_cols = self.get_visible_column_keys()
        for idx, (col_key, _, _, _) in enumerate(TALLY_LEDGER_COLUMNS):
            hidden = (col_key not in visible_cols)
            if hasattr(self, 'int_table'):
                self.int_table.setColumnHidden(idx, hidden)
            if hasattr(self, 'int_footer'):
                self.int_footer.setColumnHidden(idx, hidden)
            if hasattr(self, 'vat_table'):
                self.vat_table.setColumnHidden(idx, hidden)
            if hasattr(self, 'vat_footer'):
                self.vat_footer.setColumnHidden(idx, hidden)

        is_alias_hidden = "Alias" not in visible_cols
        txt = "👁️ Show Alias" if is_alias_hidden else "👁️ Hide Alias"
        if hasattr(self, 'btn_toggle_int_alias'):
            self.btn_toggle_int_alias.setText(txt)
        if hasattr(self, 'btn_toggle_vat_alias'):
            self.btn_toggle_vat_alias.setText(txt)

    def _toggle_ledger_alias_visibility(self):
        """Toggle visibility of Alias column in Int. and VAT Ledger tables."""
        visible_cols = self.get_visible_column_keys()
        if "Alias" in visible_cols:
            visible_cols.remove("Alias")
        else:
            visible_cols.add("Alias")
        self.save_visible_column_keys(visible_cols)
        self.apply_column_visibility()
        self._update_int_totals()
        self._update_vat_totals()

    def open_column_settings_dialog(self):
        current_visible = self.get_visible_column_keys()
        dlg = LedgerColumnSettingsDialog(current_visible, self)
        if dlg.exec():
            new_visible = dlg.get_selected_columns()
            self.save_visible_column_keys(new_visible)
            self.apply_column_visibility()
            self._update_int_totals()
            self._update_vat_totals()

    def refresh_int_ledger_table(self):
        """Populate Int. Ledger table from dbo.row_ledger_data with authentic Tally fields."""
        if not self.db_name:
            self.int_table.setRowCount(0)
            self._update_int_totals()
            return
        debtors = load_internal_debtors(self.db_name)
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["int_debtors"] = debtors
        self._populate_ledger_table(self.int_table, debtors)
        self.apply_column_visibility()
        self._update_int_totals()
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("int_ledger")

    def _update_int_totals(self):
        if not hasattr(self, 'lbl_int_count') or not hasattr(self, 'int_table'):
            return

        numeric_col_indices = [
            i for i, col in enumerate(TALLY_LEDGER_COLUMNS)
            if col[3] and col[0] != "BillwiseOn"
        ]

        visible_count = 0
        totals = {idx: 0.0 for idx in numeric_col_indices}

        for r in range(self.int_table.rowCount()):
            if not self.int_table.isRowHidden(r):
                visible_count += 1
                for idx in numeric_col_indices:
                    it = self.int_table.item(r, idx)
                    if it and it.text().strip():
                        try:
                            totals[idx] += float(it.text().replace(",", ""))
                        except Exception:
                            pass

        total_rows = self.int_table.rowCount()
        if visible_count < total_rows:
            self.lbl_int_count.setText(f"<b>{visible_count}</b> / {total_rows} ledgers")
        else:
            self.lbl_int_count.setText(f"<b>{visible_count}</b> ledgers")

        if hasattr(self, 'int_footer'):
            def _fmt_tot(v):
                if abs(v) < 1e-9:
                    return "₹0.00"
                return f"-₹{abs(v):,.2f}" if v < 0 else f"₹{v:,.2f}"

            formatted_totals = {
                idx: _fmt_tot(val)
                for idx, val in totals.items()
            }
            self.int_footer.update_totals(formatted_totals, label_col=0, label_text="Grand Total")

    def refresh_vat_ledger_table(self):
        """Populate VAT Ledger table from dbo.vat_row_ledger_data with authentic Tally fields."""
        if not self.db_name or not self.active_vat_company:
            self.vat_table.setRowCount(0)
            self._update_vat_totals()
            return
        debtors = load_vat_debtors(self.db_name, self.active_vat_company)
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["vat_debtors"] = debtors
        self._populate_ledger_table(self.vat_table, debtors)
        self.apply_column_visibility()
        self._update_vat_totals()
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("vat_ledger")

    def _update_vat_totals(self):
        if not hasattr(self, 'lbl_vat_count') or not hasattr(self, 'vat_table'):
            return

        numeric_col_indices = [
            i for i, col in enumerate(TALLY_LEDGER_COLUMNS)
            if col[3] and col[0] != "BillwiseOn"
        ]

        visible_count = 0
        totals = {idx: 0.0 for idx in numeric_col_indices}

        for r in range(self.vat_table.rowCount()):
            if not self.vat_table.isRowHidden(r):
                visible_count += 1
                for idx in numeric_col_indices:
                    it = self.vat_table.item(r, idx)
                    if it and it.text().strip():
                        try:
                            totals[idx] += float(it.text().replace(",", ""))
                        except Exception:
                            pass

        total_rows = self.vat_table.rowCount()
        if visible_count < total_rows:
            self.lbl_vat_count.setText(f"<b>{visible_count}</b> / {total_rows} ledgers")
        else:
            self.lbl_vat_count.setText(f"<b>{visible_count}</b> ledgers")

        if hasattr(self, 'vat_footer'):
            def _fmt_tot(v):
                if abs(v) < 1e-9:
                    return "₹0.00"
                return f"-₹{abs(v):,.2f}" if v < 0 else f"₹{v:,.2f}"

            formatted_totals = {
                idx: _fmt_tot(val)
                for idx, val in totals.items()
            }
            self.vat_footer.update_totals(formatted_totals, label_col=0, label_text="Grand Total")

    def _update_conf_totals(self, tbl: QTableWidget, footer: TableFooterWidget, lbl_count: QLabel = None):
        """Compute and display column-aligned totals for Vat Conf (Debtor / Creditor)."""
        if not tbl or not footer:
            return

        col_op = -1
        col_deb = -1
        col_cred = -1
        col_cin = -1
        col_cout = -1
        col_cl = -1
        col_eop = -1
        col_ecl = -1
        col_name = 1
        for c in range(tbl.columnCount()):
            hi = tbl.horizontalHeaderItem(c)
            ht = hi.text().strip().lower() if hi else ""
            if ht == "opening amount":
                col_op = c
            elif ht == "debit total":
                col_deb = c
            elif ht == "credit total":
                col_cred = c
            elif ht == "cash inflow":
                col_cin = c
            elif ht == "cash outflow":
                col_cout = c
            elif ht == "closing amount":
                col_cl = c
            elif ht == "opening ?":
                col_eop = c
            elif ht == "closing ?":
                col_ecl = c
            elif ht == "name":
                col_name = c

        visible_count = 0
        tot_op = 0.0
        tot_deb = 0.0
        tot_cred = 0.0
        tot_cin = 0.0
        tot_cout = 0.0
        tot_cl = 0.0
        tot_exp_op = 0.0
        tot_exp_cl = 0.0

        for r in range(tbl.rowCount()):
            if not tbl.isRowHidden(r):
                visible_count += 1
                for c_idx, val_key in [
                    (col_op, 'op'), (col_deb, 'deb'), (col_cred, 'cred'),
                    (col_cin, 'cin'), (col_cout, 'cout'), (col_cl, 'cl'),
                    (col_eop, 'eop'), (col_ecl, 'ecl')
                ]:
                    if c_idx >= 0:
                        it = tbl.item(r, c_idx)
                        if it and it.text().strip():
                            try:
                                v = float(it.text().replace(",", ""))
                                if val_key == 'op': tot_op += v
                                elif val_key == 'deb': tot_deb += v
                                elif val_key == 'cred': tot_cred += v
                                elif val_key == 'cin': tot_cin += v
                                elif val_key == 'cout': tot_cout += v
                                elif val_key == 'cl': tot_cl += v
                                elif val_key == 'eop': tot_exp_op += v
                                elif val_key == 'ecl': tot_exp_cl += v
                            except Exception:
                                pass

        def _fmt(val):
            if abs(val) < 1e-9:
                return "₹0.00"
            return f"-₹{abs(val):,.2f}" if val < 0 else f"₹{val:,.2f}"

        totals_dict = {}
        if col_op >= 0:
            totals_dict[col_op] = _fmt(tot_op)
        if col_deb >= 0:
            totals_dict[col_deb] = _fmt(tot_deb)
        if col_cred >= 0:
            totals_dict[col_cred] = _fmt(tot_cred)
        if col_cin >= 0:
            totals_dict[col_cin] = _fmt(tot_cin)
        if col_cout >= 0:
            totals_dict[col_cout] = _fmt(tot_cout)
        if col_cl >= 0:
            totals_dict[col_cl] = _fmt(tot_cl)
        if col_eop >= 0 and tot_exp_op != 0.0:
            totals_dict[col_eop] = _fmt(tot_exp_op)
        if col_ecl >= 0 and tot_exp_cl != 0.0:
            totals_dict[col_ecl] = _fmt(tot_exp_cl)

        for c in range(tbl.columnCount()):
            footer.setColumnHidden(c, tbl.isColumnHidden(c))
        footer.update_totals(totals_dict, label_col=col_name, label_text="Grand Total")
        if lbl_count:
            total_rows = tbl.rowCount()
            if visible_count < total_rows:
                lbl_count.setText(f"<b>{visible_count}</b> / {total_rows} records")
            else:
                lbl_count.setText(f"<b>{visible_count}</b> records")

    def _header_text_to_col_key(self, header_text: str) -> str:
        ht = (header_text or "").strip().lower()
        mapping = {
            "sn.": "sn",
            "name": "name",
            "pan no.": "pan_no",
            "alias": "alias",
            "opening amount": "opening_amount",
            "debit total": "debit_totals",
            "credit total": "credit_totals",
            "cash inflow": "cash_in",
            "cash outflow": "cash_out",
            "closing amount": "closing_amount",
            "need print ?": "need_print",
            "did you print": "did_you_print",
            "sub group": "sub_group",
            "crm": "crm",
            "get back": "get_back",
            "opening ?": "expected_opening",
            "closing ?": "expected_closing",
        }
        return mapping.get(ht, ht)

    def get_vat_conf_visible_columns(self) -> set:
        s = QSettings("JKCatalog", "VatConfDebtorColumns")
        val = s.value("visible_columns", None)
        if val is None:
            return {c[0] for c in VAT_CONF_DEBTOR_COLUMNS if c[2]}
        if isinstance(val, str):
            res = set(x.strip() for x in val.split(",") if x.strip())
        elif isinstance(val, (list, set)):
            res = set(val)
        else:
            res = {c[0] for c in VAT_CONF_DEBTOR_COLUMNS if c[2]}
        res.add("name")
        return res

    def save_vat_conf_visible_columns(self, cols: set):
        s = QSettings("JKCatalog", "VatConfDebtorColumns")
        s.setValue("visible_columns", ",".join(sorted(cols)))

    def apply_vat_conf_column_visibility(self):
        if not hasattr(self, 'debtor_table') or not self.debtor_table:
            return
        visible_keys = self.get_vat_conf_visible_columns()
        tbl = self.debtor_table
        for c in range(tbl.columnCount()):
            hi = tbl.horizontalHeaderItem(c)
            ht = hi.text().strip().lower() if hi else ""
            col_key = self._header_text_to_col_key(ht)
            is_hidden = col_key not in visible_keys
            tbl.setColumnHidden(c, is_hidden)
            if hasattr(self, 'debtor_footer') and self.debtor_footer:
                self.debtor_footer.setColumnHidden(c, is_hidden)

        is_alias_hidden = "alias" not in visible_keys
        if hasattr(self, 'btn_toggle_debtor_alias'):
            self.btn_toggle_debtor_alias.setText("Show Alias" if is_alias_hidden else "Hide Alias")

        if hasattr(self, 'debtor_footer'):
            self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))

    def _open_debtor_columns_dialog(self):
        cur_visible = self.get_vat_conf_visible_columns()
        dlg = VatConfColumnSettingsDialog(
            current_visible=cur_visible,
            on_autofit_callback=lambda: self._auto_fit_conf_columns(self.debtor_table, force=True),
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_cols = dlg.get_selected_columns()
            self.save_vat_conf_visible_columns(new_cols)
            self.apply_vat_conf_column_visibility()
            self._auto_fit_conf_columns(self.debtor_table, force=False)

    def _on_debtor_header_resized(self, logical_index: int, old_size: int, new_size: int):
        if getattr(self, '_is_programmatic_col_resize', False):
            return
        tbl = getattr(self, 'debtor_table', None)
        if not tbl:
            return
        hi = tbl.horizontalHeaderItem(logical_index)
        if not hi:
            return
        h_key = hi.text().strip().lower()
        s = QSettings("JKCatalog", "VatConfDebtorColumnWidths")
        saved_str = str(s.value("widths", "") or "")
        saved_widths = {}
        if saved_str:
            try:
                for part in saved_str.split(";"):
                    if ":" in part:
                        k, w = part.split(":", 1)
                        saved_widths[k.strip().lower()] = int(w.strip())
            except Exception:
                saved_widths = {}
        saved_widths[h_key] = new_size
        s.setValue("widths", ";".join(f"{k}:{w}" for k, w in saved_widths.items()))

    def _make_conf_amount_item(self, amt) -> NumericTableWidgetItem:
        is_blank = (
            amt is None
            or (isinstance(amt, float) and amt != amt)
            or str(amt).strip().lower() in ("", "nan", "none", "null")
        )
        if is_blank:
            it = NumericTableWidgetItem("", 0.0)
        else:
            f = 0.0 if abs(float(amt)) < 1e-9 else float(amt)
            it = NumericTableWidgetItem(f"{f:,.2f}", f)
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return it

    def _toggle_conf_alias_visibility(self):
        """Toggle visibility of Alias column in Debtor Vat Conf table."""
        visible_cols = self.get_vat_conf_visible_columns()
        if "alias" in visible_cols:
            visible_cols.remove("alias")
        else:
            visible_cols.add("alias")
        self.save_vat_conf_visible_columns(visible_cols)
        self.apply_vat_conf_column_visibility()

    def _toggle_mapping_alias_visibility(self):
        """Toggle visibility of VAT Alias (Col 2) and Internal Alias (Col 4) in Mapping table."""
        self._hide_mapping_alias = not getattr(self, '_hide_mapping_alias', False)
        if hasattr(self, 'mapping_table'):
            self.mapping_table.setColumnHidden(2, self._hide_mapping_alias)
            self.mapping_table.setColumnHidden(4, self._hide_mapping_alias)
        txt = "👁️ Show Alias" if self._hide_mapping_alias else "👁️ Hide Alias"
        if hasattr(self, 'btn_toggle_mapping_alias'):
            self.btn_toggle_mapping_alias.setText(txt)

    def _toggle_pending_chq_visibility(self):
        """Toggle visibility of Pending Chq. (Column 5) in Mapping table."""
        self._hide_pending_chq = not getattr(self, '_hide_pending_chq', False)
        if hasattr(self, 'mapping_table'):
            self.mapping_table.setColumnHidden(5, self._hide_pending_chq)
        if hasattr(self, 'mapping_footer'):
            self.mapping_footer.sync_columns()
        txt = "👁️ Show Pending Chq." if self._hide_pending_chq else "👁️ Hide Pending Chq."
        if hasattr(self, 'btn_toggle_pending_chq'):
            self.btn_toggle_pending_chq.setText(txt)
        settings = QSettings("JKCatalog", "VatBalanceMappingColumns")
        settings.setValue("hide_pending_chq", self._hide_pending_chq)

    def _show_mapping_header_context_menu(self, pos):
        """Right-click context menu on Mapping table header to toggle column visibility."""
        menu = QMenu(self)
        act_toggle_chq = menu.addAction(
            "👁️ Show Pending Chq. Column" if getattr(self, '_hide_pending_chq', False) else "👁️ Hide Pending Chq. Column"
        )
        act_toggle_chq.triggered.connect(self._toggle_pending_chq_visibility)
        menu.exec(self.mapping_table.horizontalHeader().viewport().mapToGlobal(pos))

    def refresh_mapping_table(self, select_group_id: int = 0, async_load: bool = True):
        """Populate Mapping table and Unassigned Internal Ledgers panel for active VAT company."""
        if hasattr(self, '_active_inline_cleanup') and callable(self._active_inline_cleanup):
            self._active_inline_cleanup()
            self._active_inline_cleanup = None

        if not self.db_name or not self.active_vat_company:
            self.mapping_table.setRowCount(0)
            if hasattr(self, 'unassigned_list'):
                self.unassigned_list.clear()
            if hasattr(self, 'lbl_unmapped_badge'):
                self.lbl_unmapped_badge.setVisible(False)
            return

        if async_load:
            # Stop any in-flight mapping worker
            if hasattr(self, '_mapping_refresh_worker') and self._mapping_refresh_worker and self._mapping_refresh_worker.isRunning():
                try:
                    self._mapping_refresh_worker.finished.disconnect()
                except Exception:
                    pass
                self._mapping_refresh_worker.quit()
                self._mapping_refresh_worker.wait(200)

            self._mapping_refresh_worker = _MappingRefreshWorker(
                self.db_name, self.active_vat_company, select_group_id=select_group_id, parent=self
            )
            self._mapping_refresh_worker.finished.connect(self._on_mapping_refreshed)
            self._mapping_refresh_worker.start()
        else:
            mappings = load_vat_mappings(self.db_name, self.active_vat_company)
            unassigned_int = get_unassigned_internal_debtors(self.db_name, self.active_vat_company)
            self._on_mapping_refreshed(mappings, unassigned_int, select_group_id)

    def _on_mapping_refreshed(self, mappings: list, unassigned_int: list, select_group_id: int = 0):
        """Handle refreshed mapping data on UI thread."""
        scroll_val = self.mapping_table.verticalScrollBar().value()
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["mappings"] = mappings
        self._cached_data["unassigned_int"] = unassigned_int
        self._is_populating_mapping = True
        try:
            self._populate_mapping_from_data(mappings)
            self._populate_unassigned_list(unassigned_int)
            if hasattr(self, '_rendered_tabs'):
                self._rendered_tabs.add("mapping")

            if select_group_id:
                found = False
                for r in range(self.mapping_table.rowCount()):
                    if self.mapping_table.isRowHidden(r):
                        continue
                    it = self.mapping_table.item(r, 0)
                    if it:
                        r_gid = it.data(Qt.ItemDataRole.UserRole)
                        is_match = False
                        try:
                            is_match = (r_gid is not None) and (int(r_gid) == int(select_group_id))
                        except (ValueError, TypeError):
                            is_match = (r_gid == select_group_id)

                        if is_match:
                            if getattr(self, '_staged_group_id', None) is not None:
                                self.mapping_table.selectRow(r)
                                self.mapping_table.setCurrentCell(r, 0)
                                self.mapping_table.verticalScrollBar().setValue(scroll_val)
                            else:
                                self.mapping_table.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                                self.mapping_table.selectRow(r)
                                self.mapping_table.setCurrentCell(r, 0)
                        self.mapping_table.setFocus()
                        found = True
                        break
                if not found:
                    self.mapping_table.verticalScrollBar().setValue(scroll_val)
            else:
                self.mapping_table.verticalScrollBar().setValue(scroll_val)
        finally:
            self._is_populating_mapping = False

    def _populate_mapping_from_data(self, mappings: list):
        """Fill mapping table with 6 columns:
        0: Serial No.
        1: VAT Ledger Name (with '+' button)
        2: Internal Ledger Name (with '+' button)
        3: Vat Closing (integer rounded)
        4: Int. Closing (integer rounded)
        5: balance
        """
        self.mapping_table.blockSignals(True)
        self.mapping_table.setUpdatesEnabled(False)
        self.mapping_table.viewport().setUpdatesEnabled(False)
        self.mapping_table.clearSpans()

        filtered_mappings = list(mappings)

        staged_gid = getattr(self, '_staged_group_id', None)
        staged_prior_idx = getattr(self, '_staged_prior_index', None)
        if staged_gid is not None and staged_prior_idx is not None:
            staged_curr_idx = None
            for idx, m in enumerate(filtered_mappings):
                m_gid = m.get("group_id") or m.get("id")
                try:
                    if (m_gid is not None) and (int(m_gid) == int(staged_gid)):
                        staged_curr_idx = idx
                        break
                except (ValueError, TypeError):
                    if str(m_gid) == str(staged_gid):
                        staged_curr_idx = idx
                        break
            if staged_curr_idx is not None:
                staged_m = filtered_mappings.pop(staged_curr_idx)
                target_insert_idx = min(max(0, staged_prior_idx), len(filtered_mappings))
                filtered_mappings.insert(target_insert_idx, staged_m)

        total_rows = 0
        group_specs = []
        unmapped_count = 0

        for m in filtered_mappings:
            vat_items = m.get("vat_items", [])
            internal_items = m.get("internal_items", [])

            if not vat_items and m.get("vat_ledger"):
                vat_items = [{
                    "id": m.get("id"),
                    "name": m.get("vat_ledger"),
                    "alias": "",
                    "closing": 0.0,
                    "serial_no": m.get("serial_no", 0),
                    "classification": m.get("classification", "")
                }]
            if not internal_items and m.get("internal_ledger"):
                internal_items = [{
                    "id": m.get("id"),
                    "name": m.get("internal_ledger"),
                    "alias": "",
                    "closing": 0.0,
                    "pending_chq": float(m.get("pending_chq", 0.0) or 0.0),
                }]

            n_rows = max(len(vat_items), len(internal_items), 1)
            group_specs.append((m, vat_items, internal_items, n_rows))
            total_rows += n_rows

            is_placeholder_assigned = any(
                str(ii.get("name", "")).strip().lower() in ("cash sales", "old party") for ii in internal_items
            ) or str(m.get("classification", "")).strip().lower() in ("cash sales", "old party")

            is_unmapped = (m.get("is_unmapped", False) or not internal_items) and not is_placeholder_assigned
            if is_unmapped and not m.get("is_none_vat", False):
                unmapped_count += 1

        self.mapping_table.setRowCount(total_rows)
        self.mapping_table._combined_group_ranges = []

        cur_row = 0
        for grp_idx, (m, vat_items, internal_items, n_rows) in enumerate(group_specs, start=1):
            start_row = cur_row
            group_id = m.get("group_id", 0) or m.get("id", 0)
            is_placeholder_assigned = any(
                str(ii.get("name", "")).strip().lower() in ("cash sales", "old party") for ii in internal_items
            ) or str(m.get("classification", "")).strip().lower() in ("cash sales", "old party")
            is_unmapped = (m.get("is_unmapped", False) or not internal_items) and not is_placeholder_assigned
            is_merged = m.get("is_merged", False) or (len(vat_items) > 1)
            is_none_vat = m.get("is_none_vat", False) or (str(m.get("vat_ledger", "")).strip().lower() == "none")
            staged_check_gid = getattr(self, '_staged_group_id', None)
            is_staged = False
            if staged_check_gid is not None:
                try:
                    is_staged = (int(group_id) == int(staged_check_gid))
                except (ValueError, TypeError):
                    is_staged = (str(group_id) == str(staged_check_gid))

            # Collect all distinct positive serial numbers for this merged/single group
            sn_values = [v.get("serial_no") for v in vat_items if v.get("serial_no") and v.get("serial_no") > 0]
            if not sn_values and m.get("serial_no"):
                sn_values = [m.get("serial_no")]
            primary_sn = sn_values[0] if sn_values else (m.get("serial_no") or 0)
            primary_vname = vat_items[0].get("name", "") if vat_items else m.get("vat_ledger", "")

            # Evaluate manual matching & name similarity
            is_manual = bool(m.get("is_manual", False)) or is_placeholder_assigned
            is_dissimilar = False
            if not is_unmapped and not is_none_vat:
                is_similar = _are_group_names_sufficiently_similar(vat_items, internal_items, m)
                if not is_similar:
                    is_dissimilar = True

            # Colour coding logic:
            # 1. Combined VAT ledger names (multi-name merge): distinct soft violet/lavender container
            # 2. Unmatched records: soft red
            # 3. Reserved None VAT: soft slate
            # 4. Records whose names are NOT sufficiently similar (e.g. cross-mapped or placeholder): soft amber / warm cream
            # 5. Automatically matched records & manually matched records with almost identical names: clean white / alternating slate
            if is_merged:
                # Combined VAT ledger names: distinct soft violet/lavender container
                bg_color = QColor("#ede9fe")
                fg_color = QColor("#4c1d95")
            elif is_unmapped and not is_none_vat:
                bg_color = QColor("#fef2f2")
                fg_color = QColor("#991b1b")
            elif is_none_vat:
                bg_color = QColor("#f8fafc")
                fg_color = QColor("#64748b")
            elif is_dissimilar:
                # Soft amber highlight with high-contrast text (> 10:1)
                bg_color = QColor("#fef3c7") if (grp_idx % 2 == 1) else QColor("#fffbeb")
                fg_color = QColor("#78350f")
            else:
                bg_color = QColor("#ffffff") if (grp_idx % 2 == 1) else QColor("#f8fafc")
                fg_color = QColor("#0f172a")

            if n_rows > 1:
                # Any multi-row mapping group (merged VAT or multi-internal) gets the Card enclosure with dark borders
                if is_merged:
                    # Combined VAT ledger names: prominent dark violet border with deep purple accent
                    border_color = QColor("#4c1d95")
                    accent_color = QColor("#6d28d9")
                elif is_dissimilar:
                    border_color = QColor("#b45309")
                    accent_color = QColor("#d97706")
                else:
                    # Multi-internal mapping: prominent dark blue border with ocean accent
                    border_color = QColor("#0369a1")
                    accent_color = QColor("#0284c7")

                self.mapping_table._combined_group_ranges.append(
                    (start_row, n_rows, bg_color, border_color, accent_color)
                )
            # Option A: Group Total Comparison for multi-ledger mappings (1*N, N*1, N*M)
            grp_vat_closing = sum(float(v.get("closing", 0.0) or 0.0) for v in vat_items)
            grp_int_closing = sum(float(i.get("closing", 0.0) or 0.0) for i in internal_items)
            grp_pending_chq = sum(float(i.get("pending_chq", 0.0) or 0.0) for i in internal_items)

            grp_bal_str = ""
            grp_bal_val = 0.0
            grp_neg_str = ""
            grp_neg_val = 0.0

            raw_bal = 0.0
            raw_neg = 0.0

            if grp_vat_closing < -1e-9 and grp_int_closing < -1e-9:
                # Rule 0: Both columns negative -> sum (A + B) displayed in Negative column, balance blank
                raw_neg = abs(grp_vat_closing + grp_int_closing)
                diff_neg_rounded = round_nearest_1000(raw_neg)
                grp_neg_str = f"{diff_neg_rounded:,}"
                grp_neg_val = float(diff_neg_rounded)
            elif grp_vat_closing < -1e-9:
                # Rule 1: Only Vat closing is negative -> balance blank, negative shows nearest 1,000 of abs(vat closing)
                raw_neg = abs(grp_vat_closing)
                diff_neg_rounded = round_nearest_1000(raw_neg)
                grp_neg_str = f"{diff_neg_rounded:,}"
                grp_neg_val = float(diff_neg_rounded)
            elif grp_int_closing < -1e-9:
                # Rule 2: Vat closing >= 0 and Int closing < 0 -> treat int as 0, balance shows vat closing
                raw_bal = grp_vat_closing
            elif grp_int_closing > grp_vat_closing + 1e-9:
                # Rule 3: Both non-negative, Int closing > Vat closing -> negative shows nearest 1,000 of abs(vat - int)
                raw_neg = abs(grp_vat_closing - grp_int_closing)
                diff_neg_rounded = round_nearest_1000(raw_neg)
                grp_neg_str = f"{diff_neg_rounded:,}"
                grp_neg_val = float(diff_neg_rounded)
            elif grp_vat_closing > grp_int_closing + 1e-9:
                # Rule 4: Both non-negative, Vat closing > Int closing -> balance shows nearest 1,000 of (vat - int)
                raw_bal = grp_vat_closing - grp_int_closing

            # Add pending cheques to Balance matched with int ledger (as confirmed by user)
            if not is_unmapped and grp_pending_chq > 0:
                raw_bal += grp_pending_chq

            if raw_bal > 0:
                diff_bal_rounded = round_nearest_1000(raw_bal)
                if diff_bal_rounded > 0:
                    grp_bal_str = f"{diff_bal_rounded:,}"
                    grp_bal_val = float(diff_bal_rounded)

            for k in range(n_rows):
                r = start_row + k

                # 0: Serial No. (Primary row shows single SN, merged sub-rows show clean sub_sn)
                if is_merged:
                    if k == 0:
                        sn_str = str(primary_sn) if primary_sn else ""
                        sn_val = float(primary_sn or 0)
                    else:
                        sub_sn = vat_items[k].get("serial_no") if k < len(vat_items) else 0
                        sn_str = str(sub_sn) if sub_sn else ""
                        sn_val = float(sub_sn or primary_sn or 0)
                else:
                    if k < len(vat_items):
                        v_item = vat_items[k]
                        sn_val = v_item.get("serial_no") or m.get("serial_no", 0)
                        sn_str = str(sn_val) if sn_val else ""
                    elif k == 0 and is_unmapped:
                        sn_val = m.get("serial_no", 0)
                        sn_str = str(sn_val) if sn_val else ""
                    else:
                        sn_val = 0
                        sn_str = ""

                it_sn = NumericTableWidgetItem(sn_str, float(sn_val))
                it_sn.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_sn.setBackground(bg_color)
                it_sn.setForeground(fg_color)
                it_sn.setData(Qt.ItemDataRole.UserRole, group_id)
                it_sn.setData(Qt.ItemDataRole.UserRole + 7, primary_vname)
                it_sn.setData(Qt.ItemDataRole.UserRole + 8, primary_sn)
                it_sn._mapping_group = m
                it_sn.setFlags(it_sn.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if (is_unmapped and not is_none_vat) or is_merged or is_staged or is_dissimilar:
                    f = it_sn.font()
                    f.setBold(True)
                    it_sn.setFont(f)
                self.mapping_table.setItem(r, 0, it_sn)

                # 1: VAT Ledger Name (with '+' button)
                if k < len(vat_items):
                    v_item = vat_items[k]
                    raw_vname = v_item.get("name", "")
                    v_alias = v_item.get("alias", "")
                    v_cls = v_item.get("classification") or (m.get("classification", "") if is_unmapped else "")
                    v_closing = float(v_item.get("closing", 0.0) or 0.0)
                    v_name = raw_vname
                else:
                    raw_vname = ""
                    v_alias = ""
                    v_name = ""
                    v_cls = ""
                    v_closing = 0.0

                if not v_alias and v_name:
                    v_alias = self._vat_alias_map.get(" ".join(v_name.split()).lower(), "")

                it_vl = QTableWidgetItem(v_name)
                it_vl.setBackground(bg_color)
                it_vl.setForeground(fg_color)
                it_vl.setData(Qt.ItemDataRole.UserRole, group_id)
                it_vl.setData(Qt.ItemDataRole.UserRole + 1, v_alias)
                it_vl.setData(Qt.ItemDataRole.UserRole + 2, v_name)
                it_vl.setData(Qt.ItemDataRole.UserRole + 3, "")  # No classification tag inside VAT ledger name
                it_vl.setData(Qt.ItemDataRole.UserRole + 4, bool(raw_vname) and not is_none_vat)
                it_vl.setData(Qt.ItemDataRole.UserRole + 6, is_merged)
                it_vl.setData(Qt.ItemDataRole.UserRole + 7, primary_vname)
                it_vl.setData(Qt.ItemDataRole.UserRole + 8, primary_sn)
                it_vl._mapping_group = m
                it_vl.setFlags(it_vl.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if is_merged and k == 0:
                    f_vl = it_vl.font()
                    f_vl.setBold(True)
                    it_vl.setFont(f_vl)
                self.mapping_table.setItem(r, 1, it_vl)

                # 2: Internal Ledger Name (with '+' button)
                if k < len(internal_items):
                    i_item = internal_items[k]
                    i_name = i_item.get("name", "")
                    i_alias = i_item.get("alias", "")
                    i_closing = float(i_item.get("closing", 0.0) or 0.0)
                else:
                    i_name = ""
                    i_alias = ""
                    i_closing = 0.0

                if not i_alias and i_name:
                    i_alias = self._int_alias_map.get(" ".join(i_name.split()).lower(), "")

                it_il = QTableWidgetItem(i_name)
                it_il.setBackground(bg_color)
                it_il.setForeground(fg_color)
                it_il.setData(Qt.ItemDataRole.UserRole, group_id)
                it_il.setData(Qt.ItemDataRole.UserRole + 1, i_alias)
                it_il.setData(Qt.ItemDataRole.UserRole + 2, i_name)
                it_il.setData(Qt.ItemDataRole.UserRole + 4, True)
                it_il.setData(Qt.ItemDataRole.UserRole + 7, primary_vname)
                it_il.setData(Qt.ItemDataRole.UserRole + 8, primary_sn)
                placeholder = "Click + to add internal ledger" if (is_unmapped and k == 0 and not i_name) else ""
                it_il.setData(Qt.ItemDataRole.UserRole + 5, placeholder)
                it_il._mapping_group = m
                it_il.setFlags(it_il.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 2, it_il)

                # 3: Vat Closing (Integer rounded, no decimals)
                if v_name:
                    v_close_str = f"{int(round(v_closing)):,}"
                else:
                    v_close_str = ""

                it_vc = NumericTableWidgetItem(v_close_str, v_closing)
                it_vc.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_vc.setBackground(bg_color)
                it_vc.setForeground(fg_color)
                it_vc.setData(Qt.ItemDataRole.UserRole, group_id)
                it_vc.setFlags(it_vc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 3, it_vc)

                # 4: Int. Closing (Integer rounded, no decimals)
                if i_name:
                    i_close_str = f"{int(round(i_closing)):,}"
                else:
                    i_close_str = ""

                it_ic = NumericTableWidgetItem(i_close_str, i_closing)
                it_ic.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_ic.setBackground(bg_color)
                it_ic.setForeground(fg_color)
                it_ic.setData(Qt.ItemDataRole.UserRole, group_id)
                it_ic.setFlags(it_ic.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 4, it_ic)

                # 5: Pending Chq.
                if k < len(internal_items):
                    i_chq = float(internal_items[k].get("pending_chq", 0.0) or 0.0)
                    chq_str = f"{int(round(i_chq)):,}" if i_chq > 0 else ""
                    chq_val = i_chq
                else:
                    chq_str = ""
                    chq_val = 0.0

                it_chq = NumericTableWidgetItem(chq_str, chq_val)
                it_chq.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_chq.setBackground(bg_color)
                it_chq.setForeground(fg_color)
                it_chq.setData(Qt.ItemDataRole.UserRole, group_id)
                it_chq.setFlags(it_chq.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 5, it_chq)

                # 6: Balance (Option A: Shown on primary row k == 0; sub-rows left blank)
                bal_str = grp_bal_str if k == 0 else ""
                bal_val = grp_bal_val if k == 0 else 0.0

                it_bal = NumericTableWidgetItem(bal_str, bal_val)
                it_bal.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_bal.setBackground(bg_color)
                it_bal.setForeground(fg_color)
                it_bal.setData(Qt.ItemDataRole.UserRole, group_id)
                it_bal.setFlags(it_bal.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 6, it_bal)

                # 7: Negative (Option A: Shown on primary row k == 0; sub-rows left blank)
                neg_str = grp_neg_str if k == 0 else ""
                neg_val = grp_neg_val if k == 0 else 0.0

                it_neg = NumericTableWidgetItem(neg_str, neg_val)
                it_neg.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it_neg.setBackground(bg_color)
                it_neg.setForeground(fg_color)
                it_neg.setData(Qt.ItemDataRole.UserRole, group_id)
                it_neg.setFlags(it_neg.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 7, it_neg)

                # 8: Narration (Shown on primary row k == 0; sub-rows left blank)
                narr_str = str(m.get("narration") or "").strip() if k == 0 else ""
                it_narr = QTableWidgetItem(narr_str)
                it_narr.setBackground(bg_color)
                it_narr.setForeground(fg_color)
                it_narr.setData(Qt.ItemDataRole.UserRole, group_id)
                if k == 0 and self._can_edit:
                    it_narr.setFlags(it_narr.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                else:
                    it_narr.setFlags(it_narr.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 8, it_narr)

            cur_row += n_rows

        self.mapping_table.setColumnHidden(5, getattr(self, '_hide_pending_chq', False))
        if hasattr(self, 'mapping_footer'):
            self.mapping_footer.sync_columns()

        self.mapping_table.viewport().setUpdatesEnabled(True)
        self.mapping_table.setUpdatesEnabled(True)
        self.mapping_table.blockSignals(False)
        self.mapping_table.viewport().update()

        # Update Unmapped VAT badge
        if hasattr(self, 'lbl_unmapped_badge'):
            if unmapped_count > 0:
                self.lbl_unmapped_badge.setText(f"🔴 {unmapped_count} Unmapped")
                self.lbl_unmapped_badge.setVisible(True)
            else:
                self.lbl_unmapped_badge.setVisible(False)

        # Update button states
        self._on_mapping_selection_changed()

        # Re-apply active search filter if present (preserves filter state across data refreshes/sorts)
        q = self.mapping_search.text().strip() if hasattr(self, 'mapping_search') else ""
        if q:
            self._filter_mapping_table(q)
        else:
            self._update_mapping_totals()

    def _populate_unassigned_list(self, unassigned_items: list = None):
        """Populate the right-side Unassigned Internal Ledgers list."""
        if not hasattr(self, 'unassigned_list'):
            return

        if unassigned_items is None:
            if hasattr(self, '_cached_data') and self._cached_data and "unassigned_int" in self._cached_data:
                unassigned_items = self._cached_data.get("unassigned_int", [])
            elif self.db_name and self.active_vat_company:
                unassigned_items = get_unassigned_internal_debtors(self.db_name, self.active_vat_company)
            else:
                unassigned_items = []

        self._cached_unassigned = unassigned_items or []
        query = self.unassigned_search.text().strip().lower() if hasattr(self, 'unassigned_search') else ""

        self.unassigned_list.blockSignals(True)
        self.unassigned_list.clear()

        for entry in self._cached_unassigned:
            if isinstance(entry, dict):
                name = (entry.get("Name") or "").strip()
                alias = (entry.get("Alias") or "").strip()
                cls = (entry.get("Classification") or "").strip()
            else:
                name = str(entry).strip()
                alias = ""
                cls = ""

            if name.lower() in ("none", "nan", "null"):
                name = ""
            if alias.lower() in ("none", "nan", "null"):
                alias = ""

            if not alias and name:
                alias = self._int_alias_map.get(" ".join(name.split()).lower(), "")

            if not name:
                continue

            if query:
                match = (query in name.lower()) or (query in alias.lower()) or (query in cls.lower())
                if not match:
                    continue

            display_txt = f"{name} • {cls}" if cls else name
            item = QListWidgetItem(display_txt)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.UserRole + 1, alias)
            item.setData(Qt.ItemDataRole.UserRole + 2, cls)
            if cls:
                item.setForeground(QColor("#4338ca") if cls.lower() == "cash sales" else QColor("#b45309"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.unassigned_list.addItem(item)

        self.unassigned_list.blockSignals(False)

        count_total = len(self._cached_unassigned)
        if hasattr(self, 'lbl_unassigned_count'):
            self.lbl_unassigned_count.setText(str(count_total))

        if hasattr(self, 'btn_toggle_unassigned'):
            arrow = "❯" if hasattr(self, 'unassigned_panel') and self.unassigned_panel.isVisible() else "❮"
            self.btn_toggle_unassigned.setText(f"📋 Unassigned ({count_total}) {arrow}")

        self._on_unassigned_selection_changed()

    def refresh_vat_conf_tables(self):
        """Populate Debtor and Creditor Vat Conf tables."""
        if not self.db_name or not self.active_vat_company:
            self.debtor_table.setRowCount(0)
            self.creditor_table.setRowCount(0)
            return
        d_rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, "Debtor")
        c_rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, "Creditor")
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["debtor_conf"] = d_rows
        self._cached_data["creditor_conf"] = c_rows
        self._populate_vat_conf_table_from_data(self.debtor_table, "Debtor", d_rows)
        self._populate_creditor_table_from_data(c_rows)
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("debtor_conf")
            self._rendered_tabs.add("creditor_conf")

    def _populate_vat_conf_table(self, tbl: QTableWidget, group_type: str):
        """Fetch conf data from DB and populate the table (sync path)."""
        if not self.db_name or not self.active_vat_company:
            tbl.setRowCount(0)
            if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
                self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
            elif group_type == "Creditor":
                self._apply_creditor_filters()
            return

        rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, group_type)
        if group_type == "Creditor":
            self._populate_creditor_table_from_data(rows)
            return
        self._populate_vat_conf_table_from_data(tbl, group_type, rows)

    def _populate_vat_conf_table_from_data(self, tbl: QTableWidget, group_type: str, rows: list):
        """Populate Debtor or Creditor Vat Conf table from pre-fetched rows."""
        tbl.blockSignals(True)
        tbl.setUpdatesEnabled(False)
        try:
            if str(group_type).lower() == "debtor":
                # Default sort: Need Print == 'Yes' first, then 'No', then alphabetically by Name
                rows.sort(
                    key=lambda r: (
                        0 if (r.get("need_print") or "").strip().lower() == "yes" else 1,
                        (r.get("name") or "").strip().lower()
                    )
                )

            tbl.setRowCount(len(rows))

            for r_idx, r in enumerate(rows):
                # 0: SN. (Numeric-sorted cartoon number)
                it_sn = SnTableWidgetItem(r.get("sn", ""))
                it_sn.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not self._can_edit:
                    it_sn.setFlags(it_sn.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 0, it_sn)

                # 1: Name (Read-only)
                raw_name = (r.get("name") or "").strip()
                if raw_name.lower() in ("none", "nan", "null"):
                    raw_name = ""
                it_name = QTableWidgetItem(raw_name)
                it_name.setData(Qt.ItemDataRole.UserRole, raw_name)
                it_name.setFlags(it_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 1, it_name)

                # 2: Pan No. (Read-only, centered)
                raw_pan = (r.get("pan_no") or "").strip()
                if raw_pan.lower() in ("none", "nan", "null"):
                    raw_pan = ""
                it_pan = QTableWidgetItem(raw_pan)
                it_pan.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_pan.setFlags(it_pan.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 2, it_pan)

                # 3: Alias (Read-only)
                raw_alias = (r.get("alias") or "").strip()
                if raw_alias.lower() in ("none", "nan", "null"):
                    raw_alias = ""
                it_alias = QTableWidgetItem(raw_alias)
                it_alias.setData(Qt.ItemDataRole.UserRole, raw_alias)
                it_alias.setFlags(it_alias.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 3, it_alias)

                # 4: Opening Amount (Read-only, right-aligned)
                tbl.setItem(r_idx, 4, self._make_conf_amount_item(r.get("opening_amount")))

                # 5: Debit Total (Read-only, right-aligned)
                tbl.setItem(r_idx, 5, self._make_conf_amount_item(r.get("debit_totals")))

                # 6: Credit Total (Read-only, right-aligned)
                tbl.setItem(r_idx, 6, self._make_conf_amount_item(r.get("credit_totals")))

                # 7: Cash Inflow (Read-only, right-aligned)
                tbl.setItem(r_idx, 7, self._make_conf_amount_item(r.get("cash_in")))

                # 8: Cash Outflow (Read-only, right-aligned)
                tbl.setItem(r_idx, 8, self._make_conf_amount_item(r.get("cash_out")))

                # 9: Closing Amount (Read-only, right-aligned)
                tbl.setItem(r_idx, 9, self._make_conf_amount_item(r.get("closing_amount")))

                # 10: Need Print ? (Read-only, centered, Yes-first sort)
                it_np = YesNoTableWidgetItem(r.get("need_print", ""))
                it_np.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if r.get("need_print") == "Yes":
                    it_np.setForeground(QColor("#059669"))
                    font = it_np.font()
                    font.setBold(True)
                    it_np.setFont(font)
                it_np.setFlags(it_np.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 10, it_np)

                # 11: Did You Print (Editable Yes/No/No Need)
                it_dyp = YesNoTableWidgetItem(r.get("did_you_print", ""))
                it_dyp.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not self._can_edit:
                    it_dyp.setFlags(it_dyp.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 11, it_dyp)

                # 12: Sub Group (Read-only)
                raw_sg = (r.get("sub_group") or "").strip()
                if raw_sg.lower() in ("none", "nan", "null"):
                    raw_sg = ""
                it_sg = QTableWidgetItem(raw_sg)
                it_sg.setFlags(it_sg.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 12, it_sg)

                # 13: CRM (Editable autocomplete)
                it_crm = QTableWidgetItem(r.get("crm", ""))
                if not self._can_edit:
                    it_crm.setFlags(it_crm.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 13, it_crm)

                # 14: Get Back (Editable Yes/No/N/A)
                it_gb = YesNoTableWidgetItem(r.get("get_back", ""))
                it_gb.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not self._can_edit:
                    it_gb.setFlags(it_gb.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 14, it_gb)

                # 15: Opening ? (Editable numeric, compared against Opening Amount)
                it_exp_op = ExpAmountTableWidgetItem(r.get("expected_opening", ""))
                it_exp_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not self._can_edit:
                    it_exp_op.setFlags(it_exp_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 15, it_exp_op)

                # 16: Closing ? (Editable numeric, compared against Closing Amount)
                it_exp_cl = ExpAmountTableWidgetItem(r.get("expected_closing", ""))
                it_exp_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not self._can_edit:
                    it_exp_cl.setFlags(it_exp_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r_idx, 16, it_exp_cl)

                # Apply full row solid red highlight if mismatched
                self._update_vat_conf_row_style(tbl, r_idx)

            # Apply user column visibility preferences and content-aware auto-fit
            self.apply_vat_conf_column_visibility()
            self._auto_fit_conf_columns(tbl, force=False)

        finally:
            tbl.setUpdatesEnabled(True)
            tbl.blockSignals(False)

        if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
            self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))

    def _update_vat_conf_row_style(self, tbl: QTableWidget, row: int):
        """If expected amount does not match actual amount or either is empty, paint the FULL ROW in RED."""
        col_op = -1
        col_cl = -1
        col_eop = -1
        col_ecl = -1
        col_np = -1
        for c in range(tbl.columnCount()):
            hi = tbl.horizontalHeaderItem(c)
            ht = hi.text().strip().lower() if hi else ""
            if ht == "opening amount": col_op = c
            elif ht == "closing amount": col_cl = c
            elif ht == "opening ?": col_eop = c
            elif ht == "closing ?": col_ecl = c
            elif ht == "need print ?": col_np = c

        act_op_item = tbl.item(row, col_op) if col_op >= 0 else None
        act_cl_item = tbl.item(row, col_cl) if col_cl >= 0 else None
        exp_op_item = tbl.item(row, col_eop) if col_eop >= 0 else None
        exp_cl_item = tbl.item(row, col_ecl) if col_ecl >= 0 else None

        try:
            act_op_val = float(act_op_item.text().replace(",", "").strip()) if act_op_item else 0.0
        except ValueError:
            act_op_val = 0.0

        try:
            act_cl_val = float(act_cl_item.text().replace(",", "").strip()) if act_cl_item else 0.0
        except ValueError:
            act_cl_val = 0.0

        exp_op_text = exp_op_item.text().strip() if exp_op_item else ""
        exp_cl_text = exp_cl_item.text().strip() if exp_cl_item else ""

        # Empty expected fields are NOT mismatches (check_amount_match returns True for empty)
        op_matches = check_amount_match(act_op_val, exp_op_text)
        cl_matches = check_amount_match(act_cl_val, exp_cl_text)
        is_mismatch = not (op_matches and cl_matches)

        red_bg = QColor("#fecaca")
        red_fg = QColor("#991b1b")
        normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
        normal_fg = QColor("#0f172a")

        for c in range(tbl.columnCount()):
            it = tbl.item(row, c)
            if not it:
                continue
            if is_mismatch:
                it.setBackground(red_bg)
                it.setForeground(red_fg)
            else:
                it.setBackground(normal_bg)
                if c == col_np and it.text() == "Yes":
                    it.setForeground(QColor("#059669"))
                else:
                    it.setForeground(normal_fg)

    # ── MAPPING EVENT HANDLERS & PANEL CONTROLS ─────────────────────

    def destage_and_select(self, target_gid: int = None, target_col: int = 0):
        """Commit staged in-place group to its permanent sorted location and land selection on target_gid."""
        if hasattr(self, '_active_inline_cleanup') and callable(self._active_inline_cleanup):
            try:
                self._active_inline_cleanup()
            except Exception:
                pass
            self._active_inline_cleanup = None

        staged_gid = getattr(self, '_staged_group_id', None)
        self._staged_group_id = None
        self._staged_prior_index = None

        if not hasattr(self, '_cached_data') or not self._cached_data or "mappings" not in self._cached_data:
            return

        self._is_destaging = True
        try:
            self._populate_mapping_from_data(self._cached_data["mappings"])

            desired_gid = target_gid if target_gid is not None else staged_gid
            if desired_gid is not None:
                found_row = None
                for r in range(self.mapping_table.rowCount()):
                    if self.mapping_table.isRowHidden(r):
                        continue
                    it = self.mapping_table.item(r, 0)
                    if it:
                        r_gid = it.data(Qt.ItemDataRole.UserRole)
                        is_match = False
                        try:
                            is_match = (r_gid is not None) and (int(r_gid) == int(desired_gid))
                        except (ValueError, TypeError):
                            is_match = (r_gid == desired_gid)
                        if is_match:
                            found_row = r
                            break

                if found_row is not None:
                    it_target = self.mapping_table.item(found_row, target_col) or self.mapping_table.item(found_row, 0)
                    self.mapping_table.scrollToItem(it_target, QAbstractItemView.ScrollHint.EnsureVisible)
                    self.mapping_table.selectRow(found_row)
                    self.mapping_table.setCurrentCell(found_row, target_col)
                    self.mapping_table.setFocus()
        except Exception as e:
            logger.error(f"[destage_and_select] error committing staged group (staged_gid={staged_gid}, target_gid={target_gid}): {e}", exc_info=True)
        finally:
            self._is_destaging = False

    def _on_mapping_selection_changed(self):
        """Update button enabled states based on current selection in Mapping table."""
        selected_indexes = self.mapping_table.selectedIndexes()
        has_sel = bool(selected_indexes)

        if hasattr(self, 'btn_unmap_mapping'):
            can_clear = getattr(self, '_can_clear_mapping', True)
            self.btn_unmap_mapping.setEnabled(can_clear)

        has_unassigned_sel = bool(self.unassigned_list.selectedItems()) if hasattr(self, 'unassigned_list') else False
        if hasattr(self, 'btn_assign_internal'):
            self.btn_assign_internal.setEnabled(has_unassigned_sel and has_sel)

    def _on_mapping_item_changed(self, item: QTableWidgetItem):
        """Handle in-place editing in Mapping table (Narration)."""
        if getattr(self, '_is_populating_mapping', False) or getattr(self, '_is_destaging', False):
            return
        if not item or item.column() != (self.mapping_table.columnCount() - 1):
            return

        group_id = item.data(Qt.ItemDataRole.UserRole)
        if not group_id or not self.db_name or not self.active_vat_company:
            return

        new_narration = item.text().strip()

        # Update cache in memory so in-memory destaging / sorting retains it
        if hasattr(self, '_cached_data') and self._cached_data and "mappings" in self._cached_data:
            for m in self._cached_data["mappings"]:
                if (m.get("group_id") or m.get("id")) == group_id:
                    if str(m.get("narration") or "").strip() == new_narration:
                        return
                    m["narration"] = new_narration
                    break

        save_mapping_narration(self.db_name, self.active_vat_company, group_id, new_narration)

    def _on_unassigned_item_user_clicked(self, item):
        """User explicitly clicked an unassigned item with mouse: destage any staged group."""
        if getattr(self, '_staged_group_id', None) is not None and not getattr(self, '_is_destaging', False):
            self.destage_and_select()

    def _on_unassigned_selection_changed(self):
        """Update assign button when an unassigned internal debtor is selected."""
        has_unassigned_sel = bool(self.unassigned_list.selectedItems()) if hasattr(self, 'unassigned_list') else False
        has_mapping_sel = bool(self.mapping_table.selectedIndexes()) if hasattr(self, 'mapping_table') else False
        if hasattr(self, 'btn_assign_internal'):
            self.btn_assign_internal.setEnabled(has_unassigned_sel and has_mapping_sel)

    def _filter_unassigned_list(self, text: str):
        """Filter the unassigned internal list in real time matching Name, Alias, and Classification."""
        q = text.strip().lower()
        visible_cnt = 0
        total_cnt = self.unassigned_list.count()
        tokens = [t for t in q.split() if t]
        for r in range(total_cnt):
            it = self.unassigned_list.item(r)
            if not it:
                continue
            name = str(it.data(Qt.ItemDataRole.UserRole) or "").lower()
            alias = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").lower()
            cls = str(it.data(Qt.ItemDataRole.UserRole + 2) or "").lower()
            txt = it.text().lower()
            corpus = f"{txt} {name} {alias} {cls}"
            match = all(tok in corpus for tok in tokens) if tokens else True
            it.setHidden(not match)
            if match:
                visible_cnt += 1
        if hasattr(self, 'lbl_unassigned_count'):
            if q and visible_cnt < total_cnt:
                self.lbl_unassigned_count.setText(f"{visible_cnt} / {total_cnt}")
            else:
                self.lbl_unassigned_count.setText(str(total_cnt))

    def _toggle_unassigned_panel(self):
        """Toggle visibility of right-side Unassigned Internal Ledgers panel."""
        if not hasattr(self, 'unassigned_panel'):
            return
        is_vis = self.unassigned_panel.isVisible()
        self.unassigned_panel.setVisible(not is_vis)
        arrow = "❯" if not is_vis else "❮"
        cnt = len(getattr(self, '_cached_unassigned', []))
        self.btn_toggle_unassigned.setText(f"📋 Unassigned ({cnt}) {arrow}")

    def _collapse_unassigned_panel(self):
        """Collapse the unassigned internal panel to the right."""
        if hasattr(self, 'unassigned_panel'):
            self.unassigned_panel.hide()
            cnt = len(getattr(self, '_cached_unassigned', []))
            self.btn_toggle_unassigned.setText(f"📋 Unassigned ({cnt}) ❮")

    def _assign_selected_internal_ledger(self):
        """Assign all selected unassigned internal debtors to the selected VAT group in the table."""
        if not self._can_edit:
            return
        selected_indexes = self.mapping_table.selectedIndexes()
        target_group_id = None
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid:
                target_group_id = gid
                break

        if not target_group_id:
            QMessageBox.information(self, "Select VAT Row", "Please select a VAT group in the mapping table to assign to.")
            return

        unassigned_items = self.unassigned_list.selectedItems()
        if not unassigned_items:
            QMessageBox.information(self, "Select Internal Ledger", "Please select one or more internal ledgers from the unassigned list.")
            return

        assigned_any = False
        for item in unassigned_items:
            int_name = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip()
            if int_name:
                ok = assign_internal_ledger_to_group(self.db_name, self.active_vat_company, target_group_id, int_name)
                if ok:
                    assigned_any = True

        if assigned_any:
            prior_idx = None
            if hasattr(self, '_cached_data') and self._cached_data and "mappings" in self._cached_data:
                for idx, m in enumerate(self._cached_data["mappings"]):
                    m_gid = m.get("group_id") or m.get("id")
                    try:
                        if (m_gid is not None) and (int(m_gid) == int(target_group_id)):
                            prior_idx = idx
                            break
                    except (ValueError, TypeError):
                        if str(m_gid) == str(target_group_id):
                            prior_idx = idx
                            break
            self._staged_group_id = target_group_id
            self._staged_prior_index = prior_idx
            self.refresh_mapping_table(select_group_id=target_group_id)
            self.mapping_table.setFocus()
        else:
            self._staged_group_id = None
            self._staged_prior_index = None

    def _on_unassigned_item_double_clicked(self, item: QListWidgetItem):
        """Double-clicking an unassigned internal debtor assigns it to selected VAT group (or first unmapped)."""
        if not self._can_edit:
            return
        int_name = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip()
        if not int_name:
            return

        selected_indexes = self.mapping_table.selectedIndexes()
        target_group_id = None
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid:
                target_group_id = gid
                break

        if not target_group_id:
            for r in range(self.mapping_table.rowCount()):
                it = self.mapping_table.item(r, 0)
                if it and getattr(it, '_mapping_group', {}).get("is_unmapped", False):
                    target_group_id = it.data(Qt.ItemDataRole.UserRole)
                    break

        if not target_group_id:
            QMessageBox.information(self, "Select VAT Row", "Please select a VAT row in the mapping table to assign to.")
            return

        prior_idx = None
        if hasattr(self, '_cached_data') and self._cached_data and "mappings" in self._cached_data:
            for idx, m in enumerate(self._cached_data["mappings"]):
                m_gid = m.get("group_id") or m.get("id")
                try:
                    if (m_gid is not None) and (int(m_gid) == int(target_group_id)):
                        prior_idx = idx
                        break
                except (ValueError, TypeError):
                    if str(m_gid) == str(target_group_id):
                        prior_idx = idx
                        break
        ok = assign_internal_ledger_to_group(self.db_name, self.active_vat_company, target_group_id, int_name)
        if ok:
            self._staged_group_id = target_group_id
            self._staged_prior_index = prior_idx
            self.refresh_mapping_table(select_group_id=target_group_id)
            self.mapping_table.setFocus()
        else:
            self._staged_group_id = None
            self._staged_prior_index = None

    def _unmap_selected_mapping(self):
        """Clear/unmap internal ledgers from the selected group(s), returning them to unassigned list.
        Requires 'vat_balance.clear_mapping' permission and admin password confirmation.
        """
        if not getattr(self, '_can_clear_mapping', True):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to clear mappings.")
            return

        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)

        if not group_ids:
            QMessageBox.information(self, "Select Row", "Please select one or more rows in the Mapping table to clear.")
            return

        # Security confirmation dialog requiring Admin Password
        comp_path = getattr(self, 'current_company_path', '') or getattr(self, 'company_path', '')
        comp_name = getattr(self, 'current_company_name', '') or getattr(self, 'active_vat_company', '')
        dlg = AdminPasswordConfirmDialog(
            title="Confirm Clear Mapping",
            prompt=f"Are you sure you want to clear mapping for {len(group_ids)} selected group(s)?\n\nInternal ledgers will be unlinked and returned to Unassigned.\nTo proceed, please enter Admin Password:",
            security_mgr=getattr(self, '_security_mgr', None),
            company_path=comp_path,
            company_name=comp_name,
            parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._staged_group_id = None
        self._staged_prior_index = None
        for gid in group_ids:
            unmap_vat_group(self.db_name, self.active_vat_company, gid)

        self.refresh_mapping_table()

    def _on_mapping_plus_clicked(self, row: int, col: int, group_id: int):
        """Handle click on '+' button inside Mapping cell delegate for Col 1 (VAT) or Col 2 (Int).
        Inserts an inline row directly below the target group with an autocomplete editor.
        """
        if not self._can_edit:
            return

        # 1. Clean up any existing active inline editor
        if hasattr(self, '_active_inline_cleanup') and callable(self._active_inline_cleanup):
            self._active_inline_cleanup()
            self._active_inline_cleanup = None

        # 2. Resolve target group data from clicked row
        it0 = self.mapping_table.item(row, 0)
        it1 = self.mapping_table.item(row, 1)

        target_gid = it0.data(Qt.ItemDataRole.UserRole) if it0 else group_id
        target_vname = str((it1.data(Qt.ItemDataRole.UserRole + 7) if it1 else "") or (it1.data(Qt.ItemDataRole.UserRole + 2) if it1 else "") or (it1.text() if it1 else "")).strip()
        if target_vname.startswith("↳ "):
            target_vname = target_vname[2:].strip()

        # If another group was currently staged, destage it first so its permanent location is settled
        staged_gid = getattr(self, '_staged_group_id', None)
        if staged_gid is not None:
            is_diff = False
            try:
                is_diff = int(staged_gid) != int(target_gid)
            except (ValueError, TypeError):
                is_diff = (staged_gid != target_gid)
            if is_diff:
                self._staged_group_id = None
                self._staged_prior_index = None
                if hasattr(self, '_cached_data') and self._cached_data and "mappings" in self._cached_data:
                    self._populate_mapping_from_data(self._cached_data["mappings"])

        # Record prior index so row remains exactly in place after assignment
        prior_idx = None
        if hasattr(self, '_cached_data') and self._cached_data and "mappings" in self._cached_data:
            for idx, m in enumerate(self._cached_data["mappings"]):
                m_gid = m.get("group_id") or m.get("id")
                try:
                    if (m_gid is not None) and (int(m_gid) == int(target_gid)):
                        prior_idx = idx
                        break
                except (ValueError, TypeError):
                    if str(m_gid) == str(target_gid):
                        prior_idx = idx
                        break
        if prior_idx is None:
            seen_gids = set()
            prior_idx = 0
            for r in range(row):
                it = self.mapping_table.item(r, 0)
                gid = it.data(Qt.ItemDataRole.UserRole) if it else None
                if gid and gid not in seen_gids:
                    seen_gids.add(gid)
                    prior_idx += 1

        # Guard: 'None' VAT ledger cannot be merged with other ledgers
        if col == 1 and target_vname.lower() == "none":
            QMessageBox.warning(self, "Invalid Operation", "'None' VAT ledger cannot be merged with other ledgers.")
            return

        # 3. Insert temporary inline row directly below
        insert_row = row + 1
        self._is_inline_editing = True
        try:
            self.mapping_table.clearSelection()
            self.mapping_table.setCurrentItem(None)
            self.mapping_table.insertRow(insert_row)
            self.mapping_table.setRowHeight(insert_row, 36)
        finally:
            self._is_inline_editing = False

        # 4. Fill cells with neutral, non-selectable items (prevent selection highlight)
        for c in range(self.mapping_table.columnCount()):
            it = QTableWidgetItem("")
            it.setData(Qt.ItemDataRole.UserRole, target_gid)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            it.setBackground(QColor("#f8fafc"))
            if c == 0:
                it.setText("+")
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setForeground(QColor("#059669"))
            self.mapping_table.setItem(insert_row, c, it)

        target_grp = getattr(it0, '_mapping_group', {}) if it0 else {}
        target_is_none = (
            target_grp.get("is_none_vat", False)
            or target_grp.get("serial_no") == 0
            or target_vname.lower() == "none"
        )

        # 5. Build QLineEdit with _TallyCompleter
        ed = QLineEdit()
        normal_style = """
            QLineEdit {
                background: #ffffff;
                border: 2px solid #059669;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 12px;
                font-weight: 500;
                color: #0f172a;
            }
        """
        error_style = """
            QLineEdit {
                background: #fef2f2;
                border: 2px solid #ef4444;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 12px;
                font-weight: 500;
                color: #991b1b;
            }
        """
        ed.setStyleSheet(normal_style)

        def _set_normal_style():
            ed.setStyleSheet(normal_style)

        def _set_error_style():
            ed.setStyleSheet(error_style)

        if col == 1:
            ed.setPlaceholderText("Type or select VAT Ledger to merge and press Enter (Esc to cancel)...")
            vat_opts = self._get_vat_ledger_options()
            options = []
            for opt in vat_opts:
                canon = self.resolve_vat_ledger(opt) or opt
                if canon.lower() != "none" and canon.lower() != target_vname.lower():
                    options.append(opt)
        else:
            ed.setPlaceholderText("Type or select Internal Ledger to assign and press Enter (Esc to cancel)...")
            base_options = self._get_internal_ledger_options()
            if target_is_none:
                # 'None' VAT cannot be mapped to Cash Sales or Old Party
                options = [opt for opt in base_options if opt.lower() not in ("cash sales", "old party")]
            else:
                options = ["Cash Sales", "Old Party"] + [opt for opt in base_options if opt.lower() not in ("cash sales", "old party")]

        opt_map = {opt.strip().lower(): opt for opt in options}

        def _is_exact_valid_ledger(text: str) -> str | None:
            if not text:
                return None
            t_clean = text.strip()
            t_lower = t_clean.lower()
            if t_lower in opt_map:
                return opt_map[t_lower]
            if col == 1:
                canon = self.resolve_vat_ledger(t_clean)
                if canon and canon.strip().lower() in opt_map:
                    return opt_map[canon.strip().lower()]
            elif col == 2:
                canon = self.resolve_int_ledger(t_clean)
                if canon and canon.strip().lower() in opt_map:
                    return opt_map[canon.strip().lower()]
            return None

        def _find_closest_option(text: str) -> str | None:
            if not text:
                return None
            t_clean = text.strip()
            t_norm = _norm(t_clean)
            if not t_norm:
                return None

            # 1. Check if completer proxy currently has a top matched row
            try:
                proxy = getattr(completer, '_proxy', None)
                if proxy and proxy.rowCount() > 0:
                    top_opt = proxy.data(proxy.index(0, 0), Qt.ItemDataRole.DisplayRole)
                    if top_opt:
                        return top_opt
            except Exception:
                pass

            # 2. Check normalized prefix / contains matches in options
            starts = []
            contains = []
            for opt in options:
                onorm = _norm(opt)
                if onorm.startswith(t_norm):
                    starts.append(opt)
                elif t_norm in onorm:
                    contains.append(opt)

            if starts:
                starts.sort(key=lambda x: len(x))
                return starts[0]
            if contains:
                contains.sort(key=lambda x: len(x))
                return contains[0]

            # 3. Fuzzy match via difflib
            import difflib
            matches = difflib.get_close_matches(t_clean, options, n=1, cutoff=0.35)
            if matches:
                return matches[0]

            return None

        completer = _TallyCompleter(options, ed)
        completer.setMaxVisibleItems(12)
        completer.popup().setMinimumWidth(420)
        ed.setCompleter(completer)
        ed.textEdited.connect(completer.update_prefix)
        ed.textEdited.connect(lambda: _set_normal_style())

        is_done = False

        def _cleanup():
            nonlocal is_done
            if is_done:
                return
            is_done = True
            if hasattr(self, '_active_inline_cleanup'):
                self._active_inline_cleanup = None
            try:
                completer.popup().hide()
            except Exception:
                pass
            # Remove cell widget first to prevent floating widget over viewport
            self._is_inline_editing = True
            try:
                self.mapping_table.removeCellWidget(insert_row, col)
                if insert_row < self.mapping_table.rowCount():
                    self.mapping_table.removeRow(insert_row)
                self.mapping_table.setFocus()
            finally:
                self._is_inline_editing = False

        self._active_inline_cleanup = _cleanup

        def _commit(selected_val=None):
            nonlocal is_done
            if is_done:
                return
            raw_val = (selected_val or ed.text()).strip()
            if not raw_val:
                return

            # Strictly validate against options list
            exact_val = _is_exact_valid_ledger(raw_val)
            if not exact_val:
                # Guard: Do NOT accept non-existent ledgers into database!
                _set_error_style()
                return

            val = exact_val

            # Clean up the temporary row immediately before running refresh!
            _cleanup()

            if col == 1:
                # Merge VAT Ledger
                canon_val = self.resolve_vat_ledger(val) or val
                if canon_val.lower() == "none":
                    QMessageBox.warning(self, "Invalid Operation", "'None' VAT ledger cannot be merged.")
                    return
                ok = merge_vat_ledger_into_group(self.db_name, self.active_vat_company, target_gid, canon_val, target_vat_name=target_vname)
                if ok:
                    self._staged_group_id = target_gid
                    self._staged_prior_index = prior_idx
                    self.refresh_mapping_table(select_group_id=target_gid)
                    self.mapping_table.setFocus()
                else:
                    self._staged_group_id = None
                    self._staged_prior_index = None
            elif col == 2:
                # Assign Internal Ledger
                canon_val = self.resolve_int_ledger(val) or val
                if target_is_none and canon_val.lower() in ("cash sales", "old party"):
                    QMessageBox.warning(self, "Invalid Operation", "'None' VAT cannot be mapped to Cash Sales or Old Party.")
                    return
                ok = assign_internal_ledger_to_group(self.db_name, self.active_vat_company, target_gid, canon_val, target_vat_name=target_vname)
                if ok:
                    self._staged_group_id = target_gid
                    self._staged_prior_index = prior_idx
                    self.refresh_mapping_table(select_group_id=target_gid)
                    self.mapping_table.setFocus()
                else:
                    self._staged_group_id = None
                    self._staged_prior_index = None

        def _on_activated(chosen_text: str):
            curr = ed.text().strip()
            # If what user typed is already an exact match, commit immediately
            if curr.lower() == chosen_text.strip().lower():
                _commit(chosen_text)
                return

            # Otherwise, user typed something else: select closest match and add in field,
            # but do NOT accept until Enter is pressed again!
            ed.setText(chosen_text)
            ed.selectAll()
            _set_normal_style()
            try:
                completer.popup().hide()
            except Exception:
                pass

        def _on_return_pressed():
            val = ed.text().strip()
            if not val:
                return

            # Check if text in field is already an exact match from the list
            exact_match = _is_exact_valid_ledger(val)
            if exact_match:
                _commit(exact_match)
                return

            # User typed something else that does NOT exist in the list:
            # Select the closest match and add that in the field, but do NOT accept until enter is pressed again!
            closest = _find_closest_option(val)
            if closest:
                ed.setText(closest)
                ed.selectAll()
                _set_normal_style()
                try:
                    completer.popup().hide()
                except Exception:
                    pass
            else:
                _set_error_style()

        orig_kpe = ed.keyPressEvent
        def _ed_key(ev):
            if ev.key() == Qt.Key.Key_Escape:
                _cleanup()
                return
            orig_kpe(ev)
        ed.keyPressEvent = _ed_key

        completer.activated.connect(_on_activated)
        ed.returnPressed.connect(_on_return_pressed)

        self.mapping_table.setCellWidget(insert_row, col, ed)
        self.mapping_table.clearSelection()
        self.mapping_table.setCurrentItem(None)
        self.mapping_table.scrollToItem(self.mapping_table.item(insert_row, col))
        ed.setFocus()

    def _show_mapping_context_menu(self, pos):
        """Right-click context menu on Mapping table for removing VAT/Int ledgers and setting classifications."""
        if not self._can_edit:
            return

        row = self.mapping_table.rowAt(pos.y())
        if row < 0:
            return

        it0 = self.mapping_table.item(row, 0)
        if not it0:
            return
        gid = int(it0.data(Qt.ItemDataRole.UserRole) or 0)
        mapping_data = getattr(it0, '_mapping_group', {})

        it1 = self.mapping_table.item(row, 1)
        v_name = str(it1.data(Qt.ItemDataRole.UserRole + 2) or it1.text()).strip() if it1 else ""
        if v_name.startswith("↳ "):
            v_name = v_name[2:].strip()

        it2 = self.mapping_table.item(row, 2)
        i_name = str(it2.data(Qt.ItemDataRole.UserRole + 2) or it2.text()).strip() if it2 else ""

        menu = QMenu(self)

        # Merge multiple selected groups if 2+ selected (excluding 'None' VAT groups)
        selected_indexes = self.mapping_table.selectedIndexes()
        selected_gids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            if it:
                grp = getattr(it, '_mapping_group', {})
                if grp.get("is_none_vat") or str(grp.get("vat_ledger", "")).strip().lower() == "none":
                    continue
                s_gid = it.data(Qt.ItemDataRole.UserRole)
                if s_gid and s_gid not in selected_gids:
                    selected_gids.append(s_gid)

        if len(selected_gids) > 1 and not mapping_data.get("is_none_vat", False) and v_name.lower() != "none":
            act_merge = menu.addAction(f"🔗 Merge Selected ({len(selected_gids)}) Groups into One")
            def _do_merge_selected():
                target = merge_mapping_groups(self.db_name, self.active_vat_company, selected_gids)
                if target:
                    self.refresh_mapping_table(select_group_id=target)
            act_merge.triggered.connect(_do_merge_selected)
            menu.addSeparator()

        # 1. VAT Ledger Remove (Requirement 2: remove single VAT ledger from merged VATs)
        is_merged = mapping_data.get("is_merged", False) or len(mapping_data.get("vat_items", [])) > 1
        if is_merged and v_name:
            act_remove_vat = menu.addAction(f"Remove VAT Ledger '{v_name}' from Group")
            def _do_remove_vat():
                self._staged_group_id = None
                ok = remove_vat_ledger_from_group(self.db_name, self.active_vat_company, gid, v_name)
                if ok:
                    self.refresh_mapping_table(select_group_id=gid)
            act_remove_vat.triggered.connect(_do_remove_vat)

        # Demerge group if merged
        if is_merged:
            act_demerge = menu.addAction("⚡ Demerge Group (Separate VAT Ledgers)")
            def _do_demerge():
                self._staged_group_id = None
                ok = demerge_mapping_group(self.db_name, self.active_vat_company, gid)
                if ok:
                    self.refresh_mapping_table()
            act_demerge.triggered.connect(_do_demerge)

        # 2. Internal Ledger Remove (Requirement 3: unmap single internal ledger)
        if i_name:
            act_remove_int = menu.addAction(f"Remove Internal Ledger '{i_name}' (Unmap)")
            def _do_remove_int():
                self._staged_group_id = None
                ok = remove_internal_ledger_from_group(self.db_name, self.active_vat_company, gid, i_name)
                if ok:
                    self.refresh_mapping_table(select_group_id=gid)
            act_remove_int.triggered.connect(_do_remove_int)

        # 3. Option to put "Cash Sales" or "Old Party" as internal ledger for VATs without internal ledgers
        selected_rows = sorted({idx.row() for idx in selected_indexes})
        target_unmapped = []
        rows_to_check = selected_rows if row in selected_rows else [row]
        for r_idx in rows_to_check:
            it_r0 = self.mapping_table.item(r_idx, 0)
            it_r1 = self.mapping_table.item(r_idx, 1)
            it_r2 = self.mapping_table.item(r_idx, 2)
            if not it_r0 or not it_r1:
                continue
            r_gid = int(it_r0.data(Qt.ItemDataRole.UserRole) or 0)
            r_vname = str(it_r1.data(Qt.ItemDataRole.UserRole + 2) or it_r1.text()).strip()
            if r_vname.startswith("↳ "):
                r_vname = r_vname[2:].strip()
            r_iname = str((it_r2.data(Qt.ItemDataRole.UserRole + 2) if it_r2 else "") or (it_r2.text() if it_r2 else "")).strip()
            r_grp = getattr(it_r0, '_mapping_group', {})
            r_is_none = (
                r_grp.get("is_none_vat", False)
                or r_grp.get("serial_no") == 0
                or r_vname.lower() == "none"
            )
            if r_gid and r_vname and not r_is_none:
                target_unmapped.append((r_gid, r_vname, r_iname))

        if target_unmapped:
            menu.addSeparator()
            lbl_suffix = f" for Selected ({len(target_unmapped)})" if len(target_unmapped) > 1 else ""
            act_cash = menu.addAction(f"Set Internal Ledger: Cash Sales{lbl_suffix}")
            act_old = menu.addAction(f"Set Internal Ledger: Old Party{lbl_suffix}")

            def _apply_placeholder(placeholder_name):
                for tg_id, tg_vname, _ in target_unmapped:
                    assign_internal_ledger_to_group(self.db_name, self.active_vat_company, tg_id, placeholder_name, target_vat_name=tg_vname)
                self._staged_group_id = gid
                self.refresh_mapping_table(select_group_id=gid)

            act_cash.triggered.connect(lambda: _apply_placeholder("Cash Sales"))
            act_old.triggered.connect(lambda: _apply_placeholder("Old Party"))

        # 4. Clear/Unmap All
        if mapping_data.get("internal_items"):
            menu.addSeparator()
            act_unmap_all = menu.addAction("Clear All Mappings for Group")
            act_unmap_all.triggered.connect(lambda: self._unmap_group(gid))

        if not menu.isEmpty():
            menu.addSeparator()
        act_toggle_chq = menu.addAction(
            "👁️ Show Pending Chq. Column" if getattr(self, '_hide_pending_chq', False) else "👁️ Hide Pending Chq. Column"
        )
        act_toggle_chq.triggered.connect(self._toggle_pending_chq_visibility)

        menu.exec(self.mapping_table.viewport().mapToGlobal(pos))

    def _set_mapping_cls(self, group_id: int, vat_ledger_name: str, cls: str):
        set_mapping_classification(self.db_name, self.active_vat_company, group_id, vat_ledger_name, cls)
        self.refresh_mapping_table(select_group_id=group_id)

    def _unmap_group(self, group_id: int):
        self._staged_group_id = None
        unmap_vat_group(self.db_name, self.active_vat_company, group_id)
        self.refresh_mapping_table()

    def _show_unassigned_context_menu(self, pos):
        """Right-click context menu for unassigned internal debtors: Assign to 'None' VAT, Classify as Cash Sales / Old Party."""
        if not self._can_edit:
            return
        selected_items = self.unassigned_list.selectedItems()
        if not selected_items:
            return

        menu = QMenu(self)
        count = len(selected_items)
        lbl_suffix = f" ({count})" if count > 1 else ""

        # Option: Assign to 'None' VAT (Serial 0) (Requirement 4)
        act_none = menu.addAction(f"Assign to 'None' VAT (Serial 0){lbl_suffix}")
        act_none.triggered.connect(self._assign_unassigned_to_none_vat)

        menu.addSeparator()
        # Requirement 9: Cash Sales / Old Party
        act_cash = menu.addAction(f"Classify as: Cash Sales{lbl_suffix}")
        act_old = menu.addAction(f"Classify as: Old Party{lbl_suffix}")
        act_clear_cls = menu.addAction(f"Clear Classification{lbl_suffix}")

        act_cash.triggered.connect(lambda: self._set_unassigned_cls("Cash Sales"))
        act_old.triggered.connect(lambda: self._set_unassigned_cls("Old Party"))
        act_clear_cls.triggered.connect(lambda: self._set_unassigned_cls(""))

        menu.exec(self.unassigned_list.viewport().mapToGlobal(pos))

    def _set_unassigned_cls(self, classification: str):
        selected_items = self.unassigned_list.selectedItems()
        for it in selected_items:
            int_name = str(it.data(Qt.ItemDataRole.UserRole) or it.text()).strip()
            if int_name:
                set_unassigned_classification(self.db_name, self.active_vat_company, int_name, classification)
        self.refresh_mapping_table()

    def _assign_unassigned_to_none_vat(self):
        """Assign selected internal debtor(s) to default 'None' VAT (Serial 0) group (Requirement 4)."""
        selected_items = self.unassigned_list.selectedItems()
        if not selected_items or not self.db_name or not self.active_vat_company:
            return
        db = get_db_manager()
        rows = db.execute_query(
            self.db_name,
            "SELECT TOP 1 group_id FROM dbo.vat_ledger_mapping WHERE vat_company = ? AND (serial_no = 0 OR LOWER(vat_ledger_name) = 'none')",
            (self.active_vat_company,)
        )
        if rows and rows[0][0]:
            none_gid = rows[0][0]
        else:
            run_auto_mapping_on_sync(self.db_name, self.active_vat_company)
            rows2 = db.execute_query(
                self.db_name,
                "SELECT TOP 1 group_id FROM dbo.vat_ledger_mapping WHERE vat_company = ? AND (serial_no = 0 OR LOWER(vat_ledger_name) = 'none')",
                (self.active_vat_company,)
            )
            none_gid = rows2[0][0] if rows2 else 1

        for it in selected_items:
            int_name = str(it.data(Qt.ItemDataRole.UserRole) or it.text()).strip()
            if int_name:
                assign_internal_ledger_to_group(self.db_name, self.active_vat_company, none_gid, int_name)

        self.refresh_mapping_table(select_group_id=none_gid)

    def _on_toggle_none_vat(self, checked: bool):
        """Show or hide the default 'None' VAT (Serial 0) mapping group."""
        if hasattr(self, '_cached_data') and self._cached_data:
            mappings = self._cached_data.get("mappings", [])
            self._populate_mapping_from_data(mappings)

    def _on_mapping_header_double_clicked(self, logical_index: int):
        """Sort mapping groups A -> Z (ascending), toggling to descending on second click (Requirement 15)."""
        self._staged_group_id = None
        if not hasattr(self, '_cached_data') or not self._cached_data:
            return
        mappings = list(self._cached_data.get("mappings", []))
        if not mappings:
            return

        cur_col = getattr(self.mapping_table, '_sort_col', -1)
        cur_order = getattr(self.mapping_table, '_sort_order', None)
        if cur_col == logical_index and cur_order == "asc":
            order = "desc"
            reverse = True
        else:
            order = "asc"
            reverse = False

        self.mapping_table._sort_col = logical_index
        self.mapping_table._sort_order = order

        if logical_index == 0:
            mappings.sort(key=lambda m: (m.get("serial_no") or 0), reverse=reverse)
        elif logical_index == 1:
            mappings.sort(key=lambda m: (m.get("vat_ledger") or "").lower(), reverse=reverse)
        elif logical_index == 2:
            mappings.sort(key=lambda m: (m.get("internal_ledger") or "").lower(), reverse=reverse)
        elif logical_index == 3:
            def _get_v(m):
                v_items = m.get("vat_items", [])
                if v_items:
                    return sum(float(v.get("closing", 0.0) or 0.0) for v in v_items)
                return float(m.get("vat_closing", 0.0) or 0.0)
            mappings.sort(key=_get_v, reverse=reverse)
        elif logical_index == 4:
            def _get_i(m):
                i_items = m.get("internal_items", [])
                if i_items:
                    return sum(float(i.get("closing", 0.0) or 0.0) for i in i_items)
                return float(m.get("internal_closing", 0.0) or 0.0)
            mappings.sort(key=_get_i, reverse=reverse)
        elif logical_index == 5:
            # Sort by Pending Chq.
            def _get_chq(m):
                i_items = m.get("internal_items", [])
                return sum(float(x.get("pending_chq", 0.0) or 0.0) for x in i_items) if i_items else float(m.get("pending_chq", 0.0) or 0.0)
            mappings.sort(key=_get_chq, reverse=reverse)
        elif logical_index == 6:
            # Sort by Balance (including pending chq)
            def _get_bal(m):
                v_items = m.get("vat_items", [])
                v = sum(float(x.get("closing", 0.0) or 0.0) for x in v_items) if v_items else float(m.get("vat_closing", 0.0) or 0.0)
                i_items = m.get("internal_items", [])
                i = sum(float(x.get("closing", 0.0) or 0.0) for x in i_items) if i_items else float(m.get("internal_closing", 0.0) or 0.0)
                chq = sum(float(x.get("pending_chq", 0.0) or 0.0) for x in i_items) if i_items else float(m.get("pending_chq", 0.0) or 0.0)
                raw_bal = 0.0
                if v < -1e-9 and i < -1e-9:
                    raw_bal = 0.0
                elif v < -1e-9:
                    raw_bal = 0.0
                elif i < -1e-9:
                    raw_bal = v
                elif i > v + 1e-9:
                    raw_bal = 0.0
                elif v > i + 1e-9:
                    raw_bal = v - i
                if i_items and chq > 0:
                    raw_bal += chq
                return float(round_nearest_1000(raw_bal)) if raw_bal > 0 else 0.0
            mappings.sort(key=_get_bal, reverse=reverse)
        elif logical_index == 7:
            # Sort by Negative
            def _get_neg(m):
                v_items = m.get("vat_items", [])
                v = sum(float(x.get("closing", 0.0) or 0.0) for x in v_items) if v_items else float(m.get("vat_closing", 0.0) or 0.0)
                i_items = m.get("internal_items", [])
                i = sum(float(x.get("closing", 0.0) or 0.0) for x in i_items) if i_items else float(m.get("internal_closing", 0.0) or 0.0)
                if v < -1e-9 and i < -1e-9:
                    return float(round_nearest_1000(abs(v + i)))
                if v < -1e-9:
                    return float(round_nearest_1000(abs(v)))
                if i < -1e-9:
                    return 0.0
                if i > v + 1e-9:
                    return float(round_nearest_1000(abs(v - i)))
                return 0.0
            mappings.sort(key=_get_neg, reverse=reverse)
        elif logical_index == 8:
            mappings.sort(key=lambda m: (str(m.get("narration") or "")).lower(), reverse=reverse)

        self._populate_mapping_from_data(mappings)

    def _update_mapping_totals(self):
        """Recalculate pinned grand totals for visible rows in mapping table.
        - Values in columns 3, 4, 5, 6, 7 displayed in lakhs (divided by 1,00,000).
        - Under column 2 (Internal Ledger Name), displays label 'Actual Rs.'.
        """
        if not hasattr(self, 'mapping_footer'):
            return
        total_vat = 0.0
        total_int = 0.0
        total_chq = 0.0
        total_bal = 0.0
        total_neg = 0.0
        for r in range(self.mapping_table.rowCount()):
            if self.mapping_table.isRowHidden(r):
                continue
            it3 = self.mapping_table.item(r, 3)
            it4 = self.mapping_table.item(r, 4)
            it5 = self.mapping_table.item(r, 5)
            it6 = self.mapping_table.item(r, 6)
            it7 = self.mapping_table.item(r, 7)

            if it3 and hasattr(it3, 'num_value'):
                total_vat += it3.num_value
            elif it3 and it3.text():
                try:
                    total_vat += float(it3.text().replace(",", "").strip())
                except Exception:
                    pass

            if it4 and hasattr(it4, 'num_value'):
                total_int += it4.num_value
            elif it4 and it4.text():
                try:
                    total_int += float(it4.text().replace(",", "").strip())
                except Exception:
                    pass

            if it5 and hasattr(it5, 'num_value'):
                total_chq += it5.num_value
            elif it5 and it5.text():
                try:
                    total_chq += float(it5.text().replace(",", "").strip())
                except Exception:
                    pass

            if it6 and hasattr(it6, 'num_value'):
                total_bal += it6.num_value
            elif it6 and it6.text():
                try:
                    total_bal += float(it6.text().replace(",", "").strip())
                except Exception:
                    pass

            if it7 and hasattr(it7, 'num_value'):
                total_neg += it7.num_value
            elif it7 and it7.text():
                try:
                    total_neg += float(it7.text().replace(",", "").strip())
                except Exception:
                    pass

        def _format_lakhs(val: float) -> str:
            sign = "-" if val < 0 else ""
            abs_val = abs(val)
            lakhs = int(abs_val // 100000)
            if lakhs == 0:
                return "0 lakh"
            elif lakhs == 1:
                return f"{sign}1 lakh"
            else:
                return f"{sign}{lakhs:,} lakhs"

        # Point 5: "Actual Rs." label without numeric value
        actual_str = "Actual Rs."

        self.mapping_footer.sync_columns()
        self.mapping_footer.update_totals({
            2: actual_str,
            3: _format_lakhs(total_vat),
            4: _format_lakhs(total_int),
            5: _format_lakhs(total_chq),
            6: _format_lakhs(total_bal),
            7: _format_lakhs(total_neg),
        }, label_col=0, label_text="Total")

    def _on_generic_header_double_clicked(self, table: QTableWidget, col_idx: int, update_totals_fn=None):
        """Double-clicking a column header sorts that column A -> Z (ascending), toggling on subsequent clicks (Requirement 15)."""
        cur_col = getattr(table, '_sort_col', -1)
        cur_order = getattr(table, '_sort_order', None)
        if cur_col == col_idx and cur_order == Qt.SortOrder.AscendingOrder:
            order = Qt.SortOrder.DescendingOrder
        else:
            order = Qt.SortOrder.AscendingOrder
        table._sort_col = col_idx
        table._sort_order = order
        table.sortItems(col_idx, order)
        if callable(update_totals_fn):
            update_totals_fn()

    def _on_vat_conf_item_changed(self, item: QTableWidgetItem, group_type: str, tbl: QTableWidget):
        """User modified an editable cell in Vat Conf (Debtor/Creditor)."""
        col = item.column()
        row = item.row()
        hi = tbl.horizontalHeaderItem(col)
        header_text = hi.text().strip().lower() if hi else ""

        # Dynamically locate Name and SN columns
        name_col = 1
        sn_col = 0
        for c in range(tbl.columnCount()):
            h = tbl.horizontalHeaderItem(c)
            ht = h.text().strip().lower() if h else ""
            if ht == "name":
                name_col = c
            elif ht == "sn.":
                sn_col = c

        name_item = tbl.item(row, name_col)
        if not name_item:
            return
        ledger_name = str(name_item.data(Qt.ItemDataRole.UserRole) or name_item.text()).strip()
        val = item.text().strip()

        active_comp = self.active_vat_company
        if not active_comp and self.db_name:
            active_comp = get_active_vat_company(self.db_name)
            self.active_vat_company = active_comp
        if not active_comp:
            logger.warning(f"[_on_vat_conf_item_changed] No active VAT company configured for db '{self.db_name}'")
            return

        # Cartoon Number (SN.) Validation, Swap on Duplicate & Persistence
        if header_text == "sn.":
            old_val = getattr(item, '_prev_sn', '')
            if val == old_val:
                return

            is_valid, err_msg = validate_cartoon_number(val)
            if not is_valid:
                tbl.blockSignals(True)
                item.setText(old_val)
                tbl.blockSignals(False)
                QTimer.singleShot(0, lambda msg=err_msg: QMessageBox.warning(self, "Invalid Cartoon Number", msg))
                return

            # Check if this CN already exists on another row in the table
            duplicate_row = -1
            other_ledger_name = ""
            if val:
                for r in range(tbl.rowCount()):
                    if r == row:
                        continue
                    other_it = tbl.item(r, sn_col)
                    if other_it and other_it.text().strip() == val:
                        duplicate_row = r
                        other_name_it = tbl.item(r, name_col)
                        other_ledger_name = str(other_name_it.data(Qt.ItemDataRole.UserRole) or other_name_it.text()).strip() if other_name_it else ""
                        break

            if duplicate_row >= 0:
                # Target CN is already assigned to another ledger — swap CNs to maintain uniqueness
                other_it = tbl.item(duplicate_row, sn_col)
                swap_sn = old_val
                if not swap_sn or (swap_sn.isdigit() and int(swap_sn) in _EXCLUDED_CNS):
                    # Find next available non-reserved CN
                    used = set()
                    for r in range(tbl.rowCount()):
                        if r in (row, duplicate_row):
                            continue
                        it_tmp = tbl.item(r, sn_col)
                        t_tmp = it_tmp.text().strip() if it_tmp else ""
                        if t_tmp.isdigit() and int(t_tmp) > 0:
                            used.add(int(t_tmp))
                    if val.isdigit():
                        used.add(int(val))
                    num = 1
                    while num in used or num in _EXCLUDED_CNS:
                        num += 1
                    swap_sn = str(num)

                tbl.blockSignals(True)
                other_it.setText(swap_sn)
                other_it._prev_sn = swap_sn
                item._prev_sn = val
                tbl.blockSignals(False)

                try:
                    save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "sn", val)
                    if other_ledger_name:
                        save_vat_conf_field(self.db_name, active_comp, group_type, other_ledger_name, "sn", swap_sn)
                except Exception as e:
                    logger.error(f"Failed to swap SN: {e}")
                return

            item._prev_sn = val
            try:
                save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "sn", val)
            except Exception as e:
                logger.error(f"Failed to save SN: {e}")
            return

        # Normalize Yes/No input
        if header_text in ("did you print", "get back"):
            val = normalize_yes_no(val)
            tbl.blockSignals(True)
            item.setText(val)
            tbl.blockSignals(False)

        # Dynamic cascade: if Did You Print is updated, check Get Back
        if header_text == "did you print":
            gb_col = -1
            for c in range(tbl.columnCount()):
                h_gb = tbl.horizontalHeaderItem(c)
                if h_gb and h_gb.text().strip().lower() == "get back":
                    gb_col = c
                    break
            if gb_col >= 0:
                gb_item = tbl.item(row, gb_col)
                if gb_item:
                    cur_gb = gb_item.text().strip()
                    if val == "No Need" and cur_gb in ("", "No"):
                        tbl.blockSignals(True)
                        gb_item.setText("N/A")
                        tbl.blockSignals(False)
                        try:
                            save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "get_back", "N/A")
                        except Exception:
                            pass
                    elif val != "No Need" and cur_gb == "N/A":
                        tbl.blockSignals(True)
                        gb_item.setText("")
                        tbl.blockSignals(False)
                        try:
                            save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "get_back", "")
                        except Exception:
                            pass

        field_map = {
            "sn.": "sn",
            "did you print": "did_you_print",
            "crm": "crm",
            "get back": "get_back",
            "opening ?": "expected_opening",
            "closing ?": "expected_closing",
        }
        field_name = field_map.get(header_text)
        if not field_name:
            return

        try:
            save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, field_name, val)

            # Update comparison highlight across the full row whenever Opening ? or Closing ? is modified
            if header_text in ("opening ?", "closing ?"):
                tbl.blockSignals(True)
                self._update_vat_conf_row_style(tbl, row)
                tbl.blockSignals(False)
                tbl.viewport().update()
                if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
                    self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
                elif group_type == "Creditor" and hasattr(self, 'creditor_footer'):
                    self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))

        except Exception as e:
            logger.error(f"[_on_vat_conf_item_changed] error: {e}")

    # ── SEARCH FILTERS ───────────────────────────────────────────────

    def _filter_int_table(self, query: str):
        q = query.strip().lower()
        self.int_table.setUpdatesEnabled(False)
        try:
            for r in range(self.int_table.rowCount()):
                it = self.int_table.item(r, 0)
                it_alias = self.int_table.item(r, 1)
                if not it:
                    self.int_table.setRowHidden(r, bool(q))
                    continue
                name = str(it.data(Qt.ItemDataRole.UserRole) or it.text() or "").lower()
                alias = str(it.data(Qt.ItemDataRole.UserRole + 1) or (it_alias.text() if it_alias else "") or "").lower()
                if not alias and name:
                    alias = self._int_alias_map.get(" ".join(name.split()).lower(), "").lower()
                txt = it.text().lower()
                match = (not q) or (q in txt) or (q in name) or (q in alias)
                self.int_table.setRowHidden(r, not match)
        finally:
            self.int_table.setUpdatesEnabled(True)
        self._update_int_totals()

    def _filter_vat_table(self, query: str):
        q = query.strip().lower()
        self.vat_table.setUpdatesEnabled(False)
        try:
            for r in range(self.vat_table.rowCount()):
                it = self.vat_table.item(r, 0)
                it_alias = self.vat_table.item(r, 1)
                if not it:
                    self.vat_table.setRowHidden(r, bool(q))
                    continue
                name = str(it.data(Qt.ItemDataRole.UserRole) or it.text() or "").lower()
                alias = str(it.data(Qt.ItemDataRole.UserRole + 1) or (it_alias.text() if it_alias else "") or "").lower()
                if not alias and name:
                    alias = self._vat_alias_map.get(" ".join(name.split()).lower(), "").lower()
                txt = it.text().lower()
                match = (not q) or (q in txt) or (q in name) or (q in alias)
                self.vat_table.setRowHidden(r, not match)
        finally:
            self.vat_table.setUpdatesEnabled(True)
        self._update_vat_totals()

    def _focus_mapping_search(self):
        """Focus the mapping search input and select all text."""
        if hasattr(self, 'mapping_search'):
            self.mapping_search.setFocus()
            self.mapping_search.selectAll()

    def _on_mapping_search_user_edited(self, text):
        """User typed into search input with keyboard: destage any staged group."""
        if getattr(self, '_staged_group_id', None) is not None and not getattr(self, '_is_destaging', False):
            self.destage_and_select()

    def _filter_mapping_table(self, query: str):
        q = query.strip().lower()
        total_rows = self.mapping_table.rowCount()
        if total_rows == 0:
            return
        if not q:
            self.mapping_table.setUpdatesEnabled(False)
            try:
                for r in range(total_rows):
                    self.mapping_table.setRowHidden(r, False)
            finally:
                self.mapping_table.setUpdatesEnabled(True)
            self._update_mapping_totals()
            return

        # Ensure alias maps are pre-loaded
        if not self._int_alias_map:
            self._get_internal_ledger_options()
        if not self._vat_alias_map:
            self._get_vat_ledger_options()

        # Tokenize query for multi-term AND search across fields (e.g. "Ramesh 50000" or "12 Delhi")
        tokens = [t for t in q.split() if t]
        tokens_no_commas = [t.replace(",", "") for t in tokens]

        # Group row indices by group_id
        groups = {}
        for r in range(total_rows):
            it = self.mapping_table.item(r, 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else r
            groups.setdefault(gid, []).append(r)

        self.mapping_table.setUpdatesEnabled(False)
        try:
            for gid, rows in groups.items():
                first_it = self.mapping_table.item(rows[0], 0)
                m = getattr(first_it, "_mapping_group", None)
                if not m:
                    for r_check in rows:
                        for c_check in (0, 1, 2):
                            it_chk = self.mapping_table.item(r_check, c_check)
                            if it_chk and getattr(it_chk, "_mapping_group", None):
                                m = it_chk._mapping_group
                                break
                        if m:
                            break
                if not m:
                    m = {}

                # Collect searchable strings from group dict
                group_strings = set()

                # 1. VAT names, aliases, and constituent items
                v_names_list = m.get("vat_ledgers", []) or [vi.get("name", "") for vi in m.get("vat_items", []) if vi.get("name")]
                for vn in v_names_list:
                    if vn:
                        group_strings.add(str(vn))
                        vk = " ".join(str(vn).split()).lower()
                        if vk in self._vat_alias_map:
                            group_strings.add(self._vat_alias_map[vk])

                for vi in m.get("vat_items", []):
                    if vi.get("name"):
                        group_strings.add(str(vi["name"]))
                    if vi.get("alias"):
                        group_strings.add(str(vi["alias"]))
                    if vi.get("serial_no"):
                        group_strings.add(str(vi["serial_no"]))
                    if vi.get("closing") is not None:
                        c_val = float(vi.get("closing", 0) or 0)
                        c_int = int(round(c_val))
                        group_strings.add(str(c_int))
                        group_strings.add(f"{c_int:,}")
                        group_strings.add(f"{c_val:.2f}")
                        group_strings.add(str(c_val))
                        if c_val < 0:
                            group_strings.add(str(abs(c_int)))
                            group_strings.add(f"{abs(c_int):,}")
                            group_strings.add(f"{abs(c_val):.2f}")

                # 2. Internal names, aliases, and constituent items
                i_names_list = m.get("internal_ledgers", []) or [ii.get("name", "") for ii in m.get("internal_items", []) if ii.get("name")]
                for iname in i_names_list:
                    if iname:
                        group_strings.add(str(iname))
                        ik = " ".join(str(iname).split()).lower()
                        if ik in self._int_alias_map:
                            group_strings.add(self._int_alias_map[ik])

                for ii in m.get("internal_items", []):
                    if ii.get("name"):
                        group_strings.add(str(ii["name"]))
                    if ii.get("alias"):
                        group_strings.add(str(ii["alias"]))
                    if ii.get("closing") is not None:
                        c_val = float(ii.get("closing", 0) or 0)
                        c_int = int(round(c_val))
                        group_strings.add(str(c_int))
                        group_strings.add(f"{c_int:,}")
                        group_strings.add(f"{c_val:.2f}")
                        group_strings.add(str(c_val))
                        if c_val < 0:
                            group_strings.add(str(abs(c_int)))
                            group_strings.add(f"{abs(c_int):,}")
                            group_strings.add(f"{abs(c_val):.2f}")

                # 3. Aliases, manual names, classifications, narration, and status keywords
                for a in m.get("vat_aliases", []) or []:
                    if a: group_strings.add(str(a))
                for a in m.get("internal_aliases", []) or []:
                    if a: group_strings.add(str(a))
                for mn in m.get("manual_names", []) or []:
                    if mn: group_strings.add(str(mn))
                if m.get("manual_name"):
                    group_strings.add(str(m["manual_name"]))
                if m.get("classification"):
                    group_strings.add(str(m["classification"]))
                if m.get("narration"):
                    group_strings.add(str(m["narration"]))
                if m.get("serial_no"):
                    group_strings.add(str(m["serial_no"]))
                if m.get("is_unmapped"):
                    group_strings.add("unmapped")
                if m.get("is_merged") or len(v_names_list) > 1:
                    group_strings.add("merged")
                    group_strings.add("combined")
                if m.get("is_none_vat"):
                    group_strings.add("none")

                # 4. Collect from ALL table cells in this group across all rows and all columns
                for r in rows:
                    for c in range(self.mapping_table.columnCount()):
                        it = self.mapping_table.item(r, c)
                        if it:
                            txt = it.text().strip()
                            if txt:
                                group_strings.add(txt)
                                if txt.startswith("↳ "):
                                    group_strings.add(txt[2:].strip())
                                if "," in txt:
                                    group_strings.add(txt.replace(",", ""))

                            # NumericTableWidgetItem values (Col 0, 3, 4, 5, 6)
                            if hasattr(it, "num_value") and it.num_value is not None:
                                nv = float(it.num_value)
                                int_val = int(round(nv))
                                group_strings.add(str(int_val))
                                group_strings.add(f"{int_val:,}")
                                group_strings.add(f"{nv:.2f}")
                                group_strings.add(str(nv))
                                if nv < 0:
                                    abs_int = abs(int_val)
                                    group_strings.add(str(abs_int))
                                    group_strings.add(f"{abs_int:,}")
                                    group_strings.add(f"{abs(nv):.2f}")

                            # UserRole metadata across roles
                            for role_offset in (0, 1, 2, 3, 5, 7, 8):
                                udata = it.data(Qt.ItemDataRole.UserRole + role_offset)
                                if udata is not None:
                                    s_udata = str(udata).strip()
                                    if s_udata:
                                        group_strings.add(s_udata)
                                        if "," in s_udata:
                                            group_strings.add(s_udata.replace(",", ""))

                        # Active cellWidget (e.g. inline editor)
                        cw = self.mapping_table.cellWidget(r, c)
                        if cw and hasattr(cw, "text"):
                            cw_txt = cw.text().strip()
                            if cw_txt:
                                group_strings.add(cw_txt)
                                if "," in cw_txt:
                                    group_strings.add(cw_txt.replace(",", ""))

                # Build combined lower-case corpus
                corpus_text = " ".join(group_strings).lower()
                corpus_no_commas = corpus_text.replace(",", "")
                corpus_no_punct = corpus_text.replace(".", "").replace("-", "").replace("/", "")

                # Check if all query tokens match this group
                group_match = True
                for i, tok in enumerate(tokens):
                    tok_no_comma = tokens_no_commas[i]
                    tok_no_punct = tok.replace(".", "").replace("-", "").replace("/", "")

                    if (tok in corpus_text) or \
                       (tok_no_comma in corpus_no_commas) or \
                       (tok_no_punct in corpus_no_punct):
                        continue
                    else:
                        group_match = False
                        break

                for r in rows:
                    self.mapping_table.setRowHidden(r, not group_match)
        finally:
            self.mapping_table.setUpdatesEnabled(True)
        self._update_mapping_totals()

    # ── SYNCHRONIZATION ──────────────────────────────────────────────

    def sync_int_ledger(self):
        """Trigger sync for Internal Ledger from running Tally instance."""
        if hasattr(self, '_int_worker') and self._int_worker and self._int_worker.isRunning():
            QMessageBox.warning(self, "Sync in Progress", "Internal Ledger sync is already running.")
            return

        if not self.current_company_name:
            QMessageBox.warning(self, "No Company", "Please select a company first.")
            return

        if not hasattr(self, '_int_service') or self._int_service is None:
            self._int_service = TallyService()
        else:
            self._int_service.cancelled = False

        self._int_progress = QProgressDialog("Syncing Internal Ledger from Tally...", "Cancel", 0, 0, self)
        self._int_progress.setWindowTitle("Internal Ledger Sync")
        self._int_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._int_progress.canceled.connect(self._int_service.cancel)
        self._int_progress.show()

        self._int_worker = _InternalLedgerWorker(
            self.current_company_name, self.current_company_path, self._int_service
        )
        self._int_worker.finished.connect(self._on_int_sync_done)
        self._int_worker.start()

    def _on_int_sync_done(self, count: int, error: str):
        if hasattr(self, '_int_progress') and self._int_progress:
            self._int_progress.close()

        if hasattr(self, '_int_worker') and self._int_worker:
            self._int_worker.wait()
            self._int_worker = None

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "Internal Ledger sync was cancelled.")
        elif error:
            QMessageBox.warning(self, "Sync Issue", f"Failed to sync Internal Ledger:\n{error}")
        else:
            debtors = load_internal_debtors(self.db_name) if self.db_name else []
            d_count = len(debtors)
            if self.db_name and self.active_vat_company:
                run_auto_mapping_on_sync(self.db_name, self.active_vat_company)
            QMessageBox.information(
                self, "Sync Complete",
                f"Synced {count} total internal ledgers from Tally ({d_count} Sundry Debtors)."
            )
            self.load_data(self.current_company_path, company_name=self.current_company_name, force=True)

    def sync_vat_ledger(self):
        """Trigger sync for VAT Ledger from running Tally instance."""
        if hasattr(self, '_vat_worker') and self._vat_worker and self._vat_worker.isRunning():
            QMessageBox.warning(self, "Sync in Progress", "VAT Ledger sync is already running.")
            return

        if not self.active_vat_company:
            QMessageBox.warning(
                self, "VAT Company Missing",
                "Please configure an active VAT Company first by clicking 'VAT Company'."
            )
            return

        if not hasattr(self, '_vat_service') or self._vat_service is None:
            self._vat_service = TallyService()
        else:
            self._vat_service.cancelled = False

        self._vat_progress = QProgressDialog(
            f"Syncing VAT Ledgers from Tally for '{self.active_vat_company}'...", "Cancel", 0, 0, self
        )
        self._vat_progress.setWindowTitle("VAT Ledger Sync")
        self._vat_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._vat_progress.canceled.connect(self._vat_service.cancel)
        self._vat_progress.show()

        self._vat_worker = _VatLedgerWorker(
            self.active_vat_company, self.current_company_name, self.current_company_path, self._vat_service
        )
        self._vat_worker.finished.connect(self._on_vat_sync_done)
        self._vat_worker.start()

    def _on_vat_sync_done(self, count: int, error: str):
        if hasattr(self, '_vat_progress') and self._vat_progress:
            self._vat_progress.close()

        if hasattr(self, '_vat_worker') and self._vat_worker:
            self._vat_worker.wait()
            self._vat_worker = None

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "VAT Ledger sync was cancelled.")
        elif error:
            QMessageBox.warning(self, "Sync Issue", f"Failed to sync VAT Ledgers:\n{error}")
        else:
            debtors = load_vat_debtors(self.db_name, self.active_vat_company) if self.db_name and self.active_vat_company else []
            d_count = len(debtors)
            c_count = count - d_count
            c_info = f", {c_count} Creditors" if c_count > 0 else ""
            if self.db_name and self.active_vat_company:
                run_auto_mapping_on_sync(self.db_name, self.active_vat_company)
            QMessageBox.information(
                self, "Sync Complete",
                f"Successfully synced {count} total VAT ledgers ({d_count} Debtors{c_info}) for '{self.active_vat_company}'."
            )
            self.load_data(self.current_company_path, company_name=self.current_company_name, force=True)

    # ── VAT COMPANY POPUP ────────────────────────────────────────────

    def open_vat_company_dialog(self):
        """Open the multi-profile VAT company management dialog."""
        if not self.db_name:
            QMessageBox.warning(self, "No Company", "Please select an active company first.")
            return

        dlg = VatCompanyDialog(self.db_name, self)
        dlg.company_changed.connect(self._on_vat_company_changed)
        dlg.exec()

    def _on_vat_company_changed(self, new_company: str):
        self.active_vat_company = new_company.strip()
        self.lbl_active_vat.setText(f"Active VAT Company: {self.active_vat_company}")
        # Refresh all VAT views off-thread with lazy rendering
        self.load_data(self.current_company_path, company_name=self.current_company_name, force=True)

    # ── PERMISSION CONTROL ───────────────────────────────────────────

    def apply_edit_mode(self, can_edit: bool):
        """Enforce display-only mode based on user permissions."""
        self._can_edit = can_edit
        if hasattr(self, 'mapping_table'):
            self.mapping_table._can_edit = can_edit
        if hasattr(self, 'btn_vat_company'):
            self.btn_vat_company.setEnabled(can_edit)
        if hasattr(self, 'btn_tab_sync_int'):
            self.btn_tab_sync_int.setEnabled(can_edit)
        if hasattr(self, 'btn_tab_sync_vat'):
            self.btn_tab_sync_vat.setEnabled(can_edit)
        # Lock mapping table editing across editable columns (1: VAT, 2: Int) and action buttons
        if hasattr(self, '_mapping_delegate'):
            self._mapping_delegate.can_edit = can_edit
            if hasattr(self, 'mapping_table'):
                self.mapping_table.viewport().update()

        if hasattr(self, 'mapping_table'):
            for r in range(self.mapping_table.rowCount()):
                for c in (1, 2):
                    it = self.mapping_table.item(r, c)
                    if it:
                        if can_edit:
                            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Propagate _can_edit to conf tables so VatConfDelegate can check it
        if hasattr(self, 'debtor_table'):
            self.debtor_table._can_edit = can_edit
            for r in range(self.debtor_table.rowCount()):
                for c in [0, 7, 9, 10, 11, 12]:
                    it = self.debtor_table.item(r, c)
                    if it:
                        if can_edit:
                            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

        if hasattr(self, 'creditor_table'):
            self.creditor_table._can_edit = can_edit
            for r in range(self.creditor_table.rowCount()):
                for c in [4, 5, 6]:
                    it = self.creditor_table.item(r, c)
                    if it:
                        if can_edit:
                            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def apply_clear_mapping_permission(self, can_clear: bool):
        """Update permission to clear mapping."""
        self._can_clear_mapping = can_clear
        if hasattr(self, 'btn_unmap_mapping'):
            self.btn_unmap_mapping.setEnabled(can_clear)

    # ── EXPORT / PRINT INTEGRATION HELPER ────────────────────────────

    def get_current_table(self) -> tuple[str, QTableWidget]:
        """Return (title, table_widget) for the currently focused/active tab."""
        idx = self.tabs.currentIndex()
        if idx == 0:
            return "VAT Working - Int. Ledger", self.int_table
        elif idx == 1:
            return f"VAT Working - Vat Ledger ({self.active_vat_company})", self.vat_table
        elif idx == 2:
            return f"VAT Working - Mapping ({self.active_vat_company})", self.mapping_table
        elif idx == 3:
            if hasattr(self, 'conf_tabs') and self.conf_tabs.currentIndex() == 1:
                return f"VAT Conf - Creditor ({self.active_vat_company})", self.creditor_table
            return f"VAT Conf - Debtor ({self.active_vat_company})", self.debtor_table
        elif idx == 4:
            return f"VAT Working - Empty Ledger ({self.active_vat_company})", self.empty_ledger_table
        return "VAT Working Table", self.int_table
