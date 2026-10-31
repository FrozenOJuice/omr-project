from datetime import datetime

from sqlalchemy import CheckConstraint
from sqlalchemy import DateTime
from sqlalchemy import LargeBinary
from sqlalchemy import SmallInteger
from sqlalchemy import String
from sqlalchemy import func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from db.session import Base


class SiteBranding(Base):
    __tablename__ = "site_branding"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_site_branding_singleton"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
