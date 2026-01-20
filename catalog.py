from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt, QMarginsF, QStandardPaths
from PyQt6.QtGui import QKeySequence, QPainter, QPageLayout, QPageSize, QShortcut
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog, QPrintDialog
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QRadioButton,
    QSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from tabs.Catalog.CatalogUI import Ui_CatalogTab
from A4Catalog import A4CatalogPage
from utils import clean_col_name

from db_manager import (
    PageID,
    init_db,
    list_crms,
    load_dataframe,
    save_dataframe,
    crm_update_page_map,
    crm_mark_pages_pending,
)


# ============================================================
# UI: Preview view + controller (single-page)
# ============================================================


class PreviewGraphicsView(QGraphicsView):
    """Ctrl+Wheel zoom; view anchor settings make zoom/fit stable."""

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            zoom_in = event.angleDelta().y() > 0
            factor = 1.1 if zoom_in else 0.9
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)


class PreviewController:
    """Owns QGraphicsScene/QGraphicsView and keeps the page fitted."""

    def __init__(self, container_layout: QVBoxLayout, parent: QWidget):
        self.scene = QGraphicsScene(parent)
        self.view = PreviewGraphicsView(self.scene, parent)
        container_layout.addWidget(self.view)

    def set_widget(self, widget: QWidget | None):
        self.scene.clear()
        if widget is not None:
            self.scene.addWidget(widget)
            QApplication.processEvents()
            self.fit_page()

    def fit_page(self):
        rect = self.scene.itemsBoundingRect()
        if rect.isNull():
            return
        self.view.resetTransform()
        self.view.setSceneRect(rect)
        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)


# ============================================================
# Dialog: Catalogue PDF export settings
# ============================================================
class CatalogueExportDialog(QDialog):
    """
    Export catalogue with:
    - DPI
    - Either All pages OR a custom range specified by:
      (master_sn, parent_sn, parent_page_no) start + end
    """

    def __init__(self, parent: QWidget, pages_data: list["CatalogPageData"]):
        super().__init__(parent)
        self.setWindowTitle("Export Catalogue")

        self.pages_data = pages_data or []
        self.selection: tuple[int, str, tuple[str, str, int], tuple[str, str, int]] | None = None
        # selection = (dpi, mode, start_ident, end_ident)

        root = QVBoxLayout(self)
        grid = QGridLayout()
        root.addLayout(grid)

        # DPI
        grid.addWidget(QLabel("Quality (DPI):"), 0, 0)
        self.qc = QComboBox()
        self.qc.addItem("150 (Draft)", 150)
        self.qc.addItem("300 (Standard)", 300)
        self.qc.addItem("600 (High)", 600)
        self.qc.setCurrentIndex(1)
        grid.addWidget(self.qc, 0, 1)

        # Range mode
        grid.addWidget(QLabel("Pages:"), 1, 0)
        mode_row = QHBoxLayout()
        self.radio_all = QRadioButton("All pages")
        self.radio_custom = QRadioButton("Custom range")
        self.radio_all.setChecked(True)
        mode_row.addWidget(self.radio_all)
        mode_row.addWidget(self.radio_custom)
        mode_row.addStretch(1)
        grid.addLayout(mode_row, 1, 1)

        # Custom range UI
        self.custom_box = QWidget(self)
        custom = QGridLayout(self.custom_box)

        custom.addWidget(QLabel("Start:"), 0, 0)
        self.cb_start_group = QComboBox(self.custom_box)
        self.spin_start_page = QSpinBox(self.custom_box)
        self.spin_start_page.setMinimum(1)
        custom.addWidget(self.cb_start_group, 0, 1)
        custom.addWidget(QLabel("Page:"), 0, 2)
        custom.addWidget(self.spin_start_page, 0, 3)

        custom.addWidget(QLabel("End:"), 1, 0)
        self.cb_end_group = QComboBox(self.custom_box)
        self.spin_end_page = QSpinBox(self.custom_box)
        self.spin_end_page.setMinimum(1)
        custom.addWidget(self.cb_end_group, 1, 1)
        custom.addWidget(QLabel("Page:"), 1, 2)
        custom.addWidget(self.spin_end_page, 1, 3)

        self.lbl_info = QLabel("", self.custom_box)
        custom.addWidget(self.lbl_info, 2, 0, 1, 4)

        root.addWidget(self.custom_box)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Populate groups + defaults
        self._groups = self._collect_groups_in_order()
        self._populate_group_combos()
        self._apply_defaults()

        # Wire signals
        self.radio_all.toggled.connect(self._update_enabled)
        self.radio_custom.toggled.connect(self._update_enabled)

        self.cb_start_group.currentIndexChanged.connect(lambda _: self._sync_page_limits(which="start"))
        self.cb_end_group.currentIndexChanged.connect(lambda _: self._sync_page_limits(which="end"))
        self.spin_start_page.valueChanged.connect(lambda _: self._update_info_label())
        self.spin_end_page.valueChanged.connect(lambda _: self._update_info_label())

        self._update_enabled()
        self._sync_page_limits("start")
        self._sync_page_limits("end")
        self._update_info_label()

    def _collect_groups_in_order(self) -> list[tuple[str, str]]:
        seen = set()
        out: list[tuple[str, str]] = []
        for p in self.pages_data:
            key = (str(p.master_sn).strip(), str(p.parent_sn).strip())
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out

    def _max_page_for_group(self, group: tuple[str, str]) -> int:
        ms, ps = group
        m = 1
        for p in self.pages_data:
            if str(p.master_sn).strip() == ms and str(p.parent_sn).strip() == ps:
                m = max(m, int(p.parent_page_no))
        return m

    def _populate_group_combos(self):
        self.cb_start_group.clear()
        self.cb_end_group.clear()
        for ms, ps in self._groups:
            label = f"{ms} | Parent {ps}"
            self.cb_start_group.addItem(label, (ms, ps))
            self.cb_end_group.addItem(label, (ms, ps))

    def _apply_defaults(self):
        # Both start and end default to the first group + page 1 (as you requested).
        if self.cb_start_group.count() > 0:
            self.cb_start_group.setCurrentIndex(0)
            self.cb_end_group.setCurrentIndex(0)
        self.spin_start_page.setValue(1)
        self.spin_end_page.setValue(1)

    def _update_enabled(self):
        is_custom = self.radio_custom.isChecked()
        self.custom_box.setEnabled(is_custom)

    def _sync_page_limits(self, which: str):
        if which == "start":
            group = self.cb_start_group.currentData()
            spin = self.spin_start_page
        else:
            group = self.cb_end_group.currentData()
            spin = self.spin_end_page

        if not group:
            spin.setMaximum(1)
            spin.setValue(1)
            return

        maxp = self._max_page_for_group(group)
        spin.setMaximum(maxp)
        if spin.value() > maxp:
            spin.setValue(maxp)

        self._update_info_label()

    def _update_info_label(self):
        if self.radio_all.isChecked():
            self.lbl_info.setText(f"Total pages: {len(self.pages_data)}")
            return

        sg = self.cb_start_group.currentData()
        eg = self.cb_end_group.currentData()
        if not sg or not eg:
            self.lbl_info.setText("")
            return

        sms, sps = sg
        ems, eps = eg
        sp = self.spin_start_page.value()
        ep = self.spin_end_page.value()

        self.lbl_info.setText(
            f"Start: {sms}/{sps}/{sp}    End: {ems}/{eps}/{ep}"
        )

    def _ok(self):
        dpi = int(self.qc.currentData())

        if self.radio_all.isChecked():
            # Dummy identities; exporter will ignore when mode == "all"
            first = self.pages_data[0]
            ident0 = (str(first.master_sn).strip(), str(first.parent_sn).strip(), int(first.parent_page_no))
            self.selection = (dpi, "all", ident0, ident0)
            self.accept()
            return

        sg = self.cb_start_group.currentData()
        eg = self.cb_end_group.currentData()
        if not sg or not eg:
            QMessageBox.warning(self, "Invalid", "Please select start and end group.")
            return

        start_ident = (str(sg[0]).strip(), str(sg[1]).strip(), int(self.spin_start_page.value()))
        end_ident = (str(eg[0]).strip(), str(eg[1]).strip(), int(self.spin_end_page.value()))
        self.selection = (dpi, "custom", start_ident, end_ident)
        self.accept()



# ============================================================
# Catalog building (data -> pages)
# ============================================================


@dataclass
class CatalogPageData:
    header_title: str
    products_placed: list[dict[str, Any]]
    page_update_str: str
    columns: int

    # Immutable page identity
    master_sn: str
    parent_sn: str
    parent_page_no: int  # 1-based within that parent_sn


class CatalogBuilder:
    """Pure-ish logic: df -> products -> pages_data."""

    def __init__(
        self,
        get_df_callable: Callable[[], Any],
        grid_rows: int,
        grid_cols: int,
        auto_layout_callable: Callable[[], bool],
    ):
        self.get_df_callable = get_df_callable
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols
        self.auto_layout_callable = auto_layout_callable

    # ----------------------------
    # Date helpers
    # ----------------------------

    @staticmethod
    def parse_update_date(raw: str):
        if not raw:
            return None
        text = str(raw).strip()
        if not text:
            return None
        token = text.split()[0]
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(token, fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def format_date_for_footer(dt: datetime | None) -> str:
        return dt.strftime("%d / %m") if dt else ""

    # ----------------------------
    # GUID -> identities page_map
    # ----------------------------

    @staticmethod
    def extract_page_map(pages: list[CatalogPageData]) -> Dict[Any, Set[PageID]]:
        page_map: Dict[Any, Set[PageID]] = {}
        for p in pages:
            ident: PageID = (p.master_sn, p.parent_sn, int(p.parent_page_no))
            for item in p.products_placed:
                guid_val = item["data"].get("guid")
                if not guid_val:
                    continue
                page_map.setdefault(guid_val, set()).add(ident)
        return page_map

    # ----------------------------
    # DataFrame filters
    # ----------------------------

    def load_filtered_df(self, parent: QWidget):
        df = self.get_df_callable()
        if df is None or df.empty:
            QMessageBox.warning(parent, "Empty", "No data.")
            return None

        df = df.copy()
        df.columns = [clean_col_name(c) for c in df.columns]

        tf_col = clean_col_name("true/false")
        if tf_col in df.columns:
            df = df[df[tf_col].astype(str).str.lower() == "true"]

        cb_col = clean_col_name("$ClosingBalance")
        if cb_col in df.columns:
            try:
                df[cb_col] = df[cb_col].apply(
                    lambda v: float(str(v).replace(",", ""))
                    if str(v).strip() not in ("", "None")
                    else 0.0
                )
                df = df[df[cb_col] > 0]
            except Exception:
                pass

        if df.empty:
            QMessageBox.warning(parent, "Empty", "No active products.")
            return None

        try:
            df = df.sort_values(
                by=[clean_col_name("Master Group SN"), clean_col_name("Parent SN")]
            )
        except Exception:
            pass

        return df

    # ----------------------------
    # Row -> product dicts
    # ----------------------------

    def df_to_products(self, df_rows, master_val, update_col, no_col):
        import re as _re

        def _mrp_sort_key(v):
            if v is None:
                return float("-inf")
            s = str(v).strip()
            if not s:
                return float("-inf")
            try:
                s = s.replace(",", "")
                m = _re.search(r"[-]?\d+(?:\.\d+)?", s)
                return float(m.group(0)) if m else float("-inf")
            except Exception:
                return float("-inf")

        def _mp_num(v):
            if v is None:
                return None
            s = str(v).strip()
            if not s:
                return None
            s = s.replace(",", "")
            m = _re.search(r"\d+", s)
            return int(m.group(0)) if m else None

        if no_col not in df_rows.columns:
            return []

        products: list[dict[str, Any]] = []
        image_path_col = clean_col_name("Image Path")
        guid_col = clean_col_name("GUID")

        for no_value, block in df_rows.groupby(no_col):
            grouped: dict[str, dict[str, Any]] = {}
            records = block.to_dict("records")

            for r in records:
                raw_name = (
                    r.get(clean_col_name("PRODUCT NAME RE."), "")
                    or r.get(clean_col_name("Product Name"), "")
                    or ""
                ).strip()
                if not raw_name:
                    continue

                norm = " ".join(
                    raw_name.lower().replace("-", " ").replace("_", " ").split()
                )

                row_guid = str(r.get(guid_col, "") or "").strip()

                if norm not in grouped:
                    raw_update = r.get(update_col, "") if update_col in r else ""
                    cat_val = str(r.get(clean_col_name("$Category"), "")).lower()
                    if "china" in cat_val:
                        cat_val = "चा."
                    elif "indian" in cat_val or "india" in cat_val:
                        cat_val = "ई."
                    else:
                        cat_val = ""

                    grouped[norm] = {
                        "product_name": raw_name,
                        "master_group": master_val,
                        "category": cat_val,
                        "base_units": r.get(clean_col_name("$BaseUnits"), ""),
                        "sizes": [],
                        "mrps": [],
                        "moqs": [],
                        "_mp_set": set(),
                        "master_packing": "",
                        "image_path": (r.get(image_path_col, "") or "").strip(),
                        "image_length": "1|1",
                        "_max_img_h": 1,
                        "_max_img_v": 1,
                        "no": no_value,
                        "update_date": raw_update,
                        "guid": row_guid,
                    }

                g = grouped[norm]

                mp = _mp_num(r.get(clean_col_name("Master Packing"), ""))
                if mp is not None:
                    g["_mp_set"].add(mp)

                if not (g.get("guid") or "").strip() and row_guid:
                    g["guid"] = row_guid

                if not (g.get("image_path") or "").strip():
                    candidate = (r.get(image_path_col, "") or "").strip()
                    if candidate:
                        g["image_path"] = candidate

                raw_img_len = r.get(clean_col_name("Image length"), "1|1")
                try:
                    dims = str(raw_img_len).split("|")
                    h = int(dims[0]) if len(dims) >= 1 and str(dims[0]).strip() else 1
                    v = int(dims[1]) if len(dims) >= 2 and str(dims[1]).strip() else 1
                except Exception:
                    h, v = 1, 1
                g["_max_img_h"] = max(g["_max_img_h"], h)
                g["_max_img_v"] = max(g["_max_img_v"], v)
                g["image_length"] = f"{g['_max_img_h']}|{g['_max_img_v']}"

                size_val = (
                    r.get(clean_col_name("Product Size RE."), "")
                    or r.get(clean_col_name("Product Size"), "")
                )
                mrp_val = r.get(clean_col_name("$StandardPrice"), "")
                moq_val = r.get(clean_col_name("MOQ"), "")

                g["sizes"].append(size_val)
                g["mrps"].append(mrp_val)
                g["moqs"].append(moq_val)

            for g in grouped.values():
                rows = list(zip(g["sizes"], g["mrps"], g["moqs"]))
                rows.sort(key=lambda t: _mrp_sort_key(t[1]))
                g["sizes"] = [t[0] for t in rows]
                g["mrps"] = [t[1] for t in rows]
                g["moqs"] = [t[2] for t in rows]

                g.pop("_max_img_h", None)
                g.pop("_max_img_v", None)

                base = str(g.get("base_units", "")).strip()
                mp_list = sorted(g.get("_mp_set", []))
                if mp_list:
                    g["master_packing"] = f'{",".join(map(str, mp_list))} {base}'.strip()
                else:
                    g["master_packing"] = ""
                g.pop("_mp_set", None)

                products.append(g)

        return products

    # ----------------------------
    # Flatten all products
    # ----------------------------

    def collect_products(self, df):
        master_col = clean_col_name("Master Group")
        parent_sn_col = clean_col_name("Parent SN")
        update_col = clean_col_name("Update_Date")
        no_col = clean_col_name("no")

        def norm_full(p: dict) -> str:
            raw = str(p.get("product_name", "")).strip().lower()
            return " ".join(raw.replace("-", " ").replace("_", " ").split())

        def first_price_value(p: dict) -> float:
            mrps = p.get("mrps") or []
            val = mrps[0] if mrps else ""
            try:
                s = str(val).strip().replace(",", "")
                if s in ("", "None", "nan"):
                    return float("inf")
                return float(s)
            except Exception:
                return float("inf")

        all_products_flat: list[tuple[tuple[str, str], str, dict[str, Any]]] = []

        for master in df[master_col].dropna().unique():
            master_df = df[df[master_col] == master]
            for p_sn in master_df[parent_sn_col].dropna().unique():
                parent_df = master_df[master_df[parent_sn_col] == p_sn]

                prods = self.df_to_products(parent_df, master, update_col, no_col)
                prods_sorted = sorted(
                    prods,
                    key=lambda p: (
                        norm_full(p),
                        first_price_value(p),
                        str(p.get("product_name", "")),
                    ),
                )

                group_key = (str(master).strip(), str(p_sn).strip())
                header_text = str(master).strip()

                for prod in prods_sorted:
                    prod["parent_sn"] = group_key[1]
                    all_products_flat.append((group_key, header_text, prod))

        return all_products_flat

    # ----------------------------
    # Layout products -> pages
    # ----------------------------

    def layout_pages(
        self, all_products_flat: list[tuple[tuple[str, str], str, dict[str, Any]]]
    ) -> list[CatalogPageData]:
        pages: list[CatalogPageData] = []
        if not all_products_flat:
            return pages

        is_auto = bool(self.auto_layout_callable())
        MAXR = self.grid_rows
        MAXC = self.grid_cols

        current_page_grid = [[False for _ in range(MAXC)] for _ in range(MAXR)]
        current_page_items: list[dict[str, Any]] = []

        current_group = all_products_flat[0][0]
        current_header = all_products_flat[0][1]
        current_parent_page_no = 1

        def commit_page(items, header, group_key, parent_page_no: int):
            if not items:
                return

            best_dt = None
            for it in items:
                pdv = it["data"].get("update_date")
                dt = pdv if isinstance(pdv, datetime) else CatalogBuilder.parse_update_date(pdv)
                if dt and (best_dt is None or dt > best_dt):
                    best_dt = dt

            master_sn, parent_sn = group_key
            pages.append(
                CatalogPageData(
                    header_title=header,
                    products_placed=items,
                    page_update_str=CatalogBuilder.format_date_for_footer(best_dt),
                    columns=MAXC,
                    master_sn=str(master_sn).strip(),
                    parent_sn=str(parent_sn).strip(),
                    parent_page_no=int(parent_page_no),
                )
            )

        for group_key, header_text, prod in all_products_flat:
            # page break if parent group changes
            if current_page_items and group_key != current_group:
                commit_page(current_page_items, current_header, current_group, current_parent_page_no)
                current_page_grid = [[False for _ in range(MAXC)] for _ in range(MAXR)]
                current_page_items = []
                current_group = group_key
                current_header = header_text
                current_parent_page_no = 1

            # footprint
            try:
                dims = str(prod.get("image_length", "1|1")).split("|")
                imgH = int(dims[0]) if len(dims) >= 1 else 1
                imgV = int(dims[1]) if len(dims) >= 2 else 1
            except Exception:
                imgH, imgV = 1, 1

            imgH = max(1, min(imgH, MAXC - 1))
            cspan_total = imgH + 1

            if is_auto:
                nrows = len(prod.get("sizes", []))
                if nrows >= 22:
                    rspan = 3
                elif nrows >= 8:
                    rspan = 2
                else:
                    rspan = 1
            else:
                rspan = imgV

            rspan = max(1, min(rspan, MAXR))

            placed = False
            for r in range(MAXR):
                if placed:
                    break
                for c in range(MAXC):
                    if current_page_grid[r][c]:
                        continue
                    if c + cspan_total > MAXC or r + rspan > MAXR:
                        continue

                    collision = False
                    for rr in range(rspan):
                        for cc in range(cspan_total):
                            if current_page_grid[r + rr][c + cc]:
                                collision = True
                                break
                        if collision:
                            break
                    if collision:
                        continue

                    current_page_items.append(
                        {"data": prod, "row": r, "col": c, "rspan": rspan, "cspan": cspan_total}
                    )
                    for rr in range(rspan):
                        for cc in range(cspan_total):
                            current_page_grid[r + rr][c + cc] = True
                    placed = True
                    break

            if not placed:
                # commit full page and start new page within same parent
                commit_page(current_page_items, current_header, current_group, current_parent_page_no)
                current_parent_page_no += 1

                current_page_grid = [[False for _ in range(MAXC)] for _ in range(MAXR)]
                current_page_items = []

                current_page_items.append(
                    {"data": prod, "row": 0, "col": 0, "rspan": rspan, "cspan": cspan_total}
                )
                for rr in range(rspan):
                    for cc in range(cspan_total):
                        if rr < MAXR and cc < MAXC:
                            current_page_grid[rr][cc] = True

                current_group = group_key
                current_header = header_text

        if current_page_items:
            commit_page(current_page_items, current_header, current_group, current_parent_page_no)

        return pages


# ============================================================
# Exporter (PDF/print)
# ============================================================


class PdfExporter:
    def __init__(self, owner: "CatalogTab"):
        self.owner = owner

    # ----------------------------
    # Identity-only export (used by report.py)
    # ----------------------------

    def export_identities(self, crm_name: str, mode: str, identities: list[PageID], dpi: int = 300):
        """
        Identity-only export used by report.py.
        identities: [(master_sn, parent_sn, parent_page_no), ...]
        """
        self.owner.build_catalog()

        identity_to_index: dict[PageID, int] = getattr(self.owner, "identity_to_index", {})
        indices: list[int] = []

        for ident in identities:
            key: PageID = (str(ident[0]).strip(), str(ident[1]).strip(), int(ident[2]))
            idx = identity_to_index.get(key)
            if idx is not None:
                indices.append(idx)

        if not indices:
            QMessageBox.information(self.owner, "Up to date", "No printable pages found.")
            return

        if mode == "download":
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setResolution(int(dpi))
            layout = QPageLayout(
                QPageSize(QPageSize.PageSizeId.A4),
                QPageLayout.Orientation.Portrait,
                QMarginsF(0, 0, 0, 0),
            )
            printer.setPageLayout(layout)
            printer.setFullPage(True)

            today_str = datetime.now().strftime("%Y-%m-%d")
            safe_name = str(crm_name or "report").strip().replace(" ", "_")
            default_filename = f"{safe_name}_{today_str}.pdf"

            file_path, _ = QFileDialog.getSaveFileName(
                self.owner, "Save Report", default_filename, "PDF Files (*.pdf)"
            )
            if not file_path:
                return

            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)

            self.print_indices_to_device(printer, indices, crm_name)
            QMessageBox.information(self.owner, "Success", "Report exported.")
            return

        self.preview_and_print_indices(crm_name or "", indices, dpi)

    def print_indices_to_device(self, printer: QPrinter, indices: list[int], crm_name: str | None = None):
        if not indices:
            return

        painter = QPainter()
        if not painter.begin(printer):
            return

        original_idx = self.owner.current_page_idx
        first_page = True

        try:
            printer.setFullPage(True)

            for idx in indices:
                if idx < 0 or idx >= len(self.owner.pages_data):
                    continue

                if not first_page:
                    printer.newPage()
                first_page = False

                self.owner.create_a4_widget()
                self.owner.current_page_idx = idx
                self.owner.render_current_page()
                QApplication.processEvents()

                if crm_name and self.owner.current_a4_widget:
                    self.owner.current_a4_widget.set_footer_left(crm_name)

                if not self.owner.current_a4_widget:
                    continue

                w = self.owner.current_a4_widget.width()
                h = self.owner.current_a4_widget.height()
                if w <= 0 or h <= 0:
                    continue

                paint_rect = printer.pageLayout().paintRectPixels(printer.resolution())
                sx = paint_rect.width() / w
                sy = paint_rect.height() / h
                scale_factor = min(sx, sy)

                tx = paint_rect.x() + (paint_rect.width() - w * scale_factor) / 2.0
                ty = paint_rect.y() + (paint_rect.height() - h * scale_factor) / 2.0

                painter.save()
                painter.translate(tx, ty)
                painter.scale(scale_factor, scale_factor)
                self.owner.current_a4_widget.render(painter)
                painter.restore()
        finally:
            painter.end()
            self.owner.current_page_idx = original_idx
            if self.owner.pages_data:
                self.owner.render_current_page()

    def preview_and_print_indices(self, crm_name: str, indices: list[int], dpi: int = 300):
        if not indices:
            QMessageBox.information(self.owner, "No Pages", "No pages selected.")
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
        printer.setResolution(int(dpi))

        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
        )
        printer.setPageLayout(layout)
        printer.setFullPage(True)

        preview = QPrintPreviewDialog(printer, self.owner)
        preview.setWindowTitle(f"Preview - {crm_name or 'Report'}")

        def handle_paint_request(p: QPrinter):
            self.print_indices_to_device(p, indices, crm_name)

        preview.paintRequested.connect(handle_paint_request)
        preview.exec()

    # ----------------------------
    # Catalogue export 
    # ----------------------------
    def export_catalogue_pdf(self):
        self.owner.build_catalog()

        if not self.owner.pages_data:
            QMessageBox.information(self.owner, "No Catalog", "Catalog is empty.")
            return

        dlg = CatalogueExportDialog(self.owner, pages_data=self.owner.pages_data)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selection:
            return

        dpi, mode, start_ident, end_ident = dlg.selection

        # Convert to indices
        if mode == "all":
            indices = list(range(len(self.owner.pages_data)))
        else:
            idmap = getattr(self.owner, "identity_to_index", {})
            sidx = idmap.get(start_ident)
            eidx = idmap.get(end_ident)

            if sidx is None or eidx is None:
                QMessageBox.warning(self.owner, "Invalid Range", "Start or end page not found.")
                return

            lo, hi = (sidx, eidx) if sidx <= eidx else (eidx, sidx)
            indices = list(range(lo, hi + 1))

        downloads_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        default_path = str(Path(downloads_path) / "catalog.pdf")
        file_path, _ = QFileDialog.getSaveFileName(self.owner, "Save Catalogue", default_path, "PDF Files (*.pdf)")
        if not file_path:
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(int(dpi))
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
        )
        printer.setPageLayout(layout)
        printer.setFullPage(True)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(file_path)

        self.print_indices_to_device(printer, indices, crm_name=None)
        QMessageBox.information(self.owner, "Success", f"Catalogue exported to:\n{file_path}")



# ============================================================
# CatalogTab (Qt controller)
# ============================================================


class CatalogTab(QWidget):
    def __init__(self, final_data_tab, dashboard):
        super().__init__()

        self.final_tab = final_data_tab
        self.dashboard = dashboard

        self.rows = 5
        self.cols = 4
        self.GRID_ROWS = self.rows
        self.GRID_COLS = self.cols

        self.pages_data: list[CatalogPageData] = []
        self.current_page_idx = 0
        self.total_pages = 0

        # identity -> pages_data index
        self.identity_to_index: dict[PageID, int] = {}

        self.current_a4_widget: A4CatalogPage | None = None
        self.company_path: Path | None = None
        self.sidebar_visible = False

        self.ui = Ui_CatalogTab()
        self.ui.setup_ui(self)

        self.preview = PreviewController(self.ui.page_layout, self)

        self.builder = CatalogBuilder(
            get_df_callable=self.get_catalog_df,
            grid_rows=self.GRID_ROWS,
            grid_cols=self.GRID_COLS,
            auto_layout_callable=lambda: self.ui.chk_auto_layout.isChecked(),
        )
        self.exporter = PdfExporter(self)

        self._connect_signals()
        self._initialize_ui_values()

    # -----------------------
    # UI wiring
    # -----------------------

    def _connect_signals(self):
        self.ui.btn_toggle.clicked.connect(self.toggle_sidebar)
        self.ui.btn_prev.clicked.connect(self.prev_page)
        self.ui.btn_next.clicked.connect(self.next_page)
        self.ui.spin_page.editingFinished.connect(self.jump_to_page)
        self.ui.btn_refresh.clicked.connect(self.build_catalog)

        # Export full catalogue (no page-range / no globals for export selection)
        self.ui.btn_pdf.clicked.connect(self.exporter.export_catalogue_pdf)
        self.shortcut_print = QShortcut(QKeySequence("Ctrl+P"), self)
        self.shortcut_print.activated.connect(self.exporter.export_catalogue_pdf)

        self.ui.spin_cols.valueChanged.connect(self._on_rows_cols_changed)
        self.ui.spin_rows.valueChanged.connect(self._on_rows_cols_changed)

        self.ui.combo_layout_mode.currentIndexChanged.connect(
            lambda: self._on_param_changed(rebuild=True)
        )
        self.ui.spin_img_h.valueChanged.connect(lambda: self._on_param_changed(rebuild=True))
        self.ui.spin_gap_v.valueChanged.connect(lambda: self._on_param_changed(rebuild=True))

        for spin in [
            self.ui.spin_txt_title,
            self.ui.spin_txt_header,
            self.ui.spin_txt_cell,
            self.ui.spin_fs_base_units,
            self.ui.spin_fs_category,
            self.ui.spin_fs_master_packing,
            self.ui.spin_fs_company,
            self.ui.spin_fs_heading,
            self.ui.spin_fs_page_num,
            self.ui.spin_fs_crm,
            self.ui.spin_fs_date,
        ]:
            spin.valueChanged.connect(lambda: self._on_param_changed(rebuild=True))

        color_inputs = [
            self.ui.input_card_bg,
            self.ui.input_border_color,
            self.ui.input_product_name_bg,
            self.ui.input_product_name_text,
            self.ui.input_base_units_bg,
            self.ui.input_base_units_text,
            self.ui.input_table_header_bg,
            self.ui.input_table_header_text,
            self.ui.input_table_cell_bg,
            self.ui.input_table_cell_text,
            self.ui.input_table_separator,
        ]
        for inp in color_inputs:
            inp.textChanged().connect(lambda: self._on_param_changed(rebuild=False))

        self.ui.spin_border_width.valueChanged.connect(lambda: self._on_param_changed(rebuild=False))
        self.ui.spin_border_radius.valueChanged.connect(lambda: self._on_param_changed(rebuild=False))

        for chk in [self.ui.chk_moq, self.ui.chk_master, self.ui.chk_footer]:
            chk.stateChanged.connect(lambda: self._on_param_changed(rebuild=True))

    def _initialize_ui_values(self):
        self.ui.spin_cols.setValue(self.cols)
        self.ui.spin_rows.setValue(self.rows)

    def showEvent(self, event):
        super().showEvent(event)
        self.build_catalog()

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        self.ui.sidebar.setVisible(self.sidebar_visible)

    # -----------------------
    # Layout params
    # -----------------------

    def get_formatting_params(self) -> dict:
        layout_text = self.ui.combo_layout_mode.currentText()
        l_mode = "stacked" if "Stacked" in layout_text else "side_by_side"

        return {
            "image_height": self.ui.spin_img_h.value(),
            "grid_gap_h": 1,
            "grid_gap_v": self.ui.spin_gap_v.value(),
            "card_internal_spacing": 5,
            "layout_mode": l_mode,
            "show_border": True,
            "footer_enabled": self.ui.chk_footer.isChecked(),
            "show_moq": self.ui.chk_moq.isChecked(),
            "show_master_packing": self.ui.chk_master.isChecked(),
            "title_font_size": self.ui.spin_txt_title.value(),
            "header_font_size": self.ui.spin_txt_header.value(),
            "cell_font_size": self.ui.spin_txt_cell.value(),
            "fs_base_units": self.ui.spin_fs_base_units.value(),
            "fs_category": self.ui.spin_fs_category.value(),
            "fs_master_packing": self.ui.spin_fs_master_packing.value(),
            "fs_company": self.ui.spin_fs_company.value(),
            "fs_heading": self.ui.spin_fs_heading.value(),
            "fs_page_num": self.ui.spin_fs_page_num.value(),
            "fs_crm": self.ui.spin_fs_crm.value(),
            "fs_date": self.ui.spin_fs_date.value(),
            "card_bg_color": self.ui.input_card_bg.text().strip(),
            "border_color": self.ui.input_border_color.text().strip(),
            "border_width": self.ui.spin_border_width.value(),
            "border_radius": self.ui.spin_border_radius.value(),
            "product_name_bg": self.ui.input_product_name_bg.text().strip(),
            "product_name_text": self.ui.input_product_name_text.text().strip(),
            "base_units_bg": self.ui.input_base_units_bg.text().strip(),
            "base_units_text": self.ui.input_base_units_text.text().strip(),
            "table_header_bg": self.ui.input_table_header_bg.text().strip(),
            "table_header_text": self.ui.input_table_header_text.text().strip(),
            "table_cell_bg": self.ui.input_table_cell_bg.text().strip(),
            "table_cell_text": self.ui.input_table_cell_text.text().strip(),
            "table_separator": self.ui.input_table_separator.text().strip(),
        }

    # -----------------------
    # Preview rendering
    # -----------------------

    def create_a4_widget(self):
        if self.current_a4_widget is not None:
            self.current_a4_widget.setParent(None)
            self.current_a4_widget.deleteLater()
            self.current_a4_widget = None

        self.current_a4_widget = A4CatalogPage()
        self.preview.set_widget(self.current_a4_widget)

    def render_current_page(self):
        if (not self.pages_data) or (self.current_page_idx >= len(self.pages_data)):
            self.ui.lbl_total.setText("/ 0")
            if self.current_a4_widget:
                self.current_a4_widget.clear_page()
            return

        data = self.pages_data[self.current_page_idx]

        # Keep spinbox for navigation only (sequential), header shows identity.
        self.ui.spin_page.blockSignals(True)
        self.ui.spin_page.setValue(self.current_page_idx + 1)
        self.ui.spin_page.blockSignals(False)

        if not self.current_a4_widget:
            return

        params = self.get_formatting_params()
        params["cols"] = data.columns
        self.current_a4_widget.update_options(**params)

        company_name = getattr(self.dashboard, "company_name_sanitized", "")
        prefix = str(company_name)[:3] if company_name else ""

        page_identity_text = f"{data.parent_sn} | {data.parent_page_no}"
        self.current_a4_widget.set_header(prefix, data.header_title, page_identity_text)

        self.current_a4_widget.set_footer_left("CRM_NAME")
        self.current_a4_widget.set_footer_date(data.page_update_str)

        self.current_a4_widget.clear_page()
        self.current_a4_widget.fill_page(data.products_placed)
        self.preview.fit_page()

    # -----------------------
    # Data loading
    # -----------------------

    def get_catalog_df(self):
        if not self.company_path:
            return None
        db = Path(self.company_path) / "company.db"
        if not db.exists():
            return None
        return load_dataframe(str(db), table_name="final_data")

    # -----------------------
    # Build catalog + CRM update
    # -----------------------

    def build_catalog(self):
        if not self.company_path:
            return

        db = Path(self.company_path) / "company.db"
        if not db.exists():
            return

        self.GRID_ROWS = self.ui.spin_rows.value()
        self.GRID_COLS = self.ui.spin_cols.value()
        self.builder.grid_rows = self.GRID_ROWS
        self.builder.grid_cols = self.GRID_COLS

        df = self.builder.load_filtered_df(self)
        if df is None:
            return

        try:
            self.dashboard.set_total_items(int(len(df)))
        except Exception:
            pass

        products = self.builder.collect_products(df)
        self.pages_data = self.builder.layout_pages(products)
        self.total_pages = len(self.pages_data)

        # identity -> index mapping
        self.identity_to_index = {
            (p.master_sn, p.parent_sn, int(p.parent_page_no)): i
            for i, p in enumerate(self.pages_data)
        }

        if not self.pages_data:
            self.ui.spin_page.setRange(0, 0)
            self.ui.lbl_total.setText("/ 0")
            return

        self.ui.spin_page.setRange(1, self.total_pages)
        self.ui.lbl_total.setText(f"/ {self.total_pages}")

        if self.current_page_idx >= len(self.pages_data):
            self.current_page_idx = len(self.pages_data) - 1

        if self.current_a4_widget is None:
            self.create_a4_widget()

        self.render_current_page()

        # Identity-based CRM diff + pending update
        new_page_map = CatalogBuilder.extract_page_map(self.pages_data)
        self._check_page_movement_and_update_crm(new_page_map)

    def _check_page_movement_and_update_crm(self, new_page_map: Dict[Any, Set[PageID]]):
        if not self.company_path:
            return

        db_path = Path(self.company_path) / "company.db"
        if not db_path.exists():
            return

        init_db(db_path)

        impacted_pages = crm_update_page_map(db_path, new_page_map)
        if impacted_pages:
            crm_mark_pages_pending(db_path, impacted_pages)

    # -----------------------
    # Rebuild triggers
    # -----------------------

    def _on_param_changed(self, rebuild: bool):
        if rebuild:
            self.build_catalog()
        else:
            if self.current_a4_widget and self.pages_data:
                self.render_current_page()

    def _on_rows_cols_changed(self):
        self._on_param_changed(rebuild=True)

    # -----------------------
    # Navigation (sequential UI only)
    # -----------------------

    def next_page(self):
        if self.current_page_idx + 1 < self.total_pages:
            self.current_page_idx += 1
            self.render_current_page()

    def prev_page(self):
        if self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.render_current_page()

    def jump_to_page(self):
        val = self.ui.spin_page.value()
        if 1 <= val <= self.total_pages:
            self.current_page_idx = val - 1
            self.render_current_page()

    # -----------------------
    # Company / CRM
    # -----------------------

    def set_company(self, company_path: Path):
        self.company_path = Path(company_path)
        db_path = self.company_path / "company.db"
        init_db(db_path)

    def load_crm_names(self) -> list[str]:
        if not self.company_path:
            return []
        db_path = Path(self.company_path) / "company.db"
        if not db_path.exists():
            return []
        try:
            init_db(db_path)
            return list_crms(db_path)
        except Exception:
            return []
