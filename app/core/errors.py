"""统一的机器可读错误响应。

所有错误体形如：{"code": "<machine readable>", "message": "<human readable>"}
"""

from __future__ import annotations

from fastapi.responses import JSONResponse


def error_body(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message))
