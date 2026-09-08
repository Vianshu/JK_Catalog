USE [JK_HW_Divison_082083_793e9c60];
GO
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'TNS\Jitendra')
BEGIN
    ALTER USER [TNS\Jitendra] WITH DEFAULT_SCHEMA = dbo;
END
GO

IF OBJECT_ID('TNS\Jitendra.anil_ledger', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].anil_ledger;
IF OBJECT_ID('TNS\Jitendra.bonus_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].bonus_data;
IF OBJECT_ID('TNS\Jitendra.payment_sheet_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].payment_sheet_data;
IF OBJECT_ID('TNS\Jitendra.row_ledger_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].row_ledger_data;
IF OBJECT_ID('TNS\Jitendra.supplier_accounts', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].supplier_accounts;
IF OBJECT_ID('TNS\Jitendra.supplier_records', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].supplier_records;
IF OBJECT_ID('TNS\Jitendra.team_list_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].team_list_data;
GO

IF OBJECT_ID('dbo.tp_section_data', 'U') IS NOT NULL DROP TABLE dbo.tp_section_data;
IF OBJECT_ID('dbo.tp_section_cols', 'U') IS NOT NULL DROP TABLE dbo.tp_section_cols;
IF OBJECT_ID('dbo.tp_sections', 'U') IS NOT NULL DROP TABLE dbo.tp_sections;

IF OBJECT_ID('dbo.payment_sheet_data', 'U') IS NOT NULL DROP TABLE dbo.payment_sheet_data;

IF OBJECT_ID('dbo.supplier_accounts', 'U') IS NOT NULL DROP TABLE dbo.supplier_accounts;
IF OBJECT_ID('dbo.supplier_records', 'U') IS NOT NULL DROP TABLE dbo.supplier_records;

IF OBJECT_ID('dbo.anil_ledger', 'U') IS NOT NULL DROP TABLE dbo.anil_ledger;
IF OBJECT_ID('dbo.anil_settings', 'U') IS NOT NULL DROP TABLE dbo.anil_settings;

IF OBJECT_ID('dbo.bonus_data', 'U') IS NOT NULL DROP TABLE dbo.bonus_data;
IF OBJECT_ID('dbo.team_list_data', 'U') IS NOT NULL DROP TABLE dbo.team_list_data;

IF OBJECT_ID('dbo.ins_human', 'U') IS NOT NULL DROP TABLE dbo.ins_human;
IF OBJECT_ID('dbo.ins_vehicle', 'U') IS NOT NULL DROP TABLE dbo.ins_vehicle;
IF OBJECT_ID('dbo.ins_stock', 'U') IS NOT NULL DROP TABLE dbo.ins_stock;
GO

