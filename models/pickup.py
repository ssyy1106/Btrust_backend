from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from database import Base_odoo

class SaleOrder(Base_odoo):
    __tablename__ = 'sale_order'
    id = Column(Integer, primary_key=True)
    date_order = Column(DateTime)
    state = Column(String)  # e.g. 'sale' for confirmed
    company_id = Column(Integer)
    user_id = Column(Integer, ForeignKey('res_users.id'))  # 下单用户ID

    user = relationship("ResUsers", lazy='joined')

class SaleOrderLine(Base_odoo):
    __tablename__ = 'sale_order_line'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('sale_order.id'))
    product_id = Column(Integer)
    product_uom_qty = Column(Float)
    order = relationship("SaleOrder", backref="order_lines")

# class ProductProduct(Base_odoo):
#     __tablename__ = 'product_product'
#     id = Column(Integer, primary_key=True)
#     default_code = Column(String)

class ResCompany(Base_odoo):
    __tablename__ = 'res_company'
    id = Column(Integer, primary_key=True)
    name = Column(String)

