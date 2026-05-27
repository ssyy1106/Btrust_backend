import asyncio
import os
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from sqlalchemy import text, bindparam

from config_log_env import init_config, get_config
from database import init_database, get_db_store_sqlserver_factory, dispose_engines

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.ini"

def register_fonts():
    # 尝试加载微软雅黑字体以支持中文显示
    font_path = os.path.join(os.path.dirname(__file__), "label_print", "fonts", "msyh.ttc")
    if not os.path.exists(font_path):
        font_path = "C:/Windows/Fonts/msyh.ttc"
    
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('MSYH', font_path))

async def fetch_sales_data(store, subdepts, target_date):
    """
    从店面 SQL Server 数据库读取 RPT_ITM_D 表中多个子部门的销售数据并聚合
    """
    db_gen = get_db_store_sqlserver_factory(store)
    async for db in db_gen():
        query = text("""
            SELECT 
                R.F01 as upc,
                MAX(LTRIM(RTRIM(O.F29))) as name_en,
                MAX(CASE WHEN :store = 'MT' THEN LTRIM(RTRIM(O.F255)) ELSE COALESCE(LTRIM(RTRIM(P.F2095)), LTRIM(RTRIM(O.F255))) END) as name_cn,
                SUM(R.F64) as qty,
                SUM(R.F65) as amount,
                SUM(R.F67) as weight
            FROM RPT_ITM_D R
            LEFT JOIN OBJ_TAB O ON R.F01 = O.F01
            LEFT JOIN POS_TAB P ON R.F01 = P.F01
            LEFT JOIN SDP_TAB S ON P.F04 = S.F04
            WHERE R.F1034=3 AND CAST(R.F254 AS DATE) = :target_date
              AND S.F04 IN :subdepts
            GROUP BY R.F01
            ORDER BY SUM(R.F65) DESC
        """).bindparams(bindparam("subdepts", expanding=True))
        result = await db.execute(query, {"target_date": target_date, "subdepts": tuple(subdepts), "store": store})
        return result.all()

def generate_pdf(data, filename, title_info):
    """
    生成销售数据 PDF 表格
    """
    register_fonts()
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    has_msyh = 'MSYH' in pdfmetrics.getRegisteredFontNames()
    font_name = 'MSYH' if has_msyh else 'Helvetica'

    # 定义换行样式
    wrap_style = ParagraphStyle(
        name='WrapStyle',
        fontName=font_name,
        fontSize=9,
        leading=11,
        wordWrap='CJK'  # 支持中英文混合换行
    )

    # 标题
    # title = f"Sales Report: {title_info['date']} | Store: {title_info['store']} | SubDept: {title_info['subdept']}"
    title = f"Sales Report: {title_info['date']} |  {title_info['dept']}"
    elements.append(Paragraph(title, styles['Title']))
    elements.append(Spacer(1, 12))

    # 表格数据
    table_data = [["UPC", "English Name", "Chinese Name", "Qty", "Amount", "Weight"]]
    
    total_qty = 0
    total_amount = 0
    total_weight = 0

    for row in data:
        qty = float(row.qty or 0)
        amount = float(row.amount or 0)
        weight = float(row.weight or 0)
        
        total_qty += qty
        total_amount += amount
        total_weight += weight

        table_data.append([
            row.upc,
            Paragraph(row.name_en or "", wrap_style),
            Paragraph(row.name_cn or "", wrap_style),
            f"{qty:.2f}",
            f"{amount:.2f}",
            f"{weight:.2f}"
        ])

    # 增加合计行
    table_data.append(["TOTAL", "", "", f"{total_qty:.2f}", f"{total_amount:.2f}", f"{total_weight:.2f}"])

    # 创建表格并设置样式
    # 调整列宽：将 UPC 增加到 95，名称列缩减到 110，总宽保持 450 磅以适配 A4
    t = Table(table_data, colWidths=[95, 110, 110, 45, 45, 45], repeatRows=1)
    
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), # 默认居中
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),  # 数字列右对齐
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 9),      # 统一字体大小为 9
        ('LEFTPADDING', (0, 0), (-1, -1), 2),   # 减小内边距，给长 UPC 留出空间
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        # 合计行样式
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), f"{font_name}-Bold" if not has_msyh else font_name),
        ('SPAN', (0, -1), (2, -1)), # 合并前三列显示 TOTAL
    ]))
    elements.append(t)
    doc.build(elements)

def _get_ses_client():
    config = get_config()
    sender = config.get('AWS', 'sender')
    aws_region = config.get('AWS', 'region')
    access_key = config.get('AWS', 'access_key_id')
    secret_key = config.get('AWS', 'secret_access_key')
    
    client = boto3.client(
        "ses",
        region_name=aws_region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    return sender, client

def send_email(recipients, cc_recipients, subject, body, attachment_path):
    """
    使用 AWS SES 发送带有 PDF 附件的邮件
    """
    sender, client = _get_ses_client()
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = ", ".join(recipients)
    if cc_recipients:
        msg['Cc'] = ", ".join(cc_recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    with open(attachment_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
        msg.attach(part)

    try:
        all_recipients = recipients + cc_recipients
        response = client.send_raw_email(
            Source=sender,
            Destinations=all_recipients,
            RawMessage={
                'Data': msg.as_string(),
            },
        )
        print(f"Email sent! Message ID: {response['MessageId']}")
    except ClientError as e:
        print(f"Failed to send email: {e.response['Error']['Message']}")

async def main():
    init_config(CONFIG_PATH)
    init_database()
    try:
        config = get_config()
        
        if 'SaleEmail' not in config:
            print("Section [SaleEmail] not found in config.ini")
            return

        email_str = config['SaleEmail'].get('email', '')
        cc_str = config['SaleEmail'].get('cc', '')
        subdept_str = config['SaleEmail'].get('subdepartment', '')
        store_str = config['SaleEmail'].get('store', '')
        filename_map_str = config['SaleEmail'].get('filename', '')

        if not all([email_str, subdept_str, store_str]):
            print("Missing configuration in [SaleEmail]")
            return

        emails = [e.strip() for e in email_str.split(',') if e.strip()]
        cc_emails = [e.strip() for e in cc_str.split(',') if e.strip()]
        stores = [s.strip() for s in store_str.split(',') if s.strip()]
        subdepts = [sd.strip() for sd in subdept_str.split(',') if sd.strip()]
        filenames = [f.strip() for f in filename_map_str.split(',') if f.strip()]

        # 创建 store 代码到显示名称的映射，如果没有配置 filename 则回退使用 store 代码
        store_display_map = {stores[i]: filenames[i] if i < len(filenames) else stores[i] for i in range(len(stores))}
        
        yesterday = (datetime.now() - timedelta(days=1)).date()
        date_str = yesterday.strftime("%Y-%m-%d")

        for store in stores:
            store_display = store_display_map.get(store, store)
            print(f"Processing Store: {store} ({store_display}) for SubDepts: {subdepts} on {date_str}...")
            try:
                data = await fetch_sales_data(store, subdepts, yesterday)
                
                if not data:
                    print(f"No sales data found for store {store} yesterday.")
                    continue

                # 使用 config 中的 filename 配置代替店名代码
                filename = f"{date_str}_{store_display}_Sales_Report.pdf"
                pdf_path = BASE_DIR / filename

                # PDF 标题信息显示前 3 个子部门 ID 以免过长
                display_depts = ",".join(subdepts[:3]) + ("..." if len(subdepts) > 3 else "")
                # title_info = {"date": date_str, "store": store_display, "subdept": display_depts}
                title_info = {"date": date_str, "dept": store_display}

                generate_pdf(data, str(pdf_path), title_info)
                print(f"PDF generated: {filename}")

                subject = f"Daily Sales Report - {store_display} - {date_str}"
                body = f"Please find attached {store_display} Sales report of {date_str}."
                
                send_email(emails, cc_emails, subject, body, str(pdf_path))
                
                # 发送后清理 PDF 文件
                if pdf_path.exists():
                    os.remove(pdf_path)

            except Exception as e:
                print(f"An error occurred while processing store {store}: {e}")
    finally:
        await dispose_engines()

if __name__ == "__main__":
    asyncio.run(main())