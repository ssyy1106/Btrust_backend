from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm
from reportlab.graphics import renderPDF

def draw(canvas, config, data, label_height):
    field = config.get('field', 'barcode')
    barcode_val = str(data.get(field, ''))
    if not barcode_val:
        return

    x = config.get('x', 0) * mm
    # Barcode width/height
    bw = config.get('width', 35) * mm
    bh = config.get('height', 8) * mm
    
    # Barcode y from top
    y = label_height - (config.get('y', 0) * mm) - bh

    barcode_obj = code128.Code128(barcode_val, barHeight=bh, barWidth=1.2)
    # code128 drawOn uses the provided x, y as the bottom-left of the barcode
    barcode_obj.drawOn(canvas, x, y)