import sqlite3
import os

class CatalogLogic:
    def __init__(self, db_path):
        self.db_path = db_path
    
    def get_index_data(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

    def get_page_data_list(self):
        pass
    pass