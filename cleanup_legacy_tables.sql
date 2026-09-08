-- ============================================================
-- CLEANUP LEGACY SUPP PAYMENT TABLES
-- These tables belong to an old version of the software 
-- and are completely safe to drop to save space.
-- ============================================================

USE [JK_HW_Divison_082083_793e9c60];
GO

IF OBJECT_ID('dbo.anil_grid_data', 'U') IS NOT NULL DROP TABLE dbo.anil_grid_data;
IF OBJECT_ID('dbo.bonus_grid_data', 'U') IS NOT NULL DROP TABLE dbo.bonus_grid_data;
IF OBJECT_ID('dbo.ins_grid_data', 'U') IS NOT NULL DROP TABLE dbo.ins_grid_data;
IF OBJECT_ID('dbo.record_detailed_data', 'U') IS NOT NULL DROP TABLE dbo.record_detailed_data;
IF OBJECT_ID('dbo.record_grid_data', 'U') IS NOT NULL DROP TABLE dbo.record_grid_data;
IF OBJECT_ID('dbo.teamlist_grid_data', 'U') IS NOT NULL DROP TABLE dbo.teamlist_grid_data;
IF OBJECT_ID('dbo.tp_grid_data', 'U') IS NOT NULL DROP TABLE dbo.tp_grid_data;

PRINT 'Legacy Supp Payment tables successfully removed!';
