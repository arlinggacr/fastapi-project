# WebSocket endpoints

Postman collection v2.1 and Newman cannot encode WebSocket requests, so the
collection documents them here instead. In Postman use **New → WebSocket
Request**, paste the URL, and click **Connect**.

Both endpoints take the token as a **query parameter**, because browsers cannot
set an `Authorization` header on a WebSocket handshake.

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `ws://127.0.0.1:8000/ws/auctions/{auction_id}?token=<optional>` | optional | Live feed for one auction (public read-only) |
| `ws://127.0.0.1:8000/ws/me?token=<required>` | required | Personal feed: `outbid`, `auction_started`, `auction_ended` |

Use `wss://` behind TLS.

## Ready-to-paste URLs

The collection captures `auctionId` and `accessToken` automatically. Postman
resolves collection variables inside a WebSocket URL, so you can paste:

```
ws://127.0.0.1:8000/ws/auctions/{{auctionId}}?token={{accessToken}}
ws://127.0.0.1:8000/ws/me?token={{accessToken}}
```

If the variables do not resolve, copy the raw values from the collection
variables pane instead.

## 1. Auction feed — `/ws/auctions/{auction_id}`

On connect the server sends a `snapshot`, then every event published for that
auction.

### `snapshot` (first message)

```json
{
  "type": "snapshot",
  "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
  "data": {
    "title": "Vintage mechanical watch",
    "status": "active",
    "current_price": "120.00",
    "min_next_bid": "130.00",
    "end_time": "2026-11-10T09:15:34.954000+00:00",
    "bid_count": 2,
    "seller_id": "b8e87255-52dc-4da8-8c18-ff95885112b8",
    "seller_username": "seller1_mwaf0ome",
    "you": {
      "id": "25d9fb64-11ea-4ba6-a041-610838f10935",
      "username": "bidder_mwaf0ome",
      "is_seller": false
    }
  }
}
```

`you` is `null` when the socket connected without a token.

### `bid_placed`

```json
{
  "type": "bid_placed",
  "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
  "data": {
    "bid_id": "b940f708-639c-4450-94f7-8407c745ac76",
    "amount": "120.00",
    "bidder_id": "25d9fb64-11ea-4ba6-a041-610838f10935",
    "bidder_username": "bidder2_mwaf0ome",
    "current_price": "120.00",
    "min_next_bid": "130.00",
    "end_time": "2026-11-10T09:15:34.954000+00:00",
    "bid_count": 2,
    "extended": false
  }
}
```

`extended` is `true` when the bid landed inside the anti-snipe window and
pushed `end_time` back — clients should re-render the countdown.

### `auction_started`

```json
{
  "type": "auction_started",
  "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
  "data": {
    "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
    "title": "Vintage mechanical watch",
    "start_time": "2026-11-10T08:15:34.954000+00:00",
    "end_time": "2026-11-10T09:15:34.954000+00:00",
    "starting_price": "100.00",
    "min_increment": "10.00"
  }
}
```

### `auction_ended`

```json
{
  "type": "auction_ended",
  "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
  "data": {
    "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
    "title": "Vintage mechanical watch",
    "final_price": "120.00",
    "winner_id": "25d9fb64-11ea-4ba6-a041-610838f10935",
    "winner_username": "bidder2_mwaf0ome"
  }
}
```

### `ping`

Every 25 s, so clients can detect a dead connection:

```json
{ "type": "ping", "ts": 1762762538959 }
```

### Close codes

| Code | Meaning |
| --- | --- |
| `4404` | Auction id does not exist |

Connecting without a token is allowed and yields a read-only feed (`you: null`).

## 2. Personal feed — `/ws/me`

Requires `?token=<accessToken>`. The first message is:

```json
{ "type": "ready", "user_id": "25d9fb64-11ea-4ba6-a041-610838f10935" }
```

Then every notification for that user. The envelope is the same shape as the
auction feed; `type` is the notification type.

### `outbid`

Sent to the previous leader when someone outbids them.

```json
{
  "type": "outbid",
  "user_id": "25d9fb64-11ea-4ba6-a041-610838f10935",
  "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
  "data": {
    "auction_id": "fb433bf0-cd4b-4a7b-920a-34890433f38b",
    "title": "Vintage mechanical watch",
    "new_price": "120.00",
    "by": "bidder2_mwaf0ome"
  }
}
```

`auction_started` and `auction_ended` arrive with the same `data` payloads shown
above. The same records are available over HTTP at `GET /notifications`.

Close code `4401` means the token was missing, expired or invalid.

## Manual smoke test

```bash
# Terminal 1: watch an auction (no token = read-only)
websocat "ws://127.0.0.1:8000/ws/auctions/$AUCTION_ID"

# Terminal 2: place a bid, then watch the event arrive in terminal 1
curl -s -X POST "http://127.0.0.1:8000/auctions/$AUCTION_ID/bids" \
  -H "Authorization: Bearer $BIDDER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"amount":"130.00"}'
```

`websocat` is the simplest client; `wscat -c <url>` works too.

The repository also ships `scripts/smoke_ws.py`, which exercises both sockets
end to end:

```bash
.venv/bin/python scripts/smoke_ws.py
```
