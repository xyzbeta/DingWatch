"""Alert format detection, normalization, and message template rendering."""

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from jinja2 import Environment, Template, TemplateError

_TZ_SHANGHAI = timezone(timedelta(hours=8))


def _format_alert_time(value: str) -> str:
    """Convert ISO 8601 timestamp to readable Asia/Shanghai format. Idempotent."""
    if not value:
        return ""
    s = str(value).strip()
    # 跳过无效时间（Prometheus resolves 时的占位值）
    if s.startswith("0001-") or s.startswith("0000-"):
        return ""
    # 已经是格式化时间（YYYY-MM-DD HH:MM:SS），直接返回
    if len(s) == 19 and s[4] == '-' and s[7] == '-' and s[10] == ' ' and s[13] == ':' and s[16] == ':':
        return s
    try:
        # Handle ISO 8601 with optional Z, milliseconds, timezone offset
        s = s.replace("Z", "+00:00")
        # Normalize to have timezone info
        if "+" not in s and s.count("-") <= 2:
            s += "+00:00"
        dt = datetime.fromisoformat(s)
        # Convert to Asia/Shanghai
        dt = dt.astimezone(_TZ_SHANGHAI)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(value)[:19] if len(str(value)) >= 19 else str(value)


_jinja_env = Environment()
_jinja_env.filters["format_time"] = _format_alert_time


def detect_format(alert_data: dict) -> str:
    """Detect the alert source format from JSON structure."""
    if not isinstance(alert_data, dict):
        return "generic_json"

    # Custom text (already wrapped by webhook receiver)
    if "raw_message" in alert_data:
        return "custom_text"

    # Prometheus Alertmanager: alerts list with labels/annotations
    alerts = alert_data.get("alerts")
    if isinstance(alerts, list) and len(alerts) > 0:
        first = alerts[0]
        if isinstance(first, dict) and (
            "labels" in first or "annotations" in first
        ):
            return "prometheus"
    if "commonLabels" in alert_data or "groupLabels" in alert_data:
        return "prometheus"

    # Grafana: evalMatches list, or ruleName/ruleId/ruleUrl
    if "evalMatches" in alert_data:
        return "grafana"
    if any(k in alert_data for k in ("ruleName", "ruleId", "ruleUrl")):
        state = alert_data.get("state", "")
        if state in ("alerting", "ok", "paused", "no_data"):
            return "grafana"

    return "generic_json"


def _extract_first(data: dict, *keys: str) -> Optional[str]:
    """Return the first non-empty value from a list of keys."""
    for k in keys:
        v = data.get(k)
        if v:
            return str(v)
    return None


def _normalize_severity(raw: Optional[str]) -> str:
    """Normalize severity string to critical/warning/info."""
    if not raw:
        return "info"
    s = str(raw).lower()
    if s in ("critical", "crit", "firing", "alerting", "p1", "p0"):
        return "critical"
    if s in ("warning", "warn", "p2"):
        return "warning"
    return "info"


_WORKLOAD_KEYS = ("deployment", "statefulset", "daemonset", "资源名称", "工作负载", "resource_name")
_NAMESPACE_KEYS = ("namespace", "命名空间", "所属空间", "集群")
_INSTANCE_KEYS = ("instance", "实例地址", "实例", "host", "ip")
_POD_KEYS = ("pod", "目标")
_CODE_KEYS = ("code", "错误码", "error_code")
_DESCRIPTION_KEYS = ("描述", "description", "summary")
_SEVERITY_KEYS = ("severity", "严重性")


def _add_standard_keys(details: dict) -> dict:
    """Add standard lookup keys to an alert details dict for template compatibility."""
    for k in _NAMESPACE_KEYS:
        if k in details and details[k]:
            details.setdefault("namespace", details[k])
            break
    for k in _WORKLOAD_KEYS:
        if k in details and details[k]:
            details.setdefault("workload", details[k])
            break
    for k in _INSTANCE_KEYS:
        if k in details and details[k]:
            details.setdefault("instance", details[k])
            break
    for k in _POD_KEYS:
        if k in details and details[k]:
            details.setdefault("pod", details[k])
            break
    for k in _CODE_KEYS:
        if k in details and details[k]:
            details.setdefault("code", details[k])
            break
    for k in _SEVERITY_KEYS:
        if k in details and details[k]:
            details.setdefault("severity", details[k])
            break
    for k in _DESCRIPTION_KEYS:
        if k in details and details[k]:
            details.setdefault("description", details[k])
            break
    return details


def _normalize_prometheus(data: dict) -> dict:
    alerts_list = data.get("alerts", [])
    normalized_alerts = []
    for a in alerts_list:
        labels = a.get("labels", {}) if isinstance(a, dict) else {}
        annotations = a.get("annotations", {}) if isinstance(a, dict) else {}
        details = _add_standard_keys({**labels, **annotations})
        starts = a.get("startsAt", "") if isinstance(a, dict) else ""
        normalized_alerts.append({
            "name": labels.get("alertname", ""),
            "level": _normalize_severity(labels.get("severity")),
            "description": annotations.get("description") or annotations.get("summary", ""),
            "time": _format_alert_time(starts),
            "details": details,
        })

    common_labels = data.get("commonLabels", {})
    return {
        "title": common_labels.get("alertname") or (
            normalized_alerts[0]["name"] if normalized_alerts else "PaaS Alert"
        ),
        "severity": _normalize_severity(common_labels.get("severity")),
        "message": data.get("commonAnnotations", {}).get("description", "") or data.get("status", ""),
        "source": "prometheus",
        "alerts": normalized_alerts,
        "raw_data": data,
    }


def _normalize_grafana(data: dict) -> dict:
    eval_matches = data.get("evalMatches", [])
    grafana_message = data.get("message", "")
    normalized_alerts = []
    for m in eval_matches:
        tags = m.get("tags", {}) if isinstance(m, dict) else {}
        details = _add_standard_keys(dict(tags))
        normalized_alerts.append({
            "name": m.get("metric", "") if isinstance(m, dict) else str(m),
            "level": _normalize_severity(data.get("state", "")),
            "description": grafana_message,
            "time": "",
            "details": details,
        })

    if not normalized_alerts:
        details = _add_standard_keys({})
        normalized_alerts = [{
            "name": data.get("ruleName", ""),
            "level": _normalize_severity(data.get("state", "")),
            "description": grafana_message,
            "time": "",
            "details": details,
        }]

    # Map Grafana state to status for template compatibility
    raw = dict(data)
    state = raw.get("state", "")
    if state == "alerting":
        raw.setdefault("status", "firing")
    elif state == "ok":
        raw.setdefault("status", "resolved")
    else:
        raw.setdefault("status", "firing")

    return {
        "title": data.get("title") or data.get("ruleName", "Grafana Alert"),
        "severity": _normalize_severity(state),
        "message": grafana_message,
        "source": "grafana",
        "alerts": normalized_alerts,
        "raw_data": raw,
    }


def _normalize_custom_text(data: dict) -> dict:
    alerts_list = data.get("alerts", [])
    normalized_alerts = []
    for a in alerts_list:
        if not isinstance(a, dict):
            continue
        details = _add_standard_keys(dict(a))
        raw_time = a.get("发生时间") or a.get("时间") or a.get("开始时间") or ""
        normalized_alerts.append({
            "name": a.get("规则名称") or a.get("alertname", ""),
            "level": _normalize_severity(a.get("告警级别") or a.get("severity") or a.get("严重性")),
            "description": a.get("描述") or a.get("description", ""),
            "time": _format_alert_time(raw_time),
            "details": details,
        })

    first = alerts_list[0] if alerts_list else {}
    dn = first if isinstance(first, dict) else {}
    alert_name = dn.get("规则名称") or dn.get("alertname", "")
    alert_level = dn.get("告警级别") or dn.get("severity") or dn.get("严重性")
    title = alert_name or "Custom Alert"
    if alert_name and alert_level:
        title = f"{alert_name} ({alert_level})"
    elif alert_level:
        title = f"告警 ({alert_level})"

    # Ensure raw_data has a status field for template compatibility
    raw = dict(data)
    raw.setdefault("status", "firing")

    return {
        "title": title,
        "severity": _normalize_severity(alert_level),
        "message": dn.get("描述") or dn.get("description", "") or data.get("raw_message", ""),
        "source": "custom_text",
        "alerts": normalized_alerts,
        "raw_data": raw,
    }


def _normalize_generic(data: dict) -> dict:
    title = _extract_first(data, "title", "alertname", "name") or "Alert"
    severity = _normalize_severity(
        data.get("severity") or data.get("level") or data.get("state")
    )
    message = data.get("message") or data.get("description", "")
    details = _add_standard_keys({k: v for k, v in data.items()})

    # Ensure raw_data has a status field for template compatibility
    raw = dict(data)
    raw.setdefault("status", "firing")

    return {
        "title": title,
        "severity": severity,
        "message": message,
        "source": "generic_json",
        "alerts": [{
            "name": title,
            "level": severity,
            "description": message,
            "time": data.get("timestamp") or data.get("time", ""),
            "details": details,
        }],
        "raw_data": raw,
    }


_NORMALIZERS = {
    "prometheus": _normalize_prometheus,
    "grafana": _normalize_grafana,
    "custom_text": _normalize_custom_text,
    "generic_json": _normalize_generic,
}


def normalize_alert(alert_data: dict, format_name: str) -> dict:
    """Convert format-specific alert data into a unified internal structure."""
    normalizer = _NORMALIZERS.get(format_name, _normalize_generic)
    return normalizer(alert_data)


DEFAULT_TEMPLATES = {
    "prometheus": (
        "{{ title }}\n\n"
        "{% if severity %}告警级别: {{ severity }}\n\n{% endif %}"
        "{{ message }}\n\n"
        "{% for alert in alerts %}"
        "---\n"
        "【{{ alert.name }}】{% if alert.level %}({{ alert.level }}){% endif %}\n\n"
        "{{ alert.description }}\n"
        "{% if alert.time %}告警时间: {{ alert.time | format_time }}{% endif %}\n"
        "{% endfor %}"
    ),
    "grafana": (
        "{{ title }}\n\n"
        "{% if severity %}告警级别: {{ severity }}\n\n{% endif %}"
        "{{ message }}\n\n"
        "{% for alert in alerts %}"
        "- {{ alert.name }}: {{ alert.description }}\n"
        "{% endfor %}"
    ),
    "custom_text": (
        "{{ title }}\n\n"
        "{% if severity %}告警级别: {{ severity }}\n\n{% endif %}"
        "{% for alert in alerts %}"
        "{% for k, v in alert.details.items() %}"
        "{{ k }}: {{ v }}\n"
        "{% endfor %}\n"
        "{% if not loop.last %}---\n{% endif %}"
        "{% endfor %}"
    ),
    "generic_json": (
        "{{ title }}\n\n"
        "{% if severity %}告警级别: {{ severity }}\n\n{% endif %}"
        "{% if message %}{{ message }}\n\n{% endif %}"
        "原始数据:\n"
        "{{ raw_data | tojson(indent=2) }}"
    ),
}

MAX_MESSAGE_LENGTH = 20000


def get_default_template(format_name: str) -> str:
    """Return the default Jinja2 template for a given format."""
    return DEFAULT_TEMPLATES.get(format_name, DEFAULT_TEMPLATES["generic_json"])


def render_message(template_str: str, unified_alert: dict) -> str:
    """Render a Jinja2 template with unified alert data.

    Falls back to format default template on render error.
    Truncates messages exceeding MAX_MESSAGE_LENGTH.
    """
    source = unified_alert.get("source", "generic_json")
    try:
        rendered = _jinja_env.from_string(template_str).render(**unified_alert)
    except TemplateError:
        try:
            rendered = _jinja_env.from_string(get_default_template(source)).render(**unified_alert)
        except TemplateError:
            rendered = f"### {unified_alert.get('title', 'Alert')}\n\n{unified_alert.get('message', '')}"

    if len(rendered) > MAX_MESSAGE_LENGTH:
        rendered = rendered[:MAX_MESSAGE_LENGTH] + "\n\n...(消息过长已截断)"

    return rendered
