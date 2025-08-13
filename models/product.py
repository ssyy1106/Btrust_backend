# models/product.py
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database import Base_odoo

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
