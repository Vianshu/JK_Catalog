-- =========================================================================================
-- SUPPLIER PAYMENT COMPLETE DATABASE SETUP & DATA POPULATION SCRIPT
-- Application: JK Multi Catalog — Supplier Payment Module
--
-- TARGET DATABASE INSTRUCTIONS:
-- 1. In SQL Server Management Studio (SSMS), ensure you select your Company Database from
--    the dropdown or replace [JK_HW_Divison_082083_38532a08] below with your database name.
-- 2. Click Execute (F5).
-- =========================================================================================

-- Target company database: Change name below if running on a different company DB
USE [JK_HW_Divison_082083_38532a08];
GO

-- Guard: Prevent accidental execution on system databases
IF DB_NAME() IN ('master', 'model', 'msdb', 'tempdb')
BEGIN
    RAISERROR('SAFETY ABORT: Cannot execute script on system database [%s]. Please switch to your company database first.', 16, 1, DB_NAME());
    RETURN;
END
GO

-- Ensure default schema is dbo for current user and TNS users to prevent orphaned schema tables
DECLARE @current_user NVARCHAR(128) = SUSER_SNAME();
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @current_user AND type_desc IN ('SQL_USER', 'WINDOWS_USER'))
BEGIN
    BEGIN TRY
        EXEC('ALTER USER [' + @current_user + '] WITH DEFAULT_SCHEMA = dbo;');
    END TRY
    BEGIN CATCH
    END CATCH
END
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'TNS\Jitendra')
BEGIN
    BEGIN TRY
        ALTER USER [TNS\Jitendra] WITH DEFAULT_SCHEMA = dbo;
    END TRY
    BEGIN CATCH
    END CATCH
END
GO

PRINT '======================================================';
PRINT 'STEP 1: Dropping legacy tables across schemas...';
PRINT '======================================================';
-- Drop legacy non-dbo tables if they exist
IF OBJECT_ID('[TNS\Jitendra].supplier_accounts', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].supplier_accounts;
IF OBJECT_ID('[TNS\Jitendra].supplier_records', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].supplier_records;
IF OBJECT_ID('[TNS\Jitendra].anil_ledger', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].anil_ledger;
IF OBJECT_ID('[TNS\Jitendra].team_list_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].team_list_data;
IF OBJECT_ID('[TNS\Jitendra].bonus_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].bonus_data;
IF OBJECT_ID('[TNS\Jitendra].payment_sheet_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].payment_sheet_data;
IF OBJECT_ID('[TNS\Jitendra].row_ledger_data', 'U') IS NOT NULL DROP TABLE [TNS\Jitendra].row_ledger_data;

-- Drop dbo tables
IF OBJECT_ID('dbo.tp_section_data', 'U') IS NOT NULL DROP TABLE dbo.tp_section_data;
IF OBJECT_ID('dbo.tp_section_cols', 'U') IS NOT NULL DROP TABLE dbo.tp_section_cols;
IF OBJECT_ID('dbo.tp_sections', 'U') IS NOT NULL DROP TABLE dbo.tp_sections;
IF OBJECT_ID('dbo.shared_table_cols', 'U') IS NOT NULL DROP TABLE dbo.shared_table_cols;
IF OBJECT_ID('dbo.supplier_accounts', 'U') IS NOT NULL DROP TABLE dbo.supplier_accounts;
IF OBJECT_ID('dbo.supplier_records', 'U') IS NOT NULL DROP TABLE dbo.supplier_records;
IF OBJECT_ID('dbo.anil_settings', 'U') IS NOT NULL DROP TABLE dbo.anil_settings;
IF OBJECT_ID('dbo.anil_ledger', 'U') IS NOT NULL DROP TABLE dbo.anil_ledger;
IF OBJECT_ID('dbo.team_list_data', 'U') IS NOT NULL DROP TABLE dbo.team_list_data;
IF OBJECT_ID('dbo.bonus_data', 'U') IS NOT NULL DROP TABLE dbo.bonus_data;
IF OBJECT_ID('dbo.payment_sheet_data', 'U') IS NOT NULL DROP TABLE dbo.payment_sheet_data;
IF OBJECT_ID('dbo.ins_human', 'U') IS NOT NULL DROP TABLE dbo.ins_human;
IF OBJECT_ID('dbo.ins_vehicle', 'U') IS NOT NULL DROP TABLE dbo.ins_vehicle;
IF OBJECT_ID('dbo.ins_stock', 'U') IS NOT NULL DROP TABLE dbo.ins_stock;
GO

PRINT '======================================================';
PRINT 'STEP 2: Creating complete table structures under dbo...';
PRINT '======================================================';
CREATE TABLE dbo.supplier_records (
    id INT IDENTITY PRIMARY KEY,
    name NVARCHAR(300),
    sort_order INT
);

CREATE TABLE dbo.supplier_accounts (
    id INT IDENTITY PRIMARY KEY,
    supplier_id INT,
    acc_index INT,
    acc_type NVARCHAR(100),
    naam NVARCHAR(300),
    thegana NVARCHAR(300),
    baik NVARCHAR(300),
    khata NVARCHAR(300),
    rakam NVARCHAR(100),
    jamma NVARCHAR(300),
    is_red INT DEFAULT 0
);

CREATE TABLE dbo.anil_ledger (
    id INT IDENTITY PRIMARY KEY,
    sort_order INT,
    start_date NVARCHAR(MAX),
    end_date NVARCHAR(MAX),
    days NVARCHAR(MAX),
    particular NVARCHAR(MAX),
    dr NVARCHAR(MAX),
    cr NVARCHAR(MAX),
    remarks NVARCHAR(MAX)
);

CREATE TABLE dbo.anil_settings (
    [key] NVARCHAR(100) PRIMARY KEY,
    value NVARCHAR(MAX)
);

CREATE TABLE dbo.team_list_data (
    row_idx INT NOT NULL,
    col_idx INT NOT NULL,
    cell_text NVARCHAR(MAX),
    PRIMARY KEY (row_idx, col_idx)
);

CREATE TABLE dbo.bonus_data (
    row_idx INT NOT NULL,
    col_idx INT NOT NULL,
    cell_text NVARCHAR(MAX),
    PRIMARY KEY (row_idx, col_idx)
);

CREATE TABLE dbo.payment_sheet_data (
    row_idx INT NOT NULL,
    col_idx INT NOT NULL,
    cell_text NVARCHAR(MAX),
    PRIMARY KEY (row_idx, col_idx)
);

CREATE TABLE dbo.tp_sections (
    id INT IDENTITY PRIMARY KEY,
    sort_order INT,
    name NVARCHAR(200),
    header_color NVARCHAR(50),
    is_core INT DEFAULT 0,
    card_width INT NULL,
    is_column_break INT DEFAULT 0,
    cols_locked INT DEFAULT 0
);

CREATE TABLE dbo.tp_section_cols (
    id INT IDENTITY PRIMARY KEY,
    section_id INT,
    col_index INT,
    col_name NVARCHAR(100),
    col_width INT
);

CREATE TABLE dbo.tp_section_data (
    id INT IDENTITY PRIMARY KEY,
    section_id INT,
    row_idx INT,
    col_idx INT,
    cell_text NVARCHAR(MAX),
    bg_color NVARCHAR(50),
    fg_color NVARCHAR(50)
);

CREATE TABLE dbo.ins_human (
    row_idx INT NOT NULL,
    col_idx INT NOT NULL,
    cell_text NVARCHAR(MAX),
    PRIMARY KEY (row_idx, col_idx)
);

CREATE TABLE dbo.ins_vehicle (
    row_idx INT NOT NULL,
    col_idx INT NOT NULL,
    cell_text NVARCHAR(MAX),
    PRIMARY KEY (row_idx, col_idx)
);

CREATE TABLE dbo.ins_stock (
    row_idx INT NOT NULL,
    col_idx INT NOT NULL,
    cell_text NVARCHAR(MAX),
    PRIMARY KEY (row_idx, col_idx)
);

CREATE TABLE dbo.shared_table_cols (
    id INT IDENTITY PRIMARY KEY,
    table_name NVARCHAR(100),
    col_index INT,
    col_name NVARCHAR(100),
    col_width INT
);
GO

PRINT '======================================================';
PRINT 'STEP 3: Populating Supplier Records and Accounts (39 Suppliers)...';
PRINT '======================================================';
SET IDENTITY_INSERT dbo.supplier_records ON;

INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (1, N'Vishal nat bolt', 1);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (1, 0, N'Company Account', N'विशाल नट बोल्टु उधोग', N'बिरगज', N'एभरेष्ट बैक लिमिटॆड', N'006001-05200842', N'chq rs-65250.72', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (1, 1, N'Personal Account', N'Vishal Hardware', N'', N'Everest Bank', N'00600-1052-00223', N'chq rs- 57194.68', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (2, N'Salasar HW, ktm', 2);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (2, 0, N'Company Account', N'Shri Salasar Hardware Traders', N'त्रिपुरेश्वर', N'Siddath bank', N'0061-509-5161', N'chq rs-100000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (2, 1, N'Personal Account', N'Khadak singh bista', N'new baneshwor', N'nepal sbi', N'2031 5241 4093 60NPR', N'cash rs- 194200', N'personal name', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (3, N'Rani sati, brj', 3);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (3, 0, N'Company Account', N'रोयल ट्रेड लिक', N'बिरगज', N'एभरेष्ट बैक लिमिटॆड', N'00600-1052-00537 CA', N'', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (3, 1, N'Personal Account', N'रुबि रुगटा', N'बिरगज', N'Nepal investment bank ltd', N'003-0508-0263191', N'', N'jitendra', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (3, 2, N'Other Account 1', N'Global Metal Industries', N'बिरगज', N'Global Bank', N'0110-10100-06000', N'chq rs- 366938.84', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (4, N'kk impex, brj', 4);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (4, 0, N'Company Account', N'K.K. ईम्पेक्स प्रा. ली.', N'बिरगज', N'एभरेष्ट बैक लिमिटॆड', N'00600-10520-1088', N'chq rs-7082.62', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (4, 1, N'Personal Account', N'न्यु पशुपति हार्डवेयर', N'बिरंगन्ज', N'एभरेष्ट बैक लिमिटॆड', N'00600-1050-00379', N'chq rs- 11249.88', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (5, N'Universal trading, ktm', 5);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (5, 0, N'Company Account', N'युनिवर्सल ट्रेडिग़ सेन्टर प्रा. ली.', N'काठमान्डु', N'एभरेष्ट बैक लिमिटॆड', N'01000-1052-00942', N'chq rs- 92500', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (5, 1, N'Personal Account', N'युनिवर्सल ट्रेडिग़ सेन्टर प्रा. ली.', N'Tripureshwor', N'NMB BANK', N'0820-0698-2880-0016', N'chq rs- 170000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (6, N'Manokamna ,brj', 6);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (6, 0, N'Company Account', N'Manokamna overseas', N'बिरगज', N'ग्लोबल बैक', N'110-1010-005203', N'cash rs-300000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (6, 1, N'Personal Account', N'Pawan kumar Agrawal', N'बिरगज', N'ग्लोबल बैक', N'110-70100-14846', N'', N'JITENDRA', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (6, 2, N'Other Account 1', N'Manokamna overseas', N'बिरगज', N'ग्लोबल बैक', N'0110-10100-65362', N'chq rs-78715.9', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (7, N'Kailashpati International, Brj', 7);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (7, 0, N'Company Account', N'Kailashpati international', N'बीरगज', N'Macchapucchure bank Ltd', N'1870-990-5036-00015', N'cash rs-96850', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (8, N'Balaji metal, Hetoda', 8);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (8, 0, N'Company Account', N'Balaji Metal Industries', N'Hetoda', N'mega bank', N'01000-1013-9993', N'chq rs-120000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (8, 1, N'Personal Account', N'Om prakash Bajaj', N'teku', N'Everest', N'0100-0501-0011-41', N'cash rs- 215118', N'jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (9, N'गनेश ट्रेडिग सेन्टर', 9);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (9, 0, N'Company Account', N'गनेश ट्रेडिग सेन्टर', N'विरगज', N'एभरेष्ट बैक लिमिटॆड', N'00600-105200-347', N'', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (9, 1, N'Personal Account', N'Atlantic Overseas', N'विरगज', N'GLOBAL', N'110-101-000-6050', N'', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (10, N'Bikash ji ,brj', 10);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (10, 0, N'Company Account', N'Tulip Polymer Industries', N'बीरगज', N'Nabil Bank Ltd.', N'050-101-7500-991', N'', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (10, 1, N'Personal Account', N'Kushagra International', N'बीरगज', N'एभरेष्ट बैक लिमिटॆड', N'0060-0105-2014-95', N'chq rs-192106.78', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (10, 2, N'Other Account 1', N'Win Win Hardware Products', N'बीरगज', N'Siddharth bank Ltd.', N'002-165-79101', N'chq Rs. 12000.60', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (11, N'ASIA TOOLS', 11);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (11, 0, N'Company Account', N'Asia Tools House', N'ktm', N'Prabhu Bank', N'1140-106-1196-00011', N'chq rs-50000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (11, 1, N'Personal Account', N'Mahadev Tiwari', N'ktm', N'Prabhu Bank', N'1140-13880-8100-012', N'cash rs- 63000', N'jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (12, N'Priya Impex', 12);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (12, 0, N'Company Account', N'Priya Impex', N'Druber Marg Branch', N'Nepal Investment Bank', N'00159-020-250-610', N'chq rs-105000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (12, 1, N'Personal Account', N'Mukesh kumar singhal', N'Tripureshwor branch', N'Global ime bank', N'34070-1000-2550', N'', N'jitendra agrawal', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (12, 2, N'Other Account 1', N'Aarna international pvt ltd', N'Ktm', N'NIMB Bank', N'0010-10103-10505', N'chq rs-150000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (13, N'Binayak Enterprises', 13);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (13, 0, N'Company Account', N'Binayak Overseas Trade Pvt.Ltd', N'ktm', N'Kumari Bank', N'0050-3018-7610-0001', N'chq rs-184171.92', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (13, 1, N'Personal Account', N'GANESH DATTA JOSHI', N'TRIPURESHWOR', N'LUMBINI BIKAS BANK LTD.', N'0311-1020-3647-6400-0001', N'RS-80000', N'jitendra agrawal', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (14, N'Start International', 14);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (14, 0, N'Company Account', N'Star International', N'बीरगज', N'एभरेष्ट बैक लिमिटॆड', N'00600-105201511', N'chq rs-141216/-', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (15, N'shruti enterprises', 15);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (15, 0, N'Company Account', N'shruti enterprises', N'बीरगज', N'एभरेष्ट बैक लिमिटॆड', N'0060-0105-200689', N'chq rs- 220000', N'जे.के. हार्डवेयर & कम्पनी, BRT', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (15, 1, N'Personal Account', N'Vinay bansal', N'बीरगज', N'एभरेष्ट बैक लिमिटॆड', N'600-501-211-258', N'cash rs- 100000', N'jitendra agrawal', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (16, N'shree om ji trade international', 16);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (16, 0, N'Company Account', N'श्री ओम जी ट्रेड ईन्टरनेशनल', N'बीरगज', N'Nepal investment bank', N'003590-2025-0283', N'', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (16, 1, N'Personal Account', N'sangita kumari agrawal', N'बीरगज', N'laxmi bank', N'0011-9000-146', N'', N'jitnedra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (17, N'Lotus Plastic Udhyog', 17);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (17, 0, N'Company Account', N'Lotus Plastic udhyog', N'Kalimati', N'Nepal Investment bank', N'01759-01025-0221', N'CHQ RS- 183791.86', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (17, 1, N'Personal Account', N'tamanna traders', N'Kalimati', N'Nepal Investment bank', N'01759-01025-0306', N'chq rs- 665000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (17, 2, N'Other Account 1', N'Lotus Plastic udhyog', N'Kalimati', N'Everest Bank', N'0370-0105-2000-63', N'CHQ RS- 183791.86', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (18, N'Kelash hw, brj', 18);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (18, 0, N'Company Account', N'Nirika Traders', N'बीरगज', N'Nepal Investment bank', N'0030-10500-03615', N'', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (18, 1, N'Personal Account', N'nitesh kumar Agrawal', N'बीरगज', N'Nepal Investment bank', N'0030-509000-2652', N'', N'jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (19, N'New Famous Tar Jali, Brj', 19);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (19, 0, N'Company Account', N'New Famous Tar Jali Udhyog', N'बीरगज', N'Nepal invesment bank.', N'0030-1050-0029-98', N'chq rs-135000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (19, 1, N'Personal Account', N'Ram Asis Prasad Kurmi', N'', N'Kumari Bank', N'00300-7575-4200-001', N'cash rs-90700.64', N'jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (20, N'icon, ktm', 20);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (20, 0, N'Company Account', N'ICON Traders', N'Teku Branch', N'Prabhu Bank Limited', N'1140-1137-9940-0011', N'chq rs-102908.73', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (20, 1, N'Personal Account', N'Prashant Mahesheka', N'Bhat Bateni Branch, Kathmandu', N'Laxmi Sunrise Bank Ltd', N'0142-4005-337', N'cash rs-100000', N'personal name', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (21, N'omex, brj', 21);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (21, 0, N'Company Account', N'New Omax international', N'बीरगज', N'NMB BANK', N'019-01168-3570-0016', N'chq rs-140000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (21, 1, N'Personal Account', N'OMAX MANUFACTURING', N'बीरगज', N'NMB BANK', N'019-0146-4318-0000-27', N'chq rs- 50000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (22, N'Arvind bandhu', 22);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (22, 0, N'Company Account', N'Arvind Bandhu', N'बीरगज', N'Everest Bank', N'0060-0105-2002-84', N'chq rs- 96182.77', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (22, 1, N'Personal Account', N'Nirmal Kumar agrawal', N'बीरगज', N'NMB bank', N'01900-5268-1300-011', N'cash rs- 131150', N'jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (23, N'Satyam Techno', 23);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (23, 0, N'Company Account', N'Satyam Techno Packs Pvt. Ltd.', N'Halchowk Branch', N'Nabil Bank LTD.', N'320 101 7500 654', N'chq rs- 92449.82', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (23, 1, N'Personal Account', N'Rajesh Paudel', N'Halchowk Branch', N'Nabil bank ltd.', N'032 0101 7500 806', N'cash rs- 15500', N'jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (24, N'Jagdamba Metal, Brj', 24);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (24, 0, N'Company Account', N'Jagdamba Metal Udhyog', N'बीरगज', N'एभरेष्ट बैक लिमिटॆड', N'00600-1052-01353', N'chq rs- 233765.92', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (25, N'Shiv Enterprises, Brj', 25);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (25, 0, N'Company Account', N'Shiv Enterprises', N'Birgunj', N'Machhapuchhre bank ltd', N'0040 0235 5550  0017', N'chq rs- 275000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (25, 1, N'Personal Account', N'Jay Ma Vaishno Enterprises', N'Birgunj', N'Machhapuchhre bank ltd', N'0040 0533 8430 0011', N'chq rs-115938', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (25, 2, N'Other Account 1', N'Rajendra Sharma', N'Birgunj', N'Machhapuchhre bank ltd', N'0040-0004-2980-0011', N'Rs-', N'Jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (26, N'Rani sati, Brj', 26);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (26, 0, N'Company Account', N'Royal Hardware pvt ltd', N'Birgunj', N'global bank', N'1101 0100 63407', N'chq rs- 67636.63', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (26, 1, N'Personal Account', N'Krishna Gopal Keyal', N'', N'Siddhartha Bank', N'0021-5129-121', N'cash rs-49615', N'Jitendra', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (27, N'Pashupati plastic Ind, Ktm', 27);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (27, 0, N'Company Account', N'Pashupati Plastic Industries', N'', N'Prabhu Bank', N'1880 1524 8870 0013', N'chq rs- 57600', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (28, N'Sri Maruti Mangal, hattiguda', 28);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (28, 0, N'Company Account', N'Shree Maruti Mangal', N'Hattigauda', N'Prabhu Bank', N'1000 1346 7050 0016', N'chq rs- 180000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (28, 1, N'Personal Account', N'Touchstone Multipurpose Co-operative ltd', N'New road', N'Global Ime Bank', N'3020 1010 0021 50', N'cash rs-71180', N'personal name', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (29, N'Bimal Spark House Pvt. Ltd.,Lalitpur', 29);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (29, 0, N'Company Account', N'Bimal Spark House Pvt. Ltd.', N'Lalitpur', N'Nabil Bank', N'2380 1017 5002 49', N'chq rs- 800000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (29, 1, N'Personal Account', N'Future Exim Pvt.Ltd', N'Dhobighat', N'Global Bank', N'1050-1010-0027-69', N'chq rs- 500000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (29, 2, N'Other Account 1', N'Future Exim Pvt.Ltd', N'Dhobighat', N'Sanima Bank', N'9030-1001-0000-134', N'chq rs- 400000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (30, N'R R Hardware Center, Brj', 30);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (30, 0, N'Company Account', N'R R Hardware Center, Brj', N'', N'Machhapuchchhre bank limited', N'0040 0002 0350 0042', N'chq rs- 45007.9', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (31, N'Crystal Trade Link', 31);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (31, 0, N'Company Account', N'Crystal Trade Link', N'', N'Prabhu Bank Limited', N'0320-1529-2630-0016', N'chq rs-40755', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (31, 1, N'Personal Account', N'Crystal Trade Link', N'', N'Everest Bank Limited', N'0100-0105-2013-84', N'chq rs-', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (31, 2, N'Other Account 1', N'Pradip Agrawal', N'', N'Everest Bank Limited', N'0020-0501-0062-40', N'cash rs-54000', N'personal name', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (32, N'Gahawamai Enterprises,Brj', 32);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (32, 0, N'Company Account', N'Gahawamai Enterprises,Brj', N'', N'Machhapuchhre', N'0040-0533-6560-0017', N'chq rs-255390', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (33, N'R R Hardware Center, Brj', 33);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (33, 0, N'Company Account', N'R.R Hardware Center', N'Birgunj', N'Machhapuchhre', N'0040-0002-0350-0042', N'chq rs-76496.48', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (34, N'Tara Paint & Chemical Insudtries Pvt. Ltd.', 34);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (34, 0, N'Company Account', N'TARA PAINTS & CHEMICAL INDUSTRIES PVT LTD', N'Birgunj', N'Kumari', N'0030-2488-9300-0021', N'chq rs-100000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (35, N'Himal Wire Netting Industrirs', 35);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (35, 0, N'Company Account', N'Himal Wire Netting Industrirs', N'Birgunj', N'Machhapuchhre', N'0040-9905-5340-0025', N'chq rs-114319.25', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (36, N'Global Marketing, Brj', 36);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (36, 0, N'Company Account', N'Global Marketing', N'Birgunj', N'Everest Bank Ltd', N'0060-0105-2010-70', N'chq rs-43758.6', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (36, 1, N'Personal Account', N'Bharat Bhushan Sarraf', N'Birgunj', N'Everest Bank Ltd', N'0060-0501-2013-95', N'cash rs- 49741.4', N'personal name', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (37, N'Rituraaj Impex', 37);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (37, 0, N'Company Account', N'Rituraaj Impex', N'Birgunj', N'prabhu bank', N'1880-1534-6760-0010', N'chq no-33840', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (38, N'LAXMI BANK', 38);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (38, 0, N'Company Account', N'जे.के. हार्डवेयर & कम्पनी, Brt', N'Brt', N'Laxmi Bank', N'0061-1036-434', N'chq no-10,85,000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
INSERT INTO dbo.supplier_records (id, name, sort_order) VALUES (39, N'Salasar Tools and Hardware', 39);
INSERT INTO dbo.supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma, is_red) VALUES (39, 0, N'Company Account', N'SALASAR TOOLS AND HARDWARE', N'Teku', N'Laxmi Bank', N'1661-6948-0201-1079', N'chq no-145000', N'जे.के. हार्डवेयर & कम्पनी, Brt', 0);
SET IDENTITY_INSERT dbo.supplier_records OFF;
GO

PRINT '======================================================';
PRINT 'STEP 4: Populating Anil Ledger & Anil Settings...';
PRINT '======================================================';

INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (0, N'2021-02-01', N'2021-02-24', N'23', N'Cash Payment', N'{"text": "4,000,000", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (1, N'', N'2021-02-24', N'', N'Cash Recived', N'', N'800,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (2, N'', N'2021-03-02', N'', N'Cash Recived', N'', N'700,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (3, N'2021-01-31', N'2021-04-30', N'89', N'intersted', N'{"text": "109,726", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (4, N'2021-05-01', N'2021-07-31', N'91', N'intersted', N'{"text": "117,116", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (5, N'2021-08-01', N'2021-10-30', N'90', N'intersted', N'{"text": "134,474", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (6, N'2021-11-01', N'2022-01-31', N'91', N'intersted', N'{"text": "128,406", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (7, N'2022-02-01', N'2022-04-30', N'88', N'intersted', N'{"text": "129,746", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (8, N'2022-05-01', N'2022-07-31', N'91', N'intersted', N'{"text": "116,916", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (9, N'2022-07-27', N'', N'', N'', N'', N'150,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (10, N'2022-08-21', N'', N'', N'', N'', N'50,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (11, N'2022-08-31', N'', N'', N'', N'', N'500,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (12, N'2022-08-01', N'2022-11-15', N'106', N'Interested', N'{"text": "158,724", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (13, N'2022-11-16', N'2023-02-14', N'90', N'Interested', N'{"text": "119,619", "manual": true}', N'', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (14, N'', N'', N'', N'Cash Recived', N'', N'314,727', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (15, N'2023-02-15', N'2023-03-22', N'35', N'Cash Recived', N'43,151', N'50,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (16, N'2023-03-23', N'2023-04-23', N'31', N'Cash Recived', N'38,114', N'50,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (17, N'2023-04-24', N'2023-05-21', N'27', N'Cash Recived', N'33,038', N'50,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (18, N'2023-05-22', N'2023-06-22', N'31', N'Cash Recived', N'37,673', N'75,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (19, N'2023-06-23', N'2023-10-20', N'119', N'Cash Recived', N'142,427', N'100,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (20, N'2023-10-21', N'2023-11-26', N'36', N'Cash Recived', N'43,840', N'75,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (21, N'2023-11-27', N'2024-01-16', N'50', N'Cash Recived', N'60,121', N'75,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (22, N'2024-01-17', N'2024-02-27', N'41', N'Cash Recived', N'48,998', N'75,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (23, N'2024-02-28', N'2024-04-15', N'47', N'Cash Recived', N'55,566', N'39,592', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (24, N'2024-04-16', N'2024-06-04', N'49', N'Cash Recived', N'58,317', N'45,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (25, N'2024-06-05', N'2024-06-05', N'0', N'Cash Recived', N'0', N'76,655', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (26, N'2024-06-06', N'2024-06-12', N'6', N'Cash Recived', N'6,953', N'76,954', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (27, N'2024-06-13', N'2024-07-15', N'32', N'Cash Recived', N'35,980', N'15,980', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (28, N'2024-07-16', N'2024-08-13', N'28', N'Cash Recived', N'31,759', N'13,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (29, N'2024-08-14', N'2024-09-16', N'33', N'Cash Recived', N'37,735', N'75,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (30, N'2024-09-17', N'2024-10-17', N'30', N'Cash Recived', N'33,754', N'75,247', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (31, N'2024-10-18', N'2024-12-09', N'52', N'Cash Recived', N'57,442', N'97,443', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (32, N'2024-12-10', N'2024-12-20', N'10', N'Cash Recived', N'10,849', N'-1,000,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (33, N'2024-12-21', N'2025-02-12', N'53', N'account', N'83,922', N'119,435', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (34, N'2025-02-13', N'2025-03-19', N'34', N'account', N'53,241', N'103,577', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (35, N'2025-03-20', N'2025-04-28', N'39', N'account', N'60,103', N'75,103', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (36, N'2025-04-29', N'2025-06-06', N'38', N'account', N'58,281', N'78,281', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (37, N'2025-06-07', N'2025-07-07', N'30', N'account', N'45,715', N'75,716', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (38, N'2025-07-08', N'2025-08-27', N'50', N'account', N'75,452', N'85,450', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (39, N'2025-08-28', N'2025-11-09', N'73', N'account', N'109,800', N'139,800', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (40, N'2025-11-10', N'2025-11-10', N'', N'Cash Recived', N'', N'800,000', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (41, N'2025-11-11', N'2025-12-10', N'29', N'account', N'{"text": "43,190", "manual": true}', N'75,680', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (42, N'2025-12-11', N'2026-01-12', N'32', N'account', N'34,521', N'86,169', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (43, N'2026-01-13', N'2026-03-20', N'66', N'account', N'69,518', N'99,016', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (44, N'2026-03-21', N'2026-04-22', N'32', N'account', N'33,240', N'76,506', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (45, N'2026-04-23', N'2026-06-08', N'46', N'account', N'46,801', N'75,900', NULL);
INSERT INTO dbo.anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) VALUES (46, N'2026-06-09', N'2026-07-14', N'35', N'account', N'35,107', N'75,107', NULL);
INSERT INTO dbo.anil_settings ([key], value) VALUES (N'header_state', N'AAAA/wAAAAAAAAABAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAi4AAAAHAAEAAQAAAAAAAAAAAAAAAGQAAAAGAAAAhAAAAAAAAAAHAAAAVgAAAAEAAAAAAAAAVgAAAAEAAAAAAAAAKQAAAAEAAAAAAAAAZAAAAAEAAAAAAAAAWQAAAAEAAAAAAAAAYAAAAAEAAAAAAAAAPAAAAAEAAAAAAAAD6AAAAACHAAAAAAAAAAAAAAAAAAAAAQ==');
GO

PRINT '======================================================';
PRINT 'STEP 5: Populating Today Payment Sections, Columns & Formulas...';
PRINT '======================================================';
SET IDENTITY_INSERT dbo.tp_sections ON;

INSERT INTO dbo.tp_sections (id, sort_order, name, header_color, is_core, card_width, is_column_break, cols_locked) VALUES (13, 0, N'Payments', N'#1565C0', 1, 534, 0, 1);
INSERT INTO dbo.tp_sections (id, sort_order, name, header_color, is_core, card_width, is_column_break, cols_locked) VALUES (19, 1, N'Today', N'#00695C', 1, NULL, 0, 0);
INSERT INTO dbo.tp_sections (id, sort_order, name, header_color, is_core, card_width, is_column_break, cols_locked) VALUES (20, 2, N'Upcoming', N'#4527A0', 1, NULL, 0, 0);
INSERT INTO dbo.tp_sections (id, sort_order, name, header_color, is_core, card_width, is_column_break, cols_locked) VALUES (16, 3, N'Account Table', N'#E65100', 1, NULL, 1, 0);
INSERT INTO dbo.tp_sections (id, sort_order, name, header_color, is_core, card_width, is_column_break, cols_locked) VALUES (18, 4, N'Limits & LC', N'#B71C1C', 1, NULL, 0, 0);
INSERT INTO dbo.tp_sections (id, sort_order, name, header_color, is_core, card_width, is_column_break, cols_locked) VALUES (14, 6, N'Demand Loans (DL)', N'#37ff44', 1, 817, 1, 0);
SET IDENTITY_INSERT dbo.tp_sections OFF;
GO

-- Section Columns

INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (10, 0, N'Account', 200);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (10, 1, N'Remain Cash', 110);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (10, 2, N'Bank Cash', 328);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (12, 0, N'Type', 260);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (12, 1, N'Value', 378);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (13, 0, N'Date', 86);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (13, 1, N'Party Name', 244);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (13, 2, N'To', 66);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (13, 3, N'From', 74);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (13, 4, N'Payment', 232);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 0, N'S.N', 185);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 1, N'DL No.', 218);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 2, N'Amount', 108);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 3, N'Expiry Date', 96);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 4, N'Day''s left', 77);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 5, N'Gap', 50);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 6, N'Notes', 71);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (14, 7, N'hat bsdk', 120);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (16, 0, N'Account', 114);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (16, 1, N'Remain Cash', 130);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (16, 2, N'Bank / Cash', 214);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (18, 0, N'Type', 196);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (18, 1, N'Value', 243);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (19, 0, N'Date', 113);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (19, 1, N'Party Name', 212);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (19, 2, N'To', 72);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (19, 3, N'From', 88);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (19, 4, N'Payment', 222);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (20, 0, N'Date', 87);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (20, 1, N'Party Name', 277);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (20, 2, N'To', 79);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (20, 3, N'From', 136);
INSERT INTO dbo.tp_section_cols (section_id, col_index, col_name, col_width) VALUES (20, 4, N'Payment', 147);
GO

-- Section Data & Formulas

INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 0, 1, N'Macha Bank', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 0, 2, N'macha', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 0, 3, N'from jnk', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 1, 1, N'Macha Bank', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 1, 2, N'macha', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 1, 3, N'from brt', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 2, 1, N'Macha Bank', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 2, 2, N'macha', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 2, 3, N'from btm', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 3, 1, N'Macha Bank', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 3, 2, N'macha', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 3, 3, N'from ngt', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 4, 0, N'2026-08-10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 4, 1, N'Car Loan Emi', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 4, 4, N'=IF(MAX(Date-TODAY(),0)<5,"50000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 5, 0, N'2026-09-10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 5, 1, N'Home Loan Suman Mam', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 5, 4, N'=IF(MAX(Date-TODAY(),0)<5,"77000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 6, 0, N'2026-08-16', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 6, 1, N'Interest-Macha Bank-QTR End', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 6, 4, N'=IF(MAX(Date-TODAY(),0)<7,"470000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 7, 0, N'2026-08-16', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 7, 1, N'PWCL- Every 3 Month interest', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 7, 4, N'=IF(MAX(Date-TODAY(),0)<7,"85000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 8, 0, N'2026-09-14', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 8, 1, N'PWCL- Every 3 Month', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 8, 4, N'=IF(MAX(Date-TODAY(),0)<7,"175000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 9, 0, N'2026-08-10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 9, 1, N'NEW LOAN 1013', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 9, 4, N'=IF(MAX(Date-TODAY(),0)<7,"500000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 10, 0, N'2026-08-16', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 10, 1, N'NEW LOAN 1013 interest', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 10, 4, N'=IF(MAX(Date-TODAY(),0)<7,"31000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 11, 1, N'Rajkumar ji', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 12, 0, N'fri', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 12, 1, N'Chandrodaya, Brt', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 13, 0, N'mon/tue', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 13, 1, N'Chandrodaya, KTM', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 13, 4, N'650000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 14, 1, N'ANIL SIR', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 15, 0, N'2026-08-07', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 15, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-0000c564', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 15, 4, N'=IF(MAX(Date-TODAY(),0)<3,"150000",0)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 16, 0, N'fri', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 16, 1, N'Dhiraj trading', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 17, 0, N'thu', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 17, 1, N'Priti valve & Fitting Ind, P. Ltd', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 17, 4, N'40000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 18, 0, N'sun', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 18, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-00007c36', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 19, 0, N'wed', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 19, 1, N'Aarna International Pvt.Ltd, Kathmandu', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 19, 4, N'45000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 20, 0, N'fri', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 20, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-00003ec6', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 21, 0, N'wed', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 21, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-0000c316', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 22, 1, N'Jitu sir (machha credit card)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 23, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-00009d6b', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 24, 1, N'vat', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 25, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-0000c2c3', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 25, 2, N'M11548', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 25, 3, N'rtgs', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (13, 25, 4, N'=150660*1.6015', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 0, 0, N'1', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 0, 1, N'DL-995', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 0, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 0, 3, N'2026-08-25', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 0, 4, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 1, 0, N'2', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 1, 1, N'DL-997', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 1, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 1, 3, N'2026-09-01', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 1, 4, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 1, 5, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 2, 0, N'3', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 2, 1, N'DL-1001', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 2, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 2, 3, N'2026-09-07', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 2, 4, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 2, 5, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 3, 0, N'4', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 3, 1, N'DL-1003', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 3, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 3, 3, N'2026-09-11', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 3, 4, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 3, 5, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 4, 0, N'5', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 4, 1, N'DL-1009', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 4, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 4, 3, N'2026-09-18', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 4, 4, N'2', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 4, 5, N'2', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 5, 0, N'6', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 5, 1, N'DL-1016', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 5, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 5, 3, N'2026-09-28', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 5, 4, N'12', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 5, 5, N'10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 6, 0, N'7', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 6, 1, N'DL-1024', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 6, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 6, 3, N'2026-10-01', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 6, 4, N'15', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 6, 5, N'3', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 7, 0, N'8', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 7, 1, N'DL-1029', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 7, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 7, 3, N'2026-10-06', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 7, 4, N'20', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 7, 5, N'5', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 8, 0, N'9', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 8, 1, N'DL-1036', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 8, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 8, 3, N'2026-10-12', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 8, 4, N'26', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 8, 5, N'6', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 9, 0, N'10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 9, 1, N'DL-1043', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 9, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 9, 3, N'2026-10-21', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 9, 4, N'35', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 9, 5, N'9', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 10, 0, N'11', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 10, 1, N'DL-1048', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 10, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 10, 3, N'2026-10-29', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 10, 4, N'43', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 10, 5, N'8', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 11, 0, N'12', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 11, 1, N'DL-1052', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 11, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 11, 3, N'2026-11-04', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 11, 4, N'49', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 11, 5, N'6', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 12, 0, N'13', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 12, 1, N'DL-1057', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 12, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 12, 3, N'2026-11-10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 12, 4, N'55', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 12, 5, N'6', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 13, 0, N'14', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 13, 1, N'DL-1062', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 13, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 13, 3, N'2026-11-17', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 13, 4, N'62', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 13, 5, N'7', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 14, 0, N'15', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 14, 1, N'DL-1071', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 14, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 14, 3, N'2026-11-26', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 14, 4, N'71', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 14, 5, N'9', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 15, 0, N'16', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 15, 1, N'DL-10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 15, 2, N'700000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 15, 3, N'2026-12-02', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 15, 4, N'77', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (14, 15, 5, N'6', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 0, 0, N'Laxmi Bank', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 0, 1, N'=[Account Table][Bank / Cash][1]', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 0, 2, N'3653.76', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 1, 0, N'Macha (dl settle)', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 1, 1, N'=[Account Table][Bank / Cash][2]+SUM([Payments][Payment][1:4])-SUM([Payments][Payment][5],[Payments][Payment][7:11],[Payments][Payment][13:14],[Payments][Payment][16:22],[Today][Payment][1:7])', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 1, 2, N'1008184.58', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 2, 0, N'Cash', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 2, 1, N'=[Account Table][Bank / Cash][3]-[Payments][Payment][12]-[Payments][Payment][2]-[Payments][From][13]-[Payments][Payment][24]-[Payments][From][21]-[Payments][From][23]-[Payments][Payment][25]-[Payments][From][20]-[Today][Payment][9]', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 2, 2, N'505395', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 3, 0, N'BTM', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 3, 1, N'=[Account Table][Bank / Cash][4]-[Payments][Payment][3]-[Payments][From][12]-[Today][Payment][8]-[Payments][From][18]', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 3, 2, N'430000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 4, 0, N'JNK', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 4, 1, N'=[Account Table][Bank / Cash][5]-[Payments][Payment][1]-[Payments][Payment][15]-[Payments][To][6]-[Payments][From][25]-[Payments][Payment][23]-[Today][Payment][11]-[Payments][Payment][6]-50000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 4, 2, N'50000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 5, 0, N'NGT', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 5, 1, N'=[Account Table][Bank / Cash][6]-[Payments][Payment][4]-[Payments][From][15]-[Payments][To][23]-[Today][Payment][10]-25000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (16, 5, 2, N'25000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (18, 0, 0, N'Remain Demand Loan Limit', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (18, 0, 1, N'0', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (18, 1, 0, N'Remain LC Limit', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (18, 1, 1, N'1620000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (18, 2, 0, N'Used LC', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (18, 2, 1, N'880000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (19, 0, 0, N'2026-08-07', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (19, 0, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-0000af34', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (19, 0, 3, N'cash brt', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (19, 0, 4, N'305395', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 0, 1, N'jaipur', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 0, 4, N'800000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 1, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-0000af22', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 1, 3, N'chq', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 1, 4, N'460000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 2, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-00008a10', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 2, 4, N'500000', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 3, 1, N'6c4d7196-fc87-4924-b4a5-ac40b1f640ab-0000896e', NULL, NULL);
INSERT INTO dbo.tp_section_data (section_id, row_idx, col_idx, cell_text, bg_color, fg_color) VALUES (20, 3, 4, N'176200', NULL, NULL);
GO

PRINT '======================================================';
PRINT 'STEP 6: Populating Team List, Bonus & Insurance Data...';
PRINT '======================================================';

-- team_list_data (155 cells)
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 0, N'S.N');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 1, N'Location');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 3, N'Name of Employee');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 8, N'1999');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 9, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 11, N'2081-82');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 12, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 14, N'2080-81');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 15, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 17, N'2079-80');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 18, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 20, N'2078-79');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 21, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 23, N'2077-78');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 24, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 26, N'2076-77');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 27, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 29, N'2075-76');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (0, 30, N'Salary');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 0, N'1');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 2, N'MANAGER');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 3, N'Team--Neeraj Ji');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 8, N'2082-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 9, N'100000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 20, N'2078-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 21, N'75000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 23, N'2077-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (1, 24, N'50000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (2, 0, N'2');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (2, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (2, 2, N'CRM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (2, 3, N'Team-Madhav Ghimire');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (2, 17, N'2079-11');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (2, 18, N'40000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 0, N'3');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 2, N'CRM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 3, N'Team-Naresh Kushwaha');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 14, N'2080-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 15, N'40000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 20, N'2078-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 21, N'30000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 23, N'2077-08');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (3, 24, N'25000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 0, N'4');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 2, N'ADMIN');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 3, N'Team-Harsana');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 8, N'2082-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 9, N'40000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 20, N'2078-01');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 21, N'30000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 26, N'2076-05');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 27, N'10000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 29, N'2075-11');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (4, 30, N'7000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (5, 0, N'5');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (5, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (5, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (5, 3, N'Team--Srijana Giri');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (5, 8, N'2082-12');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (5, 9, N'20000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (6, 0, N'6');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (6, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (6, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (6, 3, N'Team--Puja Sharma');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 0, N'7');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 3, N'Team-Roman Rajbanshi');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 8, N'2082-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 9, N'24000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 11, N'2081-02');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 12, N'20000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 20, N'2078-12');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (7, 21, N'15000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 0, N'8');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 3, N'Team-Surendra Paswan');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 8, N'2082-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 9, N'19000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 14, N'2081-01');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 15, N'17000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 17, N'2079-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (8, 18, N'15000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 0, N'9');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 3, N'Team-Manish Sharma');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 8, N'2082-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 9, N'19000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 14, N'2080-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 15, N'17000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 20, N'2078-05');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (9, 21, N'15000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 0, N'10');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 3, N'Team--Ashok Sahani');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 11, N'2082-01');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 12, N'17000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 23, N'2077-11');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (10, 24, N'15000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (11, 0, N'11');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (11, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (11, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (11, 3, N'Team--Dinesh Chaurasiya');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (11, 8, N'2082-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (11, 9, N'20000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (12, 0, N'13');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (12, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (12, 2, N'CRM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (12, 3, N'Team--Rabindra Yadav');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (12, 8, N'2082-08');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (12, 9, N'25-30k');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (13, 0, N'14');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (13, 1, N'HO');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (13, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (13, 3, N'Team--Raushan Kumar Yadav');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (13, 8, N'2082-07');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (13, 9, N'30000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 0, N'16');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 1, N'BTM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 2, N'CRM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 3, N'Team-Rajeev Kr.Chaurasiya');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 17, N'2078-09');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 18, N'50000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 20, N'2078-01');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 21, N'40000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 23, N'2077-10');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (14, 24, N'25000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 0, N'18');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 1, N'JNK');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 2, N'CRM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 3, N'Team--Shailendra Shrivastav');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 20, N'2079-03');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 21, N'30000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 23, N'2078-01');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (15, 24, N'25000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 0, N'21');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 1, N'NGT');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 2, N'CRM');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 3, N'Team--Ashwini Gupta');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 11, N'2081-04');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 12, N'30000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 14, N'2081-02');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (16, 15, N'25000');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (17, 0, N'23');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (17, 1, N'NGT');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (17, 2, N'Office Member');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (17, 3, N'Team--Basistha  Chaurasiya');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (17, 8, N'2082-07');
INSERT INTO dbo.team_list_data (row_idx, col_idx, cell_text) VALUES (17, 9, N'20000');
GO

-- bonus_data (80 cells)
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (0, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (0, 1, N'MANAGER');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (0, 2, N'Team--Neeraj Ji');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (0, 3, N'15000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (1, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (1, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (1, 2, N'Team-Madhav Ghimire');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (1, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (2, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (2, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (2, 2, N'Team-Naresh Kushwaha');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (2, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (3, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (3, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (3, 2, N'Team-Anjay Mishra');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (3, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (4, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (4, 1, N'ADMIN');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (4, 2, N'Team-Harsana');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (4, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (5, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (5, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (5, 2, N'Team-Roman Rajbanshi');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (5, 3, N'3000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (6, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (6, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (6, 2, N'Team-Manish Sharma');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (6, 3, N'3000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (7, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (7, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (7, 2, N'Team--Ashok Sahani');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (7, 3, N'3000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (8, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (8, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (8, 2, N'Team--Dinesh Chaurasiya');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (8, 3, N'1100.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (9, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (9, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (9, 2, N'Team--Ram Chandra Guard');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (9, 3, N'3000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (10, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (10, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (10, 2, N'Team--Rabindra Yadav');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (11, 0, N'HO');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (11, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (11, 2, N'Team--Raushan Kumar Yadav');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (12, 0, N'BTM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (12, 1, N'BM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (12, 2, N'Team--Nikhil Singh');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (12, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (13, 0, N'BTM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (13, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (13, 2, N'Team-Rajeev Kr.Chaurasiya');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (13, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (14, 0, N'BTM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (14, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (14, 2, N'Team- Santosh Singh');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (14, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (15, 0, N'BTM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (15, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (15, 2, N'Team- Ram Pujan Shah');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (16, 0, N'JNK');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (16, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (16, 2, N'Team--Shailendra Shrivastav');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (16, 3, N'10000.0');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (17, 0, N'JNK');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (17, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (17, 2, N'Team--Bijay Kumar Das');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (18, 0, N'NGT');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (18, 1, N'BM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (18, 2, N'Team--Vivek Singh');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (19, 0, N'NGT');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (19, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (19, 2, N'Team--Ashwini Gupta');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (20, 0, N'NGT');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (20, 1, N'CRM');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (20, 2, N'Team--Pramendra Karn');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (21, 0, N'NGT');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (21, 1, N'Office Member');
INSERT INTO dbo.bonus_data (row_idx, col_idx, cell_text) VALUES (21, 2, N'Team--Basistha  Chaurasiya');
GO

-- ins_vehicle (3 cells)
INSERT INTO dbo.ins_vehicle (row_idx, col_idx, cell_text) VALUES (-2, 0, N'110');
INSERT INTO dbo.ins_vehicle (row_idx, col_idx, cell_text) VALUES (-2, 2, N'110');
INSERT INTO dbo.ins_vehicle (row_idx, col_idx, cell_text) VALUES (-2, 5, N'747');
GO

-- ins_stock (3 cells)
INSERT INTO dbo.ins_stock (row_idx, col_idx, cell_text) VALUES (-2, 0, N'110');
INSERT INTO dbo.ins_stock (row_idx, col_idx, cell_text) VALUES (-2, 2, N'110');
INSERT INTO dbo.ins_stock (row_idx, col_idx, cell_text) VALUES (-2, 5, N'747');
GO

PRINT '======================================================';
PRINT 'STEP 7: Populating Shared Table Columns...';
PRINT '======================================================';

INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'bonus_data', 0, N'Location', 154);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'bonus_data', 1, N'Post', 106);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'bonus_data', 2, N'Name of Employee', 186);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'bonus_data', 3, N'Diwali Bonus', 93);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'bonus_data', 4, N'Remarks', 714);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_human', 0, N'Location', 80);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_human', 1, N'Post', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_human', 2, N'Name of Employee', 200);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_human', 3, N'Amount', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_human', 4, N'Starting Date', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_human', 5, N'Ending Date', 689);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_stock', 0, N'Location', 80);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_stock', 1, N'Post', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_stock', 2, N'Description', 200);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_stock', 3, N'Amount', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_stock', 4, N'Starting Date', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_stock', 5, N'Ending Date', 689);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_vehicle', 0, N'Location', 80);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_vehicle', 1, N'Post', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_vehicle', 2, N'Name of Employee', 200);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_vehicle', 3, N'Amount', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_vehicle', 4, N'Starting Date', 110);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'ins_vehicle', 5, N'Ending Date', 689);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 0, N'S.N', 0);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 1, N'Location', 68);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 2, N'Post', 106);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 3, N'Name of Employee', 186);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 4, N'', 30);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 5, N'2083-84', 90);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 6, N'Salary', 90);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 7, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 8, N'2082-83', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 9, N'Salary', 61);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 10, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 11, N'2081-82', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 12, N'Salary', 54);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 13, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 14, N'2080-81', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 15, N'Salary', 54);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 16, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 17, N'2079-80', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 18, N'Salary', 54);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 19, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 20, N'2078-79', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 21, N'Salary', 54);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 22, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 23, N'2077-78', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 24, N'Salary', 54);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 25, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 26, N'2076-77', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 27, N'Salary', 54);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 28, N'', 19);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 29, N'2075-76', 67);
INSERT INTO dbo.shared_table_cols (table_name, col_index, col_name, col_width) VALUES (N'team_list_data', 30, N'Salary', 54);
GO

PRINT '======================================================';
PRINT 'STEP 8: Granting permissions and verifying row counts...';
PRINT '======================================================';
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.supplier_records TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.supplier_accounts TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.anil_ledger TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.anil_settings TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.team_list_data TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.bonus_data TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.payment_sheet_data TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.tp_sections TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.tp_section_cols TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.tp_section_data TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.ins_human TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.ins_vehicle TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.ins_stock TO public;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.shared_table_cols TO public;

SELECT t.name AS [Table], SUM(p.rows) AS [Row_Count]
FROM sys.tables t
JOIN sys.partitions p ON t.object_id = p.object_id
WHERE p.index_id IN (0, 1)
  AND t.name IN (
    'supplier_records', 'supplier_accounts',
    'anil_ledger', 'anil_settings',
    'tp_sections', 'tp_section_cols', 'tp_section_data',
    'team_list_data', 'bonus_data', 'payment_sheet_data',
    'ins_human', 'ins_vehicle', 'ins_stock', 'shared_table_cols'
  )
GROUP BY t.name
ORDER BY t.name;

PRINT '======================================================';
PRINT 'SUPPLIER PAYMENT MODULE SETUP COMPLETED SUCCESSFULLY!';
PRINT '======================================================';
GO
