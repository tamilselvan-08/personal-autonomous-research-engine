import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TaskStatus
from app.models.project import Project

task_status_enum = Enum(
    TaskStatus,
    name="research_task_status_enum",
    values_callable=lambda e: [m.value for m in e],
    validate_strings=True,
)


class ResearchTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_tasks"
    __table_args__ = (
        Index("ix_research_tasks_owner_status", "owner_id", "status"),
        Index("ix_research_tasks_owner_updated", "owner_id", "updated_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum, nullable=False, server_default=TaskStatus.DRAFT.value
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped[Project | None] = relationship(lazy="joined")
