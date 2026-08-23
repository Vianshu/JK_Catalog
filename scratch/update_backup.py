import os

file_path = 'src/ui/main_window.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
'''        # ── 24-hour automatic backup ──────────────────────────────────────────
        # Hybrid trigger: fires every 24h while the app is open AND on
        # login if the company hasn’t been backed up in the past 24 hours.
        # Backups are PER-COMPANY and saved to a user-chosen folder.
        _24H_MS = 24 * 60 * 60 * 1_000  # 24 hours in milliseconds
        self._auto_backup_timer = QTimer(self)
        self._auto_backup_timer.setInterval(_24H_MS)''',
'''        # ── 12-hour automatic backup ──────────────────────────────────────────
        # Hybrid trigger: fires every 12h while the app is open AND on
        # login if the company hasn’t been backed up in the past 12 hours.
        # Backups are PER-COMPANY and saved to a user-chosen folder.
        _12H_MS = 12 * 60 * 60 * 1_000  # 12 hours in milliseconds
        self._auto_backup_timer = QTimer(self)
        self._auto_backup_timer.setInterval(_12H_MS)'''
)

content = content.replace(
'''            # ── Hybrid 24-hour auto-backup ──────────────────────────────────
            # 1. Check if this company was last backed up more than 24 h ago.
            #    If so, run a backup immediately (covers the ‘app was closed’ gap).
            # 2. (Re)start the repeating 24 h timer for as long as the app runs.
            if company_path and os.path.isdir(company_path):
                if getattr(self, '_auto_backup_timer', None) is not None:
                    self._auto_backup_timer.start()   # restarts if already running
                    logger.info("[AutoBackup] 24-hour backup timer started.")
                    self._check_startup_backup(company_path)''',
'''            # ── Hybrid 12-hour auto-backup ──────────────────────────────────
            # 1. Check if this company was last backed up more than 12 h ago.
            #    If so, run a backup immediately (covers the ‘app was closed’ gap).
            # 2. (Re)start the repeating 12 h timer for as long as the app runs.
            if company_path and os.path.isdir(company_path):
                if getattr(self, '_auto_backup_timer', None) is not None:
                    self._auto_backup_timer.start()   # restarts if already running
                    logger.info("[AutoBackup] 12-hour backup timer started.")
                    self._check_startup_backup(company_path)'''
)

content = content.replace(
'''    def _check_startup_backup(self, company_path: str):
        """Run a backup immediately on login if the last backup is >24 hours old.

        Reads the per-data-path last-backup timestamp from QSettings and triggers
        _run_auto_backup if needed.  Uses a short QTimer.singleShot delay so the
        main window has fully painted before the (potentially slow) backup starts.
        All companies sharing the same data path share one backup cycle per 24h.
        """
        from datetime import datetime, timezone
        _24H = 24 * 60 * 60  # seconds''',
'''    def _check_startup_backup(self, company_path: str):
        """Run a backup immediately on login if the last backup is >12 hours old.

        Reads the per-data-path last-backup timestamp from QSettings and triggers
        _run_auto_backup if needed.  Uses a short QTimer.singleShot delay so the
        main window has fully painted before the (potentially slow) backup starts.
        All companies sharing the same data path share one backup cycle per 12h.
        """
        from datetime import datetime, timezone
        _12H = 12 * 60 * 60  # seconds'''
)

content = content.replace(
'''        elapsed = now_ts - last_ts
        if elapsed >= _24H:
            logger.info(''','''        elapsed = now_ts - last_ts
        if elapsed >= _12H:
            logger.info(''')

content = content.replace(
'''            # Prune: keep only the 7 most recent backups for this data path
            try:
                folder = getattr(self, '_pending_backup_dir', '')
                prefix = f"JK_AutoBackup_{data_key}_"
                backups = sorted(
                    f for f in os.listdir(folder)
                    if f.startswith(prefix) and f.endswith(".jkbackup")
                )
                for old in backups[:max(0, len(backups) - 7)]:''',
'''            # Prune: keep only the 14 most recent backups for this data path
            try:
                folder = getattr(self, '_pending_backup_dir', '')
                prefix = f"JK_AutoBackup_{data_key}_"
                backups = sorted(
                    f for f in os.listdir(folder)
                    if f.startswith(prefix) and f.endswith(".jkbackup")
                )
                for old in backups[:max(0, len(backups) - 14)]:'''
)

content = content.replace(
'''        from datetime import datetime
        # Derive keys from the DATA PATH (parent of company), not the company itself.
        # This ensures all companies in the same data path share one backup per 24h.
        data_path        = os.path.dirname(os.path.normpath(company_path))
        data_key         = os.path.basename(data_path) if os.path.basename(data_path) else "DataRoot"
        today_str        = datetime.now().strftime("%Y-%m-%d")
        data_backup_dir  = os.path.join(backup_folder, data_key)''',
'''        from datetime import datetime
        # Derive keys from the DATA PATH (parent of company), not the company itself.
        # This ensures all companies in the same data path share one backup per 12h.
        data_path        = os.path.dirname(os.path.normpath(company_path))
        data_key         = os.path.basename(data_path) if os.path.basename(data_path) else "DataRoot"
        # Include AM/PM so we allow 2 backups per day (12-hour schedule)
        today_str        = datetime.now().strftime("%Y-%m-%d_%p")
        data_backup_dir  = os.path.join(backup_folder, data_key)'''
)

content = content.replace(
'''        # Guard 1: same-day file check (cross-user, cross-company)
        prefix = f"JK_AutoBackup_{data_key}_{today_str}"
        existing = [f for f in os.listdir(data_backup_dir)
                    if f.startswith(prefix) and f.endswith(".jkbackup")]
        if existing:
            logger.info(f"[AutoBackup] Today's backup already exists for '{data_key}': {existing[0]} — skipping.")
            return''',
'''        # Guard 1: same half-day file check (cross-user, cross-company)
        prefix = f"JK_AutoBackup_{data_key}_{today_str}"
        existing = [f for f in os.listdir(data_backup_dir)
                    if f.startswith(prefix) and f.endswith(".jkbackup")]
        if existing:
            logger.info(f"[AutoBackup] This half-day's backup already exists for '{data_key}': {existing[0]} — skipping.")
            return'''
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Replacements applied successfully')
