from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas, database, crud
from .webhook import process_alert # Reuse logic
import json

router = APIRouter(
    prefix="/api/v1/debug",
    tags=["debug"]
)

@router.post("/replay/{log_id}")
async def replay_webhook(log_id: int, db: Session = Depends(database.get_db)):
    log_entry = db.query(models.RequestLog).filter(models.RequestLog.id == log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Log entry not found")

    try:
        raw_body = log_entry.body

        if raw_body is None or raw_body == "" or raw_body == "Empty/Invalid Body":
            alert_data = {}
        else:
            try:
                alert_data = json.loads(raw_body)
            except json.JSONDecodeError:
                from ..services import alert_parser
                if raw_body.strip():
                    parsed_alerts = alert_parser.parse_text_to_alerts(raw_body)
                    if parsed_alerts:
                        alert_data = {"alerts": parsed_alerts, "raw_message": raw_body}
                    else:
                        alert_data = {"message": raw_body}
                else:
                    alert_data = {"message": raw_body}

    except Exception:
        raise HTTPException(status_code=400, detail="Stored body is invalid and cannot be replayed")

    # 重置状态为 pending
    crud.update_request_log_status(db, log_id, "pending", response=None, error=None)

    # 用独立 session 执行处理（process_alert 内部会自行管理 session 生命周期）
    db2 = next(database.get_db())
    try:
        return await process_alert(db2, alert_data, log_id)
    finally:
        db2.close()

@router.post("/", response_model=schemas.RequestLog)
async def debug_webhook(request: Request, db: Session = Depends(database.get_db)):
    body_bytes = await request.body()
    try:
        body_str = body_bytes.decode("utf-8")
    except:
        body_str = body_bytes.decode("utf-8", errors="ignore")
    
    headers_dict = dict(request.headers)
    headers_str = json.dumps(headers_dict, indent=2)
    
    return crud.create_request_log(db=db, headers=headers_str, body=body_str)

@router.get("/logs")
def get_debug_logs(skip: int = 0, limit: int = 50, q: str = None, db: Session = Depends(database.get_db)):
    logs = crud.get_request_logs(db, skip=skip, limit=limit, query=q)
    total = crud.count_request_logs(db, query=q)
    return {"items": logs, "total": total, "page": (skip // limit) + 1, "size": limit}
