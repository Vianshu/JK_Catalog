-- ============================================================
-- FIX SCHEMA SEGREGATION ISSUES
-- Run this on the CLIENT's company database.
-- ============================================================

-- 1. Change the default schema for the user so future tables are created in dbo
ALTER USER [TNS\Jitendra] WITH DEFAULT_SCHEMA = dbo;
GO

-- 2. Move tables that ONLY exist in TNS\Jitendra to dbo
IF OBJECT_ID('TNS\Jitendra.payment_sheet_data', 'U') IS NOT NULL AND OBJECT_ID('dbo.payment_sheet_data', 'U') IS NULL
    ALTER SCHEMA dbo TRANSFER [TNS\Jitendra].payment_sheet_data;
GO

IF OBJECT_ID('TNS\Jitendra.row_ledger_data', 'U') IS NOT NULL AND OBJECT_ID('dbo.row_ledger_data', 'U') IS NULL
    ALTER SCHEMA dbo TRANSFER [TNS\Jitendra].row_ledger_data;
GO

-- 3. For tables that exist in BOTH schemas, copy data to dbo and drop the TNS\Jitendra version
-- Anil Ledger
IF OBJECT_ID('TNS\Jitendra.anil_ledger', 'U') IS NOT NULL AND OBJECT_ID('dbo.anil_ledger', 'U') IS NOT NULL
BEGIN
    -- Uncomment the insert if you want to keep Jitendra's data:
    -- INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks)
    -- SELECT sort_order, start_date, end_date, days, particular, dr, cr, remarks FROM [TNS\Jitendra].anil_ledger;
    DROP TABLE [TNS\Jitendra].anil_ledger;
END
GO

-- Bonus Data
IF OBJECT_ID('TNS\Jitendra.bonus_data', 'U') IS NOT NULL AND OBJECT_ID('dbo.bonus_data', 'U') IS NOT NULL
BEGIN
    DROP TABLE [TNS\Jitendra].bonus_data;
END
GO

-- Supplier Accounts
IF OBJECT_ID('TNS\Jitendra.supplier_accounts', 'U') IS NOT NULL AND OBJECT_ID('dbo.supplier_accounts', 'U') IS NOT NULL
BEGIN
    DROP TABLE [TNS\Jitendra].supplier_accounts;
END
GO

-- Supplier Records
IF OBJECT_ID('TNS\Jitendra.supplier_records', 'U') IS NOT NULL AND OBJECT_ID('dbo.supplier_records', 'U') IS NOT NULL
BEGIN
    DROP TABLE [TNS\Jitendra].supplier_records;
END
GO

-- Team List Data
IF OBJECT_ID('TNS\Jitendra.team_list_data', 'U') IS NOT NULL AND OBJECT_ID('dbo.team_list_data', 'U') IS NOT NULL
BEGIN
    DROP TABLE [TNS\Jitendra].team_list_data;
END
GO

PRINT 'Schema segregation fixed. Tables moved to dbo.';
