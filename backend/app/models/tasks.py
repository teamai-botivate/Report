"""Task management domain: categories, priorities, tasks, assignments,
comments, and status history. Employees are master data imported from
`app.models.master`."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Employee
from app.models.mixins import TimestampMixin


class TaskCategory(Base, TimestampMixin):
    """A task categorization tag (e.g. Follow-up, Maintenance, Documentation)."""

    __tablename__ = "task_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class TaskPriority(Base, TimestampMixin):
    """A task priority level (Low/Medium/High/Urgent), with a numeric
    `level` for sorting."""

    __tablename__ = "task_priorities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, comment="Higher number = higher priority.")


class Task(Base, TimestampMixin):
    """A unit of work, optionally linked back to a record in another module
    via `related_module`/`related_record_id` (e.g. a delayed-delivery
    follow-up task pointing at `deliveries`)."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("task_categories.id"), index=True, nullable=False
    )
    priority_id: Mapped[int] = mapped_column(
        ForeignKey("task_priorities.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="open", index=True, comment="Allowed values: open, in_progress, completed, cancelled."
    )
    assigned_to_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )
    created_by_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    created_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    completed_on: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    related_module: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Name of the related business module, e.g. 'sales', 'purchase', 'delivery'."
    )
    related_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category: Mapped["TaskCategory"] = relationship()
    priority: Mapped["TaskPriority"] = relationship()
    assigned_to: Mapped["Employee"] = relationship(foreign_keys=[assigned_to_employee_id])
    created_by: Mapped["Employee"] = relationship(foreign_keys=[created_by_employee_id])

    __table_args__ = (
        Index("ix_tasks_category", "category_id"),
        Index("ix_tasks_priority", "priority_id"),
        Index("ix_tasks_assigned_to", "assigned_to_employee_id"),
        Index("ix_tasks_created_by", "created_by_employee_id"),
    )


class TaskAssignment(Base, TimestampMixin):
    """An (additional) employee assigned to a task, supporting multi-assignee
    tasks beyond the primary `assigned_to_employee_id` on `Task`."""

    __tablename__ = "task_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    assigned_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="assignee", comment="Allowed values: assignee, reviewer, watcher.")

    task: Mapped["Task"] = relationship()
    employee: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index("ix_task_assignments_task", "task_id"),
        Index("ix_task_assignments_employee", "employee_id"),
    )


class TaskComment(Base, TimestampMixin):
    """A comment thread entry on a task."""

    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    commented_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)

    task: Mapped["Task"] = relationship()
    employee: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index("ix_task_comments_task", "task_id"),
        Index("ix_task_comments_employee", "employee_id"),
    )


class TaskStatusHistory(Base, TimestampMixin):
    """An audit trail entry recording every status transition of a task."""

    __tablename__ = "task_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True, nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    changed_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=True
    )

    task: Mapped["Task"] = relationship()
    changed_by: Mapped["Employee | None"] = relationship()

    __table_args__ = (
        Index("ix_task_status_history_task", "task_id"),
        Index("ix_task_status_history_changed_by", "changed_by_employee_id"),
    )
