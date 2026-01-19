from PyQt6.QtWidgets import QLabel

class PaymentListUI(QLabel):
    def __init__(self):
        super().__init__("PAYMENT LIST SCREEN")
        self.setObjectName("PaymentListLabel")
        # self.setStyleSheet("font-size:24px;") # Moved to style.qss
