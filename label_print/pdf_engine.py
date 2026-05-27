from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape, LETTER
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import os
from .renderer import LabelRenderer

# 注册中文字体
def register_chinese_fonts():
    # 尝试从 label_print/fonts 目录加载微软雅黑
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "msyh.ttc")
    if not os.path.exists(font_path):
        # 备选：尝试 Windows 系统路径
        font_path = "C:/Windows/Fonts/msyh.ttc"
    
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('MSYH', font_path))

register_chinese_fonts()

class LabelPDFEngine:
    def __init__(self, template_config):
        self.config = template_config
        self.page_config = template_config['page']
        self.label_config = template_config['label']
        self.grid_config = template_config['grid']
        
        # Initialize Page Size
        if self.page_config['paper'] == 'A4':
            self.pagesize = A4
        else:
            self.pagesize = LETTER
        if self.page_config.get('orientation') == 'landscape':
            self.pagesize = landscape(self.pagesize)
            
    def generate(self, products_data):
        """
        products_data: List of dicts, each containing product fields.
        Each dict should include a 'print_count' key.
        """
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=self.pagesize)
        page_w, page_h = self.pagesize
        
        rows = self.grid_config['rows']
        cols = self.grid_config['cols']
        label_w = self.label_config['width_mm'] * mm
        label_h = self.label_config['height_mm'] * mm
        h_gap = self.grid_config.get('horizontal_gap_mm', 0) * mm
        v_gap = self.grid_config.get('vertical_gap_mm', 0) * mm
        
        # Calculate starting margins to center the grid on A4
        grid_w = (cols * label_w) + ((cols - 1) * h_gap)
        grid_h = (rows * label_h) + ((rows - 1) * v_gap)
        margin_x = (page_w - grid_w) / 2
        margin_y = (page_h - grid_h) / 2

        renderer = LabelRenderer(c, self.config['elements'])
        
        curr_row = 0
        curr_col = 0
        
        for product in products_data:
            count = product.get('print_count', 1)
            for _ in range(count):
                if curr_row >= rows:
                    c.showPage()
                    curr_row = 0
                    curr_col = 0
                
                # Calculate X (Left to Right)
                pos_x = margin_x + curr_col * (label_w + h_gap)
                # Calculate Y (Top to Bottom in Grid, but ReportLab is Bottom to Top)
                # The top of the first row starts at (page_h - margin_y)
                pos_y = page_h - (margin_y + (curr_row + 1) * label_h + curr_row * v_gap)
                
                renderer.render_label(pos_x, pos_y, product, label_w, label_h)
                
                curr_col += 1
                if curr_col >= cols:
                    curr_col = 0
                    curr_row += 1
                    
        c.save()
        buffer.seek(0)
        return buffer