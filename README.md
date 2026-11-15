# THM Dashboard

Learning-progress dashboard for the Visionet L2 Bootcamp, built on TryHackMe public profiles.

## Why there is a collector

Since mid-2026 TryHackMe sits behind Vercel's anti-bot challenge: requests from datacenter IPs
(Vercel, VPS, CI runners) and from non-browser clients get `429 challenge`. The dashboard on
Vercel therefore never calls TryHackMe itself.

```
Vercel (app.py)  --GET /api/data, POST /api/refresh (X-Collector-Secret)-->  Tailscale Funnel (HTTPS)
                                                                              |
                                          collector host: collector_api.py (127.0.0.1:8100)
                                          cron */15 + refresh button -> collector.py
                                              -> curl_cffi (browser TLS) -> SOCKS5 via Tailscale exit node
                                              -> residential connection -> tryhackme.com
                                              -> data/thm.json
```

## TryHackMe endpoints (current)

All take `username=` (the old `user=<_id>` parameter is rejected; `_id` is no longer in the profile):

| Data | Endpoint |
|---|---|
| Profile | `/api/v2/public-profile?username=` (`totalPoints`, not `points`) |
| Completed rooms | `/api/v2/public-profile/completed-rooms?username=&page=&limit=100` |
| Badges | `/api/v2/public-profile/badges?username=&page=&limit=100` (paginated, default 10) |
| Certificates | `/api/v2/certificates/public-list?username=` |
| Activity | `/api/v2/public-profile/yearly-activity?username=&year=` (returns the whole year) |

## Configuration

- `users.json` - the tracked users.
- Vercel env: `COLLECTOR_URL` (Funnel URL), `COLLECTOR_SECRET`.
- Collector host: `.env` with `COLLECTOR_SECRET`, `THM_PROXY` (default `socks5h://127.0.0.1:1055`),
  dependencies from `requirements-collector.txt`.
- Without `COLLECTOR_URL`, `app.py` reads `data/thm.json` locally (useful on the collector host).

Refreshes from the dashboard are rate limited by the collector (all users: 120 s, one user: 60 s).
