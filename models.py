from sqlalchemy.orm import declarative_base,relationship
from sqlalchemy import Column, BigInteger, String, Integer, Boolean, DateTime, ForeignKey
from datetime import datetime, timezone
from config import engine

Base = declarative_base()

class AccountLog(Base):
    __tablename__ = 'account_logs'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    account_id = Column(BigInteger, nullable=False)
    action_date = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    action = Column(String, nullable=False, default='taken')



class Email(Base):
    __tablename__ = 'emails'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    login = Column(String, nullable=True)
    password = Column(String, nullable=True)
    accountfk = Column(BigInteger, ForeignKey('accounts.id'), nullable=False)

    account = relationship("Account", back_populates="emails")


class User(Base):
    __tablename__ = 'users'
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_approved = Column(Boolean, default=False)
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))



class Account(Base):
    __tablename__ = 'accounts'
    id = Column(BigInteger, primary_key=True)
    login = Column(String)
    password = Column(String)
    behavior = Column(Integer)
    mmr = Column(Integer)
    calibration = Column(Boolean, default=False)
    status = Column(String)  # free or rented
    rented_at = Column(DateTime, nullable=True)
    renter_id = Column(Integer, nullable=True)
    rent_duration = Column(Integer, nullable=True)

    emails = relationship("Email", back_populates="account", cascade="all, delete-orphan")
Base.metadata.create_all(engine)
