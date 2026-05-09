from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from .. import database, crud, models
from ..services import alert_parser, dingtalk, alert_normalizer
from ..services.dingtalk import dingtalk_client
import json

router = APIRouter(
    prefix="/api/v1/webhook",
    tags=["webhook"]
)

def _resolve_channel(db: Session, cid: int) -> models.NotificationChannel | None:
    """Resolve a channel by ID, falling back to default for cid=-1."""
    if cid == -1:
        def_id = crud.get_system_setting(db, "default_channel_id")
        channel = None
        if def_id:
            channel = crud.get_notification_channel(db, int(def_id))
        if not channel:
            all_channels = crud.get_notification_channels(db)
            for c in all_channels:
                if c.is_enabled:
                    channel = c
                    crud.set_system_setting(db, "default_channel_id", str(c.id))
                    break
        return channel
    return crud.get_notification_channel(db, cid)


async def process_alert(db: Session, alert_data: dict, log_id: int):
    try:
        # 1. Detect format and normalize to unified structure
        source_format = alert_normalizer.detect_format(alert_data)
        unified = alert_normalizer.normalize_alert(alert_data, source_format)

        # 2. Check if alert is silenced (payload level)
        silenced_by = alert_parser.check_alert_silenced(db, alert_data)
        if silenced_by:
            crud.update_request_log_status(
                db, log_id, "silenced",
                matched_rule=None,
                error=f"Silenced by: {silenced_by}"
            )
            return {"status": "silenced", "silence": silenced_by}

        # 3. Load rules once, extract raw alerts
        rules = alert_parser.get_active_rules(db)
        raw_alerts = alert_parser.extract_raw_alerts(alert_data, source_format)

        # 4. Process each alert individually: match → render → send
        responses = []
        matched_rules = set()
        channel_names = set()
        all_success = True
        has_sent_attempt = False

        for i, raw_alert in enumerate(raw_alerts):
            match_result = alert_parser.match_single_alert(raw_alert, rules)

            if match_result:
                cid, phones, rule_name = match_result
                matched_rules.add(rule_name)
            else:
                matched_rules.add("DEFAULT_FALLBACK")
                cid = -1
                phones = []

            channel = _resolve_channel(db, cid)
            if not channel:
                responses.append({"alert_index": i, "error": "Channel not found"})
                all_success = False
                continue

            if not channel.is_enabled:
                responses.append({"alert_index": i, "channel": channel.name, "error": "Channel disabled"})
                continue

            channel_names.add(channel.name)
            has_sent_attempt = True

            # Build single-alert unified object
            single_unified = dict(unified)
            single_unified["alerts"] = [unified["alerts"][i]] if i < len(unified["alerts"]) else []

            # Render message using channel template or format default
            template_str = channel.message_template or alert_normalizer.get_default_template(source_format)
            rendered_text = alert_normalizer.render_message(template_str, single_unified)

            # Append @ mentions
            if phones:
                at_text = "\n" + " ".join([f"@{phone}" for phone in phones])
                rendered_text += at_text

            # Send via DingTalk
            try:
                config = json.loads(channel.config)
                res = dingtalk_client.send_text(
                    text=rendered_text,
                    webhook_url=config.get("webhook_url"),
                    secret=config.get("secret"),
                    access_token=config.get("access_token"),
                    at_mobiles=phones
                )
                responses.append({"alert_index": i, "channel": channel.name, "rule": rule_name if match_result else "DEFAULT_FALLBACK", "result": res})

                errcode = res.get("errcode")
                if errcode is None and "response" in res and isinstance(res["response"], dict):
                    errcode = res["response"].get("errcode")

                if errcode is not None:
                    try:
                        if int(errcode) != 0:
                            all_success = False
                    except (ValueError, TypeError):
                        all_success = False

            except Exception as e:
                responses.append({"alert_index": i, "channel": channel.name, "error": str(e)})
                all_success = False

        # 5. Update log status
        if not has_sent_attempt:
            status = "no_channel"
            error_msg = "No matched channel or default channel configured"
        else:
            status = "success" if all_success else "failed"
            error_msg = None if all_success else "One or more alerts failed"

        crud.update_request_log_status(
            db,
            log_id,
            status,
            response=json.dumps(responses, ensure_ascii=False),
            error=error_msg,
            matched_rule=",".join(matched_rules) if matched_rules else None,
            dingtalk_request_body=None,
            channel_name=",".join(channel_names) if channel_names else None
        )

        return {"status": status, "responses": responses}

    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        from ..logger import logger
        logger.error(f"Error processing webhook: {error_msg}")
        crud.update_request_log_status(db, log_id, "failed", error=str(e))
        return {"status": "error", "error": str(e)}

import asyncio

# In-Memory Queue for Async Processing
webhook_queue = asyncio.Queue()

# Background Worker
async def webhook_worker():
    while True:
        try:
            # Get item from queue
            task = await webhook_queue.get()
            db_gen = database.get_db()
            db = next(db_gen)
            try:
                # Unpack task
                alert_data = task['alert_data']
                log_id = task['log_id']
                
                # Process
                await process_alert(db, alert_data, log_id)
            finally:
                db.close()
                webhook_queue.task_done()
        except Exception as e:
            print(f"Worker error: {e}")
            await asyncio.sleep(1)

# Start worker on startup
@router.on_event("startup")
async def startup_event():
    asyncio.create_task(webhook_worker())

@router.post("/send")
async def receive_webhook(request: Request, db: Session = Depends(database.get_db)):
    body_str = ""
    headers_str = "{}"
    alert_data = {}
    
    try:
        # 1. Read Body
        body_bytes = await request.body()
        if not body_bytes:
            # Treat empty body as empty JSON object {}
            body_str = "{}"
        else:
            body_str = body_bytes.decode("utf-8")
        
        # 2. Read Headers
        headers_dict = dict(request.headers)
        headers_str = json.dumps(headers_dict, indent=2)

        # 3. Parse JSON (Validation only)
        try:
            alert_data = json.loads(body_str)
        except json.JSONDecodeError:
            # Fallback for invalid JSON or plain text
            if body_str.strip():
                 # Try to parse custom text format
                 parsed_alerts = alert_parser.parse_text_to_alerts(body_str)
                 if parsed_alerts:
                     alert_data = {"alerts": parsed_alerts, "raw_message": body_str}
                 else:
                     alert_data = {"message": body_str}
            else:
                 alert_data = {}

    except Exception as e:
        print(f"Error preparing webhook: {str(e)}")
        if not body_str:
            body_str = "Error reading body"
            alert_data = {"error": str(e)}

    # 4. Create Log & Enqueue
    # Create log entry immediately (synchronously) to get ID
    log_entry = crud.create_request_log(db, headers=headers_str, body=body_str)
    
    # Enqueue for background processing
    await webhook_queue.put({
        "alert_data": alert_data,
        "log_id": log_entry.id
    })
    
    # Return immediately
    return {"status": "queued", "log_id": log_entry.id}
