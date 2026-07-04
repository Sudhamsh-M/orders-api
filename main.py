from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List, Any
import time

# ---------- Configuration ----------
T = 41
R = 16
WINDOW = 10.0

# ---------- Create app ----------
app = FastAPI()

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Catalog ----------
ORDERS_CATALOG: List[Dict[str, Any]] = [
    {"id": i, "name": f"Order {i}", "status": "created"}
    for i in range(1, T + 1)
]

# ---------- Idempotency ----------
idempotency_store: Dict[str, Dict[str, Any]] = {}

# ---------- Rate limiting ----------
rate_limit_store: Dict[str, List[float]] = {}


def compute_next_cursor(current_index: int, limit: int) -> Optional[str]:
    next_index = current_index + limit
    if next_index < len(ORDERS_CATALOG):
        return str(ORDERS_CATALOG[next_index]["id"])
    return None


def check_rate_limit(client_id: str) -> bool:
    now = time.time()
    if client_id not in rate_limit_store:
        rate_limit_store[client_id] = []

    timestamps = rate_limit_store[client_id]
    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= R:
        rate_limit_store[client_id] = timestamps
        return False

    timestamps.append(now)
    rate_limit_store[client_id] = timestamps
    return True


# ---------- POST /orders (idempotent + rate limited) ----------
@app.post("/orders")
async def create_order(request: Request):
    client_id = request.headers.get("X-Client-Id") or "default"
    if not check_rate_limit(client_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": "10"},
        )

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")

    if idempotency_key in idempotency_store:
        order = idempotency_store[idempotency_key]
        return JSONResponse(status_code=201, content=order)

    new_id = len(idempotency_store) + T + 1
    order = {
        "id": new_id,
        "name": f"New Order {new_id}",
        "status": "created",
    }
    idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


# ---------- GET /orders (cursor pagination + rate limited) ----------
@app.get("/orders")
async def list_orders(limit: int = 10, cursor: Optional[str] = None, request: Request = None):
    client_id = request.headers.get("X-Client-Id") or "default"
    if not check_rate_limit(client_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": "10"},
        )

    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")

    if cursor is None:
        start_index = 0
    else:
        cursor_id = int(cursor)
        start_index = None
        for idx, o in enumerate(ORDERS_CATALOG):
            if o["id"] == cursor_id:
                start_index = idx
                break
        if start_index is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    end_index = start_index + limit
    page_items = ORDERS_CATALOG[start_index:end_index]
    next_cursor = compute_next_cursor(start_index, len(page_items))

    return JSONResponse(content={"items": page_items, "next_cursor": next_cursor})