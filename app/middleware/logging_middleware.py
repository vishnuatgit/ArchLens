import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("ArchLens.middleware")

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that measures the processing duration of incoming HTTP requests,
    logs request metrics, and appends the duration header to the response.
    """
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        try:
            response = await call_next(request)
        except Exception as e:
            logger.exception(
                f"Unhandled exception during processing | "
                f"Method: {request.method} | "
                f"Path: {request.url.path} | "
                f"Error: {str(e)}"
            )
            raise e
            
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        
        # Log request summary details
        logger.info(
            f"Client: {request.client.host if request.client else 'Unknown'} | "
            f"Method: {request.method} | "
            f"Path: {request.url.path} | "
            f"Status: {response.status_code} | "
            f"Duration: {process_time:.4f}s"
        )
        return response
