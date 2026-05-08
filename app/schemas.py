from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

# Logs
class RequestLogBase(BaseModel):
    headers: str
    body: str

class RequestLog(RequestLogBase):
    id: int
    timestamp: datetime
    status: str
    dingtalk_response: Optional[str] = None
    error_message: Optional[str] = None
    processed_at: Optional[datetime] = None

    matched_rule: Optional[str] = None
    
    class Config:
        from_attributes = True

# ApiToken
class ApiTokenBase(BaseModel):
    name: str
    is_active: bool = True

class ApiTokenCreate(ApiTokenBase):
    pass

class ApiToken(ApiTokenBase):
    id: int
    token: str
    created_at: datetime
    class Config:
        from_attributes = True

# Admin
class AdminBase(BaseModel):
    username: str
    nickname: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

class AdminCreate(AdminBase):
    password: str

class AdminUpdate(BaseModel):
    nickname: Optional[str] = None
    description: Optional[str] = None
    password: Optional[str] = None

class Admin(AdminBase):
    id: int
    class Config:
        from_attributes = True

# Users
class UserBase(BaseModel):
    name: str
    phone_number: str
    is_active: bool = True

class UserCreate(UserBase):
    team_ids: List[int] = []

class User(UserBase):
    id: int
    # Avoiding circular dependency in Pydantic models usually requires forward refs or simplified models
    # For now, we just won't include teams here to avoid infinite recursion if Team includes Users
    class Config:
        from_attributes = True

class UserWithTeams(User):
    teams: List['TeamSummary'] = []

# Teams
class TeamBase(BaseModel):
    name: str
    description: Optional[str] = None

class TeamSummary(TeamBase):
    id: int
    class Config:
        from_attributes = True

class TeamCreate(TeamBase):
    user_ids: List[int] = []

class Team(TeamBase):
    id: int
    users: List[User] = []
    class Config:
        from_attributes = True

# Tags
class TagBase(BaseModel):
    name: str
    color: str = "blue"

class TagCreate(TagBase):
    pass

class Tag(TagBase):
    id: int
    class Config:
        from_attributes = True

# Notification Channels
class NotificationChannelBase(BaseModel):
    name: str
    type: str = "dingtalk"
    config: str # JSON string
    is_enabled: bool = True
    message_template: Optional[str] = None  # Jinja2 template, null = use default

class NotificationChannelCreate(NotificationChannelBase):
    pass

class NotificationChannel(NotificationChannelBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

# Rules
class RuleConditionBase(BaseModel):
    key: str
    operator: str = "equals"
    value: str

class RuleConditionCreate(RuleConditionBase):
    pass

class RuleCondition(RuleConditionBase):
    id: int
    rule_id: int
    class Config:
        from_attributes = True

class RuleBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True
    match_mode: str = "AND"
    priority: int = 0
    is_exclusive: bool = False
    
    # Keeping old fields optional for backward compatibility in Pydantic but not required
    match_key: Optional[str] = None
    match_operator: Optional[str] = "equals"
    match_value: Optional[str] = None

class RuleCreate(RuleBase):
    user_ids: List[int] = []
    team_ids: List[int] = []
    conditions: List[RuleConditionCreate] = []
    tags: List[str] = [] # List of tag names
    channel_id: Optional[int] = None

class Rule(RuleBase):
    id: int
    users: List[User] = []
    teams: List[Team] = []
    conditions: List[RuleCondition] = []
    tags: List[Tag] = []
    channel_id: Optional[int] = None
    channel: Optional[NotificationChannel] = None
    class Config:
        from_attributes = True

# Config
class DingTalkConfig(BaseModel):
    webhook_url: str
    secret: str
    access_token: str

class SystemSettings(BaseModel):
    webhook_auth_enabled: bool = False
    default_channel_id: Optional[int] = None
    log_retention_days: int = 30
    silence_retention_days: int = 7  # v1.4: auto-delete expired silences after N days

# Silence
class SilenceConditionBase(BaseModel):
    key: str
    operator: str = "equals"
    value: str


class SilenceConditionCreate(SilenceConditionBase):
    pass


class SilenceCondition(SilenceConditionBase):
    id: int
    silence_id: int
    class Config:
        from_attributes = True


class SilenceBase(BaseModel):
    name: str
    reason: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: datetime
    is_active: bool = True
    match_mode: str = "AND"


class SilenceCreate(SilenceBase):
    conditions: List[SilenceConditionCreate] = []
    created_by: Optional[str] = None


class Silence(SilenceBase):
    id: int
    created_by: Optional[str] = None
    created_at: datetime
    cancelled_at: Optional[datetime] = None
    conditions: List[SilenceCondition] = []
    class Config:
        from_attributes = True


# Announcement
class AnnouncementCreate(BaseModel):
    title: str
    content: str
    target_type: str = "all" # all, team, user
    target_ids: List[int] = [] # List of team_ids or user_ids
    channel_id: Optional[int] = None

