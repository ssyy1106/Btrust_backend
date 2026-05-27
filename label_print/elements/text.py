from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics


DEFAULT_FONT = "MSYH"
def draw(canvas, config, data, label_height):
    field = config.get('field')
    text_val = str(data.get(field, ''))
    if not text_val:
        return

    x = config.get('x', 0) * mm
    # Config Y is from label top, convert to ReportLab bottom-up
    y = label_height - (config.get('y', 0) * mm)
    font_size = config.get('font_size', 10)
    
    # 检查 MSYH 字体是否已注册，如果已注册则支持中文
    available = canvas.getAvailableFonts()
    #font_name = "MSYH" if "MSYH" in available else "MSYH"
    font_name = config.get("font") or DEFAULT_FONT
    if config.get('bold') and f"{font_name}-Bold" in available:
        font_name = f"{font_name}-Bold"

    canvas.setFont(font_name, font_size)
    
    # Adjust y slightly so text isn't cut off (drawing string starts at baseline)
    # Standard offset is ~80% of font size for top alignment
    canvas.drawString(x, y - (font_size * 0.8), text_val)