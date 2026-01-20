from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

class WelcomeUI(QLabel):
    def __init__(self):
        super().__init__("WELCOME TO\nJK CATALOG")
        
        # QSS में टारगेट करने के लिए नाम
        self.setObjectName("WelcomeScreenLabel") 
        
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # नोट: यहाँ से हार्ड-कोडेड स्टाइल हटा दी गई है ताकि style.qss इसे ओवरराइड कर सके।
        # self.setStyleSheet("font-size: 42px; font-weight: bold; color: #2c3e50;")
        # Note: The above style is kept as fallback/inline preference if needed, 
        # but style.qss has a richer definition for #WelcomeScreenLabel.
        # To use QSS fully, we can comment this out:
        # self.setStyleSheet("")