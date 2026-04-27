import sqlite3
import re
import pandas as pd # Pandas ka use comparison ke liye
import datetime
from collections import Counter

class DataProcessor:
    def __init__(self, db_path):
        self.db_path = db_path

# ============================================================================
# CHAPTER 1: CLEANING & IMAGE NAME LOGIC (No Changes Here)
# ============================================================================
    def clean_for_img(self, text):
        if not text: return ""
        
        # 1. ब्रैकेट के अंदर का हिस्सा हटाना (जैसे (1/50))
        text = re.sub(r"\(.*?\)", "", text)
        
        # यह चेक करेगा कि क्या नाम 'x' से शुरू हो रहा है और उसमें कम से कम दो '.' हैं
        temp_text = text.strip()
        if temp_text.lower().startswith('x') and temp_text.count('.') > 1:
            # शुरू का 'x' और सारे '.' हटा दें
            text = re.sub(r"^[xX]\.*", "", temp_text)

        # अगर Sink 18x24 वाला कोई भी केस है, तो उसे यहीं फिक्स कर दें
        if "sink 18x24" in text.lower():
            return "Sink 18x24"
        
        # अगर Router Bit है, तो पहले साइज हटा लेते हैं ताकि Step सुरक्षित रहे
        is_router = "router bit" in text.lower()
        if is_router:
            text = re.sub(r"\d+([\/\.\d]*)\s*(mm|[\"']{1,2})?\s*[xX×]\s*\d+([\/\.\d]*)\s*(mm|[\"']{1,2})?", "", text, flags=re.I)
            
        # 2.यह 1hp, 1.5hp, 1/2hp और 1/2 hp (स्पेस के साथ) सबको एक साथ हटा देगा
        text = re.sub(r"\d+([\/\.]\d+)?\s*hp", "", text, flags=re.I)
        
        # 3. MMA/LB के साथ चिपकी हुई संख्या हटाना (जैसे MMA200, LB50)
        text = re.sub(r"\b(mma|lb)\s*\d*", "", text, flags=re.I)

        # 4. HP और Stage का जटिल कॉम्बिनेशन
        text = re.sub(r"\d+(\.\d+)?\s*hp\s*[xX×]\s*\d+\s*stage", "", text, flags=re.I)

       
        text = re.sub(r"\b(step|stage)\s+\d+\b", "", text, flags=re.I)
        text = re.sub(r"\d+(step|stage)\b", "", text, flags=re.I)
       
        # 5. No, No., # और संख्या हटाना
        text = re.sub(r"\d+#\d*(\.\d+)?(\"|''|')*", "", text)
        text = re.sub(r"No\.\s*\d+", "", text, flags=re.I)
        
        # 6. ट्रिपल क्रॉस साइज हटाना (जैसे 3x3x4)
        text = re.sub(r"\d+(\.\d+)?\s*[xX×]\s*\d+(\.\d+)?\s*[xX×]\s*\d+(\.\d+)?", "", text)

        # 7. स्लैश वाली संख्या + क्रॉस + संख्या/इंच (जैसे 3/4x1/2, 1/4''x5/8, 3/4x10'')
        text = re.sub(r"\d+[\/\\]\d+[\"']*\s*[xX×]\s*\d+([\/\.\d]*)(\"|''|'|mm|kg|mit)*", "", text)

        # 8. सादा क्रॉस और स्लैश क्रॉस (जैसे 1x10, 1x1/2", 1x8)
        text = re.sub(r"\d+(\.\d+)?\s*[xX×]\s*\d+([\/\\]\d+)?(\"|''|'|mm|kg)*", "", text)

        # 9. इंच/फिट वाली संख्या + क्रॉस + इंच/फिट/संख्या (जैसे 1.5''x3', 3/4"x8, 16mmx8")
        text = re.sub(r"\d+([\/\.\d]*)\s*(mm|[\"']{1,2})?\s*[xX×]\s*\d+([\/\.\d]*)\s*(mm|[\"']{1,2})?", "", text, flags=re.I)

        # 10. साधारण क्रॉस (जैसे 10x12) - बैकअप सुरक्षा के लिए
        text = re.sub(r"\d+(\.\d+)?\s*[xX×]\s*\d+(\.\d+)?", "", text)
        
        # 12. स्लैश और इंच का मेल (जैसे 1/2'' या 1/2")
        text = re.sub(r"\d+[\/\\]\d+(\"|''|')", "", text)
        
        # 11. स्लैश वाली यूनिट्स (जैसे 1/2kg)
        text = re.sub(r"\d+[\/\\]\d+\s*(kg|mm|mit|gm|ltr|lb)", "", text, flags=re.I)

        # 13. साधारण स्लैश वाली संख्याएं (जैसे 1/2)
        text = re.sub(r"\d+(\.\d+)?\s*[\\/]\s*\d+(\.\d+)?", "", text)

        # 15. इंच/फिट चिह्न (", '', ') के साथ साधारण संख्या (जैसे 8", 16'')
        text = re.sub(r"\b\d+(\.\d+)?(\"|''|')", "", text)

        # 16. mmx10, mmx10'' जैसे केस (यूनिट पहले फिर क्रॉस)
        text = re.sub(r"(mm|kg|mit)\s*[xX×]\s*\d+([\/\.\d]*)(\"|''|'|mm|kg)*", "", text, flags=re.I)

        # 17. यूनिट्स के साथ संख्या (mm, mit, kg, lb आदि)
        #size_pattern = r"\d+(\.\d+)?\s*(mm|mit|gm|GMS|kg|ltr|lb)\b"
        size_pattern = r"\d+(\.\d+)?(mm|mit|gm|GMS|kg|ltr|lb)\b"
        text = re.sub(size_pattern, "", text, flags=re.I)

        # 18. अंत में अगर कोई नंबर अकेला बचा है जिसके पीछे X लगा है (जैसे 100X)
        text = re.sub(r"\d+\s*[xX×]", "", text)

        # 19. स्पेशल कैरेक्टर्स हटाना
        text = re.sub(r'[\\/*?:"<>|]', '', text)

        # 20. सफाई: डबल स्पेस को सिंगल करना
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        text = re.sub(r'[.,\s]+$', '', text)
        
        return text.strip()

# ============================================================================
# CHAPTER 2: PRODUCT NAME & SIZE EXTRACTION LOGIC
# ============================================================================
    def looks_like_size(self, part):
        part = str(part).strip()
        if "मसिन" in part or "मसीन" in part:
            return False
        
        # --- No.1 और MMA200 को पहचानने के लिए ---
        if re.search(r'^(no\.?\s*\d+|mma\d+|\d+mma)$', part, flags=re.I):
            return True
        
        # --- mm के लिए विशेष शर्त: संख्या के तुरंत बाद mm होना चाहिए (बिना स्पेस के) ---
        if re.search(r'\d+mm$', part, flags=re.I):
            return True
        
        # --- नया नियम: HPx और स्टेज वाले पैटर्न के लिए (जैसे 2HPx20) ---
        if re.search(r'\d+\s*hpx\d+', part, flags=re.I):
            return True
        
        # 1. यूनिट्स के साथ साइज
        unit_pattern = r"((mma)?\d+([\/\.\d]*)\s*(mma|cm|#|mtr|लि\.|मी\.|स्टेप|मिटर|ली\.|['\"]{1,2}|gm|gms|ml|kg|kg.|pcs|no\.?|nos?|mit|ltr|lb|hp|स्टेज))$"
        if re.search(unit_pattern, part, flags=re.I):
            return True
            
        # 2. क्रॉस वाले साइज: AxB या AxBxC
        if re.search(r"\d+([\/\.\d]*)\s*[xX×]\s*\d+([\/\.\d]*)", part):
            return True
        
        # 3. स्लैश या डॉट वाले साइज
        if re.fullmatch(r"\d+([\/]\d+)+['\"]*", part) or ('.' in part and re.fullmatch(r"\d+\.\d+['\"]*", part)):
            return True    
        return False

    def extract_product_details(self, full_name):
        if not full_name: return "", ""
        
        # ओरिजिनल नाम
        original_name = str(full_name).strip()
        search_text = original_name.replace("(", " ").replace(")", " ")
        search_text = re.sub(r'\s+', ' ', search_text).strip()

        p_name = original_name 
        p_size = ""
        
        # --- 1. विशेष नियम: जिब्रि वेट ---
        if "जिब्रि वेट" in original_name:
            p_name = "जिब्रि वेट"
            p_size = original_name.replace("जिब्रि वेट", "").strip()
            return self.finalize_details(p_name, p_size)
        
        # हम यहाँ सिर्फ इन्ही तीन शब्दों को चेक कर रहे हैं ताकि बाकी पलेन्जर आइटम न बिगड़ें
        for palenjer_item in ["पलेन्जर (मीडियम)", "पलेन्जर (हेवी)", "पलेन्जर (लाईट)"]:
            if palenjer_item in original_name:
                p_name = "पलेन्जर"
                p_size = original_name.replace("पलेन्जर", "").strip()
                return self.finalize_details(p_name, p_size)
            
        # --- 3. बेड जोइन्ट के लिए सटीक मैच (Specific Check) ---
        for bed_item in ["बेड जोइन्ट (हेवी)", "बेड जोइन्ट (लाईट)", "बेड जोइन्ट (एक्स्ट्रा हेवी)"]:
            if bed_item in original_name:
                p_name = "बेड जोइन्ट"
                p_size = original_name.replace("बेड जोइन्ट", "").strip()
                return self.finalize_details(p_name, p_size)
                
        # --- 4. बिजली टेप कलर फिल्टर ---
        if "बिजली टेप" in search_text:
            colors = ["Yellow", "Red", "Green", "Blue", "Black", "White"]
            for color in colors:
                if re.search(rf"\b{color}\b", search_text, flags=re.I):
                    p_size = color
                    p_name = re.sub(rf"\b{color}\b", "", original_name, flags=re.I)
                    return self.finalize_details(p_name, p_size)
        
        # --- 5. कार्बन प्रीफिक्स चेक ---
        carbon_prefixes = ["शार्प कार्बन", "LL-कार्बन", "कार्बन"]
        for prefix in carbon_prefixes:
            if search_text.startswith(prefix):
                p_name = prefix
                p_size = search_text[len(prefix):].strip()
                return self.finalize_details(p_name, p_size)

        # --- सामान्य साइज लॉजिक ---
        tokens = re.split(r"\s+", search_text)
        found_size = ""
        
        for i in range(len(tokens) - 1, -1, -1):
            t = tokens[i]
            
            # सुधार: यदि "स्टेज" शब्द मिलता है
            if t.lower() == "स्टेज" and i > 0:
                prev_t = tokens[i-1]
                # चेक करें कि क्या पिछला शब्द HPx वाला साइज है (जैसे 2HPx20)
                if self.looks_like_size(prev_t):
                    found_size = f"{prev_t} {t}"
                    break
                # यदि पिछला शब्द सिर्फ नंबर है (जैसे 20 स्टेज)
                elif re.match(r"^\d+$", prev_t):
                    found_size = f"{prev_t} {t}"
                    break
                
            if self.looks_like_size(t):
                found_size = t
                break
            
            # mm के लिए नियम
            if i > 0 and t.lower() == "mm": continue
            
            # बाकी यूनिट्स (मी., kg आदि) के लिए पुराना स्पेस वाला लॉजिक जारी रहेगा
            if i > 0 and t.lower() in ["मी.", "मिटर", "mtr", "mma", "kg", "hp"]:
                if re.match(r"^\d+([\/\.\d]*)$", tokens[i-1]):
                    found_size = f"{tokens[i-1]} {t}"
                    break
            
        if found_size:
            p_size = found_size
            escaped_size = re.escape(found_size)
            bracket_pattern = rf"\(\s*{escaped_size}\s*\)"
            if re.search(bracket_pattern, original_name, flags=re.I):
                p_name = re.sub(bracket_pattern, "", original_name, flags=re.I)
            else:
                # --- सुधार 2: replace का उपयोग (इंच और No.1 के लिए बेहतर है) ---
                p_name = original_name.replace(found_size, "")
        else:
            p_name = original_name

        return self.finalize_details(p_name, p_size)

    def finalize_details(self, p_name, p_size):
        if p_size:
            for word in ["मसिन", "मसीन"]:
                p_size = p_size.replace(word, "")
            p_size = p_size.replace("मिटर", "मी.")
            if "मी." in p_size:
                p_size = re.sub(r'(\d+)\s+(मी\.)', r'\1\2', p_size)
            p_size = p_size.strip().strip("()").strip()

        p_name = re.sub(r' +', ' ', p_name).strip()
        p_name = p_name.replace("()", "").strip() # खाली ब्रैकेट हटाना
        while p_name.endswith("-"):
            p_name = p_name[:-1].strip()
        return p_name, p_size

# ============================================================================
# MAIN PROCESSING UNIT
# ============================================================================
    def process_and_save_final_data(self):
        try:
            now_time = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Sabse pehle processing ke liye data uthayein
            cursor.execute('SELECT rowid, Alias, Unit, Item_Name, "Product Name", Product_Size FROM catalog ORDER BY MG_SN ASC, SG_SN ASC, rowid ASC')
            rows = cursor.fetchall()
            
            row_data_list = []
            base_names_for_counting = []
            suffix_tracker = {} 

            # --- स्टेप 1: डेटा कलेक्ट करना और सफ़िक्स ग्रुपिंग ---
            for row_id, alias, unit, item_name, p_name_db, p_size_db in rows:
                safe_alias = alias if alias else ""
                original_text = safe_alias if safe_alias.strip() else item_name
                
                p_name, p_size = self.extract_product_details(item_name)
                base_name = self.clean_for_img(original_text)
                
                pattern = r"\s+(light|hevi|medium|extra\s+hevi)$"
                match = re.search(pattern, base_name, flags=re.I)
                
                core_name = base_name
                suffix = ""
                if match:
                    core_name = re.sub(pattern, "", base_name, flags=re.I).strip()
                    suffix = match.group(1).lower().strip()

                # ग्रुपिंग ट्रैक करें (ताकि पता चले 2 अलग कंडीशन हैं या नहीं)
                if core_name not in suffix_tracker:
                    suffix_tracker[core_name] = set()
                if suffix:
                    suffix_tracker[core_name].add(suffix)
                
                # डेटा कलेक्ट करना
                row_data_list.append({
                    'row_id': row_id,
                    'alias': safe_alias,
                    'unit': unit.strip() if unit else "",
                    'base_name': base_name,
                    'product_name': p_name,
                    'product_size': p_size,
                    'core_name': core_name,
                    'suffix': suffix,
                    'original_text': original_text
                })
                
                if base_name:
                    base_names_for_counting.append(base_name.lower().replace(" ", ""))

            counts = Counter(base_names_for_counting)

            # --- स्टेप 2: MOQ, Packing और Image Name लॉजिक ---
            for info in row_data_list:
                moq = None
                m_packing = None
                
                # A. MOQ & Packing Logic
                if info['alias'].strip():
                    matches = re.findall(r'\(([^)]+)\)', info['alias'])
                    if matches:
                        last_val = matches[-1].strip()
                        clean_val = last_val.lower().replace(' ', '')
                        # exception
                        if '1/2doz' in clean_val:
                            moq = f"1/2 {info['unit']}".strip()
                        else:
                            if '/' in last_val or '\\' in last_val:
                                parts = re.split(r'[/\\]', last_val)
                                raw_moq = parts[0].strip()
                                raw_packing = parts[1].strip() if len(parts) > 1 else ""
                            else:
                                raw_moq = last_val
                                raw_packing = ""

                            moq_digits = re.sub(r'\D', '', raw_moq)
                            if moq_digits:
                                moq = f"{moq_digits} {info['unit']}".strip()
                            packing_digits = re.sub(r'\D', '', raw_packing)
                            if packing_digits:
                                m_packing = f"{packing_digits} {info['unit']}".strip()

                # B. Image Name Logic (Light/Hevi कंडीशन)
                alias_clean = info['alias'].lower().strip()
                base_name_val = info['base_name']
                base_name_lower = base_name_val.lower()
                
                # 1. NEW: Sink Bypass Condition
                if "sink 18x24" in base_name_lower:
                    image_name_val = "Sink 18x24"
                elif "router bit" in base_name_lower:
                    image_name_val = base_name_val # "Router Bit 2 Step" सुरक्षित रहेगा    
                
                # 2. Priority: Carban Conditions
                elif alias_clean.startswith("ll carban"):
                    image_name_val = "LL Carban"
                elif alias_clean.startswith("sharp carban"):
                    image_name_val = "Sharp Carban"
                elif alias_clean.startswith("carban"):
                    image_name_val = "Carban"
                
                # 3. Bijli Tape Color Condition
                elif "bijli tape" in base_name_lower:
                    color_pattern = r"\s+(black|blue|green|red|yellow)\b"
                    image_name_val = re.sub(color_pattern, "", info['base_name'], flags=re.I).strip()
                    
                else:
                    # 4. Light/Hevi (2 or more condition rule)
                    core = info['core_name']
                    if len(suffix_tracker.get(core, set())) >= 2:
                        image_name_val = core
                    else:
                        # 5. Repeated/Normal Base Name
                        norm_base = info['base_name'].lower().replace(" ", "")
                        if norm_base and counts[norm_base] > 1:
                            image_name_val = info['base_name']
                        else:
                            image_name_val = info['base_name'] if info['base_name'] else info['original_text']

                # 1. Pehle DB se purani values mangwayein
                cursor.execute('SELECT "Product Name", Product_Size, Image_Name, MOQ, M_Packing FROM catalog WHERE rowid = ?', (info['row_id'],))
                old_row = cursor.fetchone()

                # 2. Nayi values jo processor ne nikali hain
                # Note: str() mein wrap kiya hai taaki None vs "" ka issue na aaye comparison mein
                new_v = (str(info['product_name']), str(info['product_size']), str(image_name_val), str(moq), str(m_packing))
                
                # 3. Purani values jo DB mein pehle se hain
                old_v = (str(old_row[0]), str(old_row[1]), str(old_row[2]), str(old_row[3]), str(old_row[4])) if old_row else None

                # 4. AGAR DATA BADLA HAI, SIRF TABHI UPDATE KAREIN
                if new_v != old_v:
                    cursor.execute("""
                        UPDATE catalog 
                        SET "Product Name" = ?, 
                            "Product_Size" = ?, 
                            "Image_Name" = ?, 
                            "MOQ" = ?, 
                            "M_Packing" = ?
                        WHERE rowid = ?
                    """, (info['product_name'], info['product_size'], image_name_val, moq, m_packing, info['row_id']))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Processor Error: {e}")
            return False
    
    def smart_db_sync(self, new_data_list):
        """
        new_data_list: Wo data jo Tally ya syncing se naya aaya hai (List of Dictionaries)
        """
        conn = sqlite3.connect(self.db_path)
        
        # 1. DB se purana data read karein
        try:
            df_old = pd.read_sql_query("SELECT * FROM catalog", conn)
        except:
            df_old = pd.DataFrame() # Agar table khali hai

        # 2. Naye data ka DataFrame banayein
        df_new = pd.DataFrame(new_data_list)

        if df_old.empty:
            # Agar DB khali hai toh pura data insert karein aur aaj ki date daalein
            df_new['Update_date'] = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            df_new.to_sql('catalog', conn, if_exists='replace', index=False)
        else:
            # 3. Dono ko GUID par merge karein (Comparison ke liye)
            # Hum check karenge ki kya koi bhi column badla hai
            # Hum Update_date ko comparison se bahar rakhenge
            cols_to_compare = [c for c in df_new.columns if c != 'Update_date']
            
            for index, row_new in df_new.iterrows():
                guid = row_new['GUID']
                
                # Purani row dhundein
                row_old = df_old[df_old['GUID'] == guid]
                
                if row_old.empty:
                    # Naya Item hai -> Insert
                    row_new['Update_date'] = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                    # SQL Insert Logic...
                else:
                    # Purana Item hai -> Compare karein
                    # Hum sirf un columns ko dekh rahe hain jo important hain
                    changed = False
                    for col in cols_to_compare:
                        if str(row_new[col]) != str(row_old.iloc[0][col]):
                            changed = True
                            break
                    
                    if changed:
                        # Sirf tabhi update karein jab kuch badla ho
                        now_time = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                        # SQL Update query with current now_time...
                    else:
                        # Kuch nahi badla -> Do nothing (Date purani hi rahegi)
                        pass
        
        conn.close()
    
    def generate_complex_ids(self):
        """Generate deterministic IDs encoding the full product hierarchy.
        
        Format: {MG}_{SG}_{cluster}_{item}_{variant}
        Example: 03_15_01_02_03 = MG 03, SG 15, fuzzy cluster 01, item 02, variant 03
        
        Hierarchy:
          - MG/SG: Master Group / Sub Group from super_master
          - cluster: Fuzzy similarity cluster (via cluster_products)
          - item: Unique product name within the cluster
          - variant: Size/price variant within that product name
        """
        from src.logic.text_utils import cluster_products, normalize_name
        
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('UPDATE catalog SET ID = NULL')
            cursor.execute(
                'SELECT rowid, "Product Name", MG_SN, SG_SN, MRP, Product_Size '
                'FROM catalog ORDER BY MG_SN, SG_SN, rowid ASC'
            )
            rows = cursor.fetchall()
            
            # Group by (MG_SN, SG_SN)
            combined_groups = {}
            for r in rows:
                mg = str(r["MG_SN"]).strip() if r["MG_SN"] else "00"
                sg = str(r["SG_SN"]).strip() if r["SG_SN"] else "00"
                key = f"{mg}-{sg}"
                if key not in combined_groups:
                    combined_groups[key] = []
                combined_groups[key].append(dict(r))
            
            for key, items in combined_groups.items():
                mg_sn, sg_sn = key.split('-')
                
                def get_name(x):
                    return str(x.get("Product Name", "")).strip()
                def get_price(x):
                    try:
                        return float(str(x.get("MRP", "0")).replace(",", "").strip())
                    except:
                        return 999999.0
                
                # Fuzzy cluster
                clusters = cluster_products(items, get_name_fn=get_name, get_price_fn=get_price)
                
                for ci, cluster in enumerate(clusters, start=1):
                    # Sort cluster by (name, price)
                    cluster.sort(key=lambda x: (normalize_name(get_name(x)), get_price(x)))
                    
                    # Sub-group by exact normalized product name
                    item_groups = {}
                    item_order = []
                    for row in cluster:
                        nname = normalize_name(get_name(row))
                        if nname not in item_groups:
                            item_groups[nname] = []
                            item_order.append(nname)
                        item_groups[nname].append(row)
                    
                    for ii, nname in enumerate(item_order, start=1):
                        variants = item_groups[nname]
                        # Variants are already sorted by price from the cluster sort
                        for vi, item in enumerate(variants, start=1):
                            final_id = f"{mg_sn}_{sg_sn}_{ci:02d}_{ii:02d}_{vi:02d}"
                            cursor.execute(
                                "UPDATE catalog SET ID = ? WHERE rowid = ?",
                                (final_id, item["rowid"])
                            )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error generating IDs: {e}")
            return False
        
    def get_display_data(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM catalog")
            data = cursor.fetchall()
            conn.close()
            return data
        except:
            return []