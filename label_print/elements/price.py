from reportlab.lib.units import mm

# def draw(canvas, config, data, label_height):
#     field = config.get('field', 'unit_price')
#     price_val = data.get(field, 0.0)
#     currency = config.get('currency', '$')
    
#     display_text = f"{currency}{price_val:.2f}"
    
#     x = config.get('x', 0) * mm
#     y = label_height - (config.get('y', 0) * mm)
#     font_size = config.get('font_size', 20)
    
#     available = canvas.getAvailableFonts()
#     # 优先使用 MSYH 粗体，如果没有则使用 MSYH，最后回退 Helvetica
#     font_name = "MSYH" if "MSYH" in available else "Helvetica-Bold"
    
#     canvas.setFont(font_name, font_size)
#     # Price often needs to be slightly lower than text
#     canvas.drawString(x, y - (font_size * 0.8), display_text)


def draw(canvas, config, data, label_height):
    value = data.get(config["field"])
    if value is None:
        return

    price = float(value)
    dollars = int(price)
    cents = int(round((price - dollars) * 100))

    x = config.get("x", 0) * mm
    y = label_height - config.get("y", 0) * mm

    font = config.get("font", "MSYH")
    currency = config.get("currency", "$")
    unit = data.get(config.get("unit_field", "unit"), "ea")

    dollar_size = config.get("dollar_font_size", config.get("font_size", 20))
    cent_size = config.get("cent_font_size", int(dollar_size * 0.55))
    currency_size = config.get("currency_font_size", int(dollar_size * 0.45))
    unit_size = config.get("unit_font_size", int(dollar_size * 0.3))

    canvas.setFont(font, currency_size)
    canvas.drawString(x, y - dollar_size * 0.75, currency)

    canvas.setFont(font, dollar_size)
    dollar_x = x + 8 * mm
    canvas.drawString(dollar_x, y - dollar_size * 0.85, str(dollars))

    dollar_width = canvas.stringWidth(str(dollars), font, dollar_size)

    canvas.setFont(font, cent_size)
    cent_x = dollar_x + dollar_width + 1 * mm
    canvas.drawString(cent_x, y - cent_size * 0.45, f"{cents:02d}")

    canvas.setFont(font, unit_size)
    canvas.drawString(cent_x + 8 * mm, y - dollar_size * 0.85, f"/{unit}")