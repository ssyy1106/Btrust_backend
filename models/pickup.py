from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from database import Base_pickup

class SaleOrder(Base_pickup):
    __tablename__ = 'sale_order'
    id = Column(Integer, primary_key=True)
    date_order = Column(DateTime)
    state = Column(String)  # e.g. 'sale' for confirmed
    company_id = Column(Integer)

class SaleOrderLine(Base_pickup):
    __tablename__ = 'sale_order_line'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('sale_order.id'))
    product_id = Column(Integer)
    product_uom_qty = Column(Float)
    order = relationship("SaleOrder", backref="order_lines")

class ProductProduct(Base_pickup):
    __tablename__ = 'product_product'
    id = Column(Integer, primary_key=True)
    default_code = Column(String)

class ResCompany(Base_pickup):
    __tablename__ = 'res_company'
    id = Column(Integer, primary_key=True)
    name = Column(String)

