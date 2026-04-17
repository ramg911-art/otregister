from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Boolean
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
    role = Column(String(32), default="optometrist")


class RolePermission(Base):
    """Per-role toggles for granular modules (see app.permission_modules)."""

    __tablename__ = "role_permissions"

    role = Column(String(32), primary_key=True)
    module_key = Column(String(64), primary_key=True)
    allowed = Column(Boolean, nullable=False, default=False)


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
    # EMR (SKP) internal patient id from search; used to refresh phone without UHID lookup
    patient_emr_id = Column(String(50), nullable=True)
    patient_phone = Column(String(32), nullable=True)

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

    patient_feedback = relationship(
        "PatientFeedback",
        back_populates="ot_register",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PatientFeedback(Base):
    """Post-discharge feedback for an OT register row (one row per case)."""

    __tablename__ = "patient_feedback"

    id = Column(Integer, primary_key=True, index=True)
    ot_register_id = Column(
        Integer,
        ForeignKey("ot_register.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    feedback_call_done = Column(Boolean, default=False)
    call_marked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    rating = Column(Integer, nullable=True)  # 1–5
    comments = Column(Text, nullable=True)

    # "correct" | "incorrect" — medicine administration
    medicine_administration = Column(String(16), nullable=True)

    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    ot_register = relationship("OTRegister", back_populates="patient_feedback")
    call_marked_by = relationship("User", foreign_keys=[call_marked_by_user_id])
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])


class IntravitrealDrugMaster(Base):
    __tablename__ = "intravitreal_drug_master"

    id = Column(Integer, primary_key=True, index=True)
    drug_name = Column(String, unique=True, nullable=False)