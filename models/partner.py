from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base_odoo

class ResPartner(Base_odoo):
    __tablename__ = 'res_partner'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    parent_id = Column(Integer, ForeignKey('res_partner.id'))

    # 自关联：parent partner
    parent = relationship("ResPartner", remote_side=[id], backref="children")
    users = relationship("ResUsers", back_populates="partner")
