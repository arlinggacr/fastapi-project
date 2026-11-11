"""Generate a Postman v2.1 collection from the live OpenAPI schema.

Every operation is described declaratively below, but the paths, parameter
names and body schemas come from ``app.openapi()``. A coverage assertion fails
the build if an endpoint exists that the collection does not include, so the
two can never drift.

Usage:
    .venv/bin/python scripts/generate_postman.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.main import app

OUT_DIR = Path(__file__).resolve().parents[1] / "postman"
COLLECTION = OUT_DIR / "Auction-API.postman_collection.json"
ENVIRONMENT = OUT_DIR / "Auction-API.postman_environment.json"

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000"
PASSWORD = "Passw0rd!123"

SELLER = "{{sellerToken}}"
BIDDER = "{{accessToken}}"
BIDDER2 = "{{bidder2Token}}"
ADMIN = "{{adminToken}}"
PUBLIC = None


def unique_account(prefix: str, email_var: str, user_var: str) -> str:
    """Pre-request script giving each run a fresh, valid account."""
    return "\n".join(
        [
            "// Fresh account per run so the collection is repeatable.",
            "const suffix = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);",
            f"pm.collectionVariables.set('{email_var}', `{prefix}_${{suffix}}@example.com`);",
            f"pm.collectionVariables.set('{user_var}', `{prefix}_${{suffix}}`);",
        ]
    )


CREATE_AUCTION_SCRIPT = "\n".join(
    [
        "// end_time must be in the future, so recompute the window each run.",
        "const now = Date.now();",
        "pm.collectionVariables.set('startTime', new Date(now - 1000).toISOString());",
        "pm.collectionVariables.set('endTime', new Date(now + 60 * 60 * 1000).toISOString());",
    ]
)

SAVE_TOKENS = "\n".join(
    [
        "const body = pm.response.json().data;",
        "pm.collectionVariables.set('%s', body.access_token);",
        "pm.collectionVariables.set('refreshToken', body.refresh_token);",
        "pm.test('tokens issued', () => pm.expect(body.access_token).to.be.a('string'));",
    ]
)

# Each entry: folder, name, method, path, auth, body override, scripts.
REQUESTS: list[dict[str, Any]] = [
    # ---------------- 0. Meta ----------------
    {"folder": "0. Meta", "name": "Service info", "method": "get", "path": "/", "auth": PUBLIC},
    {"folder": "0. Meta", "name": "Health check", "method": "get", "path": "/health", "auth": PUBLIC},

    # ---------------- 1. Auth ----------------
    {
        "folder": "1. Auth",
        "name": "Register seller",
        "method": "post",
        "path": "/auth/register",
        "auth": PUBLIC,
        "body": {"email": "{{sellerEmail}}", "username": "{{sellerUsername}}", "password": PASSWORD},
        "prerequest": unique_account("seller", "sellerEmail", "sellerUsername"),
        "test": "pm.test('created', () => pm.response.to.have.status(201));\n"
        "pm.collectionVariables.set('sellerId', pm.response.json().data.id);",
    },
    {
        "folder": "1. Auth",
        "name": "Register bidder",
        "method": "post",
        "path": "/auth/register",
        "auth": PUBLIC,
        "body": {"email": "{{bidderEmail}}", "username": "{{bidderUsername}}", "password": PASSWORD},
        "prerequest": unique_account("bidder", "bidderEmail", "bidderUsername"),
        "test": "pm.test('created', () => pm.response.to.have.status(201));\n"
        "pm.collectionVariables.set('userId', pm.response.json().data.id);",
    },
    {
        "folder": "1. Auth",
        "name": "Login seller (saves sellerToken)",
        "method": "post",
        "path": "/auth/login",
        "auth": PUBLIC,
        "body": {"email": "{{sellerEmail}}", "password": PASSWORD},
        "test": SAVE_TOKENS % "sellerToken",
    },
    {
        "folder": "1. Auth",
        "name": "Login bidder (saves accessToken)",
        "method": "post",
        "path": "/auth/login",
        "auth": PUBLIC,
        "body": {"email": "{{bidderEmail}}", "password": PASSWORD},
        "test": SAVE_TOKENS % "accessToken",
    },
    {
        "folder": "1. Auth",
        "name": "Register bidder 2 (for outbid test)",
        "method": "post",
        "path": "/auth/register",
        "auth": PUBLIC,
        "body": {
            "email": "{{bidder2Email}}",
            "username": "{{bidder2Username}}",
            "password": PASSWORD,
        },
        "prerequest": unique_account("bidder2", "bidder2Email", "bidder2Username"),
        "test": "pm.test('created', () => pm.response.to.have.status(201));",
    },
    {
        "folder": "1. Auth",
        "name": "Login bidder 2 (saves bidder2Token)",
        "method": "post",
        "path": "/auth/login",
        "auth": PUBLIC,
        "body": {"email": "{{bidder2Email}}", "password": PASSWORD},
        "test": "pm.test('ok', () => pm.response.to.have.status(200));\n"
        "pm.collectionVariables.set('bidder2Token', pm.response.json().data.access_token);",
    },
    {
        "folder": "1. Auth",
        "name": "Login admin (needs scripts/create_admin.py)",
        "method": "post",
        "path": "/auth/login",
        "auth": PUBLIC,
        "body": {"email": "{{adminEmail}}", "password": "{{adminPassword}}"},
        "test": "if (pm.response.code === 200) {\n"
        "  pm.collectionVariables.set('adminToken', pm.response.json().data.access_token);\n"
        "} else {\n"
        "  console.warn('Admin login failed - run scripts/create_admin.py first.');\n"
        "}",
    },
    {
        "folder": "1. Auth",
        "name": "Refresh tokens",
        "method": "post",
        "path": "/auth/refresh",
        "auth": PUBLIC,
        "body": {"refresh_token": "{{refreshToken}}"},
        "test": SAVE_TOKENS % "accessToken",
    },
    {
        "folder": "1. Auth",
        "name": "Change bidder password (optional)",
        "method": "post",
        "path": "/auth/me/password",
        "auth": BIDDER,
        "body": {"current_password": PASSWORD, "new_password": "N3wPassw0rd!456"},
        "description": "Optional. Changes the bidder password, so rerun 'Register bidder' afterwards.",
    },

    # ---------------- 2. Users ----------------
    {"folder": "2. Users", "name": "My profile", "method": "get", "path": "/users/me", "auth": BIDDER},
    {
        "folder": "2. Users",
        "name": "Public profile",
        "method": "get",
        "path": "/users/{user_id}",
        "auth": PUBLIC,
        "path_values": {"user_id": "{{sellerId}}"},
    },

    # ---------------- 3. Auctions ----------------
    {
        "folder": "3. Auctions",
        "name": "Create auction (saves auctionId)",
        "method": "post",
        "path": "/auctions",
        "auth": SELLER,
        "body": {
            "title": "Vintage mechanical watch",
            "description": "Serviced 1968 chronograph, original box.",
            "category": "watches",
            "image_url": "https://example.com/watch.jpg",
            "starting_price": "100.00",
            "min_increment": "10.00",
            "start_time": "{{startTime}}",
            "end_time": "{{endTime}}",
        },
        "prerequest": CREATE_AUCTION_SCRIPT,
        "test": "const body = pm.response.json().data;\n"
        "pm.collectionVariables.set('auctionId', body.id);\n"
        "pm.collectionVariables.set('sellerId', body.seller.id);\n"
        "pm.test('created', () => pm.response.to.have.status(201));\n"
        "pm.test('starts active', () => pm.expect(body.status).to.be.oneOf(['active', 'scheduled']));",
    },
    {
        "folder": "3. Auctions",
        "name": "List auctions",
        "method": "get",
        "path": "/auctions",
        "auth": PUBLIC,
        "query": {
            "seller_id": "{{sellerId}}",
            "page": "1",
            "page_size": "20",
        },
        "test": "const body = pm.response.json();\n"
        "pm.test('page shape', () => {\n"
        "  pm.expect(body).to.have.property('data');\n"
        "  pm.expect(body).to.have.property('pagination');\n"
        "  pm.expect(body.pagination).to.have.property('totalData');\n"
        "});\n"
        "// Do not clobber auctionId - it is captured by 'Create auction'.\n"
        "pm.test('created auction is listed for its seller', () => {\n"
        "  const id = pm.collectionVariables.get('auctionId');\n"
        "  pm.expect(body.data.map((a) => a.id)).to.include(id);\n"
        "});",
    },
    {
        "folder": "3. Auctions",
        "name": "Get auction",
        "method": "get",
        "path": "/auctions/{auction_id}",
        "auth": PUBLIC,
        "test": "pm.test('has min_next_bid', () => pm.expect(pm.response.json().data).to.have.property('min_next_bid'));",
    },
    {
        "folder": "3. Auctions",
        "name": "Update auction (seller)",
        "method": "patch",
        "path": "/auctions/{auction_id}",
        "auth": SELLER,
        "body": {"title": "Vintage mechanical watch (updated)"},
        "description": (
            "Only allowed while the auction is still `scheduled`. The created "
            "auction starts immediately, so a 409 here is expected."
        ),
        "test": "pm.test('editable only while scheduled', () => pm.expect(pm.response.code).to.be.oneOf([200, 409]));",
    },
    {
        "folder": "3. Auctions",
        "name": "Watch auction (bidder)",
        "method": "post",
        "path": "/auctions/{auction_id}/watch",
        "auth": BIDDER,
        "test": "pm.test('watching', () => pm.response.to.have.status(204));",
    },
    {
        "folder": "3. Auctions",
        "name": "Unwatch auction (bidder)",
        "method": "delete",
        "path": "/auctions/{auction_id}/watch",
        "auth": BIDDER,
    },

    # ---------------- 4. Bids ----------------
    {
        "folder": "4. Bids",
        "name": "Place bid (bidder)",
        "method": "post",
        "path": "/auctions/{auction_id}/bids",
        "auth": BIDDER,
        "body": {"amount": "110.00"},
        "test": "const body = pm.response.json().data;\n"
        "pm.collectionVariables.set('bidId', body.bid.id);\n"
        "pm.test('accepted', () => pm.response.to.have.status(201));\n"
        "pm.test('price updated', () => pm.expect(body.current_price).to.eql('110.00'));",
        "description": "The seller cannot bid on their own auction, hence the bidder token.",
    },
    {
        "folder": "4. Bids",
        "name": "Outbid with bidder 2 (creates notification)",
        "method": "post",
        "path": "/auctions/{auction_id}/bids",
        "auth": BIDDER2,
        "body": {"amount": "120.00"},
        "test": "pm.test('accepted', () => pm.response.to.have.status(201));",
        "description": (
            "Bidder 1 gets an `outbid` notification, which makes the "
            "Notifications folder meaningful."
        ),
    },
    {
        "folder": "4. Bids",
        "name": "Bid history",
        "method": "get",
        "path": "/auctions/{auction_id}/bids",
        "auth": PUBLIC,
        "query": {"limit": "50"},
        "test": "pm.test('array', () => pm.expect(pm.response.json().data).to.be.an('array'));",
    },

    # ---------------- 5. Notifications ----------------
    {
        "folder": "5. Notifications",
        "name": "List notifications",
        "method": "get",
        "path": "/notifications",
        "auth": BIDDER,
        "query": {"limit": "50"},
        "test": "const body = pm.response.json().data;\n"
        "if (body.length) pm.collectionVariables.set('notificationId', body[0].id);\n"
        "pm.test('array', () => pm.expect(body).to.be.an('array'));",
    },
    {
        "folder": "5. Notifications",
        "name": "Unread count",
        "method": "get",
        "path": "/notifications/unread-count",
        "auth": BIDDER,
        "test": "pm.test('has unread', () => pm.expect(pm.response.json().data).to.have.property('unread'));",
    },
    {
        "folder": "5. Notifications",
        "name": "Mark notification read",
        "method": "post",
        "path": "/notifications/{notification_id}/read",
        "auth": BIDDER,
        "path_values": {"notification_id": "{{notificationId}}"},
        "description": (
            "Bidder 1 was outbid by bidder 2, so at least one notification "
            "should exist. Returns 404 when there is nothing to mark."
        ),
        "test": "pm.test('marked or nothing to mark', () => pm.expect(pm.response.code).to.be.oneOf([204, 404]));",
    },

    # ---------------- 6. Admin ----------------
    {
        "folder": "6. Admin",
        "name": "List users (admin)",
        "method": "get",
        "path": "/admin/users",
        "auth": ADMIN,
        "query": {"page": "1", "page_size": "50"},
        "test": "const body = pm.response.json().data;\n"
        "const mine = pm.collectionVariables.get('userId');\n"
        "const other = body.find((u) => u.id !== mine);\n"
        "if (other) pm.collectionVariables.set('targetUserId', other.id);",
    },
    {
        "folder": "6. Admin",
        "name": "Set user role (admin)",
        "method": "patch",
        "path": "/admin/users/{user_id}/role",
        "auth": ADMIN,
        "path_values": {"user_id": "{{targetUserId}}"},
        "body": {"role": "admin"},
    },
    {
        "folder": "6. Admin",
        "name": "Enable / disable user (admin)",
        "method": "patch",
        "path": "/admin/users/{user_id}/active",
        "auth": ADMIN,
        "path_values": {"user_id": "{{targetUserId}}"},
        "query": {"is_active": "true"},
    },
    {
        "folder": "6. Admin",
        "name": "Platform stats (admin)",
        "method": "get",
        "path": "/admin/stats",
        "auth": ADMIN,
        "test": "pm.test('shape', () => {\n"
        "  const b = pm.response.json().data;\n"
        "  ['users', 'auctions', 'bids', 'active_auctions'].forEach((k) => pm.expect(b).to.have.property(k));\n"
        "});",
    },

    # ---------------- 8. Cleanup (terminal) ----------------
    {
        "folder": "8. Cleanup (terminal)",
        "name": "Force end auction (admin)",
        "method": "post",
        "path": "/admin/auctions/{auction_id}/end",
        "auth": ADMIN,
        "description": "Terminal: ends the auction immediately and notifies watchers.",
        "test": "pm.test('ended', () => pm.expect(pm.response.json().data.status).to.eql('ended'));",
    },
    {
        "folder": "8. Cleanup (terminal)",
        "name": "Cancel auction (seller)",
        "method": "post",
        "path": "/auctions/{auction_id}/cancel",
        "auth": SELLER,
        "description": (
            "Terminal. Returns 409 once the auction has ended, which is why the "
            "test accepts it - run this before 'Force end' if you want a 200."
        ),
        "test": "pm.test('cancel or already ended', () => pm.expect(pm.response.code).to.be.oneOf([200, 409]));",
    },
    {
        "folder": "8. Cleanup (terminal)",
        "name": "Delete auction (seller)",
        "method": "delete",
        "path": "/auctions/{auction_id}",
        "auth": SELLER,
        "description": "Only allowed when the auction is not active.",
        "test": "pm.test('deleted', () => pm.expect(pm.response.code).to.be.oneOf([204, 409]));",
    },
]

FOLDER_ORDER = [
    "0. Meta",
    "1. Auth",
    "2. Users",
    "3. Auctions",
    "4. Bids",
    "5. Notifications",
    "6. Admin",
    "7. WebSockets (docs)",
    "8. Cleanup (terminal)",
]

# Path parameter -> collection variable holding the id.
DEFAULT_PATH_VALUES = {
    "auction_id": "{{auctionId}}",
    "user_id": "{{userId}}",
    "notification_id": "{{notificationId}}",
}

# Query params that are noisy or destructive when always sent.
QUERY_DISABLED = {
    ("get", "/auctions"): {"status", "category", "q"},
    ("get", "/notifications"): {"limit"},
}


def resolve(spec: dict, node: dict) -> dict:
    seen = 0
    while "$ref" in node and seen < 10:
        node = spec["components"]["schemas"][node["$ref"].split("/")[-1]]
        seen += 1
    return node


def example_for(spec: dict, node: dict) -> Any:
    node = resolve(spec, node)
    if "enum" in node:
        return node["enum"][0]
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        return example_for(spec, options[0]) if options else None
    kind = node.get("type")
    if kind == "object":
        return {k: example_for(spec, v) for k, v in node.get("properties", {}).items()}
    if kind == "array":
        return [example_for(spec, node.get("items", {}))]
    if kind == "string":
        return {
            "email": "user@example.com",
            "uuid": "00000000-0000-0000-0000-000000000000",
            "date-time": "{{startTime}}",
        }.get(node.get("format"), "string")
    if kind == "integer":
        return 1
    if kind == "number":
        return 1
    if kind == "boolean":
        return True
    return None


def bearer(token: str) -> dict:
    return {
        "type": "bearer",
        "bearer": [{"key": "token", "value": token, "type": "string"}],
    }


def build_item(spec: dict, entry: dict) -> dict:
    method = entry["method"]
    path = entry["path"]
    operation = spec["paths"][path][method]
    key = (method, path)

    path_params = [p["name"] for p in operation.get("parameters", []) if p.get("in") == "path"]
    query_params = [p for p in operation.get("parameters", []) if p.get("in") == "query"]

    segments = [s for s in path.strip("/").split("/") if s]
    postman_path = [f":{s[1:-1]}" if s.startswith("{") else s for s in segments]

    # Map every path parameter onto the collection variable that holds its id.
    # Falling back to `{{<param_name>}}` would reference a variable that does
    # not exist, leaving literal braces in the URL and causing a 422.
    variables = []
    for name in path_params:
        value = (entry.get("path_values") or {}).get(name) or DEFAULT_PATH_VALUES.get(name)
        if not value:
            raise SystemExit(f"{method.upper()} {path}: no collection variable for path param {name!r}")
        variables.append({"key": name, "value": value})

    query = []
    provided = entry.get("query") or {}
    disabled = QUERY_DISABLED.get(key, set())
    for param in query_params:
        name = param["name"]
        query.append(
            {
                "key": name,
                "value": provided.get(name, ""),
                "description": param.get("description", ""),
                "disabled": name in disabled or name not in provided,
            }
        )

    # `raw` must use Postman's :variable syntax too - Newman executes `raw`.
    raw = "{{baseUrl}}/" + "/".join(postman_path)
    enabled = [q for q in query if not q["disabled"] and q["value"] != ""]
    if enabled:
        raw += "?" + "&".join(f"{q['key']}={q['value']}" for q in enabled)

    url: dict[str, Any] = {"raw": raw, "host": ["{{baseUrl}}"], "path": postman_path}
    if query:
        url["query"] = query
    if variables:
        url["variable"] = variables

    request: dict[str, Any] = {
        "method": method.upper(),
        "header": [],
        "url": url,
        "description": entry.get("description") or operation.get("description") or f"{method.upper()} {path}",
    }

    if entry.get("auth"):
        request["auth"] = bearer(entry["auth"])

    body_schema = (
        operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    )
    if body_schema:
        body = entry.get("body") or example_for(spec, body_schema)
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }

    item: dict[str, Any] = {"name": entry["name"], "request": request, "response": []}

    events = []
    if entry.get("prerequest"):
        events.append(
            {
                "listen": "prerequest",
                "script": {"type": "text/javascript", "exec": entry["prerequest"].splitlines()},
            }
        )
    if entry.get("test"):
        events.append(
            {
                "listen": "test",
                "script": {"type": "text/javascript", "exec": entry["test"].splitlines()},
            }
        )
    if events:
        item["event"] = events

    return item


def assert_full_coverage(spec: dict) -> None:
    described = {(e["method"], e["path"]) for e in REQUESTS}
    available = {
        (m, p)
        for p, ops in spec["paths"].items()
        for m in ops
        if m in {"get", "post", "patch", "delete", "put"}
    }
    missing = available - described
    extra = described - available
    if missing or extra:
        raise SystemExit(f"coverage mismatch. missing={sorted(missing)} extra={sorted(extra)}")


def build_collection() -> dict:
    spec = app.openapi()
    assert_full_coverage(spec)

    buckets: dict[str, list[dict]] = {}
    for entry in REQUESTS:
        buckets.setdefault(entry["folder"], []).append(build_item(spec, entry))

    folders = [{"name": name, "item": buckets[name]} for name in FOLDER_ORDER if name in buckets]

    ws_note = (
        "**WebSocket endpoints** (not runnable in Postman/Newman collections)\n\n"
        "- `GET {{wsUrl}}/ws/auctions/{auctionId}?token=<optional>` - live auction feed. "
        "Sends `snapshot` on connect, then `bid_placed`, `auction_started`, `auction_ended`, `ping`.\n"
        "- `GET {{wsUrl}}/ws/me?token=<required>` - personal feed: `outbid`, `auction_started`, `auction_ended`.\n\n"
        "In Postman use **New -> WebSocket Request** and paste the URL. "
        "See `postman/WEBSOCKETS.md` for a ready-to-paste example.\n"
    )

    return {
        "info": {
            "_postman_id": "b7f1c2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
            "name": "Auction API",
            "description": (
                "Realtime auction API - every endpoint.\n\n"
                "**Run order (Collection Runner works as-is)**\n"
                "1. `1. Auth` - registers a fresh seller and bidder, then logs both in.\n"
                "2. `3. Auctions` - the seller creates an auction (`auctionId` captured).\n"
                "3. `4. Bids` - the bidder bids (the seller cannot bid on their own lot).\n"
                "4. `5. Notifications`, `6. Admin`.\n"
                "5. `8. Cleanup` - terminal operations (force end, cancel, delete).\n\n"
                "**Captured variables**: `sellerToken`, `accessToken`, `refreshToken`, "
                "`sellerId`, `userId`, `auctionId`, `bidId`, `notificationId`, `targetUserId`, `adminToken`.\n\n"
                "**Admin folder** needs a real admin:\n"
                "`uv run python scripts/create_admin.py --email admin@example.com "
                "--username admin --password 'S3curePassw0rd!'`\n"
                "then set the `adminEmail` / `adminPassword` collection variables.\n\n"
                "Emails are randomised per run, so the collection is repeatable.\n\n"
                + ws_note
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
        "auth": bearer(BIDDER),
        "variable": [
            {"key": "baseUrl", "value": BASE_URL, "type": "string"},
            {"key": "wsUrl", "value": WS_URL, "type": "string"},
            {"key": "accessToken", "value": "", "type": "string"},
            {"key": "refreshToken", "value": "", "type": "string"},
            {"key": "sellerToken", "value": "", "type": "string"},
            {"key": "bidder2Token", "value": "", "type": "string"},
            {"key": "adminToken", "value": "", "type": "string"},
            {"key": "userId", "value": "", "type": "string"},
            {"key": "sellerId", "value": "", "type": "string"},
            {"key": "targetUserId", "value": "", "type": "string"},
            {"key": "auctionId", "value": "", "type": "string"},
            {"key": "bidId", "value": "", "type": "string"},
            {"key": "notificationId", "value": "", "type": "string"},
            {"key": "sellerEmail", "value": "", "type": "string"},
            {"key": "sellerUsername", "value": "", "type": "string"},
            {"key": "bidderEmail", "value": "", "type": "string"},
            {"key": "bidderUsername", "value": "", "type": "string"},
            {"key": "bidder2Email", "value": "", "type": "string"},
            {"key": "bidder2Username", "value": "", "type": "string"},
            {"key": "adminEmail", "value": "admin@example.com", "type": "string"},
            {"key": "adminPassword", "value": PASSWORD, "type": "string"},
            {"key": "startTime", "value": "", "type": "string"},
            {"key": "endTime", "value": "", "type": "string"},
        ],
    }


def build_environment() -> dict:
    return {
        "id": "c8e2d3f4-5a6b-4c7d-9e0f-1a2b3c4d5e6f",
        "name": "Auction API - Local",
        "values": [
            {"key": "baseUrl", "value": BASE_URL, "type": "default", "enabled": True},
            {"key": "wsUrl", "value": WS_URL, "type": "default", "enabled": True},
            {"key": "adminEmail", "value": "admin@example.com", "type": "default", "enabled": True},
            {"key": "adminPassword", "value": PASSWORD, "type": "secret", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    }


_CAPTURE_RE = re.compile(r"pm\.collectionVariables\.set\(\s*['\"]([A-Za-z0-9_]+)['\"]")


def captured_variables(collection: dict) -> set[str]:
    """Names the collection writes into ``collectionVariables`` at runtime."""
    found: set[str] = set()

    def walk(items: list[dict]) -> None:
        for item in items:
            for event in item.get("event", []):
                script = event.get("script", {}).get("exec", [])
                text = "\n".join(script) if isinstance(script, list) else str(script)
                found.update(_CAPTURE_RE.findall(text))
            walk(item.get("item", []))

    walk(collection.get("item", []))
    return found


def assert_environment_scope(collection: dict) -> None:
    """Fail if the environment shadows a variable the collection captures.

    Postman resolves ``{{name}}`` from the environment *before* the
    collection, so an empty ``accessToken`` in the environment wins over the
    token a login script stored in ``collectionVariables``. Every
    authenticated request would then send an empty bearer token. Runtime
    captures must therefore live in the collection only.
    """
    env_keys = {value["key"] for value in build_environment()["values"]}
    shadowed = env_keys & captured_variables(collection)
    if shadowed:
        raise SystemExit(
            "environment defines runtime-captured variables, which shadow the "
            f"collection values: {sorted(shadowed)}"
        )


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    collection = build_collection()
    assert_environment_scope(collection)
    COLLECTION.write_text(json.dumps(collection, indent=2) + "\n")
    ENVIRONMENT.write_text(json.dumps(build_environment(), indent=2) + "\n")

    total = sum(len(f.get("item", [])) for f in collection["item"])
    print(f"wrote {COLLECTION.relative_to(OUT_DIR.parent)} ({total} requests)")
    print(f"wrote {ENVIRONMENT.relative_to(OUT_DIR.parent)}")


if __name__ == "__main__":
    main()
