# models/product.py
from sqlalchemy import Column, Integer, String, ForeignKey, Float, DateTime
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
