from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, JSON, Time, BigInteger 
from sqlalchemy.orm import relationship
from database import Base
import datetime
from pydantic import BaseModel
from typing import List, Optional

class Invoice(Base):
    __tablename__ = "invoice"

    id = Column(Integer, primary_key=True, index=True)
    createtime = Column(DateTime, default=datetime.datetime.now())
    modifytime = Column(DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    creatorid = Column(BigInteger)
    modifierid = Column(BigInteger)
    number = Column(String, index=True)
    status = Column(Integer, default=0)
    totalamount = Column(Float)
    remark = Column(String)
    invoicedate = Column(Date)
    entrytime = Column(Date)
    #department = Column(Integer)
    store = Column(String)
    #supplier = Column(BigInteger)
    supplierid = Column(BigInteger, ForeignKey("supplier.id"))  # ✅ 加入供应商外键

    supplier = relationship("Supplier", back_populates="invoices", lazy="joined")  # ✅ 反向关系
    details = relationship("InvoiceDetail", back_populates="invoice", cascade="all, delete-orphan", lazy="selectin")
    attachments = relationship("InvoiceAttachment", back_populates="invoice", lazy="selectin")


class InvoiceDetail(Base):
    __tablename__ = "invoicedetail"

    id = Column(Integer, primary_key=True, index=True)
    invoiceid = Column(Integer, ForeignKey("invoice.id"))
    createtime = Column(DateTime, default=datetime.datetime.now())
    modifytime = Column(DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    creatorid = Column(BigInteger)
    modifierid = Column(BigInteger)
    status = Column(Integer, default=0)
    totalamount = Column(Float)
    department = Column(Integer)

    invoice = relationship("Invoice", back_populates="details", lazy="selectin")

class InvoiceAttachment(Base):
    __tablename__ = "invoiceattachment"

    id = Column(Integer, primary_key=True, index=True)
    createtime = Column(DateTime, default=datetime.datetime.now())
    modifytime = Column(DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    creatorid = Column(BigInteger)
    modifierid = Column(BigInteger)
    invoiceid = Column(Integer, ForeignKey("invoice.id"))  # 加外键 ✅
    status = Column(Integer)
    path = Column(String)
    thumbnail = Column(String)
    sort = Column(Integer)
    # 反向关系：一个附件对应一个发票
    invoice = relationship("Invoice", back_populates="attachments")
    def __repr__(self):
        return f"<InvoiceAttachment(id={self.id}, invoiceid={self.invoiceid}, path={self.path})>"
    

class Supplier(Base):
    __tablename__ = "supplier"

    id = Column(BigInteger, primary_key=True, index=True)
    createtime = Column(DateTime, default=datetime.datetime.now())
    modifytime = Column(DateTime, default=datetime.datetime.now(), onupdate=datetime.datetime.now())
    creatorid = Column(BigInteger)
    modifierid = Column(BigInteger)
    name = Column(JSON, nullable=False)  #{ "zh": "供应商名", "en": "Supplier Name" }
    status = Column(Integer, default=0)
    telephone = Column(String, default="")
    remark = Column(String)
    email = Column(String)
    contact = Column(String)

    invoices = relationship("Invoice", back_populates="supplier", lazy="selectin")
    def __repr__(self):
        return f"id is {self.id} name is {self.name}"
