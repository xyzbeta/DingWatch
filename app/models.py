from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

# Association Tables
rule_user_association = Table(
    "rule_user",
    Base.metadata,
    Column("rule_id", Integer, ForeignKey("rules.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)

rule_team_association = Table(
    "rule_team",
    Base.metadata,
    Column("rule_id", Integer, ForeignKey("rules.id")),
    Column("team_id", Integer, ForeignKey("teams.id")),
)

user_team_association = Table(
    "user_team",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("team_id", Integer, ForeignKey("teams.id")),
)

rule_tag_association = Table(
    "rule_tag",
    Base.metadata,
    Column("rule_id", Integer, ForeignKey("rules.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)

class SystemSetting(Base):
    __tablename__ = "system_settings"
    
    key = Column(String, primary_key=True, index=True)
    value = Column(String)

class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    nickname = Column(String, nullable=True)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    
    rules = relationship("Rule", secondary=rule_user_association, back_populates="users")
    teams = relationship("Team", secondary=user_team_association, back_populates="users")

class Team(Base):
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)
    
    users = relationship("User", secondary=user_team_association, back_populates="teams")
    rules = relationship("Rule", secondary=rule_team_association, back_populates="teams")

class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # New fields for advanced matching
    match_mode = Column(String, default="AND") # AND, OR
    priority = Column(Integer, default=0)      # Higher number = higher priority
    is_exclusive = Column(Boolean, default=False) # If True, stop matching after this rule
    
    channel_id = Column(Integer, ForeignKey("notification_channels.id"), nullable=True)
    channel = relationship("NotificationChannel", back_populates="rules")

    # Matching logic - Deprecated in v1.1. We now use 'conditions' table.
    # Keeping these columns for DB schema compatibility only.
    match_key = Column(String, nullable=True) 
    match_operator = Column(String, nullable=True)
    match_value = Column(String, nullable=True)
    
    conditions = relationship("RuleCondition", back_populates="rule", cascade="all, delete-orphan")
    
    users = relationship("User", secondary=rule_user_association, back_populates="rules")
    teams = relationship("Team", secondary=rule_team_association, back_populates="rules")
    tags = relationship("Tag", secondary=rule_tag_association, back_populates="rules")

class Tag(Base):
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    color = Column(String, default="blue") # e.g. blue, red, green
    
    rules = relationship("Rule", secondary=rule_tag_association, back_populates="tags")

class RuleCondition(Base):
    __tablename__ = "rule_conditions"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("rules.id"))
    
    key = Column(String)  # e.g., "namespace"
    operator = Column(String, default="equals") # equals, contains, regex, startswith, exists
    value = Column(String) # e.g., "ops-system"
    
    rule = relationship("Rule", back_populates="conditions")


class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.now)
    headers = Column(Text)
    body = Column(Text)
    
    status = Column(String, default="pending") # pending, success, failed, no_match
    dingtalk_response = Column(Text, nullable=True)
    dingtalk_request_body = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    matched_rule = Column(String, nullable=True)
    channel_name = Column(String, nullable=True)

class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(String, default="dingtalk") # dingtalk, wechat, etc.
    config = Column(Text) # JSON string
    is_enabled = Column(Boolean, default=True)
    message_template = Column(Text, nullable=True)  # Jinja2 template, null = use default
    created_at = Column(DateTime, default=datetime.now)

    rules = relationship("Rule", back_populates="channel")

class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    token = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Silence(Base):
    __tablename__ = "silences"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    reason = Column(String, nullable=True)
    starts_at = Column(DateTime, default=datetime.utcnow)
    ends_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    match_mode = Column(String, default="AND")  # AND / OR
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    cancelled_at = Column(DateTime, nullable=True)

    conditions = relationship("SilenceCondition", back_populates="silence", cascade="all, delete-orphan")


class SilenceCondition(Base):
    __tablename__ = "silence_conditions"

    id = Column(Integer, primary_key=True, index=True)
    silence_id = Column(Integer, ForeignKey("silences.id"))
    key = Column(String)
    operator = Column(String, default="equals")  # equals, contains, regex, startswith
    value = Column(String)

    silence = relationship("Silence", back_populates="conditions")
