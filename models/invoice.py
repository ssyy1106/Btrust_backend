from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base
import datetime

class Invoice(Base):
    __tablename__ = "invoice"

    id = Column(Integer, primary_key=True, index=True)
    createtime = Column(DateTime, default=datetime.datetime.utcnow)
    modifytime = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    creatorid = Column(Integer)
    modifierid = Column(Integer)
    number = Column(String, index=True)
    status = Column(Integer, default=0)
    totalamount = Column(Float)
    remark = Column(String)
    invoicedate = Column(Date)
    entrytime = Column(Date)
    department = Column(Integer)

    details = relationship("InvoiceDetail", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceDetail(Base):
    __tablename__ = "invoicedetail"

    id = Column(Integer, primary_key=True, index=True)
    invoiceid = Column(Integer, ForeignKey("invoice.id"))
    createtime = Column(DateTime, default=datetime.datetime.utcnow)
    modifytime = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    creatorid = Column(Integer)
    modifierid = Column(Integer)
    status = Column(Integer, default=0)
    totalamount = Column(Float)
    department = Column(Integer)

    invoice = relationship("Invoice", back_populates="details")
