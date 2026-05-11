from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from .. import models
import re

def parse_text_to_alerts(text: str) -> List[Dict[str, str]]:
    """
    解析自定义文本格式的告警为结构化数据
    """
    alerts = []
    current_alert = {}
    
    # Split by newlines
    lines = text.strip().split('\n')
    for line in lines:
        line = re.sub(r'<br\s*/?>\s*$', '', line).strip()
        if not line:
            if current_alert:
                alerts.append(current_alert)
                current_alert = {}
            continue
            
        # Ignore header lines like [12]FIRING
        if line.startswith('[') and 'FIRING' in line:
            continue
            
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                key, val = parts
                current_alert[key.strip()] = val.strip()
            
    if current_alert:
        alerts.append(current_alert)
        
    return alerts

def _find_value(data, target_key):
    """Recursively find all values matching a key in nested dicts/lists."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == target_key:
                yield v
            if isinstance(v, (dict, list)):
                yield from _find_value(v, target_key)
    elif isinstance(data, list):
        for item in data:
            yield from _find_value(item, target_key)


def check_condition(data, key, operator, target_val) -> bool:
    """Check if a condition matches against alert data."""
    if not key:
        return False

    found_values = list(_find_value(data, key))

    if operator == "exists":
        return len(found_values) > 0

    if not found_values:
        return False

    for v in found_values:
        str_v = str(v)
        if operator == "equals":
            if str_v == target_val:
                return True
        elif operator == "contains":
            if target_val in str_v:
                return True
        elif operator == "startswith":
            if str_v.startswith(target_val):
                return True
        elif operator == "regex":
            try:
                if re.search(target_val, str_v):
                    return True
            except Exception:
                pass
    return False


def get_active_rules(db: Session):
    """查询所有启用的规则，按优先级降序排列，预加载 users 和 teams."""
    from sqlalchemy.orm import selectinload
    return db.query(models.Rule).filter(models.Rule.is_active == True)\
        .options(
            selectinload(models.Rule.users),
            selectinload(models.Rule.teams).selectinload(models.Team.users),
            selectinload(models.Rule.conditions),
        )\
        .order_by(models.Rule.priority.desc()).all()


def extract_raw_alerts(alert_data: Dict[str, Any], format_name: str) -> List[Dict[str, Any]]:
    """根据数据源格式从 payload 中提取单条原始告警列表."""
    if format_name == "prometheus":
        alerts = alert_data.get("alerts", [])
        return alerts if alerts else [alert_data]
    elif format_name == "grafana":
        eval_matches = alert_data.get("evalMatches", [])
        return eval_matches if eval_matches else [alert_data]
    elif format_name == "custom_text":
        alerts = alert_data.get("alerts", [])
        return alerts if alerts else [alert_data]
    else:
        return [alert_data]


def match_single_alert(alert_data: Dict[str, Any], rules: list) -> tuple[int, List[str], str] | None:
    """对单条告警按规则优先级匹配，命中第一个即返回 (channel_id, 手机号列表, 规则名称)；未命中返回 None."""
    for rule in rules:
        conditions_to_check = []
        if rule.conditions:
            for c in rule.conditions:
                conditions_to_check.append((c.key, c.operator, c.value))

        if not conditions_to_check:
            continue

        match_mode = rule.match_mode or "AND"

        if match_mode == "AND":
            is_match = all(
                check_condition(alert_data, key, op, val)
                for key, op, val in conditions_to_check
            )
        elif match_mode == "OR":
            is_match = any(
                check_condition(alert_data, key, op, val)
                for key, op, val in conditions_to_check
            )

        if is_match:
            cid = rule.channel_id if rule.channel_id else -1
            phones = []
            for user in rule.users:
                if user.is_active and user.phone_number:
                    phones.append(user.phone_number)
            for team in rule.teams:
                for user in team.users:
                    if user.is_active and user.phone_number:
                        phones.append(user.phone_number)
            return cid, phones, rule.name

    return None


def check_alert_silenced(db: Session, alert_data: dict) -> Optional[str]:
    """Check if the alert matches any active silence rule.

    Returns the silence name if silenced, None otherwise.
    Uses the same check_condition/find_value logic as match_rules.
    """
    from .. import crud as crud_module
    silences = crud_module.get_active_silences(db)
    if not silences:
        return None

    for silence in silences:
        if not silence.conditions:
            continue
        match_mode = silence.match_mode or "AND"
        conditions_data = [(c.key, c.operator, c.value) for c in silence.conditions]

        if match_mode == "AND":
            all_met = True
            for key, op, val in conditions_data:
                if not check_condition(alert_data, key, op, val):
                    all_met = False
                    break
            if all_met:
                return silence.name
        elif match_mode == "OR":
            for key, op, val in conditions_data:
                if check_condition(alert_data, key, op, val):
                    return silence.name

    return None
