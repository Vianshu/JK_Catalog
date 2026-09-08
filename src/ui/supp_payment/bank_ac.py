# =============================================================================
# bank_ac_tab.py — _AccCard, _SupplierSection, RecordTab (Bank A/C)
# =============================================================================
import os
import re as _re
import json as _json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter,
    QFormLayout, QApplication, QAbstractScrollArea, QFileDialog,
    QColorDialog, QTextEdit, QStyledItemDelegate, QStyle,
    QAbstractItemDelegate,
)
from PyQt6.QtCore import (
    Qt, QTimer, QDate, QEvent, QMimeData, QSettings, QRect, QPoint,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPixmap, QPainter, QKeySequence,
    QShortcut, QCursor, QImage, QPen, QFontMetrics,
)
from src.logic.db_manager import get_db_manager, build_logical_name
from .shared import (
    _PrintExportMixin, ModernTableDelegate,
    _bold_font, _norm_font,
    _SCROLLBAR_STYLE, _TABLE_STYLE, _SECTION_HEADER_STYLE,
    _BTN_PRIMARY, _BTN_SECONDARY, _BTN_DANGER,
    _MENU_STYLE, _POPUP_STYLE, _CARD_MENU_STYLE,
    _setup_smart_header, _DbTable, get_icon,
)
from src.ui.table_nav_mixin import UniversalCellDelegate

# ===========================================================================
# RECORD TAB ΓÇö Supplier Bank Accounts
# ===========================================================================
_REC_FIELDS = [
    ("naam",    "नाम",        "Name"),
    ("thegana", "ठेगाना",    "Address"),
    ("baik",    "बैंक",       "Bank"),
    ("khata",   "खाता न.",   "Account No."),
    ("rakam",   "रकम",        "Amount"),
    ("jamma",   "जम्मा गर्ने","Deposit To"),
]

# ΓöÇΓöÇΓöÇ color tokens ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
_C_CO_BG     = "#f0faf5"   # company card background
_C_CO_BORDER = "#b2dfcc"   # company card border
_C_CO_ACCENT = "#1e7a4b"   # company label/header accent
_C_CO_HEAD   = "#e6f5ee"   # company column header bg

_C_PE_BG     = "#f0fdfa"   # personal card bg
_C_PE_BORDER = "#5eead4"   # personal card border
_C_PE_ACCENT = "#0f766e"   # personal label/header accent
_C_PE_HEAD   = "#ccfbf1"   # personal column header bg

_C_SUP_HEADER  = "#f8f9fa"  # supplier row header bg
_C_PAGE_BG     = "#eef0f3"  # scroll-area bg
_C_CARD_NORM   = "#ffffff"  # unselected card bg
_C_SEP         = "#d1d5db"  # thin separators

# ΓöÇΓöÇΓöÇ common input stylesheet ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
def _field_ss(accent_color="#1a4a8a", is_amount=False):
    """Uniform field stylesheet. Amount gets bold text only ΓÇö no green tint."""
    return f"""
        QLineEdit {{
            background:#ffffff; border:1px solid #d1d5db;
            border-radius:0px; padding:0px 2px; margin:0px;
            color:#111827;
            {'font-weight:bold;' if is_amount else ''}
        }}
        QLineEdit:hover {{ border-color:{accent_color}; }}
        QLineEdit:focus {{ border:1px solid {accent_color}; background:white; }}
        QLineEdit:read-only {{
            background:#f9fafb; border-color:#e5e7eb;
            color:#374151;
        }}
    """


class _AccCard(QFrame):
    """One compact account card ΓÇö label | input rows, right-click to delete."""

    def __init__(self, supplier_id, acc_idx, acc_data, db, db_name,
                 is_company=True, can_edit=True, refresh_fn=None, parent=None):
        super().__init__(parent)
        self.supplier_id  = supplier_id
        self.acc_idx      = acc_idx
        self._db          = db
        self._db_name     = db_name
        self._can_edit    = can_edit
        self._is_company  = is_company
        self._saving      = False
        self._selected    = False
        self._refresh_fn  = refresh_fn
        self._field_edits = []  # list of (fkey, QLineEdit)

        self.is_red = bool(acc_data.get("is_red", 0))

        if self.is_red:
            accent = "#ef4444"
            bg     = "#fef2f2"
            border = "#f87171"
        else:
            accent = _C_CO_ACCENT if is_company else _C_PE_ACCENT
            bg     = _C_CO_BG     if is_company else _C_PE_BG
            border = _C_CO_BORDER if is_company else _C_PE_BORDER

        self.setObjectName("AccCard")
        self._norm_ss = (
            f"QFrame#AccCard{{background:{bg};border:1px solid {border};"
            f"border-radius:3px;}}"
        )
        self._sel_ss = (
            f"QFrame#AccCard{{background:{bg};border:2px solid {accent};"
            f"border-radius:3px;}}"
        )
        self.setStyleSheet(self._norm_ss)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QFormLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)  # Zero whitespace like a tight table
        lay.setHorizontalSpacing(0)
        lay.setVerticalSpacing(0)
        lay.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        fm_cache = {}  # font ΓåÆ QFontMetrics, computed once per font object

        for fkey, flabel_np, flabel_en in _REC_FIELDS:
            val = acc_data.get(fkey, "")
            is_amount = fkey == "rakam"

            lbl = QLabel(f"{flabel_np}:")
            lbl.setFont(_norm_font(9))
            lbl.setStyleSheet(
                f"color:{'#065f3a' if is_amount and is_company else accent if is_amount else '#6b7280'};"
                f"font-weight:{'600' if is_amount else '400'};"
                f"background:transparent; padding-right:2px;"
            )

            edit_font = _bold_font(11) if is_amount else _norm_font(10)
            edit = QLineEdit(val)
            edit.setFont(edit_font)
            edit.setStyleSheet(_field_ss(accent, is_amount))
            edit.setReadOnly(not can_edit)
            edit.setFixedHeight(34)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if is_amount:
                edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            edit.editingFinished.connect(self._save)
            
            def _adjust_width(txt, ed=edit):
                txt = str(txt)
                fm = ed.fontMetrics()
                # 30px padding for margins and borders
                w = fm.horizontalAdvance(txt) + 30
                # Don't let it get too small
                ed.setMinimumWidth(max(150, w))
            edit.textChanged.connect(_adjust_width)
            _adjust_width(str(val))

            lay.addRow(lbl, edit)
            self._field_edits.append((fkey, edit))

        # Enable right-click context menu for Delete/Mark-Red
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------------
    def _show_context_menu(self, _):
        if not self._can_edit:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
            QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
            QMenu::item:selected{background:#fee2e2;color:#b91c1c;border-radius:2px;}
        """)
        act_red = menu.addAction("Unmark Red" if self.is_red else "Mark as Red")
        menu.addSeparator()
        act_del = menu.addAction("Delete Account")
        act_del.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_TrashIcon))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_del:
            self._delete_self()
        elif chosen == act_red:
            self.is_red = not self.is_red
            self._save_red_state()

    def _save_red_state(self):
        conn = self._db.get_connection(self._db_name)
        if not conn: return
        try:
            conn.cursor().execute("UPDATE supplier_accounts SET is_red=? WHERE supplier_id=? AND acc_index=?",
                                  (1 if self.is_red else 0, self.supplier_id, self.acc_idx))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("Error saving red state:", e)
        if callable(self._refresh_fn):
            self._refresh_fn()

    def _delete_self(self):
        msg = QMessageBox(self.window())
        msg.setWindowTitle("Delete Account")
        msg.setText(f"Delete this {'Company' if self._is_company else 'Personal'} account card?")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM supplier_accounts WHERE supplier_id=? AND acc_index=?",
                (self.supplier_id, self.acc_idx))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[AccCard] delete error:", e)
            return
        if callable(self._refresh_fn):
            self._refresh_fn()

    def set_selected(self, sel: bool):
        self._selected = sel
        self.setStyleSheet(self._sel_ss if sel else self._norm_ss)

    def is_selected(self) -> bool:
        return self._selected

    def set_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        for _, e in self._field_edits:
            e.setReadOnly(not can_edit)

    def _save(self):
        if not self._db_name or self._saving or not self._can_edit:
            return
        self._saving = True
        conn = self._db.get_connection(self._db_name)
        if not conn:
            self._saving = False
            return
        cur = conn.cursor()
        try:
            for fkey, edit in self._field_edits:
                cur.execute(
                    f"UPDATE supplier_accounts SET {fkey}=? "
                    f"WHERE supplier_id=? AND acc_index=?",
                    (edit.text().strip(), self.supplier_id, self.acc_idx))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[AccCard] _save error:", e)
        finally:
            self._saving = False


class _SupplierSection(QFrame):
    """One supplier: compact header + two-column account area (Company | Personal)."""

    def __init__(self, supplier_id, name, accounts, db, db_name,
                 can_edit=True, refresh_fn=None, parent=None):
        super().__init__(parent)
        self.supplier_id  = supplier_id
        self._db          = db
        self._db_name     = db_name
        self._can_edit    = can_edit
        self._saving      = False
        self._refresh_fn  = refresh_fn
        self._acc_cards: list[_AccCard] = []
        self._card_field_edits: set = set()   # all QLineEdits inside cards
        self._selected    = False

        self.setObjectName("SupplierSection")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._norm_ss = (
            "QFrame#SupplierSection{"
            "background:#ffffff;border:1px solid #d1d5db;"
            "border-radius:4px;}"
        )
        self._sel_ss = (
            "QFrame#SupplierSection{"
            "background:#f8fffc;border:2px solid #1e7a4b;"
            "border-radius:4px;}"
        )
        self.setStyleSheet(self._norm_ss)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Supplier header (now a left card)
        hdr = QFrame()
        hdr.setObjectName("SuppHdr")
        hdr.setFixedWidth(200) # Give it a fixed width so it acts like a column
        self.hdr = hdr # Save reference for selection styling
        hdr.setStyleSheet(
            f"QFrame#SuppHdr{{background:{_C_SUP_HEADER};"
            f"border-right:1px solid {_C_SEP};" # border on the right
            f"border-radius:4px 0 0 4px;}}"
        )
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(10, 10, 6, 10)
        hdr_lay.setSpacing(8)

        # Index badge
        badge = QLabel(f"#{supplier_id}")
        badge.setFont(_bold_font(8))
        badge.setFixedSize(32, 18)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "color:#374151;background:#e5e7eb;"
            "border-radius:2px;font-size:8pt;")
        hdr_lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Supplier name
        self._name_edit = QTextEdit(name)
        self._name_edit.setPlaceholderText("Supplier / Party Name...")
        self._name_edit.setFont(_bold_font(12))
        self._name_edit.setStyleSheet("""
            QTextEdit {
                background:transparent; border:none;
                color:#111827; font-size:12pt; font-weight:600;
            }
            QTextEdit:focus {
                border-bottom:1px solid #1e7a4b;
                background:transparent;
            }
            QTextEdit:read-only { color:#1f2937; }
        """)
        self._name_edit.setReadOnly(not can_edit)
        self._name_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._name_edit.customContextMenuRequested.connect(self._show_context_menu)
        self._name_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._name_edit.installEventFilter(self)
        
        # Auto-resize height as text changes to prevent cutting off long names
        self._name_edit.document().documentLayout().documentSizeChanged.connect(
            lambda size: self._name_edit.setMinimumHeight(int(size.height()) + 10)
        )
        
        hdr_lay.addWidget(self._name_edit)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Install event filter on hdr background frame so clicking anywhere
        # on the supplier name panel also triggers section selection
        hdr.installEventFilter(self)

        root.addWidget(hdr)

        # ΓòÉΓòÉ Two-column body ΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉ
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # Split accounts into company vs personal
        co_accs = [(a.get("acc_idx", i), a) for i, a in enumerate(accounts)
                   if "company" in a.get("type", "").lower()]
        pe_accs = [(a.get("acc_idx", i), a) for i, a in enumerate(accounts)
                   if "company" not in a.get("type", "").lower()]

        for is_co, accs_for_col, head_txt, head_bg, head_accent in [
            (True,  co_accs, "COMPANY ACCOUNTS",  _C_CO_HEAD, _C_CO_ACCENT),
            (False, pe_accs, "PERSONAL ACCOUNTS", _C_PE_HEAD, _C_PE_ACCENT),
        ]:
            if not accs_for_col:
                continue
                
            col = QWidget()
            col.setStyleSheet("background:transparent;")
            # Fixed horizontal size so column hugs its card content width
            col.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            col_lay = QVBoxLayout(col)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(0)

            # -- cards in a fixed-size container so header can match its width --
            cards_widget = QWidget()
            cards_widget.setStyleSheet("background:transparent;")
            cards_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            cards_row_lay = QHBoxLayout(cards_widget)
            cards_row_lay.setContentsMargins(0, 0, 0, 0)
            cards_row_lay.setSpacing(0)
            for acc_idx, acc_data in accs_for_col:
                card = _AccCard(
                    supplier_id, acc_idx, acc_data,
                    db, db_name, is_co, can_edit, refresh_fn=self._refresh_fn, parent=body)
                card.setMinimumWidth(250)
                # Use installEventFilter instead of monkey-patching mousePressEvent
                # so child QLineEdit widgets keep native click-to-position-cursor behavior
                card.installEventFilter(self)
                # Also filter each field QLineEdit so clicks on them
                # propagate to the section selection handler
                for _, field_edit in card._field_edits:
                    field_edit.installEventFilter(self)
                    self._card_field_edits.add(field_edit)
                cards_row_lay.addWidget(card)
                self._acc_cards.append(card)

            # Header label -- width synced to cards_widget after layout
            col_hdr = QLabel(head_txt)
            col_hdr.setFont(_bold_font(10))
            col_hdr.setFixedHeight(28)
            col_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col_hdr.setStyleSheet(
                f"color:{head_accent};background:{head_bg};"
                f"border-bottom:1px solid {'#c2ddd0' if is_co else '#c0cfe8'};"
                f"border-radius:2px;font-size:10pt;letter-spacing:0.5px;")

            col_lay.addWidget(col_hdr)
            col_lay.addWidget(cards_widget)
            col_lay.addStretch()

            # No stretch factor -- column is exactly as wide as its content
            body_lay.addWidget(col)

        root.addWidget(body)

    # ------------------------------------------------------------------
    def eventFilter(self, source, event):
        if source == self._name_edit:
            if event.type() == QEvent.Type.FocusOut:
                self._save_name()
            elif event.type() == QEvent.Type.MouseButtonPress:
                # Let the user click in the text area to edit, but also select the section
                if hasattr(self, 'click_callback'):
                    try:
                        self.click_callback(event, self)
                    except Exception:
                        pass
                # Do NOT return True — QTextEdit still needs to process cursor positioning
        elif event.type() == QEvent.Type.MouseButtonPress and (
            source in self._acc_cards or source in self._card_field_edits
            or source is self.hdr
        ):
            # Click anywhere on a card, its fields, or supplier header → select this section
            if hasattr(self, 'click_callback'):
                try:
                    self.click_callback(event, self)
                except Exception:
                    pass
            # Do NOT consume — QLineEdit still gets focus and cursor placement
        return super().eventFilter(source, event)

    def _acc_click(self, event, card: _AccCard):
        pass
        # Bubble up so RecordTab can update its status bar
        if hasattr(self.parent(), '_update_status'):
            try:
                self.parent()._update_status()  # type: ignore
            except Exception:
                pass

    def set_selected(self, sel: bool):
        """Select/deselect the supplier section frame only ΓÇö not the account cards."""
        self._selected = sel
        self.setStyleSheet(self._sel_ss if sel else self._norm_ss)

    def is_selected(self) -> bool:
        return self._selected

    def selected_cards(self) -> list:
        return [c for c in self._acc_cards if c.is_selected()]

    def set_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._name_edit.setReadOnly(not can_edit)
        for c in self._acc_cards:
            c.set_edit_mode(can_edit)

    def _save_name(self):
        if not self._db_name or self._saving or not self._can_edit:
            return
        self._saving = True
        conn = self._db.get_connection(self._db_name)
        if not conn:
            self._saving = False
            return
        cur = conn.cursor()
        try:
            cur.execute("UPDATE supplier_records SET name=? WHERE id=?",
                        (self._name_edit.toPlainText().strip(), self.supplier_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[SupplierSection] _save_name error:", e)
        finally:
            self._saving = False

    def _show_context_menu(self, _):
        if not self._can_edit:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
            QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
            QMenu::item:selected{background:#fee2e2;color:#b91c1c;border-radius:2px;}
        """)
        act_del = menu.addAction("Delete Supplier")
        act_del.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_TrashIcon))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_del:
            self._delete_supplier()

    def _delete_supplier(self):
        """Delete this entire supplier record + all its accounts."""
        name = self._name_edit.toPlainText().strip() or f"Supplier #{self.supplier_id}"
        msg = QMessageBox(self.window())
        msg.setWindowTitle("Delete Supplier")
        msg.setText(f"Delete supplier '{name}' and ALL its account cards?")
        msg.setInformativeText("This cannot be undone.")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM supplier_accounts WHERE supplier_id=?",
                        (self.supplier_id,))
            cur.execute("DELETE FROM supplier_records WHERE id=?",
                        (self.supplier_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[SupplierSection] _delete_supplier error:", e)
            return
        if callable(self._refresh_fn):
            self._refresh_fn()


class RecordTab(_PrintExportMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._db = get_db_manager()
        self._db_name = ""
        self._sections: list[_SupplierSection] = []
        self._last_clicked_idx = -1
        self.no_border_cols = [1]  # Col 1 is "Name", do not draw horizontal lines so it merges vertically

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Body Content ──
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        main_layout.addWidget(body_widget, 1)

        # (No top header anymore)

        # ── Search Input (Inline in right bar) ──
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Search supplier...")
        self._search.setStyleSheet("""
            QLineEdit {
                background: #ecfdf5; 
                border: 1px solid #059669; 
                border-radius: 4px;
                padding: 4px;
                font-size: 10pt; 
                color: #064e3b;
            }
        """)
        self._search.setFixedHeight(32)
        self._search.textChanged.connect(self._filter_sections)
        self._search.hide() # Hidden when collapsed

        # ── Right Bar ──
        right_bar = QWidget()
        right_bar.setStyleSheet("background:#f8fafc; border-left:1px solid #e2e8f0;")
        right_bar.setFixedWidth(52)
        rlay = QVBoxLayout(right_bar)
        rlay.setContentsMargins(6, 16, 6, 16)
        rlay.setSpacing(12)
        
        rlay.addWidget(self._search)

        self._btn_search = QPushButton()
        self._btn_search.setIcon(get_icon("search.svg"))
        self._btn_search.setStyleSheet(_BTN_PRIMARY)
        self._btn_search.setFixedHeight(32)
        self._btn_search.clicked.connect(self.toggle_search)
        rlay.addWidget(self._btn_search)

        self._btn_add = QPushButton()
        self._btn_add.setIcon(get_icon("user_add.svg"))
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(lambda: self._add_supplier())
        rlay.addWidget(self._btn_add)

        self._btn_add_co = QPushButton()
        self._btn_add_co.setIcon(get_icon("company_add.svg"))
        self._btn_add_co.setStyleSheet(_BTN_PRIMARY)
        self._btn_add_co.setFixedHeight(32)
        self._btn_add_co.clicked.connect(self._add_company_acct)
        rlay.addWidget(self._btn_add_co)

        self._btn_add_pe = QPushButton()
        self._btn_add_pe.setIcon(get_icon("personal_add.svg"))
        self._btn_add_pe.setStyleSheet(_BTN_PRIMARY)
        self._btn_add_pe.setFixedHeight(32)
        self._btn_add_pe.clicked.connect(self._add_personal_acct)
        rlay.addWidget(self._btn_add_pe)

        shortcut = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_C), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._copy_selected_as_image)
        self.btn_copy_records = QPushButton()
        self.btn_copy_records.setIcon(get_icon("copy.svg"))
        self.btn_copy_records.setStyleSheet(_BTN_PRIMARY)
        self.btn_copy_records.setFixedHeight(32)
        self.btn_copy_records.clicked.connect(self._copy_selected_as_image)
        rlay.addWidget(self.btn_copy_records)

        self._sel_status = QLabel("")
        self._sel_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sel_status.setWordWrap(True)
        rlay.addWidget(self._sel_status)

        def on_toggle_bank(expanded):
            if expanded:
                self._search.show()
                self._btn_search.hide()
                self._btn_add.setText(" Add Bank A/C")
                self._btn_add_co.setText(" Add Company")
                self._btn_add_pe.setText(" Add Personal")
            else:
                self._search.hide()
                self._search.clear()
                self._btn_search.show()
                self._btn_add.setText("")
                self._btn_add_co.setText("")
                self._btn_add_pe.setText("")
            self._update_status()

        self._init_print_export(rlay, "Supplier Bank Accounts", table_getter=self._get_tables_for_excel, print_table_getter=self._get_tables_for_print, right_bar=right_bar, on_toggle_cb=on_toggle_bank)
        self._export_title_on_left = True
        
        rlay.addStretch()
        main_layout.addWidget(right_bar)



        # ══ Scroll area ══════════════════════════════════════════════════
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{_C_PAGE_BG};}}"
            "QScrollBar:vertical{width:7px;background:transparent;}"
            "QScrollBar::handle:vertical{background:#c1c9d2;border-radius:3px;min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#a0aab4;}"
        )
        self._container = QWidget()
        self._container.setStyleSheet(f"background:{_C_PAGE_BG};")
        self._c_lay = QVBoxLayout(self._container)
        self._c_lay.setContentsMargins(8, 8, 8, 8)
        self._c_lay.setSpacing(0)  # No gap between supplier cards
        self._scroll.setWidget(self._container)
        body_layout.addWidget(self._scroll)

    def toggle_search(self):
        """Expand the right panel if collapsed, then focus the search input."""
        # Check the actual right-bar widget width instead of the shared class-level
        # _right_bar_expanded flag, which is shared across ALL tabs using _PrintExportMixin
        # and would wrongly report 'expanded' if any other tab had opened its sidebar.
        btn = getattr(self, 'btn_toggle', None)
        if btn:
            # The right bar is collapsed when its width <= 60px (collapsed state = 52px)
            right_bar = btn.parentWidget()
            is_expanded = right_bar is not None and right_bar.width() > 60
            if not is_expanded:
                btn.click()
        self._search.setFocus()

        # Keyboard shortcuts removed    # ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._ensure_tables()
        self._load_cards()

    def _ensure_tables(self):
        for tname, ddl in [
            ("supplier_records",
             "CREATE TABLE supplier_records "
             "(id INT IDENTITY PRIMARY KEY, name NVARCHAR(300), sort_order INT)"),
            ("supplier_accounts",
             "CREATE TABLE supplier_accounts "
             "(id INT IDENTITY PRIMARY KEY, supplier_id INT, acc_index INT, "
             "acc_type NVARCHAR(100), naam NVARCHAR(300), thegana NVARCHAR(300), "
             "baik NVARCHAR(300), khata NVARCHAR(300), rakam NVARCHAR(100), "
             "jamma NVARCHAR(300), is_red INT DEFAULT 0)"),
        ]:
            self._db.ensure_table(self._db_name, tname, ddl)

    def _load_cards(self):
        # Capture currently selected supplier IDs to persist across reload
        selected_ids = {s.supplier_id for s in self._sections if s.is_selected()}

        for w in self._sections:
            try:
                w.setParent(None)
                w.deleteLater()
            except RuntimeError:
                pass
        self._sections.clear()
        self._last_clicked_idx = -1
        while self._c_lay.count() > 0:
            item = self._c_lay.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        suppliers = self._db.execute_query(
            self._db_name,
            "SELECT id, name FROM supplier_records ORDER BY sort_order, id"
        ) or []

        for sup_id, sup_name in suppliers:
            try:
                accs = self._db.execute_query(
                    self._db_name,
                    "SELECT acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red "
                    "FROM supplier_accounts WHERE supplier_id=? ORDER BY acc_index",
                    (sup_id,)
                )
            except Exception:
                accs = None
                
            if accs is None:
                accs = self._db.execute_query(
                    self._db_name,
                    "SELECT acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma "
                    "FROM supplier_accounts WHERE supplier_id=? ORDER BY acc_index",
                    (sup_id,)
                ) or []
                
            acc_list = []
            for r in accs:
                acc_list.append({
                    "acc_idx": r[0],
                    "type": r[1] or "Account",
                    "naam": r[2] or "", "thegana": r[3] or "",
                    "baik": r[4] or "", "khata": r[5] or "",
                    "rakam": r[6] or "", "jamma": r[7] or "",
                    "is_red": r[8] if len(r) > 8 else 0,
                })

            section = _SupplierSection(
                sup_id, sup_name or "", acc_list,
                self._db, self._db_name, self._can_edit,
                refresh_fn=self._load_cards,
                parent=self._container)
            
            # Restore selection state
            if sup_id in selected_ids:
                section.set_selected(True)
                
            section.click_callback = self._section_click
            # Wrap in HBox + stretch so section only takes its content width,
            # not the full scroll-area width (Qt stretches VBox children horizontally).
            row_wrap = QHBoxLayout()
            row_wrap.setContentsMargins(0, 0, 0, 0)
            row_wrap.setSpacing(0)
            row_wrap.addWidget(section)
            row_wrap.addStretch()
            self._c_lay.addLayout(row_wrap)
            self._sections.append(section)

        self._c_lay.addStretch()
        self._update_status()

    # ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    def _section_click(self, event, section: _SupplierSection):
        mods = event.modifiers()
        curr_idx = self._sections.index(section) if section in self._sections else -1

        if mods & Qt.KeyboardModifier.ControlModifier:
            section.set_selected(not section.is_selected())
            if section.is_selected():
                self._last_clicked_idx = curr_idx
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            lo = self._last_clicked_idx
            if lo >= 0 and curr_idx >= 0:
                a, b = sorted([lo, curr_idx])
                for i, s in enumerate(self._sections):
                    s.set_selected(a <= i <= b)
            else:
                self._select_only(section, curr_idx)
        else:
            if section.is_selected():
                # Click on already-selected card ΓåÆ deselect it
                section.set_selected(False)
                self._last_clicked_idx = -1
            else:
                self._select_only(section, curr_idx)

        self._update_status()
        # Also let the edit widget receive focus naturally
        section._name_edit.setFocus()

    def _select_only(self, section, idx=-1):
        for s in self._sections:
            s.set_selected(s is section)
        self._last_clicked_idx = idx

    def _deselect_all(self):
        for s in self._sections:
            s.set_selected(False)
        self._last_clicked_idx = -1
        self._update_status()

    def _filter_sections(self, text: str):
        """Show/hide supplier cards whose name matches the search query."""
        q = text.strip().lower()
        for s in self._sections:
            name = s._name_edit.toPlainText().lower()
            s.setVisible(not q or q in name)

    def _get_tables_for_excel(self):
        """Kept for compatibility — actual export uses _do_bank_excel_export."""
        return []

    def _do_export(self):
        """Override to use custom Bank A/c Excel writer."""
        any_selected = any(s.is_selected() for s in self._sections)

        visible_sections = []
        for sec in self._sections:
            if sec.isHidden():
                continue
            if any_selected and not sec.is_selected():
                continue
            cards = [c for c in sec._acc_cards if c.isVisible()]
            if not cards:
                continue
            company_cards  = [c for c in cards if c._is_company]
            personal_cards = [c for c in cards if not c._is_company]
            visible_sections.append((sec, company_cards, personal_cards))

        if not visible_sections:
            QMessageBox.information(self, "Nothing to Export", "No data found to export.")
            return

        settings = QSettings("TallySync", "SuppPayment")
        last_dir = settings.value("export_last_dir", "")
        default_name = "Supplier_Bank_Accounts.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel File",
            os.path.join(last_dir, default_name) if last_dir else default_name,
            "Excel Files (*.xlsx)"
        )
        if not path:
            return
        settings.setValue("export_last_dir", os.path.dirname(path))

        try:
            import xlsxwriter
        except ImportError:
            QMessageBox.critical(self, "Missing Library", "xlsxwriter is not installed.")
            return

        try:
            wb = xlsxwriter.Workbook(path)
            ws = wb.add_worksheet("Bank Accounts")

            # ── Formats ─────────────────────────────────────────────────────
            def _fmt(bold=False, bg=None, border_left=1, border_right=1,
                     border_top=1, border_bottom=1, align="left", wrap=False):
                props = {
                    "valign": "vcenter", "font_name": "Calibri", "font_size": 10,
                    "text_wrap": wrap, "align": align,
                    "left": border_left, "right": border_right,
                    "top": border_top,  "bottom": border_bottom,
                }
                if bold:  props["bold"] = True
                if bg:    props["bg_color"] = bg
                return wb.add_format(props)

            hdr_fmt   = _fmt(bold=True, bg="#dbeafe", align="center")
            no_border = _fmt(border_left=0, border_right=0, border_top=0, border_bottom=0)

            # S.N. and A/C of: NEVER have top/bottom borders — only left+right
            sn_fmt    = _fmt(border_top=0, border_bottom=0, align="center")
            name_fmt  = _fmt(border_top=0, border_bottom=0, wrap=True)

            # Data cells — 4 variants: first row, middle rows, last row, only row (first+last)
            # Label cell: left=1, right=0 (hidden internal border). Value cell: left=0, right=1
            def _data_fmts(is_first, is_last):
                t = 1 if is_first else 0
                b = 1 if is_last  else 0
                lbl = _fmt(bg="#f1f5f9", border_top=t, border_bottom=b, border_right=0)
                val = _fmt(border_top=t, border_bottom=b, border_left=0, wrap=True)
                return lbl, val

            # ── Column widths ────────────────────────────────────────────────
            ws.set_column(0, 0, 5)
            ws.set_column(1, 1, 16)
            ws.set_column(2, 2, 10)
            ws.set_column(3, 3, 28)
            ws.set_column(4, 4, 10)
            ws.set_column(5, 5, 28)
            ws.set_column(6, 6, 10)
            ws.set_column(7, 7, 28)

            # ── Header row ───────────────────────────────────────────────────
            ws.set_row(0, 20)
            ws.write(0, 0, "S.N.",   hdr_fmt)
            ws.write(0, 1, "A/C of", hdr_fmt)
            ws.merge_range(0, 2, 0, 3, "Company Account", hdr_fmt)
            ws.merge_range(0, 4, 0, 5, "Prasnal Account", hdr_fmt)
            ws.merge_range(0, 6, 0, 7, "Account 3",       hdr_fmt)

            # ── Data rows ────────────────────────────────────────────────────
            n_fields  = len(_REC_FIELDS)
            excel_row = 1
            for sn_idx, (sec, co_cards, pe_cards) in enumerate(visible_sections, start=1):
                supplier_name = sec._name_edit.toPlainText().strip() or "Unnamed Supplier"

                co0 = co_cards[0] if co_cards else None
                pe0 = pe_cards[0] if pe_cards else None
                ex0 = (co_cards[1] if len(co_cards) > 1 else
                       (pe_cards[1] if len(pe_cards) > 1 else None))

                co0_vals = {fk: ed.text().strip() for fk, ed in co0._field_edits} if co0 else {}
                pe0_vals = {fk: ed.text().strip() for fk, ed in pe0._field_edits} if pe0 else {}
                ex0_vals = {fk: ed.text().strip() for fk, ed in ex0._field_edits} if ex0 else {}

                for field_idx, (fkey, nepali_lbl, _english) in enumerate(_REC_FIELDS):
                    is_first = (field_idx == 0)
                    is_last  = (field_idx == n_fields - 1)
                    lbl_f, val_f = _data_fmts(is_first, is_last)

                    ws.set_row(excel_row, 18)
                    # S.N. and Name — no top/bottom borders, value only on first row
                    ws.write(excel_row, 0, sn_idx if is_first else "", sn_fmt)
                    ws.write(excel_row, 1, supplier_name if is_first else "", name_fmt)
                    # Data pairs — Nepali label | value, hidden internal border
                    ws.write(excel_row, 2, nepali_lbl, lbl_f)
                    ws.write(excel_row, 3, co0_vals.get(fkey, "") if co0 else "", val_f)
                    ws.write(excel_row, 4, nepali_lbl, lbl_f)
                    ws.write(excel_row, 5, pe0_vals.get(fkey, "") if pe0 else "", val_f)
                    ws.write(excel_row, 6, nepali_lbl, lbl_f)
                    ws.write(excel_row, 7, ex0_vals.get(fkey, "") if ex0 else "", val_f)
                    excel_row += 1

                # Spacer row between suppliers — completely borderless
                ws.set_row(excel_row, 6)
                for c in range(8):
                    ws.write(excel_row, c, "", no_border)
                excel_row += 1

            wb.close()
            QMessageBox.information(self, "Export Complete", f"File saved to:\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export Excel:\n{e}")




    def _get_tables_for_print(self):

        """Builds export tables in the format for Print:
            Sn | Name | Company Account | Personal Account
            1  | John | Name: John Co   | Name: John
               |      | Addr: KTM       | Addr: BKT
               |      | Bank: Nabil     | Bank: NIC
               ...
        """
        any_selected = any(s.is_selected() for s in self._sections)
        
        # 1. Gather data and count rows
        total_rows = 0
        visible_sections = []
        for sec in self._sections:
            if sec.isHidden():
                continue
            if any_selected and not sec.is_selected():
                continue

            cards = [c for c in sec._acc_cards if c.isVisible()]
            if not cards:
                continue

            company_cards  = [c for c in cards if c._is_company]
            personal_cards = [c for c in cards if not c._is_company]
            max_pairs = max(len(company_cards), len(personal_cards), 1)
            
            # 6 fields per pair. Plus 1 spacer row if multiple pairs
            rows_for_sec = max_pairs * len(_REC_FIELDS)
            if max_pairs > 1:
                rows_for_sec += (max_pairs - 1)
                
            total_rows += rows_for_sec + 1 # +1 for spacer row between suppliers
            visible_sections.append((sec, company_cards, personal_cards, max_pairs))

        if total_rows == 0:
            return []

        # 2. Build the single combined table
        tbl = QTableWidget(total_rows, 4)
        tbl.setHorizontalHeaderLabels(["Sn", "Name", "Company Account", "Personal Account"])
        
        def _set(r, c, text):
            tbl.setItem(r, c, QTableWidgetItem(str(text) if text else ""))

        no_h_borders = set()
        
        row = 0
        sn = 1
        for sec, co_cards, pe_cards, max_pairs in visible_sections:
            supplier_name = sec._name_edit.toPlainText().strip() or "Unnamed Supplier"
            
            for pair_idx in range(max_pairs):
                co = co_cards[pair_idx] if pair_idx < len(co_cards) else None
                pe = pe_cards[pair_idx] if pair_idx < len(pe_cards) else None

                co_vals = {fk: ed.text().strip() for fk, ed in co._field_edits} if co else {}
                pe_vals = {fk: ed.text().strip() for fk, ed in pe._field_edits} if pe else {}

                for field_idx, (fkey, _ftype, flabel) in enumerate(_REC_FIELDS):
                    if pair_idx == 0 and field_idx == 0:
                        _set(row, 0, str(sn))
                        _set(row, 1, supplier_name)
                    else:
                        _set(row, 0, "")
                        _set(row, 1, "")
                        
                    co_text = f"{_ftype}: {co_vals.get(fkey, '')}" if co else ""
                    pe_text = f"{_ftype}: {pe_vals.get(fkey, '')}" if pe else ""
                    
                    _set(row, 2, co_text)
                    _set(row, 3, pe_text)
                    is_first_row = (pair_idx == 0 and field_idx == 0)
                    is_last_row  = (pair_idx == max_pairs - 1 and field_idx == len(_REC_FIELDS) - 1)
                    
                    if not (is_first_row or is_last_row):
                        no_h_borders.add((row, 2))
                        no_h_borders.add((row, 3))
                    row += 1

                if pair_idx < max_pairs - 1:
                    _set(row, 0, "")
                    _set(row, 1, "")
                    _set(row, 2, "-------------------")
                    _set(row, 3, "-------------------")
                    row += 1
            sn += 1
            
            # Spacer row between suppliers
            _set(row, 0, "")
            _set(row, 1, "")
            _set(row, 2, "")
            _set(row, 3, "")
            row += 1

        self.no_border_cols = [0, 1]
        return [{"title": "Bank Accounts", "table": tbl, "no_h_borders": no_h_borders}]


    def _update_status(self):
        n_sup = sum(1 for s in self._sections if s.is_selected())
        n_acc = sum(len(s.selected_cards()) for s in self._sections)
        total = n_sup if n_sup else n_acc
        
        is_expanded = self.btn_copy_records.parentWidget().width() > 60
        base = " Copy" if is_expanded else ""
        from src.ui.supp_payment.shared import _BTN_PRIMARY
        if total == 0:
            self.btn_copy_records.setText(base)
            self.btn_copy_records.setStyleSheet(_BTN_PRIMARY)
        else:
            self.btn_copy_records.setText(f"{base} ({total})")
            # Fake 'active' style since we don't have _BTN_PRIMARY_ACTIVE in shared.py
            self.btn_copy_records.setStyleSheet(_BTN_PRIMARY.replace("#059669", "#047857"))

        if total == 0:
            self._sel_status.setText("")
            self._sel_status.setStyleSheet("")
        else:
            if is_expanded:
                label = (f"{n_sup} supplier{'s' if n_sup>1 else ''}"
                         if n_sup else f"{n_acc} account card{'s' if n_acc>1 else ''}")
                self._sel_status.setText(f"✓ {label}")
                self._sel_status.setStyleSheet(
                    "color:#d1fae5;padding:4px;"
                    "border-radius:2px;font-weight:bold;font-size:8pt;"
                    "border:1px solid #1e7a4b;background:#0d3526;")
            else:
                self._sel_status.setText(f"✓\n{total}")
                self._sel_status.setStyleSheet(
                    "color:#d1fae5;padding:4px;"
                    "border-radius:2px;font-weight:bold;font-size:8pt;"
                    "border:1px solid #1e7a4b;background:#0d3526;")

    def _copy_selected_text(self):
        tables = self._get_tables_for_export()
        if not tables:
            QMessageBox.information(self, "No Selection", "No visible or selected records to copy.")
            return
            
        tsv_lines = []
        for table_info in tables:
            title = table_info.get("title", "")
            tbl = table_info.get("table")
            tsv_lines.append(f"{title}")
            for r in range(tbl.rowCount()):
                row_data = []
                for c in range(tbl.columnCount()):
                    it = tbl.item(r, c)
                    row_data.append(it.text().strip() if it else "")
                tsv_lines.append("\t".join(row_data))
            tsv_lines.append("") # spacer
            
        QApplication.clipboard().setText("\n".join(tsv_lines))
        
        # Flash status
        old_style = self._sel_status.styleSheet()
        old_text = self._sel_status.text()
        self._sel_status.setText("  Copied to Clipboard!")
        self._sel_status.setStyleSheet("color:#10b981;padding:2px 8px;border-radius:2px;font-weight:bold;border:1px solid #059669;background:#064e3b;")
        QTimer.singleShot(2000, lambda: (self._sel_status.setText(old_text), self._sel_status.setStyleSheet(old_style)))
        
    def _copy_selected_as_image(self):
        selected = [s for s in self._sections if s.is_selected()]
        if not selected:
            QMessageBox.information(self, "No Selection",
                                    "Click a supplier header to select it.\n"
                                    "Ctrl+Click = multi ┬╖ Shift+Click = range.")
            return

        # High-DPI Off-screen Rendering (3x Scale)
        scale = 3
        margin = 8
        scaled_margin = margin * scale
        bg = QColor(_C_PAGE_BG)
        images = []
        for sec in selected:
            ow, oh = sec.width(), sec.height()
            # Add a small height buffer to absorb the 1pxΓåÆ2px border inflation
            # that happens when a section is selected (selected border = 2px vs 1px).
            # Without this, the bottom gets clipped by exactly that difference.
            h_buffer = 4

            # Render at 3x without touching the live widget at all
            img = QImage(ow * scale, (oh + h_buffer) * scale, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(bg)

            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.scale(scale, scale)
            sec.render(painter)
            painter.end()
            images.append(img)


        max_w = max(img.width() for img in images)
        gap = 2 * scale          # 2px gap between cards (was full margin = 8px each side)
        total_h = scaled_margin + sum(img.height() for img in images) + gap * max(len(images) - 1, 0) + scaled_margin
        
        # Stitch all scaled sections onto a final massive canvas
        result = QImage(max_w + scaled_margin * 2, total_h, QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(bg)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        y = scaled_margin
        for img in images:
            painter.drawImage(scaled_margin, y, img)
            y += img.height() + gap
        painter.end()

        # Place the pristine high-resolution image directly on the clipboard
        QApplication.clipboard().setImage(result)
        self.btn_copy_records.setText("\u2713 Copied!")
        QTimer.singleShot(2000, lambda: self.btn_copy_records.setText(" Copy"))

    # ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    def _add_supplier(self):
        if not self._can_edit or not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO supplier_records(name, sort_order) VALUES(?,?)",
                ("New Supplier", 9999))
            cur.execute("SELECT @@IDENTITY")
            new_id = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO supplier_accounts(supplier_id, acc_index, acc_type) VALUES(?,?,?)",
                (new_id, 0, "Company Account"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[RecordTab] _add_supplier error:", e)
            return
        self._load_cards()
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum())

    def _add_company_acct(self):
        self._add_account_to_selected("Company Account")

    def _add_personal_acct(self):
        self._add_account_to_selected("Personal Account")

    def _add_account_to_selected(self, acc_type: str):
        if not self._can_edit or not self._db_name:
            return
        selected = [s for s in self._sections if s.is_selected()]
        if not selected:
            QMessageBox.information(self, "Select Supplier",
                                    "Please select a supplier first.")
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            for sec in selected:
                res = self._db.execute_query(
                    self._db_name,
                    "SELECT ISNULL(MAX(acc_index), -1) FROM supplier_accounts WHERE supplier_id=?",
                    (sec.supplier_id,))
                next_idx = (res[0][0] if res else -1) + 1
                cur.execute(
                    "INSERT INTO supplier_accounts(supplier_id, acc_index, acc_type)"
                    " VALUES(?,?,?)",
                    (sec.supplier_id, next_idx, acc_type))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[RecordTab] _add_account error:", e)
            return
        self._load_cards()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._btn_add.setEnabled(can_edit)
        self._btn_add_co.setEnabled(can_edit)
        self._btn_add_pe.setEnabled(can_edit)
        for s in self._sections:
            s.set_edit_mode(can_edit)


