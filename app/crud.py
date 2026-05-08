from sqlalchemy.orm import Session
from datetime import datetime
from . import models, schemas
import bcrypt

# Logs
def create_request_log(db: Session, headers: str, body: str, channel_name: str = None):
    db_log = models.RequestLog(headers=headers, body=body, status="pending", channel_name=channel_name)
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def update_request_log_status(db: Session, log_id: int, status: str, response: str = None, error: str = None, matched_rule: str = None, dingtalk_request_body: str = None, channel_name: str = None):
    db_log = db.query(models.RequestLog).filter(models.RequestLog.id == log_id).first()
    if db_log:
        db_log.status = status
        db_log.dingtalk_response = response
        db_log.error_message = error
        if matched_rule:
            db_log.matched_rule = matched_rule
        if dingtalk_request_body:
            db_log.dingtalk_request_body = dingtalk_request_body
        if channel_name:
            db_log.channel_name = channel_name
        db_log.processed_at = datetime.now()
        db.commit()
        db.refresh(db_log)
    return db_log

def get_request_logs(db: Session, skip: int = 0, limit: int = 50, query: str = None):
    q = db.query(models.RequestLog)
    if query:
        # Simple search in body or matched_rule or status
        search = f"%{query}%"
        q = q.filter(
            (models.RequestLog.body.like(search)) | 
            (models.RequestLog.matched_rule.like(search)) |
            (models.RequestLog.status.like(search))
        )
    return q.order_by(models.RequestLog.timestamp.desc()).offset(skip).limit(limit).all()

def count_request_logs(db: Session, query: str = None):
    q = db.query(models.RequestLog)
    if query:
        search = f"%{query}%"
        q = q.filter(
            (models.RequestLog.body.like(search)) | 
            (models.RequestLog.matched_rule.like(search)) |
            (models.RequestLog.status.like(search))
        )
    return q.count()

# Admin
def get_admin_by_username(db: Session, username: str):
    return db.query(models.Admin).filter(models.Admin.username == username).first()

def create_admin(db: Session, admin: schemas.AdminCreate):
    hashed_password = bcrypt.hashpw(admin.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db_admin = models.Admin(
        username=admin.username,
        password_hash=hashed_password,
        nickname=admin.nickname,
        description=admin.description,
        is_active=admin.is_active
    )
    db.add(db_admin)
    db.commit()
    db.refresh(db_admin)
    return db_admin

def update_admin(db: Session, admin_id: int, admin: schemas.AdminUpdate):
    db_admin = db.query(models.Admin).filter(models.Admin.id == admin_id).first()
    if db_admin:
        if admin.nickname is not None:
            db_admin.nickname = admin.nickname
        if admin.description is not None:
            db_admin.description = admin.description
        if admin.password is not None and admin.password:
            db_admin.password_hash = bcrypt.hashpw(admin.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db.commit()
        db.refresh(db_admin)
    return db_admin

# Users
def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(name=user.name, phone_number=user.phone_number, is_active=user.is_active)
    if user.team_ids:
        teams = db.query(models.Team).filter(models.Team.id.in_(user.team_ids)).all()
        db_user.teams = teams
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user(db: Session, user_id: int, user: schemas.UserCreate):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if db_user:
        db_user.name = user.name
        db_user.phone_number = user.phone_number
        db_user.is_active = user.is_active
        if user.team_ids is not None:
             teams = db.query(models.Team).filter(models.Team.id.in_(user.team_ids)).all()
             db_user.teams = teams
        db.commit()
        db.refresh(db_user)
    return db_user

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()

# Teams
def create_team(db: Session, team: schemas.TeamCreate):
    db_team = models.Team(name=team.name, description=team.description)
    if team.user_ids:
        users = db.query(models.User).filter(models.User.id.in_(team.user_ids)).all()
        db_team.users = users
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return db_team

def update_team(db: Session, team_id: int, team: schemas.TeamCreate):
    db_team = db.query(models.Team).filter(models.Team.id == team_id).first()
    if db_team:
        db_team.name = team.name
        db_team.description = team.description
        if team.user_ids is not None:
            users = db.query(models.User).filter(models.User.id.in_(team.user_ids)).all()
            db_team.users = users
        db.commit()
        db.refresh(db_team)
    return db_team

def get_teams(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Team).offset(skip).limit(limit).all()

def delete_team(db: Session, team_id: int):
    db_team = db.query(models.Team).filter(models.Team.id == team_id).first()
    if db_team:
        db.delete(db_team)
        db.commit()
        return True
    return False

# Rules
def create_rule(db: Session, rule: schemas.RuleCreate):
    # Set first condition as match_key/value for compatibility - DEPRECATED in v1.1
    # We no longer rely on these fields, but keeping them in DB for now.
    # primary_condition = rule.conditions[0] if rule.conditions else None
    
    db_rule = models.Rule(
        name=rule.name, 
        description=rule.description,
        is_active=rule.is_active,
        match_mode=rule.match_mode,
        priority=rule.priority,
        is_exclusive=rule.is_exclusive,
        channel_id=rule.channel_id,
        # match_key=primary_condition.key if primary_condition else rule.match_key, 
        # match_operator=primary_condition.operator if primary_condition else rule.match_operator,
        # match_value=primary_condition.value if primary_condition else rule.match_value
    )
    
    if rule.conditions:
        for cond in rule.conditions:
            db_cond = models.RuleCondition(key=cond.key, operator=cond.operator, value=cond.value)
            db_rule.conditions.append(db_cond)
    
    if rule.tags:
        tags = []
        for tag_name in rule.tags:
            tag = db.query(models.Tag).filter(models.Tag.name == tag_name).first()
            if not tag:
                tag = models.Tag(name=tag_name, color="blue")
                db.add(tag)
                db.flush()  # flush to get ID, don't commit yet
            tags.append(tag)
        db_rule.tags = tags

    if rule.user_ids:
        users = db.query(models.User).filter(models.User.id.in_(rule.user_ids)).all()
        db_rule.users = users
    if rule.team_ids:
        teams = db.query(models.Team).filter(models.Team.id.in_(rule.team_ids)).all()
        db_rule.teams = teams

    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule

def update_rule(db: Session, rule_id: int, rule: schemas.RuleCreate):
    db_rule = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if db_rule:
        db_rule.name = rule.name
        db_rule.description = rule.description
        db_rule.is_active = rule.is_active
        db_rule.match_mode = rule.match_mode
        db_rule.priority = rule.priority
        db_rule.is_exclusive = rule.is_exclusive
        db_rule.channel_id = rule.channel_id
        
        # Update compatibility fields - DEPRECATED in v1.1
        # primary_condition = rule.conditions[0] if rule.conditions else None
        # db_rule.match_key = primary_condition.key if primary_condition else rule.match_key
        # db_rule.match_operator = primary_condition.operator if primary_condition else rule.match_operator
        # db_rule.match_value = primary_condition.value if primary_condition else rule.match_value
        
        # Update conditions (replace all)
        db_rule.conditions = []
        if rule.conditions:
            for cond in rule.conditions:
                db_cond = models.RuleCondition(key=cond.key, operator=cond.operator, value=cond.value)
                db_rule.conditions.append(db_cond)
        
        if rule.tags is not None:
            tags = []
            for tag_name in rule.tags:
                tag = db.query(models.Tag).filter(models.Tag.name == tag_name).first()
                if not tag:
                    tag = models.Tag(name=tag_name, color="blue")
                    db.add(tag)
                    db.flush()
                tags.append(tag)
            db_rule.tags = tags
        
        if rule.user_ids is not None:
             users = db.query(models.User).filter(models.User.id.in_(rule.user_ids)).all()
             db_rule.users = users
        if rule.team_ids is not None:
             teams = db.query(models.Team).filter(models.Team.id.in_(rule.team_ids)).all()
             db_rule.teams = teams
             
        db.commit()
        db.refresh(db_rule)
    return db_rule

def get_rules(db: Session, skip: int = 0, limit: int = 100, tag: str = None):
    q = db.query(models.Rule)
    if tag:
        q = q.join(models.Rule.tags).filter(models.Tag.name == tag)
    return q.offset(skip).limit(limit).all()

def get_tags(db: Session):
    return db.query(models.Tag).all()

# System Settings
def get_system_setting(db: Session, key: str):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == key).first()
    return setting.value if setting else None
    
# Api Tokens
def create_api_token(db: Session, name: str, token: str):
    db_token = models.ApiToken(name=name, token=token)
    db.add(db_token)
    db.commit()
    db.refresh(db_token)
    return db_token

def get_api_tokens(db: Session):
    return db.query(models.ApiToken).all()

def delete_api_token(db: Session, token_id: int):
    token = db.query(models.ApiToken).filter(models.ApiToken.id == token_id).first()
    if token:
        db.delete(token)
        db.commit()
        return True
    return False

def set_system_setting(db: Session, key: str, value: str):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == key).first()
    if not setting:
        setting = models.SystemSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    db.commit()
    db.refresh(setting)
    return setting

# Notification Channels
def get_notification_channels(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.NotificationChannel).offset(skip).limit(limit).all()

def get_notification_channel(db: Session, channel_id: int):
    return db.query(models.NotificationChannel).filter(models.NotificationChannel.id == channel_id).first()

def create_notification_channel(db: Session, channel: schemas.NotificationChannelCreate):
    db_channel = models.NotificationChannel(
        name=channel.name,
        type=channel.type,
        config=channel.config,
        is_enabled=channel.is_enabled,
        message_template=channel.message_template
    )
    db.add(db_channel)
    db.commit()
    db.refresh(db_channel)
    return db_channel

def update_notification_channel(db: Session, channel_id: int, channel: schemas.NotificationChannelCreate):
    db_channel = db.query(models.NotificationChannel).filter(models.NotificationChannel.id == channel_id).first()
    if db_channel:
        db_channel.name = channel.name
        db_channel.type = channel.type
        db_channel.config = channel.config
        db_channel.is_enabled = channel.is_enabled
        db_channel.message_template = channel.message_template
        db.commit()
        db.refresh(db_channel)
    return db_channel

def delete_notification_channel(db: Session, channel_id: int):
    db_channel = db.query(models.NotificationChannel).filter(models.NotificationChannel.id == channel_id).first()
    if db_channel:
        db.delete(db_channel)
        db.commit()
        return True
    return False


# Silences
def create_silence(db: Session, silence: schemas.SilenceCreate):
    db_silence = models.Silence(
        name=silence.name,
        reason=silence.reason,
        starts_at=silence.starts_at or datetime.utcnow(),
        ends_at=silence.ends_at,
        is_active=True,
        match_mode=silence.match_mode,
        created_by=silence.created_by,
    )
    for cond in silence.conditions:
        db_cond = models.SilenceCondition(key=cond.key, operator=cond.operator, value=cond.value)
        db_silence.conditions.append(db_cond)

    db.add(db_silence)
    db.commit()
    db.refresh(db_silence)
    return db_silence


def get_active_silences(db: Session):
    """Return silences that are active and not yet expired."""
    now = datetime.utcnow()
    return db.query(models.Silence).filter(
        models.Silence.is_active == True,
        models.Silence.starts_at <= now,
        models.Silence.ends_at >= now
    ).order_by(models.Silence.created_at.desc()).all()


def get_silences(db: Session, include_expired: bool = True):
    q = db.query(models.Silence)
    if not include_expired:
        now = datetime.now()
        q = q.filter(models.Silence.ends_at >= now, models.Silence.is_active == True)
    return q.order_by(models.Silence.created_at.desc()).all()


def cancel_silence(db: Session, silence_id: int):
    db_silence = db.query(models.Silence).filter(models.Silence.id == silence_id).first()
    if db_silence:
        db_silence.is_active = False
        db_silence.cancelled_at = datetime.utcnow()
        db.commit()
        db.refresh(db_silence)
    return db_silence


def update_silence(db: Session, silence_id: int, silence: schemas.SilenceCreate):
    db_silence = db.query(models.Silence).filter(models.Silence.id == silence_id).first()
    if not db_silence:
        return None
    db_silence.name = silence.name
    db_silence.reason = silence.reason
    db_silence.ends_at = silence.ends_at
    db_silence.match_mode = silence.match_mode
    # Replace conditions
    db_silence.conditions = []
    for cond in silence.conditions:
        db_cond = models.SilenceCondition(key=cond.key, operator=cond.operator, value=cond.value)
        db_silence.conditions.append(db_cond)
    db.commit()
    db.refresh(db_silence)
    return db_silence


def delete_silence(db: Session, silence_id: int):
    db_silence = db.query(models.Silence).filter(models.Silence.id == silence_id).first()
    if db_silence:
        db.delete(db_silence)
        db.commit()
        return True
    return False
