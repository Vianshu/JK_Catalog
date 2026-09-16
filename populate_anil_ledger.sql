USE [JK_HW_Divison_082083_e867f96e];
GO

-- ============================================================
-- POPULATE ANIL LEDGER ONLY
-- Source: Supp. Bank account recod.xlsx  (sheet: Anil Dai Hisab)
-- Run this on the client company database.
--
-- ROW 0: DR = 4,000,000 is the Opening Balance (Cash Payment).
--   The application reads row 0 DR as the starting amount.
-- ROWS 1+: DR is left blank here.
--   The app auto-calculates interest (18%/365 x days x prev balance).
-- CR: Cash payments received, stored as entered in the spreadsheet.
-- ============================================================

PRINT 'Clearing anil_ledger...';
DELETE FROM dbo.anil_ledger;

PRINT 'Inserting anil_ledger rows...';
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

PRINT 'Done. anil_ledger populated with 48 rows.';
GO