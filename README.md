# Auction API

Realtime auction platform on FastAPI + Neon Postgres + Upstash Redis.

Users list their own items for auction; **anyone except the seller can bid**.
Live updates are pushed over WebSockets, and bidding is race-safe: concurrent
bids for the same price are arbitrated by a Redis Lua script, so exactly one
wins.

## Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.11, managed with `uv` |
| Web | FastAPI + Uvicorn |
| Database | Neon Postgres 18 (SQLAlchemy 2 async + psycopg 3) |
| Migrations | Alembic |
| Cache / realtime | Upstash Redis (REST or native TCP) |
| Auth | Argon2 (`pwdlib`) + JWT access/refresh (`pyjwt`) |
| Validation | Pydantic v2 DTOs + `bleach` sanitisation |

## Project layout

```
src/
├── main.py                     app factory, lifespan, middleware, error handler
├── api/router.py               aggregates every module router (no logic)
├── common/
│   ├── constants/enums.py      UserRole, AuctionStatus, NotificationType
│   ├── helpers/pagination.py   page/offset clamping
│   └── responses/errors.py     ApiError + typed helpers (409/403/404...)
├── core/
│   ├── config.py               pydantic-settings from .env
│   ├── keys.py                 every Redis key name in one place
│   ├── money.py                Decimal <-> integer cents
│   ├── realtime.py             Broker: stream + pub/sub fan-out
│   ├── redis.py                Gateway interface + RESP and REST backends
│   └── time.py                 UTC helpers
├── database/
│   ├── session.py              async engine, SessionLocal, get_session
│   └── models.py               imports all entities so Alembic sees them
├── middlewares/security.py     security headers + body size limit
├── modules/
│   ├── auth/        controllers → services            (login, refresh)
│   ├── users/       controllers → services → repositories → entities
│   ├── auctions/    controllers → services → repositories → entities
│   ├── notifications/ controllers → services → repositories → entities
│   └── admin/       controllers
└── utils/
    ├── deps.py                 FastAPI dependencies (auth, gateway, broker)
    ├── rate_limit.py           Redis fixed-window limiter
    ├── sanitize.py             XSS / URL / LIKE hardening
    └── security.py             hashing + JWT
```

Each module follows **controller → service → repository**:

* **controllers** – HTTP/WebSocket surface only: parse, call a service, return.
* **services** – business rules and orchestration.
* **repositories** – the only place that talks to the database.
* **entities** – SQLAlchemy models, colocated with their module.
* **dtos** – request validation and response shapes.

## Getting started

```bash
uv sync
cp .env.example .env          # then fill in DB_URL + Upstash credentials
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

Docs: <http://127.0.0.1:8000/docs>

Create your first admin:

```bash
uv run python scripts/create_admin.py \
  --email you@example.com --username admin --password 'S3curePassw0rd!'
```

## Environment

See `.env.example`. Notable keys:

* `DB_URL` – Neon connection string (`postgresql://…?sslmode=require`). The app
  rewrites it to `postgresql+psycopg://` automatically.
* `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` – REST access.
* `REDIS_URL` – optional `rediss://` endpoint. When present the app uses native
  pub/sub; otherwise it polls Redis Streams over REST.
* `JWT_SECRET` – generate with `python -c "import secrets;print(secrets.token_urlsafe(48))"`.

## API

### Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | email + username + password |
| POST | `/auth/login` | rate limited per IP+email |
| POST | `/auth/refresh` | rotate the token pair |
| POST | `/auth/me/password` | change password |
| GET | `/users/me` | current profile |
| GET | `/users/{id}` | public profile |

### Auctions
| Method | Path | Notes |
|---|---|---|
| POST | `/auctions` | seller creates a lot |
| GET | `/auctions` | filters: `status`, `category`, `q`, `seller_id`, paging |
| GET | `/auctions/{id}` | includes `min_next_bid`, watchers, bid count |
| PATCH | `/auctions/{id}` | seller/admin, scheduled only |
| DELETE | `/auctions/{id}` | seller/admin, not while active |
| POST | `/auctions/{id}/cancel` | seller/admin |
| POST | `/auctions/{id}/watch` | subscribe to start/end notifications |
| DELETE | `/auctions/{id}/watch` | unsubscribe |
| POST | `/auctions/{id}/bids` | place a bid |
| GET | `/auctions/{id}/bids` | history, highest first |

### Notifications
| Method | Path |
|---|---|
| GET | `/notifications` (`unread_only`, `limit`) |
| GET | `/notifications/unread-count` |
| POST | `/notifications/{id}/read` |

### Admin
| Method | Path |
|---|---|
| GET | `/admin/users` |
| PATCH | `/admin/users/{id}/role` |
| PATCH | `/admin/users/{id}/active` |
| POST | `/admin/auctions/{id}/end` |
| GET | `/admin/stats` |

### WebSockets
| Path | Auth | Purpose |
|---|---|---|
| `/ws/auctions/{id}?token=` | optional | snapshot on connect, then `bid_placed` (`extended: true` when the anti-snipe window fired), `auction_started`, `auction_ended`, `ping` |
| `/ws/me?token=` | required | personal `outbid`, `auction_started`, `auction_ended` |

```js
const ws = new WebSocket(`wss://host/ws/auctions/${id}?token=${accessToken}`);
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "bid_placed") updatePrice(msg.data.current_price);
};
```

## Bidding rules

1. The **seller cannot bid** on their own auction.
2. The first bid must be **≥ starting price**; afterwards each bid must be
   **≥ current price + min_increment**.
3. Bids are only accepted while the auction is `active`.
4. **Anti-sniping**: a bid within `EXTENSION_WINDOW_SECONDS` of the end pushes
   `end_time` out by `EXTENSION_SECONDS`.
5. Validation happens inside one Lua script (`BID_SCRIPT` in
   `bidding_service.py`), so two simultaneous bids cannot both succeed.

Amounts are stored as integer **cents** in Redis and `NUMERIC(12,2)` in
Postgres; `Decimal` is used at the API boundary.

## Security notes

* Every query is built with SQLAlchemy expressions → bound parameters, no
  string interpolation. Search terms have `%`/`_` escaped so `LIKE` patterns
  cannot be injected.
* Free-text fields are normalised and passed through `bleach` (no tags
  allowed) before storage; control characters are removed. `image_url` only
  accepts `http(s)` and rejects quote/angle-bracket characters, blocking
  `javascript:` and attribute-breakout payloads.
* Passwords are never sanitised, only length-bounded, then hashed with Argon2.
* Responses carry `nosniff`, `DENY` framing, a deny-all CSP and a strict
  referrer policy. Bodies over 1 MiB are rejected with `413`.
* Unhandled exceptions return a generic message — stack traces and driver
  errors are logged, never serialised.
* Login is rate limited in Redis; JWT type claims are enforced so a refresh
  token cannot be used as an access token.

## Postman

Every endpoint is exported as a ready-to-run collection, generated from
`app.openapi()` so it cannot drift from the code — the generator fails the build
if an endpoint is missing or unknown.

```bash
uv run python scripts/generate_postman.py   # writes postman/*.json
```

| File | Contents |
|---|---|
| `postman/Auction-API.postman_collection.json` | 32 requests in 8 folders, with assertions and variable capture |
| `postman/Auction-API.postman_environment.json` | `baseUrl`, `wsUrl`, admin credentials |
| `postman/WEBSOCKETS.md` | the two WebSocket endpoints, with payloads |

Import the collection and environment into Postman, then **Run collection**.
It is self-contained and repeatable:

1. `1. Auth` registers a fresh seller, bidder and second bidder, then logs all
   three in (emails are randomised per run).
2. `3. Auctions` creates an auction as the seller and captures `auctionId`.
3. `4. Bids` has the bidder bid, then the second bidder outbid them — which
   produces the `outbid` notification the next folder reads.
4. `6. Admin` needs a real admin (see below).
5. `8. Cleanup` is terminal: force end, cancel, delete.

The admin folder expects an admin account:

```bash
uv run python scripts/create_admin.py --email admin@example.com \
  --username admin --password 'Passw0rd!123'
```

The same run works headless with Newman, with or without the environment file:

```bash
npx --yes newman@6 run postman/Auction-API.postman_collection.json
npx --yes newman@6 run postman/Auction-API.postman_collection.json \
  -e postman/Auction-API.postman_environment.json
```

The environment holds configuration only (`baseUrl`, `wsUrl`, admin
credentials). Tokens and IDs are captured at runtime into collection
variables, and must never be duplicated in the environment: Postman resolves
environment values first, so an empty `accessToken` there would shadow the
token a login script stored. `scripts/generate_postman.py` enforces this.

WebSocket requests cannot be encoded in a Postman collection, so they live in
`postman/WEBSOCKETS.md`.

## Tests

```bash
uv run pytest                 # full suite
uv run ruff check src tests   # lint
uv run python scripts/smoke.py            # end-to-end against live services
uv run python scripts/smoke_realtime.py   # streams, scheduler, notifications
uv run python scripts/smoke_ws.py         # websocket handshake + live push
```

The suite runs against the services configured in `.env` and creates
throwaway records prefixed with random suffixes.
