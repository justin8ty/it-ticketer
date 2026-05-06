from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship, synonym

from db import Base


class Requester(Base):
    __tablename__ = "requester"

    requester_id = Column(Integer, primary_key=True)
    requester_name = Column(String(255), nullable=False)
    requester_email = Column(String(255), nullable=False, index=True)
    requester_phone = Column(String(50), nullable=True)

    # Prototype notification fields; requester still has no login account.
    telegram_chat_id = Column(String(64), nullable=True)
    notification_preference = Column(String(20), nullable=False, default="BOTH")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tickets = relationship("Ticket", back_populates="requester")

    id = synonym("requester_id")
    name = synonym("requester_name")
    email = synonym("requester_email")
    phone = synonym("requester_phone")


class Technician(Base):
    __tablename__ = "technician"

    technician_id = Column(Integer, primary_key=True)
    technician_name = Column(String(255), nullable=False)
    technician_email = Column(String(255), unique=True, nullable=False)
    technician_phone = Column(String(50), nullable=True)
    technician_password_hash = Column(String(255), nullable=False)
    skill_group = Column(String(100), nullable=False, default="General")
    active_status = Column(Boolean, default=True)
    availability_status = Column(String(50), default="Available")  # Available / Busy / Off

    telegram_chat_id = Column(String(64), nullable=True)
    notification_preference = Column(String(20), nullable=False, default="BOTH")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tickets = relationship("Ticket", back_populates="assigned_technician")

    id = synonym("technician_id")
    name = synonym("technician_name")
    email = synonym("technician_email")
    phone = synonym("technician_phone")
    password_hash = synonym("technician_password_hash")
    is_active = synonym("active_status")
    availability = synonym("availability_status")


class Admin(Base):
    __tablename__ = "admin"

    admin_id = Column(Integer, primary_key=True)
    admin_name = Column(String(255), nullable=False)
    admin_email = Column(String(255), unique=True, nullable=False)
    admin_password_hash = Column(String(255), nullable=False)
    active_status = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    action_logs = relationship("AdminActionLog", back_populates="admin")

    id = synonym("admin_id")
    name = synonym("admin_name")
    email = synonym("admin_email")
    password_hash = synonym("admin_password_hash")
    is_active = synonym("active_status")


class Category(Base):
    __tablename__ = "category"

    category_id = Column(Integer, primary_key=True)
    category_name = Column(String(100), unique=True, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    tickets = relationship("Ticket", back_populates="category_ref")

    id = synonym("category_id")
    name = synonym("category_name")

    def __str__(self) -> str:
        return self.category_name


class Priority(Base):
    __tablename__ = "priority"

    priority_id = Column(Integer, primary_key=True)
    priority_name = Column(String(50), unique=True, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    tickets = relationship("Ticket", back_populates="priority_ref")

    id = synonym("priority_id")
    name = synonym("priority_name")

    def __str__(self) -> str:
        return self.priority_name


class Status(Base):
    __tablename__ = "status"

    status_id = Column(Integer, primary_key=True)
    status_name = Column(String(50), unique=True, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    tickets = relationship("Ticket", back_populates="status_ref")

    id = synonym("status_id")
    name = synonym("status_name")

    def __str__(self) -> str:
        return self.status_name


class Ticket(Base):
    __tablename__ = "ticket"

    ticket_id = Column(Integer, primary_key=True)
    issue_title = Column(String(255), nullable=False)
    tracking_token = Column(String(64), unique=True, nullable=False)
    description = Column(Text, nullable=False)

    # AI triage output stays on the ticket table by design.
    ai_summary = Column(Text, nullable=True)
    ai_suggestion = Column(Text, nullable=True)
    ai_suggested_skill_group = Column(String(100), nullable=True)
    ai_model = Column(String(100), nullable=True)
    ai_raw_json = Column(Text, nullable=True)
    health_questions_json = Column(Text, nullable=True)

    requester_id = Column(Integer, ForeignKey("requester.requester_id"), nullable=False)
    assigned_technician_id = Column(Integer, ForeignKey("technician.technician_id"), nullable=True)
    status_id = Column(Integer, ForeignKey("status.status_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("category.category_id"), nullable=False)
    priority_id = Column(Integer, ForeignKey("priority.priority_id"), nullable=False)

    # Admin governance fields used by the current closure override workflow.
    closure_override = Column(Boolean, default=False)
    override_reason = Column(Text, nullable=True)
    override_by_admin_id = Column(Integer, ForeignKey("admin.admin_id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requester = relationship("Requester", back_populates="tickets", lazy="joined")
    assigned_technician = relationship("Technician", back_populates="tickets", lazy="joined")
    override_by_admin = relationship("Admin", lazy="joined")
    status_ref = relationship("Status", back_populates="tickets", lazy="joined")
    category_ref = relationship("Category", back_populates="tickets", lazy="joined")
    priority_ref = relationship("Priority", back_populates="tickets", lazy="joined")
    messages = relationship("Message", back_populates="ticket")
    attachments = relationship("Attachment", back_populates="ticket")
    health_checks = relationship("HealthCheck", back_populates="ticket")
    closure_confirmations = relationship(
        "ClosureConfirmation",
        back_populates="ticket",
        order_by="ClosureConfirmation.confirmation_id",
    )

    id = synonym("ticket_id")
    ai_solution_suggestion = synonym("ai_suggestion")

    @property
    def token(self) -> str:
        return self.tracking_token

    @token.setter
    def token(self, value: str) -> None:
        self.tracking_token = value

    @property
    def requester_name(self) -> str | None:
        return self.requester.requester_name if self.requester else None

    @property
    def requester_email(self) -> str | None:
        return self.requester.requester_email if self.requester else None

    @property
    def requester_phone(self) -> str | None:
        return self.requester.requester_phone if self.requester else None

    @property
    def requester_telegram_chat_id(self) -> str | None:
        return self.requester.telegram_chat_id if self.requester else None

    @property
    def requester_notification_preference(self) -> str | None:
        return self.requester.notification_preference if self.requester else None

    @property
    def category(self) -> str | None:
        return self.category_ref.category_name if self.category_ref else None

    @property
    def priority(self) -> str | None:
        return self.priority_ref.priority_name if self.priority_ref else None

    @property
    def status(self) -> str | None:
        return self.status_ref.status_name if self.status_ref else None

    @property
    def ai_suggested_solution(self) -> str | None:
        return self.ai_suggestion

    @ai_suggested_solution.setter
    def ai_suggested_solution(self, value: str | None) -> None:
        self.ai_suggestion = value

    @property
    def closure_confirmation(self):
        if not self.closure_confirmations:
            return None
        return self.closure_confirmations[-1]


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (
        CheckConstraint(
            "requester_id IS NULL OR technician_id IS NULL",
            name="chk_message_sender_not_both",
        ),
    )

    message_id = Column(Integer, primary_key=True)
    message_text = Column(Text, nullable=False)
    message_type = Column(String(20), nullable=False, default="Public")  # Public / Internal
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=False)
    requester_id = Column(Integer, ForeignKey("requester.requester_id"), nullable=True)
    technician_id = Column(Integer, ForeignKey("technician.technician_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="messages")
    requester = relationship("Requester")
    technician = relationship("Technician")

    id = synonym("message_id")
    content = synonym("message_text")

    @property
    def author_role(self) -> str:
        if self.requester_id:
            return "Requester"
        if self.technician_id:
            return "Technician"
        return "System"

    @property
    def author_id(self) -> int | None:
        return self.requester_id or self.technician_id


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint(
            "uploaded_by_requester_id IS NULL OR uploaded_by_technician_id IS NULL",
            name="chk_attachment_uploader_not_both",
        ),
    )

    attachment_id = Column(Integer, primary_key=True)
    attachment_name = Column(String(255), nullable=False)
    attachment_path = Column(String(500), nullable=False)
    attachment_hash = Column(String(64), nullable=False)
    attachment_type = Column(String(50), nullable=False, default="Issue")  # Issue / Proof-of-Fix
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=False)
    uploaded_by_requester_id = Column(Integer, ForeignKey("requester.requester_id"), nullable=True)
    uploaded_by_technician_id = Column(Integer, ForeignKey("technician.technician_id"), nullable=True)
    attachment_description = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="attachments")
    uploaded_by_requester = relationship("Requester")
    uploaded_by_technician = relationship("Technician")

    id = synonym("attachment_id")
    filename = synonym("attachment_name")
    path = synonym("attachment_path")
    sha256 = synonym("attachment_hash")
    created_at = synonym("uploaded_at")
    description = synonym("attachment_description")

    @property
    def uploaded_by_role(self) -> str | None:
        if self.uploaded_by_requester_id:
            return "Requester"
        if self.uploaded_by_technician_id:
            return "Technician"
        return None

    @property
    def uploaded_by_id(self) -> int | None:
        return self.uploaded_by_requester_id or self.uploaded_by_technician_id


class HealthCheck(Base):
    __tablename__ = "health_check"

    health_check_id = Column(Integer, primary_key=True)
    health_check_checklist = Column(Text, nullable=False)  # JSON string
    health_check_result = Column(String(20), nullable=False, default="PASS")  # PASS / FAIL
    health_check_notes = Column(Text, nullable=True)
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=False)
    technician_id = Column(Integer, ForeignKey("technician.technician_id"), nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="health_checks")
    technician = relationship("Technician")

    id = synonym("health_check_id")
    checklist_json = synonym("health_check_checklist")
    result = synonym("health_check_result")
    notes = synonym("health_check_notes")
    created_at = synonym("checked_at")


class ClosureConfirmation(Base):
    __tablename__ = "closure_confirmation"

    confirmation_id = Column(Integer, primary_key=True)
    e_sign = Column(String(255), nullable=True)
    confirmation_status = Column(String(30), nullable=False, default="NOT_REQUESTED")
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=False)
    requester_id = Column(Integer, ForeignKey("requester.requester_id"), nullable=False)
    requested_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="closure_confirmations")
    requester = relationship("Requester")

    id = synonym("confirmation_id")
    signature_name = synonym("e_sign")
    status = synonym("confirmation_status")


class AdminActionLog(Base):
    __tablename__ = "admin_action_log"

    log_id = Column(Integer, primary_key=True)
    action_type = Column(String(100), nullable=False)
    action_reason = Column(Text, nullable=True)
    admin_id = Column(Integer, ForeignKey("admin.admin_id"), nullable=False)
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=True)
    action_time = Column(DateTime, default=datetime.utcnow)

    admin = relationship("Admin", back_populates="action_logs")
    ticket = relationship("Ticket")

    id = synonym("log_id")
    action = synonym("action_type")
    details = synonym("action_reason")
    created_at = synonym("action_time")
