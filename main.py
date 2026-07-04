from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List, Any
import time

T = 41
R = 16
WINDOW = 10.0

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ORDERS_CATALOG: List[Dict[str, Any]] = [
    {"id": i, "name": f"Order {i}", "status": "created"}
    for i in range(1, T + 1)
]

idempotency_store: Dict[str, Dict[str, Any]] = {}
rate_limit_store: Dict[str, List[float]] = {}


def check_rate_limit(client_id: str) -> bool:
    now = time.time()
    if client_id not in rate_limit_store:
        rate_limit_store[client_id] = []

    timestamps = [t for t in rate_limit_store[client_id] if now - t < WINDOW]

    if len(timestamps) >= R:
        rate_limit_store[client_id] = timestamps
        return False

    timestamps.append(now)
    rate_limit_store[client_id] = timestamps
    return True


def rate_limit_response():
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
        headers={"Retry-After": "10"},
    )


def get_page(limit: int, cursor: Optional[str]):
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")

    if cursor is None:
        start_index = 0
    else:
        try:
            cursor_id = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

        start_index = None
        for idx, order in enumerate(ORDERS_CATALOG):
            if order["id"] == cursor_id:
                start_index = idx
                break

        if start_index is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    end_index = start_index + limit
    items = ORDERS_CATALOG[start_index:end_index]

    next_cursor = None
    if end_index < len(ORDERS_CATALOG):
        next_cursor = str(ORDERS_CATALOG[end_index]["id"])

    return items, next_cursor


@app.post("/orders")
async def create_order(request: Request):
    client_id = request.headers.get("X-Client-Id") or "default"
    if not check_rate_limit(client_id):
        return rate_limit_response()

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")

    if idempotency_key in idempotency_store:
        return JSONResponse(status_code=201, content=idempotency_store[idempotency_key])

    new_id = len(idempotency_store) + T + 1
    order = {
        "id": new_id,
        "name": f"New Order {new_id}",
        "status": "created",
    }
    idempotency_store[idempotency_key] = order
    return JSONResponse(status_code=201, content=order)


@app.get("/orders")
async def list_orders(limit: int = 10, cursor: Optional[str] = None, request: Request = None):
    client_id = request.headers.get("X-Client-Id") or "default"
    if not check_rate_limit(client_id):
        return rate_limit_response()

    items, next_cursor = get_page(limit, cursor)
    return JSONResponse(content={"items": items, "next_cursor": next_cursor})