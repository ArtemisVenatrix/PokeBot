# ORM models for the database. Pretty straight forward stuff if you know how sqlAlchemy works.
import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, ForeignKey, Date, Boolean, Table, Column
from typing import List
from sqlalchemy.ext import hybrid


class Base(DeclarativeBase):
    pass


subscriber_association_table = Table(
    "subscriber_association_table",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("guild_id", ForeignKey("guilds.id"), primary_key=True),
)



class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    notif_subscriptions: Mapped[List["Guild"]] = relationship(
        secondary=subscriber_association_table, back_populates="member_subs"
    )


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column()
    parent_guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id"))

    def __repr__(self) -> str:
        return f"Subscriber(id={self.id!r}, username={self.user_id!r}, parent_guild_id={self.parent_guild_id!r})"


class Guild(Base):
    # must have row id set to discord guild id at time of creation
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    art_channel_id: Mapped[int] = mapped_column(nullable=True)
    member_subs: Mapped[List["User"]] = relationship(
        secondary=subscriber_association_table, back_populates="notif_subscriptions"
    )
    art_streaks: Mapped[List["ArtStreak"]] = relationship()

    def __repr__(self) -> str:
        return f"Guild(id={self.id!r}, member_subs={self.member_subs.__repr__()!r})"


class ArtStreak(Base):
    __tablename__ = "art_streaks"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id"))
    guild: Mapped["Guild"] = relationship(back_populates="art_streaks")
    user_id: Mapped[int] = mapped_column()
    creation_date: Mapped[Date] = mapped_column(Date())
    end_date: Mapped[Date] = mapped_column(Date(), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean(), default=True)
    freezes: Mapped[int] = mapped_column(default=2)
    submissions: Mapped[List["ArtStreakSubmission"]] = relationship()

    def __repr__(self) -> str:
        return f"ArtStreak(id={self.id!r}" \
               f", guild_id={self.guild_id!r}" \
               f", user_id={self.user_id!r}" \
               f", creation_date={self.creation_date!r})" \
               f", end_date={self.end_date!r}" \
               f", active={self.active}" \
               f", freezes={self.freezes}"


    @hybrid.hybrid_property
    def get_duration(self) -> datetime.timedelta:
        if self.active:
            return datetime.date.today() - self.creation_date + datetime.timedelta(1)
        else:
            return self.end_date - self.creation_date + datetime.timedelta(1)


class ArtStreakSubmission(Base):
    __tablename__ = "art_streak_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    art_streak_id: Mapped[int] = mapped_column(ForeignKey("art_streaks.id"))
    art_streak: Mapped["ArtStreak"] = relationship(back_populates="submissions")
    creation_date: Mapped[Date] = mapped_column(Date())
    message_link: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column()

    def __repr__(self) -> str:
        return f"ArtStreakSubmission(id={self.id!r}" \
               f", art_streak_id={self.art_streak_id!r}" \
               f", creation_date={self.creation_date!r}" \
               f", message_link={self.message_link!r})"


class PersistentVars(Base):
    __tablename__ = "persistent_vars"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_streak_check_date: Mapped[Date] = mapped_column(Date())

    def __repr__(self) -> str:
        return f"PersistentVars(id={self.id!r}" \
               f", last_streak_check_date={self.last_streak_check_date!r})"

