"""
Lambda: results_handler
Triggered by: API Gateway
  GET /results/{job_id}   → single result (existing)
  GET /history/{session_id} → all jobs for a session (NEW)
"""
import json, os
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
table    = dynamodb.Table(os.environ["DYNAMODB_TABLE"])


def handler(event, context):
    path = event.get("rawPath", "") or event.get("path", "")

    # Route: GET /history/{session_id}
    if "/history/" in path:
        return _handle_history(event)

    # Route: GET /results/{job_id}
    return _handle_result(event)


# ─────────────────────────────────────────────────────────────────────────────
# /results/{job_id}
# ─────────────────────────────────────────────────────────────────────────────

def _handle_result(event):
    try:
        params = event.get("pathParameters") or {}
        job_id = params.get("job_id", "").strip()
        if not job_id:
            return _err(400, "Missing job_id. Use: GET /results/{job_id}")

        item = table.get_item(Key={"job_id": job_id}).get("Item")
        if not item:
            return _err(404, f"No job found: {job_id}")

        status = item.get("status", "unknown")

        if status == "completed":
            analysis = json.loads(item.get("analysis_json", "{}"))
            return _ok({
                "job_id":    job_id,
                "status":    "completed",
                "is_ai":      _parse_bool(item.get("is_ai")),
                "score":      _f(item.get("score")),
                "confidence": _f(item.get("confidence")),
                "label":      item.get("label", ""),
                "provider":   "huggingface",
                "details":    analysis.get("details", {}),
                "ai_percentage":    _f(item.get("ai_percentage")),
                "human_percentage": round(100 - (_f(item.get("ai_percentage")) or 0), 2),
                "classification":   item.get("classification", "unknown"),
                "confidence_level": item.get("confidence_level", "none"),
                "completed_at":     item.get("completed_at"),
                # Version history metadata
                "session_id":    item.get("session_id", ""),
                "filename":      item.get("filename", ""),
                "file_type":     item.get("file_type", "text"),
                "version_label": item.get("version_label", ""),
                "submitted_at":  item.get("submitted_at"),
                "text_preview":  item.get("text_preview", ""),
            })

        if status in ("queued", "processing"):
            return _ok({"job_id": job_id, "status": status,
                        "message": "Analysis in progress — poll again in 2 seconds."}, 202)

        if status == "failed":
            return _err(500, f"Analysis failed: {item.get('error', 'unknown error')}")

        return _ok({"job_id": job_id, "status": status})

    except ClientError as e:
        return _err(500, f"AWS error: {e.response['Error']['Message']}")
    except Exception as e:
        return _err(500, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# /history/{session_id}  — scan for all jobs belonging to this session
# ─────────────────────────────────────────────────────────────────────────────

def _handle_history(event):
    try:
        params     = event.get("pathParameters") or {}
        session_id = params.get("session_id", "").strip()
        if not session_id:
            return _err(400, "Missing session_id. Use: GET /history/{session_id}")

        # DynamoDB scan filtered by session_id.
        # For production with high volume, add a GSI on session_id.
        resp  = table.scan(FilterExpression=Attr("session_id").eq(session_id))
        items = resp.get("Items", [])

        # Handle paginated results
        while "LastEvaluatedKey" in resp:
            resp  = table.scan(
                FilterExpression=Attr("session_id").eq(session_id),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))

        # Sort by submitted_at descending (newest first)
        items.sort(key=lambda x: int(x.get("submitted_at", 0)), reverse=True)

        history = []
        for item in items:
            history.append({
                "job_id":        item.get("job_id"),
                "status":        item.get("status", "unknown"),
                "filename":      item.get("filename", "Pasted text"),
                "file_type":     item.get("file_type", "text"),
                "version_label": item.get("version_label", ""),
                "submitted_at":  item.get("submitted_at"),
                "completed_at":  item.get("completed_at"),
                "ai_percentage": _f(item.get("ai_percentage")),
                "human_percentage": round(100 - (_f(item.get("ai_percentage")) or 0), 2)
                                    if item.get("ai_percentage") else None,
                "label":         item.get("label", ""),
                "confidence_level": item.get("confidence_level", "none"),
                "classification":   item.get("classification", "unknown"),
            })

        return _ok({"session_id": session_id, "count": len(history), "history": history})

    except ClientError as e:
        return _err(500, f"AWS error: {e.response['Error']['Message']}")
    except Exception as e:
        return _err(500, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _parse_bool(v):
    if v is None: return None
    if isinstance(v, bool): return v
    return str(v).lower() == "true"

def _ok(body, code=200):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body, default=str),
    }

def _err(code, msg):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"error": msg}),
    }