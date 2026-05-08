from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models, schemas, database, crud
from datetime import datetime, time, timedelta

router = APIRouter(
    prefix="/api/v1/stats",
    tags=["stats"]
)

@router.get("/")
def get_dashboard_stats(db: Session = Depends(database.get_db)):
    # Today's start time
    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), time.min)
    
    # Total alerts today
    today_count = db.query(models.RequestLog).filter(models.RequestLog.timestamp >= today_start).count()
    
    # Today success
    success_count = db.query(models.RequestLog).filter(
        models.RequestLog.timestamp >= today_start,
        models.RequestLog.status == "success"
    ).count()
    
    # Active rules
    active_rules_count = db.query(models.Rule).filter(models.Rule.is_active == True).count()
    
    # Active teams
    active_teams_count = db.query(models.Team).count()

    # Daily Stats (Last 7 days) — single query with GROUP BY
    seven_days_ago = datetime.combine(now.date() - timedelta(days=6), time.min)
    daily_query = db.query(
        func.date(models.RequestLog.timestamp).label("day"),
        func.count(models.RequestLog.id).label("cnt")
    ).filter(
        models.RequestLog.timestamp >= seven_days_ago
    ).group_by(func.date(models.RequestLog.timestamp)).order_by("day").all()

    daily_map = {row.day: row.cnt for row in daily_query}
    daily_stats = []
    for i in range(6, -1, -1):
        day = now.date() - timedelta(days=i)
        date_str = day.strftime("%m-%d")
        daily_stats.append({"date": date_str, "count": daily_map.get(str(day), 0)})
    
    return {
        "today_count": today_count,
        "success_count": success_count,
        "active_rules_count": active_rules_count,
        "active_teams_count": active_teams_count,
        "daily_stats": daily_stats
    }
