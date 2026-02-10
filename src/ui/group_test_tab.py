from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea, QFrame, QCheckBox, QComboBox, QMessageBox,
    QProgressBar, QApplication, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QFont, QColor
import os
import sqlite3

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
            
        self.clear_list()
        self.btn_load.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_status.setText("Fetching pages...")
        
        # Use QTimer to allow UI update start
        QTimer.singleShot(100, self._load_process)

    def _load_process(self):
        try:
            # 1. Get distinct Subgroups (Group, SG_SN)
            catalog_db = os.path.join(self.company_path, "catalog.db")
            if not os.path.exists(catalog_db):
                self.loading_finished("Catalog DB not found.")
                return

            conn = sqlite3.connect(catalog_db)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT group_name, sg_sn FROM catalog_pages ORDER BY group_name, CAST(sg_sn AS INTEGER)")
            subgroups = cursor.fetchall()
            conn.close()
            
            total_groups = len(subgroups)
            if total_groups == 0:
                self.loading_finished("No subgroups found.")
                return
            
            self.lbl_status.setText(f"Found {total_groups} subgroups. Processing...")
            self.progress.setMaximum(total_groups)
            
            # 2. Iterate and fetch items per subgroup
            for i, (group_name, sg_sn) in enumerate(subgroups):
                # Fetch raw products (pre-sorted by price in logic, but we will re-sort)
                items = self.logic.get_sorted_products_from_db(group_name, sg_sn)
                
                # --- SORTING LOGIC ---
                # "Bracket Sanitization + Long Word Heuristic"
                # 1. Cleaning: Remove (…) and […] content aggressively to unify variants.
                # 2. Matching:
                #    A. High Fuzzy Score (>85%) -> Same Group
                #    B. Shared LONG Word (>5 chars) -> Same Group (Catch "Chainsaw")
                
                import re
                from difflib import SequenceMatcher

                def clean_cat_name(n):
                    n = n.lower()
                    n = re.sub(r'chain\s*saw', 'chainsaw', n)
                    # Remove content in brackets
                    n = re.sub(r'\(.*?\)', '', n) 
                    n = re.sub(r'\[.*?\]', '', n)
                    # Remove digits
                    n = re.sub(r'\d+', '', n)
                    # Remove punctuation
                    n = re.sub(r'[^\w\s]', ' ', n)
                    return " ".join(n.split())

                def has_long_common_word(n1, n2, min_len=5):
                    # Exclude common weak words from this "magic link" check
                    COMMON_IGNORE = {'black', 'white', 'heavy', 'super', 'power', 'auto', 'manual'}
                    w1 = set(n1.split())
                    w2 = set(n2.split())
                    common = w1.intersection(w2)
                    for w in common:
                        if len(w) >= min_len and w not in COMMON_IGNORE:
                            return True
                    return False

                def is_similar(clean_a, clean_b):
                    if not clean_a or not clean_b: return False
                    
                    # 1. Exact Match (after cleaning) - Fast path for bracket variants
                    if clean_a == clean_b: return True
                    
                    # 2. Long Common Word (The "Chainsaw" Rule)
                    # Use length > 5 to catch "Chainsaw" (8), "Hammer" (6), "Driver" (6)
                    # But avoid "Cock" (4), "Sink" (4), "Bib" (3)
                    if has_long_common_word(clean_a, clean_b, min_len=5):
                        return True
                        
                    # 3. High Fuzzy Match (Fallback for typos/small diffs)
                    # 85% is strict enough to separate "Sink Cock" from "Bib Cock"
                    # "pvc sink cock" vs "pvc bib cock" -> ratio ~ 70-75% -> Fails (Correct)
                    ratio = SequenceMatcher(None, clean_a, clean_b).ratio()
                    return ratio >= 0.85

                clusters = [] # List of lists
                
                for item in items:
                    name = item.get("product_name", "")
                    clean_n = clean_cat_name(name)
                    
                    added = False
                    for cluster in clusters:
                        # Compare with representative
                        rep_name = cluster[0].get("product_name", "")
                        rep_clean = clean_cat_name(rep_name)
                        
                        if is_similar(clean_n, rep_clean):
                            cluster.append(item)
                            added = True
                            break
                    
                    if not added:
                        clusters.append([item])
                
                # Sort Items WITHIN Clusters by Price (ASC)
                for cluster in clusters:
                    cluster.sort(key=lambda x: x.get("sort_price", 0))

                # Sort Clusters Themselves by the MIN Price of their content
                # (Cheapest group appears first)
                clusters.sort(key=lambda c: (c[0].get("sort_price", 0) if c else 0))
                
                # Display Logic
                # Add Header
                header_lbl = QLabel(f"📂 {group_name} > {sg_sn} ({len(items)} items)")
                header_lbl.setStyleSheet("background: #555; color: white; font-weight: bold; padding: 5px; margin-top: 10px;")
                self.container_layout.addWidget(header_lbl)

                for c_idx, cluster in enumerate(clusters):
                    if not cluster: continue
                    
                    # Visual Separator
                    cluster_rep = cluster[0].get("product_name", "Unknown")
                    min_p = cluster[0].get("sort_price", 0)
                    
                    c_header = QLabel(f"   🔹 Group {c_idx+1}: ~ {cluster_rep} (Starts ₹{min_p})")
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
                
                self.progress.setValue(i + 1)
                QApplication.processEvents() # Keep UI responsive
            
            self.loading_finished(f"Loaded successfully. Subgroups: {total_groups}")
            
        except Exception as e:
            self.loading_finished(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()

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
