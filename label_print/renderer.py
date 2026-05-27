from reportlab.lib.units import mm
from .elements import text, price, barcode

class LabelRenderer:
    def __init__(self, canvas, elements_config):
        self.canvas = canvas
        self.elements = elements_config
        self.drawers = {
            'text': text.draw,
            'price': price.draw,
            'barcode': barcode.draw
        }

    def render_label(self, x, y, data, label_width_pts, label_height_pts):
        """
        x, y: Bottom-left coordinate of the label on the page (in points)
        """
        self.canvas.saveState()
        # Move origin to the bottom-left of the current label
        self.canvas.translate(x, y)
        
        for elem in self.elements:
            elem_type = elem.get('type')
            drawer = self.drawers.get(elem_type)
            if drawer:
                # We pass label_height_pts to drawers so they can calculate 
                # coordinates from the top down if needed.
                drawer(self.canvas, elem, data, label_height_pts)
        
        self.canvas.restoreState()