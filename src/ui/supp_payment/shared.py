# -*- coding: utf-8 -*-
# =============================================================================
# supp_payment_shared.py — Shared constants, helpers, delegate, and _DbTable
# Imported by all supp_payment_* sub-modules.
# =============================================================================
# =============================================================================
# supp_payment.py  ΓÇô  Supplier Payment Module (Redesigned)
# =============================================================================
import os
import weakref
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter,
    QFormLayout, QApplication, QAbstractScrollArea, QFileDialog, QColorDialog, QTextEdit
)
from PyQt6.QtCore import (
    Qt, QTimer, QDate, QEvent, QMimeData, QSettings,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPixmap, QPainter, QKeySequence, QShortcut, QCursor, QImage, QIcon,
)
from src.logic.db_manager import get_db_manager, build_logical_name

from src.ui.table_exporter import export_tables_to_excel
from src.ui.table_printer import print_tables_via_preview


def get_icon(name):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return QIcon(os.path.join(base, "icons", name))

class _PrintExportMixin:
    _right_bar_expanded = False
    # Stores (weakref_to_widget, apply_state_fn) pairs.
    # Dead refs (widget destroyed) are pruned before each dispatch.
    _right_bar_callbacks = []

    @staticmethod
    def _prune_callbacks():
        """Remove entries whose widget has been garbage-collected."""
        _PrintExportMixin._right_bar_callbacks = [
            (wr, cb) for wr, cb in _PrintExportMixin._right_bar_callbacks
            if wr() is not None
        ]

    def _init_print_export(self, layout, title, supports_print=True, table_getter=None, print_table_getter=None, right_bar=None, on_toggle_cb=None):
        self._export_title = title
        self._table_getter = table_getter if table_getter else lambda: [{"title": title, "table": self.table}]
        self._print_table_getter = print_table_getter if print_table_getter else self._table_getter
        self._export_grid_cols = 1
        self._export_title_on_left = False

        self.btn_export = QPushButton()
        self.btn_export.setIcon(get_icon("excel.svg"))
        self.btn_export.setStyleSheet(_BTN_PRIMARY)
        self.btn_export.clicked.connect(self._do_export)

        if supports_print:
            self.btn_print = QPushButton()
            self.btn_print.setIcon(get_icon("print.svg"))
            self.btn_print.setStyleSheet(_BTN_PRIMARY)
            self.btn_print.clicked.connect(self._do_print)

        if right_bar:
            self.btn_toggle = QPushButton()
            self.btn_toggle.setIcon(get_icon("chevron-left.svg"))
            from PyQt6.QtCore import QSize
            self.btn_toggle.setIconSize(QSize(20, 20))
            self.btn_toggle.setStyleSheet("""
                QPushButton {
                    background: #ffffff; 
                    border: 1px solid #e2e8f0; 
                    border-radius: 16px; 
                }
                QPushButton:hover {
                    background: #f8fafc; 
                    border: 1px solid #cbd5e1;
                }
                QPushButton:pressed {
                    background: #f1f5f9;
                }
                QToolTip {
                    background-color: #1e293b; color: #ffffff; border: none;
                    padding: 5px 9px; border-radius: 4px; font-size: 11px;
                }
            """)
            self.btn_toggle.setFixedSize(32, 32)
            self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.insertWidget(0, self.btn_toggle, 0, Qt.AlignmentFlag.AlignHCenter)
            
            def apply_state(expanded):
                # Guard: widget may have been deleted between callback registration and dispatch
                try:
                    if not right_bar or not self.btn_toggle:
                        return
                except RuntimeError:
                    return
                if expanded:
                    right_bar.setFixedWidth(140)
                    self.btn_toggle.setIcon(get_icon("chevron-right.svg"))
                    self.btn_export.setText(" Excel")
                    self.btn_export.setIcon(get_icon("excel.svg"))
                    if supports_print: 
                        self.btn_print.setText(" Print")
                        self.btn_print.setIcon(get_icon("print.svg"))
                else:
                    right_bar.setFixedWidth(52)
                    self.btn_toggle.setIcon(get_icon("chevron-left.svg"))
                    self.btn_export.setText("")
                    self.btn_export.setIcon(get_icon("excel.svg"))
                    if supports_print: 
                        self.btn_print.setText("")
                        self.btn_print.setIcon(get_icon("print.svg"))
                if on_toggle_cb: on_toggle_cb(expanded)

            def on_toggle():
                is_expanded = right_bar.width() > 60
                new_state = not is_expanded
                _PrintExportMixin._right_bar_expanded = new_state
                # Prune dead widget refs before dispatching
                _PrintExportMixin._prune_callbacks()
                for _wr, cb in _PrintExportMixin._right_bar_callbacks:
                    try:
                        cb(new_state)
                    except RuntimeError:
                        pass  # C++ object already deleted — will be pruned next cycle
                    except Exception:
                        pass
                
            self.btn_toggle.clicked.connect(on_toggle)

            # Keyboard shortcut — Ctrl+R toggles the right panel from anywhere in this tab
            from PyQt6.QtGui import QShortcut, QKeySequence
            _shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
            _shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            _shortcut.activated.connect(on_toggle)
            
            # Register with a weak-ref to self so dead tabs are auto-pruned
            _PrintExportMixin._right_bar_callbacks.append((weakref.ref(self), apply_state))

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: apply_state(_PrintExportMixin._right_bar_expanded))

        layout.addWidget(self.btn_export)
        if supports_print:
            layout.addWidget(self.btn_print)

    def _do_export(self):
        tables = self._table_getter()
        if not tables:
            QMessageBox.information(self, "Nothing to Export", "No data found to export.")
            return

        default_name = f"{self._export_title.replace(' ', '_')}.xlsx"
        # Retrieve last-used directory from QSettings for convenience
        settings = QSettings("TallySync", "SuppPayment")
        last_dir = settings.value("export_last_dir", "")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel File",
            os.path.join(last_dir, default_name) if last_dir else default_name,
            "Excel Files (*.xlsx)"
        )
        if not path:
            return  # user cancelled

        # Remember directory for next time
        settings.setValue("export_last_dir", os.path.dirname(path))

        success = export_tables_to_excel(
            os.path.dirname(path), os.path.basename(path), tables, self,
            grid_cols=self._export_grid_cols, title_on_left=self._export_title_on_left
        )
        if success:
            QMessageBox.information(
                self, "Export Complete",
                f"File saved to:\n{path}"
            )

    def _do_print(self):
        tables = self._print_table_getter()
        nbc = getattr(self, "no_border_cols", [])
        print_tables_via_preview(tables, self, self._export_title, no_border_cols=nbc)

from src.ui.table_nav_mixin import (
    UniversalCellDelegate, 
    CELL_TYPE_ROLE, 
    AUTOCOMPLETE_ITEMS_ROLE,
    UNIVERSAL_TABLE_STYLE
)

from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFontMetrics, QFont
from PyQt6.QtCore import Qt, QRect

# ---------------------------------------------------------------------------
# Safe arithmetic expression evaluator (used by ModernTableDelegate)
# ---------------------------------------------------------------------------
import ast as _ast
import operator as _operator

_ARITH_OPS = {
    _ast.Add:  _operator.add,
    _ast.Sub:  _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div:  _operator.truediv,
}
_UNARY_OPS = {
    _ast.USub: _operator.neg,
    _ast.UAdd: _operator.pos,
}

def _split_top_level(s: str, sep: str = ',') -> list:
    """Split *s* at top-level *sep* characters (ignoring those inside parens/brackets)."""
    parts, depth, current = [], 0, []
    for ch in s:
        if ch in '([':
            depth += 1; current.append(ch)
        elif ch in ')]':
            depth -= 1; current.append(ch)
        elif ch == sep and depth == 0:
            parts.append(''.join(current)); current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


def _find_cmp_op_at_depth0(s: str):
    """Return (op_str, start, end) of the first comparison operator at depth 0, or None."""
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in '([':   depth += 1
        elif ch in ')]': depth -= 1
        elif depth == 0:
            two = s[i:i+2]
            if two in ('<=', '>=', '<>', '!='):
                return two, i, i + 2
            if ch in '<>=':
                return ch, i, i + 1
        i += 1
    return None


def _eval_if_formula(formula_str: str, row: int, table) -> float | None:
    """Evaluate  =IF(condition, true_val, false_val)  formulas.

    Supported condition forms
    ─────────────────────────
    • Simple numeric comparison   →  0<1  |  5>=3  |  2=2
    • Arithmetic comparison       →  10+5>12  |  (A+B)/2>0
    • Date-distance pattern       →  MAX(ColName-TODAY(),0)<30
      where ColName must match a column header in *table* (case-insensitive).

    true_val and false_val may be any arithmetic expression understood by
    _safe_eval_expr (numbers, +, -, *, /, parentheses).

    Returns
    ───────
    float   – the evaluated result (true_val or false_val).
    None    – the formula is syntactically malformed (caller shows raw text).
    """
    s = formula_str.strip()
    if not s.upper().startswith('=IF('):
        return None
    if not s.endswith(')'):
        return None

    inner = s[4:-1]                          # strip  =IF(  and  )
    parts = _split_top_level(inner)
    if len(parts) != 3:
        return None

    cond_str  = parts[0].strip()
    true_str  = parts[1].strip()
    false_str = parts[2].strip()

    true_val  = _safe_eval_expr(true_str)
    false_val = _safe_eval_expr(false_str)
    if true_val is None or false_val is None:
        return None

    # ── Condition branch 1: MAX(ColName-TODAY(),0) OP N ──────────────────
    _date_m = _re.match(
        r'^MAX\(\s*([\w\s]+?)\s*-\s*TODAY\(\)\s*,\s*0\s*\)'
        r'\s*([<>]=?|<>|!=|=)\s*(-?\d+(?:\.\d+)?)\s*$',
        cond_str, _re.IGNORECASE
    )
    if _date_m:
        col_ref, op, thr_s = _date_m.groups()
        col_ref   = col_ref.strip()
        threshold = float(thr_s)

        ref_col = next(
            (c for c in range(table.columnCount())
             if (h := table.horizontalHeaderItem(c)) and
                h.text().strip().lower() == col_ref.lower()),
            -1
        )
        if ref_col >= 0:
            date_item = table.item(row, ref_col)
            if date_item and date_item.text().strip():
                from PyQt6.QtCore import QDate
                d = QDate.fromString(date_item.text().strip(), "yyyy-MM-dd")
                if d.isValid():
                    days = max(QDate.currentDate().daysTo(d), 0)
                    _cmp = {'<': days < threshold, '>': days > threshold,
                            '<=': days <= threshold, '>=': days >= threshold,
                            '=': days == threshold, '<>': days != threshold,
                            '!=': days != threshold}
                    return true_val if _cmp.get(op, False) else false_val
        # Column not found or date invalid → use false_val as safe fallback
        return false_val

    # ── Condition branch 2: general arithmetic comparison ─────────────────
    found = _find_cmp_op_at_depth0(cond_str)
    if found:
        op, start, end = found
        left  = _safe_eval_expr(cond_str[:start].strip())
        right = _safe_eval_expr(cond_str[end:].strip())
        if left is not None and right is not None:
            _cmp = {'<': left < right, '>': left > right,
                    '<=': left <= right, '>=': left >= right,
                    '=': left == right, '<>': left != right,
                    '!=': left != right}
            return true_val if _cmp.get(op, False) else false_val

    return None   # truly malformed — caller will show the raw formula text


def _safe_eval_expr(expr: str):
    """Safely evaluate a pure arithmetic expression string.

    Supported: numeric literals (int/float), +  -  *  /  ( )  and unary -.
    Anything else (function calls, names, strings, …) raises ValueError,
    which is caught here and causes None to be returned.

    Returns:
        float  — result of the expression, or
        None   — if the expression is invalid / contains non-arithmetic nodes.
    """
    try:
        tree = _ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return None

    def _eval(node):
        if isinstance(node, _ast.Expression):
            return _eval(node.body)
        elif isinstance(node, _ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError("non-numeric constant")
            return float(node.value)
        elif isinstance(node, _ast.BinOp):
            op_fn = _ARITH_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"unsupported operator: {type(node.op)}")
            left  = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, _ast.Div) and right == 0:
                raise ZeroDivisionError("division by zero")
            return op_fn(left, right)
        elif isinstance(node, _ast.UnaryOp):
            op_fn = _UNARY_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"unsupported unary op: {type(node.op)}")
            return op_fn(_eval(node.operand))
        elif isinstance(node, _ast.Call):
            # Allow MAX(a,b,...) and MIN(a,b,...) only
            func_name = ""
            if isinstance(node.func, _ast.Name):
                func_name = node.func.id.upper()
            if func_name == "MAX":
                return max(_eval(a) for a in node.args)
            elif func_name == "MIN":
                return min(_eval(a) for a in node.args)
            else:
                raise ValueError(f"disallowed function: {func_name}")
        else:
            raise ValueError(f"disallowed node: {type(node)}")

    try:
        return _eval(tree)
    except (ValueError, ZeroDivisionError, TypeError, RecursionError):
        return None


# ---------------------------------------------------------------------------
# Formula role & =IF() evaluator (used by ModernTableDelegate + _SectionCardV2)
# ---------------------------------------------------------------------------

# Custom item-data role used to persist the raw formula text on the
# QTableWidgetItem while the cell displays its evaluated result.
FORMULA_ROLE = Qt.ItemDataRole.UserRole + 50

import re as _re


class ModernTableDelegate(UniversalCellDelegate):
    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.status_colors = {
            "completed": ("#dcfce7", "#166534"),
            "paid": ("#dcfce7", "#166534"),
            "pending": ("#fef9c3", "#854d0e"),
            "processing": ("#dbeafe", "#1e40af"),
            "active": ("#dcfce7", "#166534"),
            "overdue": ("#fee2e2", "#991b1b"),
            "approved": ("#e0e7ff", "#3730a3"),
            "sent": ("#f3e8ff", "#6b21a8"),
            "draft": ("#f1f5f9", "#475569"),
            "clear": ("#f1f5f9", "#475569"),
        }
        
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        model = index.model()
        header = ""
        if hasattr(model, "headerData"):
            val = model.headerData(index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            if val is not None: header = str(val).lower()
            
        if "amount" in header or "balance" in header or "rs" in header or "dr" in header or "cr" in header or "value" in header or "cash" in header or "bank" in header:
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                from PyQt6.QtGui import QFont, QFontMetrics
                font = QFont("Consolas", 10)
                fm = QFontMetrics(font)
                # + 24 for padding to match paint margins
                w = fm.horizontalAdvance(str(text)) + 24
                if w > size.width():
                    size.setWidth(w)
        return size

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        self.initStyleOption(option, index)
        text = option.text
        if text is None: text = ""
        text = str(text).strip()
        
        # Background highlighting
        # NOTE: we do NOT fill on selection — instead we draw a green border
        # at the end of this method (matching UniversalCellDelegate behaviour).
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        bg_brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg_brush:
            # Safely extract color from brush to avoid PyQt overload resolution issues
            if isinstance(bg_brush, QBrush):
                painter.fillRect(option.rect, bg_brush.color())
            elif isinstance(bg_brush, QColor):
                painter.fillRect(option.rect, bg_brush)
            else:
                painter.fillRect(option.rect, QBrush(bg_brush).color())
            
        model = index.model()
        header = ""
        if hasattr(model, "headerData"):
            val = model.headerData(index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            if val is not None: header = str(val).lower()
        

        
        rect = option.rect
        rect.adjust(8, 4, -8, -4)
        
        fg_brush = index.data(Qt.ItemDataRole.ForegroundRole)
        custom_fg = None
        if fg_brush:
            if isinstance(fg_brush, QBrush): custom_fg = fg_brush.color()
            elif isinstance(fg_brush, QColor): custom_fg = fg_brush
        
        if "status" in header and text:
            status_key = text.lower()
            bg_c, text_c = self.status_colors.get(status_key, ("#f1f5f9", "#475569"))
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            pill_rect = QRect(0, 0, text_width + 16, fm.height() + 8)
            pill_rect.moveCenter(option.rect.center())
            
            painter.setBrush(QBrush(QColor(bg_c)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill_rect, 6, 6)
            
            painter.setPen(custom_fg if custom_fg else QColor(text_c))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)
            
        elif "amount" in header or "balance" in header or "rs" in header or "dr" in header or "cr" in header or "value" in header or "cash" in header or "bank" in header:
            painter.setPen(custom_fg if custom_fg else QColor("#1e293b"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            
        elif "party" in header or "name" in header or "particular" in header or "remarks" in header or "account" in header or "type" in header:
            painter.setPen(custom_fg if custom_fg else QColor("#1e293b")) # Standard dark text
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            
        else:
            painter.setPen(custom_fg if custom_fg else QColor("#334155"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            
        painter.restore()

    def setEditorData(self, editor, index):
        """If the cell holds a formula, show the raw formula in the editor
        (not the evaluated result) so the user can inspect / modify it.
        Falls back to the base-class behaviour for plain cells."""
        from PyQt6.QtWidgets import QLineEdit
        if isinstance(editor, QLineEdit):
            formula = index.data(FORMULA_ROLE)
            if formula:
                editor.setText(str(formula))
                return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        """Intercept commit to evaluate formulas and arithmetic before saving.

        Priority:
          1. =IF(MAX(ColName-TODAY(),0) OP N, V, F) — date-conditional formula.
             Stores the raw formula text in FORMULA_ROLE so it can be restored
             in the editor on next click.  The *evaluated* number is written as
             the display value and is what downstream calculations see.
          2. Plain arithmetic  (+  -  *  /)  — evaluated immediately via
             _safe_eval_expr; no formula is stored.
          3. Everything else — passed through unchanged.

        date / autocomplete cell-types are fully delegated to the base class.
        """
        from src.ui.table_nav_mixin import CELL_TYPE_ROLE
        cell_type = index.data(CELL_TYPE_ROLE) or self._cell_type

        if cell_type in ("date", "autocomplete"):
            super().setModelData(editor, model, index)
            return

        from PyQt6.QtWidgets import QLineEdit
        from PyQt6.QtCore import Qt as _Qt
        if not isinstance(editor, QLineEdit):
            super().setModelData(editor, model, index)
            return

        text = editor.text().strip()

        # --- Priority 1: =IF() formula ---
        if text.upper().startswith('=IF('):
            owner_table = getattr(self._owner, 'table', None)
            result = _eval_if_formula(text, index.row(), owner_table) if owner_table else None

            # Store formula on the item so (a) editor restores it and (b) _save_data persists it
            view = owner_table
            if view:
                it = view.item(index.row(), index.column())
                if not it:
                    from PyQt6.QtWidgets import QTableWidgetItem
                    it = QTableWidgetItem()
                    view.setItem(index.row(), index.column(), it)
                it.setData(FORMULA_ROLE, text)

            # Write the evaluated number as the visible cell value
            if result is not None:
                formatted = str(int(result)) if isinstance(result, float) and result.is_integer() else f"{result:.6g}"
            else:
                # Formula is malformed or references a missing column — keep
                # the raw formula text visible so the user can see and fix it.
                formatted = text
            model.setData(index, formatted, _Qt.ItemDataRole.EditRole)
            return

        # --- Priority 2: plain arithmetic ---
        import re as _re
        _HAS_ARITH = bool(_re.search(r'\d[+\-*/]|[+\-*/]\d|[+\-*/]\s*\(', text))
        if _HAS_ARITH:
            result = _safe_eval_expr(text)
            if result is not None:
                if isinstance(result, float) and result.is_integer():
                    formatted = str(int(result))
                else:
                    formatted = f"{result:.6g}"
                model.setData(index, formatted, _Qt.ItemDataRole.EditRole)
                return

        # --- Priority 3: plain text ---
        super().setModelData(editor, model, index)

# ---------------------------------------------------------------------------
# Shared font helpers
# ---------------------------------------------------------------------------
def _bold_font(size=10):
    f = QFont()
    f.setFamilies(["Segoe UI", "Noto Sans Devanagari", "Mangal", "Arial Unicode MS"])
    f.setPointSize(size)
    f.setWeight(QFont.Weight.Bold)
    return f

def _norm_font(size=10):
    f = QFont()
    f.setFamilies(["Segoe UI", "Noto Sans Devanagari", "Mangal", "Arial Unicode MS"])
    f.setPointSize(size)
    return f

# ---------------------------------------------------------------------------
# Common stylesheet constants
# ---------------------------------------------------------------------------
_SCROLLBAR_STYLE = """
QScrollBar:vertical {
    border: none; background: transparent; width: 6px; margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.2); min-height: 20px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: rgba(0, 0, 0, 0.4); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    border: none; background: transparent; height: 6px; margin: 0px 0px 0px 0px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 0, 0, 0.2); min-width: 20px; border-radius: 3px;
}
QScrollBar::handle:horizontal:hover { background: rgba(0, 0, 0, 0.4); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
"""

_TABLE_STYLE = UNIVERSAL_TABLE_STYLE + """
QTableWidget {
    background: #ffffff;
    border: none;
    gridline-color: #64748b;
    color: #1e293b;
    font-size: 10pt;
    selection-background-color: transparent;
    selection-color: #1e293b;
    outline: none;
}
QTableWidget::item {
    padding: 6px;
}
QTableWidget::item:selected {
    background-color: transparent;
    color: #1e293b;
    border: 2px solid #059669;
}
QHeaderView::section:horizontal {
    background: #f1f5f9;
    color: #475569;
    padding: 2px 6px;
    min-height: 22px;
    max-height: 26px;
    border: none;
    border-bottom: 1px solid #64748b;
    border-right: 1px solid #64748b;
    font-weight: 700;
    font-size: 9pt;
    text-transform: uppercase;
}
QHeaderView::section:horizontal:last {
    border-right: none;
}
"""


_SECTION_HEADER_STYLE = (
    "background: #ffffff; color: {color}; padding: 14px 16px; "
    "border-radius: 12px 12px 0 0; font-weight: 800; font-size: 11pt; "
    "border-bottom: 1px solid #e2e8f0;"
)

_BTN_PRIMARY = """
QPushButton {
    background: #059669; color: white; border: none;
    border-radius: 5px; padding: 5px 14px; font-weight: bold; font-size: 10pt;
}
QPushButton:hover { background: #047857; }
QPushButton:disabled { background: #94a3b8; }
QToolTip { background-color: #1e293b; color: #ffffff; border: none; padding: 5px 9px; border-radius: 4px; font-size: 11px; }
"""

_BTN_SECONDARY = """
QPushButton {
    background: #f1f5f9; color: #374151; border: 1px solid #cbd5e1;
    border-radius: 5px; padding: 5px 14px; font-size: 10pt;
}
QPushButton:hover { background: #e2e8f0; }
"""

_BTN_DANGER = """
QPushButton {
    background: #ef4444; color: white; border: none;
    border-radius: 5px; padding: 5px 14px; font-weight: bold; font-size: 10pt;
}
QPushButton:hover { background: #dc2626; }
"""

_MENU_STYLE = """
    QMenu {
        background: #ffffff; color: #1e293b;
        border: 1px solid #e2e8f0;
        padding: 4px 0;
    }
    QMenu::item { padding: 7px 20px; font-size: 10pt; }
    QMenu::item:selected { background: #f1f5f9; color: #1e293b; }
    QMenu::item:disabled { color: #94a3b8; }
    QMenu::separator { height: 1px; background: #e2e8f0; margin: 3px 8px; }
"""

_POPUP_STYLE = """
    QDialog, QMessageBox, QInputDialog, QColorDialog {
        background: #ffffff; color: #0f172a;
    }
    QLabel { color: #0f172a; font-size: 10pt; }
    QLineEdit {
        background: #ffffff; color: #0f172a;
        border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 8px;
    }
    QPushButton {
        background: #f1f5f9; color: #374151; border: 1px solid #cbd5e1;
        border-radius: 4px; padding: 5px 15px; font-weight: bold;
    }
    QPushButton:hover { background: #e2e8f0; }
"""


def _styled_get_text(parent, title: str, label: str, text: str = ""):
    """Replacement for QInputDialog.getText() that guarantees white/light styling.

    Static methods like QInputDialog.getText() can fail to inherit the global
    app stylesheet when the parent widget has its own local setStyleSheet().
    This helper instantiates the dialog explicitly and applies _POPUP_STYLE
    directly, which always wins regardless of the parent's local styles.

    Returns (text_value, ok) — identical signature to QInputDialog.getText().
    """
    from PyQt6.QtWidgets import QInputDialog
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(text)
    dlg.setStyleSheet(_POPUP_STYLE)
    ok = dlg.exec()
    return dlg.textValue(), bool(ok)


def _styled_question(parent, title: str, text: str, buttons):
    """Replacement for QMessageBox.question() with guaranteed white styling."""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setStandardButtons(buttons)
    msg.setStyleSheet(_POPUP_STYLE)
    return msg.exec()


def _styled_warning(parent, title: str, text: str):
    """Replacement for QMessageBox.warning() with guaranteed white styling."""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.setStyleSheet(_POPUP_STYLE)
    msg.exec()


def _styled_info(parent, title: str, text: str):
    """Replacement for QMessageBox.information() with guaranteed white styling."""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.setStyleSheet(_POPUP_STYLE)
    msg.exec()

def _styled_get_color(parent):
    """Replacement for QColorDialog.getColor() with guaranteed white styling."""
    from PyQt6.QtWidgets import QColorDialog
    from PyQt6.QtGui import QColor
    dlg = QColorDialog(parent)
    dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
    dlg.setStyleSheet(_POPUP_STYLE)
    if dlg.exec():
        return dlg.currentColor()
    return QColor()


# Context menu style for card-level right-click menus (red-toned selection).
_CARD_MENU_STYLE = """
    QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
    QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
    QMenu::item:selected{background:#fee2e2;color:#b91c1c;border-radius:2px;}
"""

# ===========================================================================
# Simple DB-backed QTableWidget
# ===========================================================================


def _setup_smart_header(table):
    hdr = table.horizontalHeader()
    hdr.setHighlightSections(False)
    hdr.setMinimumSectionSize(20)
    
    # Force the header height to be strictly 24px to eliminate top/bottom whitespace
    hdr.setFixedHeight(24)
    
    # Stretch the last section so the table fills the full width, aligning the right borders
    hdr.setStretchLastSection(True)
    
    # Must use string-based signals to avoid garbage collection of local closures
    hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    
    # Attach a state object to the table to store our lambda/slot
    if not hasattr(table, '_smart_hdr_menu'):
        def _show_menu(pos):
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(table)
            menu.setStyleSheet("""
                QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
                QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
                QMenu::item:selected{background:#e2e8f0;color:#0f172a;border-radius:2px;}
            """)
            act_fit = menu.addAction("Fit Column to Content")
            act_fit_all = menu.addAction("Fit All Columns to Content")
            
            # Show current stretch state
            is_stretch = hdr.stretchLastSection()
            act_stretch = menu.addAction("Stretch Last Column (On)" if is_stretch else "Stretch Last Column (Off)")
            
            # Lock column widths (if table has a card ref with lock support, e.g. Today Payment cards)
            card = getattr(table, '_card_ref', None)
            has_lock_support = card and hasattr(card, '_cols_locked') and hasattr(card, '_set_cols_locked')
            act_lock = None
            if has_lock_support:
                menu.addSeparator()
                is_locked = getattr(card, '_cols_locked')
                act_lock = menu.addAction("🔓  Unlock Column Widths" if is_locked else "🔒  Lock Column Widths")

            chosen = menu.exec(hdr.mapToGlobal(pos))
            if chosen == act_fit:
                idx = hdr.logicalIndexAt(pos)
                table.resizeColumnToContents(idx)
            elif chosen == act_fit_all:
                table.resizeColumnsToContents()
            elif chosen == act_stretch:
                hdr.setStretchLastSection(not is_stretch)
            elif act_lock and chosen == act_lock:
                card._set_cols_locked(not getattr(card, '_cols_locked'))
                
        table._smart_hdr_menu = _show_menu
        hdr.customContextMenuRequested.connect(table._smart_hdr_menu)


class _DbTable(QTableWidget):
    """A clean QTableWidget backed by a single SQL table.
    Schema: (row_idx INT, col_idx INT, cell_text NVARCHAR(MAX), PRIMARY KEY (row_idx, col_idx))
    """
    def __init__(self, table_name: str, headers: list, widths: list,
                 parent=None, row_count=0):
        super().__init__(0, len(headers), parent)
        self._table_name = table_name
        self._db = get_db_manager()
        self._db_name = ""
        self._headers = headers
        self._widths = widths
        self._loading = False
        self._can_edit = True
        self._min_rows = max(0, row_count)  # Bug 1b: minimum visible rows after load
        self._is_edit_mode = False           # tracks F2 edit mode (cursor at end, no selection)

        self.setFont(_norm_font())
        self.setAlternatingRowColors(True)
        self.setStyleSheet(_TABLE_STYLE)
        self.setHorizontalHeaderLabels(headers)
        _setup_smart_header(self)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setDefaultSectionSize(26)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)

        self.itemChanged.connect(self._on_change)
        self.horizontalHeader().sectionResized.connect(self._on_section_resized)

        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)

        self.setItemDelegate(ModernTableDelegate(self))

    def set_db_name(self, db_name: str, path: str = None):
        self._db_name = db_name
        if path:
            self._db.ensure_database_exists(db_name, path)
        self._ensure_table()
        self.load_from_db()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            | QTableWidget.EditTrigger.EditKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )

    def _ensure_table(self):
        if not self._db_name:
            return
        ddl = (f"CREATE TABLE {self._table_name} "
               f"(row_idx INT NOT NULL, col_idx INT NOT NULL, "
               f"cell_text NVARCHAR(MAX), PRIMARY KEY (row_idx, col_idx))")
        self._db.ensure_table(self._db_name, self._table_name, ddl)

    def _on_change(self, item):
        if self._loading:
            return
        # Dynamically resize the column to fit new content but respect minimum width and header text
        self._enforce_min_widths(item.column())
        
        # Debounced 300ms save ΓÇô consistent with _SectionCardV2 strategy
        self._save_timer.start(300)

    def _on_section_resized(self, logicalIndex, oldSize, newSize):
        if self._loading: return
        
        if not hasattr(self, '_resize_timers'):
            self._resize_timers = {}
            
        if logicalIndex not in self._resize_timers:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda idx=logicalIndex: self._enforce_col_min(idx))
            self._resize_timers[logicalIndex] = t
            
        self._resize_timers[logicalIndex].start(300)

    def _enforce_col_min(self, logicalIndex):
        if self._loading: return
        min_w = self._widths[logicalIndex] if logicalIndex < len(self._widths) else 0
        hdr_item = self.horizontalHeaderItem(logicalIndex)
        hdr_text = hdr_item.text() if hdr_item else ""
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(hdr_text) + 20
        required_w = max(min_w, text_w)
        if self.columnWidth(logicalIndex) < required_w:
            self.horizontalHeader().blockSignals(True)
            self.setColumnWidth(logicalIndex, required_w)
            self.horizontalHeader().blockSignals(False)

    def _do_save(self):
        """Save table contents using a single atomic transaction to prevent data loss."""
        if not self._db_name or self._loading:
            return
        if getattr(self, '_load_failed', False):
            print(f"[_DbTable] Blocked save for {self._table_name} to prevent data loss after load failure.")
            return
            
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(f"DELETE FROM {self._table_name}")
            # Collect all non-empty cells first, then send in one batched round-trip.
            rows_to_insert = [
                (r, c, self.item(r, c).text())
                for r in range(self.rowCount())
                for c in range(self.columnCount())
                if self.item(r, c) and self.item(r, c).text()
            ]
            if rows_to_insert:
                cur.executemany(
                    f"INSERT INTO {self._table_name} (row_idx, col_idx, cell_text) VALUES (?,?,?)",
                    rows_to_insert
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[_DbTable] _do_save error ({self._table_name}):", e)

    # keep save_to_db as alias for external callers
    def save_to_db(self):
        self._do_save()

    def _enforce_min_widths(self, col=None):
        fm = self.fontMetrics()
        
        if col is not None:
            cols = [col]
        else:
            cols = range(self.columnCount())
            
        for i in cols:
            # Use sizeHintForColumn instead of resizeColumnToContents so we don't snap back
            # if the user manually dragged the column to be wider.
            min_w = self.sizeHintForColumn(i)
            saved_w = self._widths[i] if i < len(self._widths) else 0
            min_w = max(min_w, saved_w)
            
            h_item = self.horizontalHeaderItem(i)
            if h_item and h_item.text():
                # Add 24px padding for sort indicator and margins
                min_w = max(min_w, fm.horizontalAdvance(h_item.text()) + 24)
            if self.columnWidth(i) < min_w:
                self.setColumnWidth(i, min_w)

    def load_from_db(self):
        if not self._db_name:
            return
        self._loading = True
        rows = self._db.execute_query(
            self._db_name,
            f"SELECT row_idx, col_idx, cell_text FROM {self._table_name} ORDER BY row_idx, col_idx"
        )
        if rows is None:
            self._load_failed = True
            self._loading = False
            print(f"[_DbTable] Failed to load data from {self._table_name}.")
            return
        self._load_failed = False
        
        self.blockSignals(True)
        self.clearContents()
        self.setRowCount(0)
        for r, c, txt in rows:
            while self.rowCount() <= int(r):
                self.insertRow(self.rowCount())
                for ci in range(self.columnCount()):
                    self.setItem(self.rowCount() - 1, ci, QTableWidgetItem(""))
            it = QTableWidgetItem(txt or "")
            self.setItem(int(r), int(c), it)
        # Bug 1b: Pad up to the minimum row count so the table is never visually empty
        while self.rowCount() < self._min_rows:
            r = self.rowCount()
            self.insertRow(r)
            for c in range(self.columnCount()):
                self.setItem(r, c, QTableWidgetItem(""))
        self.blockSignals(False)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._enforce_min_widths)
        self._loading = False

    def add_row(self):
        if not self._can_edit:
            return
        self.blockSignals(True)
        r = self.rowCount()
        self.insertRow(r)
        for c in range(self.columnCount()):
            self.setItem(r, c, QTableWidgetItem(""))
        self.blockSignals(False)
        self._enforce_min_widths()
        self.scrollToBottom()
        # Save the new empty row directly (no timer, no thread)
        self._do_save()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F2 and self._can_edit:
            # Set flag BEFORE super() so setEditorData sees it.
            # Qt opens the editor via EditKeyPressed trigger inside super().
            self._is_edit_mode = True
            super().keyPressEvent(event)
        elif self._can_edit and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for it in self.selectedItems():
                it.setText("")
        else:
            super().keyPressEvent(event)

    def closeEditor(self, editor, hint):
        """Reset F2 edit-mode flag when any editor closes so normal typing
        never inherits the 'cursor at end, no selection' F2 behaviour."""
        self._is_edit_mode = False
        super().closeEditor(editor, hint)

    # ── Right-click context menu with Delete Row ──────────────────────────

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QBrush, QColor

        sel_rows = sorted({i.row() for i in self.selectedItems()})
        lbl = f"\u2715  Delete {len(sel_rows)} Row(s)" if sel_rows else "\u2715  Delete Row"
        act_del = menu.addAction(lbl)
        act_del.setEnabled(bool(sel_rows) and self._can_edit)

        menu.addSeparator()
        act_add_above = menu.addAction("\u2191  Add Row Above")
        act_add_above.setEnabled(self._can_edit and bool(sel_rows))

        act_add_below = menu.addAction("\u2193  Add Row Below")
        act_add_below.setEnabled(self._can_edit and bool(sel_rows))
        
        menu.addSeparator()
        act_add = menu.addAction("\u2295  Add Row (Bottom)")
        act_add.setEnabled(self._can_edit)

        menu.addSeparator()
        a_color = menu.addAction("\u25cf  Set Cell Color")
        a_text_color = menu.addAction("\u25d0  Set Text Color")
        a_clear = menu.addAction("\u25cb  Clear Colors")

        chosen = menu.exec(event.globalPos())

        if chosen == act_del and sel_rows:
            msg = QMessageBox(self)
            msg.setWindowTitle("Delete Rows")
            msg.setText(f"Delete {len(sel_rows)} row(s)? This cannot be undone.")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setStyleSheet(_POPUP_STYLE)
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self.blockSignals(True)
                for r in reversed(sel_rows):
                    self.removeRow(r)
                # Pad back to minimum rows if needed
                while self.rowCount() < self._min_rows:
                    r = self.rowCount()
                    self.insertRow(r)
                    for c in range(self.columnCount()):
                        self.setItem(r, c, QTableWidgetItem(""))
                self.blockSignals(False)
                self.resizeColumnsToContents()
                self._do_save()

        elif chosen == act_add_above and sel_rows:
            self.blockSignals(True)
            r = min(sel_rows)
            self.insertRow(r)
            for c in range(self.columnCount()):
                self.setItem(r, c, QTableWidgetItem(""))
            self.blockSignals(False)
            self._save_timer.start(300)

        elif chosen == act_add_below and sel_rows:
            self.blockSignals(True)
            r = max(sel_rows) + 1
            self.insertRow(r)
            for c in range(self.columnCount()):
                self.setItem(r, c, QTableWidgetItem(""))
            self.blockSignals(False)
            self._save_timer.start(300)

        elif chosen == act_add:
            self.add_row()
            
        elif chosen == a_color:
            color = _styled_get_color(self)
            if color.isValid():
                self.blockSignals(True)
                for idx in self.selectedIndexes():
                    it = self.item(idx.row(), idx.column())
                    if not it:
                        it = QTableWidgetItem("")
                        self.setItem(idx.row(), idx.column(), it)
                    it.setBackground(QBrush(color))
                self.blockSignals(False)
                self.resizeColumnsToContents()
                self._do_save()

        elif chosen == a_text_color:
            color = _styled_get_color(self)
            if color.isValid():
                self.blockSignals(True)
                for idx in self.selectedIndexes():
                    it = self.item(idx.row(), idx.column())
                    if not it:
                        it = QTableWidgetItem("")
                        self.setItem(idx.row(), idx.column(), it)
                    it.setForeground(QBrush(color))
                self.blockSignals(False)
                self.resizeColumnsToContents()
                self._do_save()

        elif chosen == a_clear:
            self.blockSignals(True)
            for idx in self.selectedIndexes():
                it = self.item(idx.row(), idx.column())
                if it:
                    it.setBackground(QBrush())
                    it.setForeground(QBrush())
            self.blockSignals(False)
            self.resizeColumnsToContents()
            self._do_save()


# ===========================================================================
# Section card widget used in Today Payment
