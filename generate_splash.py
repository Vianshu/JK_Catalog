import os
from PIL import Image, ImageDraw, ImageFont
import math

def create_splash_png(output_path, icon_path):
    width, height = 700, 480
    
    # Very dark navy/teal background
    bg_color = (13, 20, 31) 
    
    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # 1. Add Logo
    try:
        icon = Image.open(icon_path)
        # resize icon to 180x180
        icon = icon.resize((180, 180), Image.Resampling.LANCZOS)
        # convert to RGBA
        icon = icon.convert("RGBA")
        
        logo_x = (width - 180) // 2
        logo_y = 60
        img.paste(icon, (logo_x, logo_y), icon)
    except Exception as e:
        print(f"Failed to load icon: {e}")
        
    # 2. Add Title Text
    # Try to load a nice font, fallback to default
    font_large = None
    try:
        # Try finding Arial or Segoe UI
        font_large = ImageFont.truetype("arialbd.ttf", 44)
    except:
        font_large = ImageFont.load_default()
        
    title = "JK Catalog Multi"
    
    # get text size
    # bbox = left, top, right, bottom
    bbox = draw.textbbox((0, 0), title, font=font_large)
    tw = bbox[2] - bbox[0]
    tx = (width - tw) // 2
    ty = 260
    draw.text((tx, ty), title, fill=(255, 255, 255, 255), font=font_large)
    
    # 3. Add Separator Line (Gradient-like or two-tone)
    line_y = 330
    line_w = 200
    line_x = (width - line_w) // 2
    
    # Teal segment
    draw.line([(line_x, line_y), (line_x + line_w//2, line_y)], fill=(11, 155, 138, 255), width=2)
    # Orange segment
    draw.line([(line_x + line_w//2, line_y), (line_x + line_w, line_y)], fill=(255, 140, 0, 255), width=2)
    
    # 4. Add "Loading, please wait..." text
    font_small = None
    try:
        font_small = ImageFont.truetype("arial.ttf", 18)
    except:
        font_small = ImageFont.load_default()
        
    loading_text = "Loading, please wait..."
    bbox2 = draw.textbbox((0, 0), loading_text, font=font_small)
    tw2 = bbox2[2] - bbox2[0]
    tx2 = (width - tw2) // 2
    ty2 = 350
    draw.text((tx2, ty2), loading_text, fill=(11, 155, 138, 255), font=font_small)
    
    # 5. Draw a static circular spinner (since PyInstaller splash is static)
    spinner_y = 400
    spinner_x = width // 2
    spinner_r = 16
    
    # Draw a faint circle
    draw.arc([spinner_x - spinner_r, spinner_y - spinner_r, spinner_x + spinner_r, spinner_y + spinner_r], 0, 360, fill=(30, 50, 70, 255), width=4)
    # Draw a bright arc segment
    draw.arc([spinner_x - spinner_r, spinner_y - spinner_r, spinner_x + spinner_r, spinner_y + spinner_r], -90, 45, fill=(11, 155, 138, 255), width=4)

    # Save to disk
    # Convert RGBA to RGB (with black/dark background) if saving as JPEG, but PNG handles RGBA.
    # We'll save as PNG for main.py / pyinstaller
    img.save(output_path, "PNG")
    print(f"Saved {output_path}")

def create_inno_wizards(icon_path):
    # WizardImageFile (164x314) - Large side image for Inno Setup Welcome/Finish pages
    w, h = 164, 314
    bg_color = (13, 20, 31) 
    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)
    
    try:
        icon = Image.open(icon_path).convert("RGBA")
        icon = icon.resize((100, 100), Image.Resampling.LANCZOS)
        img.paste(icon, ((w-100)//2, (h-100)//2 - 40), icon)
    except: pass
    
    try:
        font = ImageFont.truetype("arialbd.ttf", 18)
    except:
        font = ImageFont.load_default()
        
    title = "JK Catalog\nMulti"
    draw.text((15, 230), title, fill=(255, 255, 255), font=font, align="center")
    
    img.save("WizardImageFile.bmp", "BMP")
    print("Saved WizardImageFile.bmp")

    # WizardSmallImageFile (55x58) - Small top-right icon for other pages
    w2, h2 = 55, 58
    img2 = Image.new("RGB", (w2, h2), bg_color)
    try:
        icon2 = Image.open(icon_path).convert("RGBA")
        icon2 = icon2.resize((45, 45), Image.Resampling.LANCZOS)
        img2.paste(icon2, (5, 6), icon2)
    except: pass
    
    img2.save("WizardSmallImageFile.bmp", "BMP")
    print("Saved WizardSmallImageFile.bmp")

if __name__ == "__main__":
    create_splash_png("splash.png", "JK_Icon.ico")
    create_inno_wizards("JK_Icon.ico")
