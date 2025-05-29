import os
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Depends, Header, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP
import sys
import logging
from fastapi import Request
from fastapi.responses import JSONResponse

DD_API = "https://api.dontdie.com"

app = FastAPI(title="Don't Die MCP")

# Add CORS middleware to allow requests from the web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Allow the web UI
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint that verifies Redis connectivity."""
    try:
        # Test Redis connection
        await redis_client.ping()
        return {"status": "healthy", "service": "dd-mcp"}
    except Exception as e:
        return {"status": "unhealthy", "service": "dd-mcp", "error": str(e)}

# Global exception handler for detailed error logging

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc)})



# --- BEGIN: Dependencies and helpers ---

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))

async def bearer(auth: str = Header(None, alias="authorization")):
    
    if auth is None or not auth.strip():
        # Fallback to env var for local dev or MCP proxy
        auth = os.environ.get('DD_TOKEN', '')
        
        if auth and not auth.startswith("Bearer "):
            auth = f"Bearer {auth}"
    if not auth or not auth.startswith("Bearer "):
        
        raise HTTPException(401, "Missing Bearer")
    parts = auth.split(maxsplit=1)
    if len(parts) != 2 or not parts[1]:
        
        raise HTTPException(401, "Invalid Bearer format")
    return parts[1]


# --- END: Dependencies and helpers ---

# --- BEGIN: All endpoint definitions must come BEFORE MCP mount ---

from fastapi import Query

@app.get("/getDdScore", operation_id="get_dd_score")
async def get_dd_score(
    date: str = Query(None, description="A single date in YYYY-MM-DD format."),
    start_date: str = Query(None, description="Start date for a range in YYYY-MM-DD format."),
    end_date: str = Query(None, description="End date for a range in YYYY-MM-DD format."),
    days: int = Query(None, description="Number of days prior to the specified date (inclusive). Used only with 'date'."),
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    # Validation logic for parameter combinations
    if not date and not (start_date and end_date):
        raise HTTPException(422, "You must provide either 'date' or both 'start_date' and 'end_date'.")
    if date and (start_date or end_date):
        raise HTTPException(422, "Provide either 'date' or ('start_date' and 'end_date'), not both.")
    if (start_date and not end_date) or (end_date and not start_date):
        raise HTTPException(422, "Both 'start_date' and 'end_date' must be provided together.")
    if days is not None and not date:
        raise HTTPException(422, "'days' can only be used with 'date'.")
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    uid = await redis_client.get(token)
    if uid:
        uid = uid.decode()
    if not uid:  # step 1: resolve userId
        headers = {
            "Authorization": f"Bearer {token}",
            "x-dd-client-id": client_id,
        }
        
        async with httpx.AsyncClient() as h:
            resp = await h.get(
                f"{DD_API}/account",
                headers=headers,
            )
        resp.raise_for_status()
        uid = resp.json()["id"]
        await redis_client.set(token, uid, ex=86400)  # 24 h TTL cache
    # step 2: fetch score(s)
    headers = {
        "Authorization": f"Bearer {token}",
        "x-dd-client-id": client_id,
    }
    results = {}
    import datetime

    def daterange(start, end):
        for n in range(int((end - start).days) + 1):
            yield start + datetime.timedelta(n)

    if date and days is not None:
        # Fetch for N days prior to date (inclusive)
        end_dt = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        start_dt = end_dt - datetime.timedelta(days=days-1)
        fetch_dates = [d.strftime("%Y-%m-%d") for d in daterange(start_dt, end_dt)]
    elif start_date and end_date:
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        fetch_dates = [d.strftime("%Y-%m-%d") for d in daterange(start_dt, end_dt)]
    elif date:
        fetch_dates = [date]
    else:
        fetch_dates = []  # Should not happen due to validation above

    async with httpx.AsyncClient() as h:
        for d in fetch_dates:
            resp = await h.get(
                f"{DD_API}/user-profile/{uid}/score-v2",
                params={"date": d},
                headers=headers,
            )
            if resp.status_code == 200:
                results[d] = resp.json()
            else:
                results[d] = {"error": f"Failed to fetch score for {d}", "status_code": resp.status_code}
    return results

@app.get("/getMeasurements", operation_id="get_measurements")
async def get_measurements(
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    category_id = await get_category_id_by_name("Measurements", token, client_id)
    return await fetch_biomarkers(token, client_id, category_id)

@app.get("/getCapabilities", operation_id="get_capabilities")
async def get_capabilities(
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    category_id = await get_category_id_by_name("Capabilities", token, client_id)
    return await fetch_biomarkers(token, client_id, category_id)

@app.get("/getBiomarkers", operation_id="get_biomarkers")
async def get_biomarkers(
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    category_id = await get_category_id_by_name("Biomarkers", token, client_id)
    return await fetch_biomarkers(token, client_id, category_id)

@app.get("/getAllBiomarkers", operation_id="get_all_biomarkers")
async def get_all_biomarkers(
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    categories = await get_biomarker_categories(token, client_id)
    print("\n[DEBUG] Categories fetched:", file=sys.stderr)
    for cat in categories:
        print(f"  - {cat['name']} (id={cat['id']})", file=sys.stderr)

    results = {}
    for cat in categories:
        cat_id = cat["id"]
        cat_name = cat["name"]
        try:
            results[cat_name] = await fetch_biomarkers(token, client_id, cat_id)
        except Exception as e:
            results[cat_name] = {"error": str(e)}

    return results

@app.get("/getUserProtocols", operation_id="get_user_protocols")
async def get_user_protocols(
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id"),
    include_sections: bool = False
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    print("[DEBUG] get_user_protocols: client_id value:", client_id,
          file=sys.stderr, flush=True)
    protocols = await fetch_user_protocols(token, client_id)
    if not include_sections:
        return protocols
    results = []
    for proto in protocols:
        proto_id = proto.get("id")
        proto_result = dict(proto)
        if proto_id:
            try:
                proto_result["sections"] = await fetch_protocol_sections(
                    token, client_id, proto_id
                )
            except Exception as e:
                proto_result["sections_error"] = str(e)

        results.append(proto_result)
    return results

@app.post("/createUserProtocolSection", operation_id="create_user_protocol_section")
async def create_user_protocol_section_endpoint(
    protocol_id: str,
    section_data: dict = Body(...),
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(401, "Missing x-dd-client-id")
    return await create_user_protocol_section(
        token, client_id, protocol_id, section_data
    )

@app.post("/createUserProtocol", operation_id="create_user_protocol")
async def create_user_protocol_endpoint(
    protocol_data: dict = Body(...),
    token: str = Depends(bearer),
    client_id: str = Header(None, alias="x-dd-client-id")
):
    if not client_id:
        client_id = os.environ.get("DD_CLIENT_ID", "")
    if client_id == "":
        raise HTTPException(401, "Missing x-dd-client-id")
    return await create_user_protocol(token, client_id, protocol_data)

# --- END: All endpoint definitions must come BEFORE MCP mount ---

mcp = FastApiMCP(app)
mcp.mount()

# Debug: Print registered methods for /mcp
for route in app.routes:
    if hasattr(route, "path") and route.path == "/mcp":
        print(
            f"[DEBUG] /mcp route methods: {getattr(route, 'methods', None)}",
            file=sys.stderr, flush=True
        )

# Cache key for biomarker categories
BIOMARKER_CATEGORIES_KEY = "biomarker_categories"
CATEGORIES_CACHE_TTL = 86400  # 24 hours

async def get_biomarker_categories(token, client_id):
    cached = await redis_client.get(BIOMARKER_CATEGORIES_KEY)
    if cached:
        import json
        return json.loads(cached)
    headers = {
        "Authorization": f"Bearer {token}",
        "x-dd-client-id": client_id,
    }
    async with httpx.AsyncClient() as h:
        resp = await h.get(
            f"{DD_API}/system/biomarker-categories",
            headers=headers,
        )
    resp.raise_for_status()
    categories = resp.json()
    await redis_client.set(
        BIOMARKER_CATEGORIES_KEY,
        __import__('json').dumps(categories),
        ex=CATEGORIES_CACHE_TTL
    )
    return categories

# Helper to get category_id by name
async def get_category_id_by_name(name, token, client_id):
    cats = await get_biomarker_categories(token, client_id)
    for cat in cats:
        if cat["name"].lower() == name.lower():
            return cat["id"]
    raise ValueError(f"Category '{name}' not found")

async def get_uid(token, client_id):
    print("[DEBUG] get_uid called", file=sys.stderr, flush=True)
    print("[DEBUG] client_id in get_uid:", client_id, file=sys.stderr, flush=True)
    uid = await redis_client.get(token)
    if uid:
        return uid.decode()
    headers = {
        "Authorization": f"Bearer {token}",
        "x-dd-client-id": client_id,
    }
    async with httpx.AsyncClient() as h:
        resp = await h.get(
            f"{DD_API}/account",
            headers=headers,
        )
    resp.raise_for_status()
    uid = resp.json()["id"]
    await redis_client.set(token, uid, ex=86400)
    return uid

# Fetch user protocols (correct endpoint)
async def fetch_user_protocols(token, client_id):
    user_id = await get_uid(token, client_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "x-dd-client-id": client_id,
    }
    async with httpx.AsyncClient() as h:
        resp = await h.get(
            f"{DD_API}/user-health/{user_id}/protocols",
            headers=headers,
        )
    resp.raise_for_status()
    return resp.json()

# Fetch all sections for a protocol (correct endpoint)
async def fetch_protocol_sections(token, client_id, protocol_id):
    user_id = await get_uid(token, client_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "x-dd-client-id": client_id,
    }
    async with httpx.AsyncClient() as h:
        resp = await h.get(
            f"{DD_API}/user-health/{user_id}/protocols/{protocol_id}/sections",
            headers=headers,
        )
    resp.raise_for_status()
    return resp.json()

# Create a user protocol section (POST)
async def create_user_protocol_section(token, client_id, protocol_id, section_data):
    user_id = await get_uid(token, client_id)
    if 'status' not in section_data:
        section_data['status'] = 'Draft'
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Client-Id": client_id,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as h:
        resp = await h.post(
            f"{DD_API}/user-health/{user_id}/protocols/{protocol_id}/sections",
            headers=headers,
            json=section_data,
        )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logging.error(
            f"Error creating protocol section: {e.response.text}"
        )
        raise
    return resp.json()

# Create a user protocol (POST)
async def create_user_protocol(token, client_id, protocol_data):
    user_id = await get_uid(token, client_id)
    if 'status' not in protocol_data:
        protocol_data['status'] = 'Draft'
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Client-Id": client_id,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as h:
        resp = await h.post(
            f"{DD_API}/user-health/{user_id}/protocols",
            headers=headers,
            json=protocol_data,
        )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logging.error(
            f"Error creating protocol: {e.response.text}"
        )
        raise
    return resp.json()

async def fetch_biomarkers(token, client_id, category_id):
    headers = {
        "Authorization": f"Bearer {token}",
        "x-dd-client-id": client_id,
    }
    async with httpx.AsyncClient() as h:
        resp = await h.get(
            f"{DD_API}/account/biomarkers",
            params={"categoryId": category_id},
            headers=headers,
        )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logging.error(
            f"Error fetching biomarkers for category_id={category_id}: "
            f"{e.response.text}"
        )
        raise
    return resp.json()
