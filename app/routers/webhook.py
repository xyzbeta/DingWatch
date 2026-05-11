from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .. import database, crud, models
from ..services import alert_parser, dingtalk, alert_normalizer
from ..services.dingtalk import dingtalk_client
import json

router = APIRouter(
    prefix="/api/v1/webhook",
    tags=["webhook"]
)

def _resolve_channel_mem(cid: int, all_channels: list, default_channel_id: str | None) -> tuple:
    """Resolve channel from preloaded data, no DB access.
    Returns (channel, new_default_id_or_None).
    """
    if cid == -1:
        channel = None
        if default_channel_id:
            cid_int = int(default_channel_id)
            channel = next((c for c in all_channels if c.id == cid_int), None)
        if not channel:
            for c in all_channels:
                if c.is_enabled:
                    return c, c.id
        return channel, None
    channel = next((c for c in all_channels if c.id == cid), None)
    return channel, None


async def process_alert(db: Session, alert_data: dict, log_id: int, query_params: dict = None):
    try:
        # ===== Phase 1: All DB reads =====
        source_format = alert_normalizer.detect_format(alert_data)
        unified = alert_normalizer.normalize_alert(alert_data, source_format)
        unified["params"] = query_params or {}

        silenced_by = alert_parser.check_alert_silenced(db, alert_data)
        if silenced_by:
            crud.update_request_log_status(
                db, log_id, "silenced",
                matched_rule=None,
                error=f"Silenced by: {silenced_by}"
            )
            return {"status": "silenced", "silence": silenced_by}

        rules = alert_parser.get_active_rules(db)
        raw_alerts = alert_parser.extract_raw_alerts(alert_data, source_format)
        all_channels = crud.get_notification_channels(db)
        default_channel_id = crud.get_system_setting(db, "default_channel_id")

        # Release session before HTTP calls
        db.close()

        # ===== Phase 2: Matching, rendering, HTTP calls (no DB held) =====
        responses = []
        matched_rules = set()
        channel_names = set()
        all_success = True
        has_sent_attempt = False
        new_default_channel_id = None

        for i, raw_alert in enumerate(raw_alerts):
            match_result = alert_parser.match_single_alert(raw_alert, rules)

            if match_result:
                cid, phones, rule_name = match_result
                matched_rules.add(rule_name)
            else:
                matched_rules.add("DEFAULT_FALLBACK")
                cid = -1
                phones = []

            channel, new_def_id = _resolve_channel_mem(cid, all_channels, default_channel_id)
            if new_def_id:
                new_default_channel_id = new_def_id

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

        # ===== Phase 3: Write results with fresh session =====
        if not has_sent_attempt:
            status = "no_channel"
            error_msg = "No matched channel or default channel configured"
        else:
            status = "success" if all_success else "failed"
            error_msg = None if all_success else "One or more alerts failed"

        db2 = next(database.get_db())
        try:
            if new_default_channel_id:
                crud.set_system_setting(db2, "default_channel_id", str(new_default_channel_id))
            crud.update_request_log_status(
                db2,
                log_id,
                status,
                response=json.dumps(responses, ensure_ascii=False),
                error=error_msg,
                matched_rule=",".join(matched_rules) if matched_rules else None,
                dingtalk_request_body=None,
                channel_name=",".join(channel_names) if channel_names else None
            )
        finally:
            db2.close()

        return {"status": status, "responses": responses}

    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        from ..logger import logger
        logger.error(f"Error processing webhook: {error_msg}")
        # Always use a fresh session for error logging (Phase 1 session may already be closed)
        try:
            db_err = next(database.get_db())
            try:
                crud.update_request_log_status(db_err, log_id, "failed", error=str(e))
            finally:
                db_err.close()
        except Exception:
            pass
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
                query_params = task.get('query_params', {})

                # Process
                await process_alert(db, alert_data, log_id, query_params)
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
    try:
        log_entry = crud.create_request_log(db, headers=headers_str, body=body_str)
    except Exception as e:
        import traceback
        print(f"Error creating request log: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"status": "error", "error": f"Database error: {str(e)}"})

    # Extract query parameters for template rendering
    query_params = dict(request.query_params)

    # Enqueue for background processing
    await webhook_queue.put({
        "alert_data": alert_data,
        "log_id": log_entry.id,
        "query_params": query_params
    })
    
    # Return immediately
    return {"status": "queued", "log_id": log_entry.id}
