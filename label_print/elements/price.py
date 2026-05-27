from reportlab.lib.units import mm

def draw(canvas, config, data, label_height):
    field = config.get('field', 'unit_price')
    price_val = data.get(field, 0.0)
    currency = config.get('currency', '$')
    
    display_text = f"{currency}{price_val:.2f}"
    
    x = config.get('x', 0) * mm
    y = label_height - (config.get('y', 0) * mm)
    font_size = config.get('font_size', 20)
    
    available = canvas.getAvailableFonts()
    # 优先使用 MSYH 粗体，如果没有则使用 MSYH，最后回退 Helvetica
    font_name = "MSYH" if "MSYH" in available else "Helvetica-Bold"
    
    canvas.setFont(font_name, font_size)
    # Price often needs to be slightly lower than text
    canvas.drawString(x, y - (font_size * 0.8), display_text)