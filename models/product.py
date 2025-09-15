# models/product.py
from sqlalchemy import Column, Integer, String, ForeignKey, Float, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database import Base_odoo, Base_store_sqlserver

class ObjTab(Base_store_sqlserver):
    __tablename__ = "OBJ_TAB"
    F01 = Column(String, primary_key=True)  # barcode
    F17 = Column(String)  # category code
    F29 = Column(String)  # 英文名
    F255 = Column(String) # 中文名
    F155 = Column(String) # 品牌
    F22 = Column(String) # 规格
    F23 = Column(String)
    F82 = Column(String) # 是否称重

class UMETab(Base_store_sqlserver):
    __tablename__ = "UME_TAB"
    F2173 = Column(String) # 英文名
    F1146 = Column(String, primary_key=True) # EN
    F23 = Column(String, primary_key=True) # ID

class CatTab(Base_store_sqlserver):
    __tablename__ = "CAT_TAB"
    F17 = Column(String, primary_key=True)   # category code
    F1023 = Column(String)                   # category 名称

class PriceTab(Base_store_sqlserver):
    __tablename__ = "PRICE_TAB"
    F01 = Column(String, primary_key=True)       # barcode
    F113 = Column(String, primary_key=True)      # 价格类型 REG/INSTORE/促销
    F35 = Column(DateTime, primary_key=True)     # 开始日期
    F129 = Column(DateTime) # 结束日期
    F30 = Column(Float)    # 单价
    F140 = Column(Float)   # 打包价金额
    F142 = Column(Integer) # 打包数量
    F33 = Column(String)   # 价格单位 I/E

class StockQuant(Base_odoo):
    __tablename__ = "stock_quant"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("product_product.id"), index=True)
    quantity = Column(Float)

class ProductCategory(Base_odoo):
    __tablename__ = "product_category"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    parent_id = Column(Integer, ForeignKey("product_category.id"), nullable=True)

    parent = relationship("ProductCategory", remote_side=[id], backref="children")


class ProductTemplate(Base_odoo):
    __tablename__ = "product_template"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(JSONB)
    categ_id = Column(Integer, ForeignKey("product_category.id"))
    type = Column(String)  # 'product', 'consu', 'service'

    category = relationship("ProductCategory", backref="templates")


class ProductProduct(Base_odoo):
    __tablename__ = "product_product"

    id = Column(Integer, primary_key=True, index=True)
    default_code = Column(String)  # itemCode
    barcode = Column(String)
    product_tmpl_id = Column(Integer, ForeignKey("product_template.id"))

    template = relationship("ProductTemplate", backref="variants")

class IrAttachment(Base_odoo):
    __tablename__ = "ir_attachment"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)  # 文件名，例如 'image_1920'
    res_model = Column(String)  # 关联模型，例如 'product.template'
    res_id = Column(Integer)    # 关联记录的 id
    store_fname = Column(String)  # filestore 中存储的文件名
    mimetype = Column(String)     # 文件类型，例如 'image/jpeg'
    type = Column(String)         # 文件存储类型：'binary' 或 'url'
