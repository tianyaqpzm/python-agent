import time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理：确保所有错误响应包含 error_code 和 error_msg。
    支持 HTTPException(detail={"error_code": "...", "error_msg": "..."})
    """
    trace_id = request.headers.get("X-Trace-Id", "")
    path = request.url.path
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    error_code = "500"
    error_msg = str(exc)
    status_code = 500

    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        if isinstance(exc.detail, dict):
            error_code = exc.detail.get("error_code", str(status_code))
            error_msg = exc.detail.get("error_msg", str(exc.detail))
        else:
            error_code = str(status_code)
            error_msg = str(exc.detail)
    else:
        logger.error(f"【系统崩溃】{request.method} {path} traceId={trace_id}", exc_info=True)

    error_body = {
        "traceId": trace_id,
        "status": status_code,
        "error_code": error_code,
        "error_msg": error_msg,
        "path": path,
        "timestamp": timestamp
    }
    
    return JSONResponse(
        status_code=status_code,
        content=error_body
    )
