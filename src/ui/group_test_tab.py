from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea, QFrame, QCheckBox, QComboBox, QMessageBox,
    QProgressBar, QApplication, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QPixmap, QFont, QColor
import os
import sqlite3
from src.logic.text_utils import clean_cat_name, is_similar, cluster_products


class GroupPreviewWorker(QThread):
    """Background worker for loading and clustering products.
    Runs DB queries and clustering off the main thread."""
    progress_update = pyqtSignal(int, int, str)  # (current, total, status_text)
    data_ready = pyqtSignal(list)  # List of {group_name, sg_sn, items, clusters}
    finished_signal = pyqtSignal(str)  # Final status message
    
    def __init__(self, logic, company_path):
        super().__init__()
        self.logic = logic
        self.company_path = company_path
    
    def run(self):
        try:
            catalog_db = os.path.join(self.company_path, "catalog.db")
            if not os.path.exists(catalog_db):
                self.finished_signal.emit("Catalog DB not found.")
                return
            
            conn = sqlite3.connect(catalog_db)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT group_name, sg_sn FROM catalog_pages ORDER BY group_name, CAST(sg_sn AS INTEGER)")
            subgroups = cursor.fetchall()
            conn.close()
            
            total_groups = len(subgroups)
            if total_groups == 0:
                self.finished_signal.emit("No subgroups found.")
                return
            
            all_results = []
            
            for i, (group_name, sg_sn) in enumerate(subgroups):
                self.progress_update.emit(i + 1, total_groups, f"Processing {group_name} > {sg_sn}...")
                
                # Heavy work: DB fetch + clustering
                items = self.logic.get_sorted_products_from_db(group_name, sg_sn)
                clusters = cluster_products(items)
                
                all_results.append({
                    "group_name": group_name,
                    "sg_sn": sg_sn,
                    "items": items,
                    "clusters": clusters
                })
            
            # Emit all data at once for main thread to render
            self.data_ready.emit(all_results)
            self.finished_signal.emit(f"Loaded successfully. Subgroups: {total_groups}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_signal.emit(f"Error: {str(e)}")


class ProductCardRow(QFrame):
    def __init__(self, product_data, page_info):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ProductCardRow {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin-bottom: 4px;
            }
            ProductCardRow:hover {
                border: 1px solid #3498db;
                background-color: #f8fbff;
            }
        """)
        self.setFixedHeight(100)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # 1. Image Preview
        self.img_lbl = QLabel()
        self.img_lbl.setFixedSize(90, 90)
        self.img_lbl.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ddd;")
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setScaledContents(True)
        
        img_path = product_data.get("image_path", "")
        if img_path and os.path.exists(img_path):
            pix = QPixmap(img_path)
            if not pix.isNull():
                 self.img_lbl.setPixmap(pix)
            else:
                self.img_lbl.setText("Invalid\nImage")
        else:
             self.img_lbl.setText("No\nImage")
             
        layout.addWidget(self.img_lbl)
        
        # 2. Details
        details_layout = QVBoxLayout()
        details_layout.setSpacing(2)
        
        # Name
        self.product_name = product_data.get("product_name", "Unknown")
        lbl_name = QLabel(self.product_name)
        lbl_name.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        details_layout.addWidget(lbl_name)
        
        # Group / Subgroup
        grp = f"{page_info.get('group_name', '')} > {page_info.get('sg_sn', '')}"
        lbl_grp = QLabel(grp)
        lbl_grp.setStyleSheet("color: #666; font-size: 10px;")
        details_layout.addWidget(lbl_grp)
        
        # Size & Price
        sizes = product_data.get("sizes", [])
        
        # Handle MRP (List or String)
        mrps = product_data.get("mrps", [])
        if not mrps:
            # Fallback to single 'mrp' key if exists
            single_mrp = product_data.get("mrp", "")
            mrp_str = str(single_mrp) if single_mrp else "N/A"
        else:
            # Join unique MRPs if multiple
            unique_mrps = sorted(list(set([str(m) for m in mrps if m])))
            mrp_str = ", ".join(unique_mrps) if unique_mrps else "N/A"
        
        info_str = f"Sizes: {len(sizes)} | MRP: {mrp_str}"
        lbl_info = QLabel(info_str)
        lbl_info.setStyleSheet("color: #333; font-size: 11px;")
        details_layout.addWidget(lbl_info)
        
        details_layout.addStretch()
        layout.addLayout(details_layout, 1)
        
        # 3. Page Info (Right Side)
        page_layout = QVBoxLayout()
        page_lbl = QLabel(f"Page: {page_info.get('page_no', 0)}")
        page_lbl.setStyleSheet("font-weight: bold; color: #2980b9;")
        page_layout.addWidget(page_lbl, 0, Qt.AlignmentFlag.AlignRight)
        
        # Visual Order
        order_lbl = QLabel(f"Pos: {product_data.get('row')},{product_data.get('col')}")
        order_lbl.setStyleSheet("color: #888; font-size: 10px;")
        page_layout.addWidget(order_lbl, 0, Qt.AlignmentFlag.AlignRight)
        
        page_layout.addStretch()
        layout.addLayout(page_layout)


class GroupTestTab(QWidget):
    def __init__(self):
        super().__init__()
        self.company_path = None
        self.logic = None
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Top Controls
        top_bar = QHBoxLayout()
        
        self.btn_load = QPushButton("🔄 Load Preview")
        self.btn_load.clicked.connect(self.load_data)
        self.btn_load.setFixedHeight(30)
        top_bar.addWidget(self.btn_load)
        
        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search products...")
        self.search_input.setFixedHeight(30)
        self.search_input.setFixedWidth(200)
        self.search_input.textChanged.connect(self.filter_items)
        top_bar.addWidget(self.search_input)
        
        self.lbl_status = QLabel("Ready")
        top_bar.addWidget(self.lbl_status)
        
        top_bar.addStretch()
        layout.addLayout(top_bar)
        
        # Content Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: #f5f5f5;")
        
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setSpacing(5)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)
        
        # Progress Bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

    def filter_items(self, text):
        text = text.lower().strip()
        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, ProductCardRow):
                if text in widget.product_name.lower():
                    widget.show()
                else:
                    widget.hide()

    def set_logic(self, logic, company_path):
        self.logic = logic
        self.company_path = company_path

    def load_data(self):
        if not self.logic or not self.company_path:
            QMessageBox.warning(self, "Error", "Company not loaded.")
            return
        
        # Prevent double-loads
        if hasattr(self, '_load_worker') and self._load_worker and self._load_worker.isRunning():
            return
        
        self.clear_list()
        self.btn_load.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_status.setText("Fetching pages...")
        
        # Create and start worker thread
        self._load_worker = GroupPreviewWorker(self.logic, self.company_path)
        self._load_worker.progress_update.connect(self._on_load_progress)
        self._load_worker.data_ready.connect(self._on_data_ready)
        self._load_worker.finished_signal.connect(self._on_load_finished)
        self._load_worker.start()
    
    def _on_load_progress(self, current, total, status_text):
        """Handle progress updates from the worker."""
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.lbl_status.setText(status_text)
    
    def _on_data_ready(self, all_results):
        """Render the processed data into widgets (runs on main thread)."""
        for result in all_results:
            group_name = result["group_name"]
            sg_sn = result["sg_sn"]
            items = result["items"]
            clusters = result["clusters"]
            
            # Add Header
            header_lbl = QLabel(f"\U0001f4c2 {group_name} > {sg_sn} ({len(items)} items)")
            header_lbl.setStyleSheet("background: #555; color: white; font-weight: bold; padding: 5px; margin-top: 10px;")
            self.container_layout.addWidget(header_lbl)

            for c_idx, cluster in enumerate(clusters):
                if not cluster: continue
                
                # Visual Separator
                cluster_rep = cluster[0].get("product_name", "Unknown")
                min_p = cluster[0].get("sort_price", 0)
                
                c_header = QLabel(f"   \U0001f539 Group {c_idx+1}: ~ {cluster_rep} (Starts \u20b9{min_p})")
                c_header.setStyleSheet("color: #2c3e50; font-weight: bold; font-style: italic; margin-top: 5px;")
                self.container_layout.addWidget(c_header)
                
                for item in cluster:
                    page_info = {
                        "group_name": group_name,
                        "sg_sn": sg_sn,
                        "page_no": "-"
                    }
                    
                    card = ProductCardRow(item, page_info)
                    bg_col = "#ffffff" if c_idx % 2 == 0 else "#f9f9f9"
                    card.setStyleSheet(f"""
                        ProductCardRow {{
                            background-color: {bg_col};
                            border: 1px solid #e0e0e0;
                            border-radius: 6px;
                            margin-bottom: 2px;
                            margin-left: 20px;
                        }}
                        ProductCardRow:hover {{
                            border: 1px solid #3498db;
                            background-color: #eaf2f8;
                        }}
                    """)
                    self.container_layout.addWidget(card)
    
    def _on_load_finished(self, msg):
        """Handle load completion."""
        self.loading_finished(msg)
        self._load_worker = None

    def loading_finished(self, msg):
        self.lbl_status.setText(msg)
        self.progress.setVisible(False)
        self.btn_load.setEnabled(True)

    def clear_list(self):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
