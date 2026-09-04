import os
path = 'src/logic/data_transfer.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# For _merge_catalog_bundle
text = text.replace(
'''        cursor.execute(
            f"SELECT COUNT(*) FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        if cursor.fetchone()[0] == 0:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue''',
'''        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)''')

text = text.replace(
'''        if not live_exists:
            # Create and populate missing table
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[dbo].[{tbl_b}]")''',
'''        if not live_exists:
            # Create and populate missing table
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")''')

text = text.replace(
'''        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[dbo].[{tbl_b}]"
        )''',
'''        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}]"
        )''')


# For _merge_supp_payment
text = text.replace(
'''        if not live_exists:
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
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")''',
'''        if not live_exists:
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
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")''')

text = text.replace(
'''                cursor.execute(
                    f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                    f"SELECT {col_list} FROM [{temp_b}].[dbo].[{tbl_b}] "
                    f"WHERE sheet_key = '{safe_key}'"
                )''',
'''                cursor.execute(
                    f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                    f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}] "
                    f"WHERE sheet_key = '{safe_key}'"
                )''')


# For _merge_simple_module
text = text.replace(
'''        if not live_exists:
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[dbo].[{tbl_b}]")''',
'''        if not live_exists:
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")''')


with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
