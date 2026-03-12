from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from sqlalchemy.orm import relationship


# --------------------------------------------------
# User table (for OT Register login)
# --------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="staff")


# --------------------------------------------------
# IOL Master table
# --------------------------------------------------
class IOLMaster(Base):
    __tablename__ = "iol_master"

    id = Column(Integer, primary_key=True, index=True)
    iol_name = Column(String(100), nullable=False)
    package = Column(String(50), nullable=False)

    # Relationship to OT Register
    ot_records = relationship(
        "OTRegister",
        back_populates="iol",
        cascade="all, delete-orphan"
    )


# --------------------------------------------------
# OT Register table
# --------------------------------------------------
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


from sqlalchemy import Date

class OTRegister(Base):
    __tablename__ = "ot_register"

    id = Column(Integer, primary_key=True, index=True)

    patient_uhid = Column(String)
    patient_name = Column(String)

    date_of_surgery = Column(Date, nullable=False)   # ✅ ADD THIS

    surgery = Column(String, nullable=False)
    category = Column(String)
    surgeon_name = Column(String)
    eye = Column(String)

    iol_id = Column(Integer, ForeignKey("iol_master.id"))
    iol = relationship("IOLMaster")

    intravitreal_drug_id = Column(
        Integer,
        ForeignKey("intravitreal_drug_master.id"),
        nullable=True
    )
    intravitreal_drug = relationship("IntravitrealDrugMaster")

    is_vue = Column(Boolean, default=False)
class IntravitrealDrugMaster(Base):
    __tablename__ = "intravitreal_drug_master"

    id = Column(Integer, primary_key=True, index=True)
    drug_name = Column(String, unique=True, nullable=False)