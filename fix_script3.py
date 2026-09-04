import os

path = 'src/logic/data_transfer.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add MISSING_TABLE_PKS if not there
if "MISSING_TABLE_PKS =" not in text:
    pks_def = """logger = get_logger(__name__)

# Map of tables to their primary key columns for reconstruction
MISSING_TABLE_PKS = {
    "payment_sheet_data": "id",
    "supplier_records": "id",
    "supplier_accounts": "id",
    "anil_ledger": "id",
    "anil_settings": "[key]",
    "tp_sections": "id",
    "tp_section_cols": "id",
    "tp_section_data": None,
    "godown": "id",
    "cheques": "id"
}"""
    text = text.replace("logger = get_logger(__name__)", pks_def)


# 2. Fix _merge_catalog_bundle
old_catalog = '''        cursor.execute(
            f"SELECT COUNT(*) FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        if cursor.fetchone()[0] == 0:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue'''
new_catalog = '''        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)'''
text = text.replace(old_catalog, new_catalog)

old_catalog_insert1 = '''        if not live_exists:
            # Create and populate missing table
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[dbo].[{tbl_b}]")
            logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")
            continue'''
new_catalog_insert1 = '''        if not live_exists:
            # Create and populate missing table
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")
            logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")

            pk_col = MISSING_TABLE_PKS.get(table)
            if pk_col:
                try:
                    cursor.execute(f"ALTER TABLE [{live_b}].[dbo].[{tbl_b}] ADD PRIMARY KEY ({pk_col})")
                    logger.info(f"[SelectiveRestore] Reconstructed Primary Key on '{table}' ({pk_col}).")
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Failed to reconstruct PK on '{table}': {e}")
            continue'''
text = text.replace(old_catalog_insert1, new_catalog_insert1)

old_catalog_insert2 = '''        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[dbo].[{tbl_b}]"
        )'''
new_catalog_insert2 = '''        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}]"
        )'''
text = text.replace(old_catalog_insert2, new_catalog_insert2)


# 3. Fix _merge_supp_payment
old_supp = '''        cursor.execute(
            f"SELECT COUNT(*) FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        if cursor.fetchone()[0] == 0:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue'''
new_supp = '''        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)'''
text = text.replace(old_supp, new_supp)

old_supp_insert1 = '''        if not live_exists:
            if table == "payment_sheet_data" and sheet_filter is not None:
                safe_keys = [k.replace("'", "''") for k in sheet_filter]
                keys_str = ", ".join(f"'{k}'" for k in safe_keys)
                if not keys_str:
                    keys_str = "''"  # Fallback if empty list (though shouldn't happen)
                cursor.execute(
                    f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[dbo].[{tbl_b}] "
                    f"WHERE sheet_key IN ({keys_str})"
                )
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' with {len(sheet_filter)} sheets.")
            else:
                cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[dbo].[{tbl_b}]")
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")
            continue'''
new_supp_insert1 = '''        if not live_exists:
            if table == "payment_sheet_data" and sheet_filter is not None:
                safe_keys = [k.replace("'", "''") for k in sheet_filter]
                keys_str = ", ".join(f"'{k}'" for k in safe_keys)
                if not keys_str:
                    keys_str = "''"  # Fallback if empty list (though shouldn't happen)
                cursor.execute(
                    f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}] "
                    f"WHERE sheet_key IN ({keys_str})"
                )
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' with {len(sheet_filter)} sheets.")
            else:
                cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")
            
            pk_col = MISSING_TABLE_PKS.get(table)
            if pk_col:
                try:
                    cursor.execute(f"ALTER TABLE [{live_b}].[dbo].[{tbl_b}] ADD PRIMARY KEY ({pk_col})")
                    logger.info(f"[SelectiveRestore] Reconstructed Primary Key on '{table}' ({pk_col}).")
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Failed to reconstruct PK on '{table}': {e}")
            continue'''
text = text.replace(old_supp_insert1, new_supp_insert1)

old_supp_insert2 = '''                cursor.execute(
                    f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                    f"SELECT {col_list} FROM [{temp_b}].[dbo].[{tbl_b}] "
                    f"WHERE sheet_key = '{safe_key}'"
                )'''
new_supp_insert2 = '''                cursor.execute(
                    f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                    f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}] "
                    f"WHERE sheet_key = '{safe_key}'"
                )'''
text = text.replace(old_supp_insert2, new_supp_insert2)

old_supp_insert3 = '''            cursor.execute(
                f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                f"SELECT {col_list} FROM [{temp_b}].[dbo].[{tbl_b}]"
            )'''
new_supp_insert3 = '''            cursor.execute(
                f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}]"
            )'''
text = text.replace(old_supp_insert3, new_supp_insert3)


# 4. Fix _merge_simple_module
old_simple = '''        cursor.execute(
            f"SELECT COUNT(*) FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        if cursor.fetchone()[0] == 0:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue'''
new_simple = '''        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)'''
text = text.replace(old_simple, new_simple)

old_simple_insert1 = '''        if not live_exists:
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[dbo].[{tbl_b}]")
            logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")
            continue'''
new_simple_insert1 = '''        if not live_exists:
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")
            logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")

            pk_col = MISSING_TABLE_PKS.get(table)
            if pk_col:
                try:
                    cursor.execute(f"ALTER TABLE [{live_b}].[dbo].[{tbl_b}] ADD PRIMARY KEY ({pk_col})")
                    logger.info(f"[SelectiveRestore] Reconstructed Primary Key on '{table}' ({pk_col}).")
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Failed to reconstruct PK on '{table}': {e}")
            continue'''
text = text.replace(old_simple_insert1, new_simple_insert1)

old_simple_insert2 = '''        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[dbo].[{tbl_b}]"
        )'''
new_simple_insert2 = '''        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}]"
        )'''
text = text.replace(old_simple_insert2, new_simple_insert2)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("done")
