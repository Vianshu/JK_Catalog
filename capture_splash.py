import os
import time
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

def capture_html_to_png(html_path, output_png):
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=600,500")
    chrome_options.add_argument("--hide-scrollbars")
    
    # Initialize WebDriver
    print("Initializing Chrome...")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return False
        
    try:
        # Get absolute path to html
        abs_path = "file:///" + os.path.abspath(html_path).replace("\\", "/")
        print(f"Loading {abs_path}")
        driver.get(abs_path)
        
        # Wait a moment for fonts to load
        time.sleep(2)
        
        # Take screenshot
        driver.save_screenshot(output_png)
        print(f"Saved {output_png}")
    finally:
        driver.quit()
        
    return True

def create_inno_wizards(splash_png):
    # WizardImageFile (164x314) - Crop from left side or center
    img = Image.open(splash_png)
    
    # Center crop for 164x314
    w, h = 164, 314
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    wizard_img = img.crop((left, top, left + w, top + h))
    wizard_img.save("WizardImageFile.bmp", "BMP")
    print("Saved WizardImageFile.bmp")

    # WizardSmallImageFile (55x58) - Crop from center logo area
    w2, h2 = 55, 58
    left2 = (img.width - w2) // 2
    # Logo is higher up, let's crop near the top center
    top2 = 60
    wizard_small = img.crop((left2, top2, left2 + w2, top2 + h2))
    wizard_small.save("WizardSmallImageFile.bmp", "BMP")
    print("Saved WizardSmallImageFile.bmp")

if __name__ == "__main__":
    success = capture_html_to_png("splash_design.html", "splash.png")
    if success:
        create_inno_wizards("splash.png")
