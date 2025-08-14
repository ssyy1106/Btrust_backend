from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base_odoo  # 你的Base模型定义
#from .partner import ResPartner 

class ResUsers(Base_odoo):
    __tablename__ = 'res_users'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)  # 用户名，可以加上
    login = Column(String)  # 登录账号
    email = Column(String(255))
    company_id = Column(Integer, ForeignKey('res_company.id'))
    partner_id = Column(Integer, ForeignKey('res_partner.id'))

    company = relationship("ResCompany", back_populates="users")
    partner = relationship("ResPartner", back_populates="users")

class ResCompany(Base_odoo):
    __tablename__ = 'res_company'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    country_id = Column(Integer)

    users = relationship("ResUsers", back_populates="company")
