-- ============================================================
-- SUPP PAYMENT DATABASE DIAGNOSTIC SCRIPT
-- Run this on the CLIENT's company database to understand
-- what tables exist and how they differ from the expected schema.
-- ============================================================

PRINT '======================================================';
PRINT 'STEP 1: List ALL supp_payment related tables in this DB';
PRINT '======================================================';
SELECT 
    t.name AS TableName,
    p.rows AS RowCount,
    CAST(SUM(a.total_pages) * 8 / 1024.0 AS DECIMAL(10,2)) AS SizeMB
FROM sys.tables t
INNER JOIN sys.indexes i ON t.object_id = i.object_id
INNER JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
WHERE t.name IN (
    'tp_sections', 'tp_section_cols', 'tp_section_data',
    'payment_sheet_data',
    'supplier_records', 'supplier_accounts',
    'anil_ledger', 'anil_settings',
    'bonus_data', 'team_list_data',
    'ins_human', 'ins_vehicle', 'ins_stock'
)
GROUP BY t.name, p.rows
ORDER BY t.name;

PRINT '';
PRINT '======================================================';
PRINT 'STEP 2: Column structure of each table (vs expected)';
PRINT '======================================================';

-- Helper: show all columns for each table
SELECT 
    t.name AS TableName,
    c.column_id AS ColOrder,
    c.name AS ColumnName,
    tp.name AS DataType,
    c.max_length,
    c.is_nullable
FROM sys.tables t
JOIN sys.columns c ON t.object_id = c.object_id
JOIN sys.types tp ON c.user_type_id = tp.user_type_id
WHERE t.name IN (
    'tp_sections', 'tp_section_cols', 'tp_section_data',
    'payment_sheet_data',
    'supplier_records', 'supplier_accounts',
    'anil_ledger', 'anil_settings',
    'bonus_data', 'team_list_data',
    'ins_human', 'ins_vehicle', 'ins_stock'
)
ORDER BY t.name, c.column_id;

PRINT '';
PRINT '======================================================';
PRINT 'STEP 3: tp_sections contents (all rows)';
PRINT '======================================================';
IF OBJECT_ID('tp_sections', 'U') IS NOT NULL
    SELECT * FROM tp_sections ORDER BY sort_order, id;
ELSE
    PRINT 'tp_sections does NOT exist';

PRINT '';
PRINT '======================================================';
PRINT 'STEP 4: tp_section_cols - check for duplicate/rogue entries';
PRINT '======================================================';
IF OBJECT_ID('tp_section_cols', 'U') IS NOT NULL
BEGIN
    -- Show all saved column entries
    SELECT 
        sc.section_id,
        s.name AS section_name,
        sc.col_index,
        sc.col_name,
        sc.col_width
    FROM tp_section_cols sc
    LEFT JOIN tp_sections s ON sc.section_id = s.id
    ORDER BY sc.section_id, sc.col_index;

    -- Flag sections with more columns saved than the core spec expects (5 cols = Payments/Today/Upcoming)
    PRINT '';
    PRINT 'Sections with MORE than 5 saved columns (potential duplicates):';
    SELECT 
        sc.section_id,
        s.name AS section_name,
        COUNT(*) AS saved_col_count
    FROM tp_section_cols sc
    LEFT JOIN tp_sections s ON sc.section_id = s.id
    GROUP BY sc.section_id, s.name
    HAVING COUNT(*) > 5
    ORDER BY sc.section_id;
END
ELSE
    PRINT 'tp_section_cols does NOT exist';

PRINT '';
PRINT '======================================================';
PRINT 'STEP 5: Row counts per section (to see which have data)';
PRINT '======================================================';
IF OBJECT_ID('tp_section_data', 'U') IS NOT NULL
    SELECT 
        d.section_id,
        s.name AS section_name,
        COUNT(DISTINCT d.row_idx) AS data_rows
    FROM tp_section_data d
    LEFT JOIN tp_sections s ON d.section_id = s.id
    GROUP BY d.section_id, s.name
    ORDER BY d.section_id;
ELSE
    PRINT 'tp_section_data does NOT exist';

PRINT '';
PRINT '======================================================';
PRINT 'STEP 6: supplier_accounts - check is_red column exists';
PRINT '======================================================';
IF OBJECT_ID('supplier_accounts', 'U') IS NOT NULL
BEGIN
    SELECT COUNT(*) AS supplier_count FROM supplier_accounts;
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('supplier_accounts') AND name = 'is_red')
        PRINT 'is_red column EXISTS (schema is up to date)';
    ELSE
        PRINT 'WARNING: is_red column MISSING (old schema - migration needed)';
END
ELSE
    PRINT 'supplier_accounts does NOT exist';

PRINT '';
PRINT '======================================================';
PRINT 'STEP 7: Missing columns check on tp_section_data';
PRINT '======================================================';
IF OBJECT_ID('tp_section_data', 'U') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('tp_section_data') AND name = 'bg_color')
        PRINT 'bg_color: EXISTS';
    ELSE
        PRINT 'bg_color: MISSING';
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('tp_section_data') AND name = 'fg_color')
        PRINT 'fg_color: EXISTS';
    ELSE
        PRINT 'fg_color: MISSING';
END

PRINT '';
PRINT '======================================================';
PRINT 'STEP 8: Missing columns check on tp_sections';
PRINT '======================================================';
IF OBJECT_ID('tp_sections', 'U') IS NOT NULL
BEGIN
    DECLARE @cols TABLE (col_name NVARCHAR(100));
    INSERT INTO @cols VALUES ('is_core'), ('card_width'), ('is_column_break'), ('cols_locked');
    
    SELECT 
        c.col_name,
        CASE WHEN sc.name IS NOT NULL THEN 'EXISTS' ELSE 'MISSING' END AS status
    FROM @cols c
    LEFT JOIN sys.columns sc 
        ON sc.object_id = OBJECT_ID('tp_sections') AND sc.name = c.col_name;
END

PRINT '';
PRINT 'Diagnostic complete. Share these results to determine the fix needed.';
