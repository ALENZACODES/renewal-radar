# Broker dashboard

Built on the tenant-separated `BrokerWorkspace` (`backend/renewal/broker/`).
Every call checks the workspace token, and every query is filtered by
workspace id, so one broker can't see another broker's clients.

## Pipeline (`pipeline.py`)

```
new -> documents_requested -> analysis_ready -> negotiating -> renewed | switched
  \__________________________________________/             \-> closed_lost -> new (reopen)
```

Closed stages (`renewed`, `switched`, `closed_lost`) accept no further moves
except reopening a lost client. Invalid moves return 422 with the allowed list.

Renewal windows: `overdue`, `under_30_days`, `30_to_90_days`,
`90_to_180_days`, `over_180_days`, `no_date`.

### Priority score (0 to 100)

| Part | Points |
|---|---|
| Urgency | 45 overdue or under 30 days, 35 for 30 to 90, 20 for 90 to 180, 5 later, 10 with no date |
| Stage | 10 new, 15 documents requested, 20 analysis ready or negotiating |
| Rate gap | balance x (client rate - market 5-year posted) / 100, one point per $200 a year, max 25 |

Each client's `priority_reasons` lists the parts that produced the score. The
market rate comes from the reference rate book (lender figure if available,
otherwise the chartered-bank proxy).

## Data (`dashboard.py`)

- `broker_profiles`: stage, lender, balance, rate, rate type. Updates only
  change the fields that were sent.
- `broker_stage_history`: every move with an optional note.
- `broker_tasks`: call, email, meeting, document or review, with a due date.
  **Call, email and meeting tasks require a recorded `contact_homeowner`
  consent** for that client.
- Every change writes to the workspace audit trail.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v5/broker/workspaces/{wid}/dashboard?top=10` | Counts by stage and window, balance maturing within 90 days, retention rate, top priorities, overdue and upcoming tasks |
| `GET /api/v5/broker/workspaces/{wid}/clients/{cid}` | Client view with priority reasons and stage history |
| `PATCH /api/v5/broker/workspaces/{wid}/clients/{cid}/profile` | Lender, balance, rate, rate type |
| `POST /api/v5/broker/workspaces/{wid}/clients/{cid}/stage` | Move stage (validated) |
| `POST /api/v5/broker/workspaces/{wid}/clients/{cid}/tasks` | Add a task (contact tasks need consent) |
| `POST /api/v5/broker/workspaces/{wid}/tasks/{task_id}/done` | Complete a task |

All endpoints take `X-Broker-Token`. Wrong tokens and other tenants' ids both
return 404 so the API doesn't reveal whether an id exists.
