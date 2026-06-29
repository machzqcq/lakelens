# Security & Audit

Honest assessment of where the app stands today vs. production-ready, plus
the concrete remediations needed before exposing it on the public internet
or against real customer data.

The app is **good for internal demos / dev / staging environments** out of
the box. It is **not** production-ready until the items in
[§ Production-readiness checklist](#production-readiness-checklist) are
addressed.

---

## Table of contents

1. [Threat model](#threat-model)
2. [What's already hardened](#whats-already-hardened)
3. [What's NOT hardened (and the fix)](#whats-not-hardened-and-the-fix)
4. [Production-readiness checklist](#production-readiness-checklist)
5. [Audit / compliance posture](#audit--compliance-posture)
6. [Incident-response runbook stubs](#incident-response-runbook-stubs)

---

## Threat model

| Asset | Why an attacker would want it | Sensitivity |
|---|---|---|
| Cost data (`billing_usage`) | Reveals spend, project sizes, headcount inferences | Medium-High |
| User identities (`auth_users`) | Enumeration, credential stuffing | Medium |
| LLM API keys (env / `.env`) | Free LLM credits, attribution to your account | High |
| Databricks tokens (`DATABRICKS_TOKEN`) | Read everything in the workspace | **Critical** |
| Bcrypt password hashes | Offline cracking | High |
| OAuth client secrets | Impersonate the app at the IdP | High |

| Adversary | Capability |
|---|---|
| Unauthenticated remote attacker | Network access to API/UI |
| Authenticated low-privilege user | Valid JWT for `user` role |
| Authenticated admin | Valid JWT for `admin` role; can manage users/roles |
| Co-tenant (multi-tenant deploy) | Shouldn't exist — see [§ Single-tenant assumption](#single-tenant-assumption) |
| Insider with DB access | Direct Postgres credentials |

---

## What's already hardened

### Authentication & sessions

- **Bcrypt** password hashing (cost factor 12), input truncated to 72 bytes
  before hashing per bcrypt's spec.
- **JWT** access tokens, HS256-signed via the `JWT_SECRET` env var. Default
  TTL 24 h.
- **Email verification** required before email/password login (only).
- **OAuth state** (CSRF token) generated server-side, validated on
  callback, single-use.
- **GitHub primary email fallback** — when the public profile email is
  null, the backend fetches `/user/emails` and picks the verified primary.
- **No user enumeration on `/resend-verification`** — the endpoint always
  returns success regardless of whether the email exists.

### Authorization

- **Router-level `Depends(get_current_user)`** on every data router
  (`billing`, `compute`, `analytics`, `chat`).
- **`require_admin` dependency** on the entire `admin` router.
- **`is_admin` check** on the frontend hides admin nav items, AND
  `<RequireAdmin>` wraps the admin routes (so a user can't navigate
  directly via URL).
- **Self-protection on admin endpoints**: an admin can't delete their own
  account or remove their own admin role (both 400).
- **Admin-provisioned accounts** (`POST /api/admin/users`) are created
  active and (by default) pre-verified with an admin-set password, so the
  flow is gated behind `require_admin` rather than the email loop.
- **Data-scope filters** translate a custom role's JSON into SQL `WHERE`
  clauses, applied **before execution on every billing and analytics
  endpoint** (including the `analytics_service` helpers) and the
  cluster/warehouse listings — there are no unscoped data paths. Admins
  bypass; a logged-in user with no custom role is unrestricted; a
  role-less user sees nothing (`__deny_all__`). Only **non-system**
  (custom) roles define scope: the always-assigned `user` system role is
  neutral, so a scoped role can't be silently cancelled by it.
  Multi-role users get the union of allowed values per dimension. Filter
  list values are coerced to `str` so an int/string type mismatch can't
  accidentally widen (or void) the `IN` clause.
- **Per-role feature flags** (`auth_roles.features` JSON column) gate
  every UI surface AND every gated route. The frontend's `useFeatures()`
  hook hides the sidebar entry; the `<RequireFeature>` route wrapper
  redirects to `/` when the user lacks the key. A disabled feature is
  unreachable by direct URL — there is no "bypass" for non-admins.
  Admins and the bootstrap `user` role get every feature; only
  explicitly-restricted custom roles can shrink the set. The canonical
  registry of keys lives in `backend/features_registry.py` and is
  validated server-side on role create/edit — unknown keys are silently
  dropped so a stale client can't smuggle them in.

### Generated SQL (chatbot)

- LLM output is parsed for a single `\`\`\`sql\`\`\`` block; trailing semicolons
  are stripped; multi-statement SQL is rejected.
- `_is_safe_select` regex blocks DML / DDL / `ATTACH` / `COPY` / `PRAGMA`
  keywords.
- Every chatbot SQL is wrapped as `SELECT * FROM (<llm-sql>) LIMIT N` so
  even a SELECT can't run unbounded.
- Execution happens in **DuckDB on parquet** — completely isolated from
  Postgres. The LLM has no access to the auth tables or the operational DB.
- Every call is logged to SQLite + JSONL with the user's question, the
  generated SQL, the system prompt hash, the raw LLM response, the result
  shape, and the elapsed time.

### Database Explorer (admin ad-hoc SQL)

- The entire `/api/admin/db` router is behind `require_admin`.
- `/api/admin/db/query` accepts a **single** statement only — `;`-chained
  statements are rejected after comment-stripping.
- The statement must start with `SELECT` or `WITH`; a keyword blocklist
  rejects `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE/
  COPY/CALL/DO/SET/...` even in otherwise-`SELECT` text.
- Defense-in-depth at the DB: the query runs in a `SET TRANSACTION READ
  ONLY` transaction with `SET LOCAL statement_timeout = 15s`, and the
  session is rolled back in a `finally` so the explorer can never leave a
  write/locked transaction open. Result is capped at 1,000 rows.
- It runs against the **operational Postgres** (not the chatbot's DuckDB),
  so it *can* read the auth tables — acceptable because it is admin-only
  and strictly read-only, but worth noting in the threat model.

### Transport / app-shell

- **CORS** is open (`allow_origins=["*"]`) — see "Not hardened".
- **No `eval` / `Function` / `dangerouslySetInnerHTML`** in the frontend.
  All user content goes through React's escaping.
- All client → server requests carry the JWT in `Authorization: Bearer`,
  not as cookies — so CSRF isn't an attack class for the API.
- Theme picker writes to `localStorage` only.

### Secrets

- `.env` is `.gitignore`'d.
- LLM API keys are read at call time; never logged or returned in any
  response.
- AWS credentials are read by `boto3`'s default chain (env / profile /
  IMDS) — no key handling in code.

---

## What's NOT hardened (and the fix)

### CORS open to all origins

`backend/main.py` sets `allow_origins=["*"]`. Acceptable for local dev,
**not** for prod.

```python
# Replace with explicit origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "https://your-domain.example").split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### JWT in localStorage

Tokens in `localStorage` are readable by any JS on the same origin. An XSS
becomes account takeover.

**Fix**: use httpOnly + Secure + SameSite=Lax cookies for the access token.
Requires:
- A small CSRF token on state-changing endpoints (POST/PATCH/DELETE).
- `credentials: 'include'` on fetch.

### Default secrets baked in

`auth_utils.JWT_SECRET` defaults to a placeholder string when `JWT_SECRET`
env is missing. **Always set `JWT_SECRET` to ≥256 bits of entropy.**

`.env.example` includes placeholder LLM keys. **Rotate any keys you see
there if they were ever exposed.**

### No rate limiting

`/api/auth/login` accepts unlimited attempts per IP / per email. Trivially
brute-forceable.

**Fix**: put a reverse proxy in front (Cloudflare, nginx `limit_req`, AWS
WAF, GCP Cloud Armor) or use `slowapi` / `fastapi-limiter` (Redis-backed).

Suggested limits:
- `/api/auth/login`: 5 / min / IP, 20 / hour / email
- `/api/auth/register`: 3 / min / IP
- `/api/chat/ask`: 60 / min / user (LLM cost shield)

### OAuth state in-process

`_oauth_state` is a Python dict. Behind multiple workers / containers,
state initiated on container A won't be found by container B → 400 on
callback.

**Fix**: Redis-backed store, or a signed-cookie state (JWT short-lived).

### No refresh tokens / token revocation

Logout is purely client-side. A leaked JWT works until it expires (24 h).

**Fix**: implement refresh tokens with a server-side revocation store
(Redis blacklist). Drop access TTL to 15 min.

### Password policy is minimal

Only `min_length=8`. No complexity / breach-corpus check.

**Fix**: integrate `zxcvbn` (frontend hint) and check against
`HaveIBeenPwned` k-anonymity API on register.

### No audit log of admin actions

Role assignment / user deletion isn't recorded.

**Fix**: a small `audit_log` table — `actor_user_id`, `action`,
`target_type`, `target_id`, `metadata json`, `created_at`. Write from each
mutating admin endpoint.

### Database connection uses a single user

`DB_USER` reads + writes everything. A SQL-injection bug → game over.

**Fix**: separate `app_rw` (used by FastAPI) from `app_admin` (migrations
only). Do NOT give `app_rw` superuser or DDL rights.

### No DB-level encryption at rest documented

The compose file uses default Postgres without TDE. Acceptable for
local; in cloud, **enable encryption at rest** on the managed DB
(RDS / Cloud SQL / Azure Postgres flex all support it natively).

### No TLS enforcement

The compose stack speaks plain HTTP. **Fix at the edge**: terminate TLS
at the cloud load balancer (ALB / Front Door / GCLB) and redirect
HTTP→HTTPS.

### Single-tenant assumption

The schema has one `account_id` field but no `tenant_id` on `auth_users`
or anywhere else. **Don't run multiple Databricks accounts' data through
one deployment.** Every data table mixes tenant data via `workspace_id` —
a leaky filter is a data crossover.

If you must multi-tenant: add `tenant_id` everywhere, use a Postgres RLS
(Row-Level Security) policy, and tie it to the JWT's `tenant_id` claim.

### No session timeout

Idle users keep their JWT for the full 24h. **Fix**: short access TTL +
refresh tokens (above) or sliding-session cookies.

### No MFA / TOTP

Email/password without a second factor.

**Fix**: `pyotp` + a `mfa_secrets` table. Force on admin role.

### Email verification token reuse / inspection

The verification token is high-entropy (48 bytes urlsafe), single-use,
and TTL'd at 24h. **Watch out**: if you log the URL anywhere (proxy
access logs!) the token is exposed. Move it to a POST body if your edge
logs query strings.

### Chatbot data leakage

A user with the `admin` role bypasses RBAC filters and the chatbot — by
design — runs LLM-generated SQL against the **full** parquet dataset.

For non-admins, **the chatbot does not currently apply data-scope
filters**. The LLM is told the schema, generates SQL, and DuckDB runs it.
A creative user could query data their `user`-role wouldn't see in the
dashboards.

**Fix options**:
1. Build a SQL rewriter that injects the role's WHERE clauses into the
   generated SQL before execution (non-trivial).
2. Restrict chatbot to admins for v1 — easy: add `Depends(require_admin)`
   to the chat router.
3. Tell the LLM about the user's role and rely on prompt-following
   (weakest; not recommended for security boundaries).

We recommend option 2 until option 1 is implemented.

### Logs may contain PII

`query_logger` records every chatbot question. If a user types email
addresses or other PII into a question, those land in the SQLite + JSONL
logs.

**Fix**: redact obvious patterns (email regex) before write; or treat
`logs/*` as PII and apply the same retention / encryption you apply to
the DB.

### Dependencies

Frontend uses `xlsx` (SheetJS Community). The community edition has
known CVEs around malformed Excel parsing on the **read** path. We don't
read user-supplied Excel — we only **write** — so we're not in the
vulnerable code path. Still, watch advisories.

Backend uses `passlib[bcrypt]` only as a fallback; `bcrypt` 4.x is
imported directly in `auth_utils` to avoid passlib's known
incompatibility (`AttributeError: module 'bcrypt' has no attribute
'__about__'`).

---

## Production-readiness checklist

Print this and tick before any prod cutover.

### Secrets & config
- [ ] `JWT_SECRET` set to a 256-bit random value (e.g.
      `openssl rand -base64 64`)
- [ ] All `*_API_KEY` values rotated from anything in `.env.example`
- [ ] `DEFAULT_ADMIN_PASSWORD` removed; bootstrap admin created once
      then unset
- [ ] Database password ≥ 24 chars, generated, stored in
      Secrets Manager / Key Vault / Secret Manager
- [ ] Databricks PAT scoped to read-only on `system.*`

### Network
- [ ] Backend behind TLS at the edge (LB / ingress)
- [ ] CORS restricted to your frontend origin(s) only
- [ ] Postgres NOT publicly accessible (private subnet / vnet)
- [ ] Frontend served from a CDN with HSTS + CSP headers

### Auth
- [ ] OAuth credentials provisioned for any provider you advertise
- [ ] OAuth callback URLs locked to your prod domain at the IdP
- [ ] Rate limiting on `/api/auth/login` and `/api/auth/register`
- [ ] httpOnly+Secure cookie option implemented OR documented as known
      risk
- [ ] (Optional) MFA on admin role

### Data
- [ ] Postgres encryption-at-rest enabled (RDS / Cloud SQL / Azure flex)
- [ ] Postgres backup + PITR enabled (≥7-day retention)
- [ ] Parquet files stored encrypted (S3 SSE-S3 / GCS CMEK / Azure SSE)
- [ ] Multi-AZ / multi-zone Postgres for HA
- [ ] Distinct read-write vs admin DB roles
- [ ] No `auto-extract` of Databricks data on every boot — schedule
      it explicitly

### Observability
- [ ] Application logs shipped to centralized log store (CloudWatch /
      Stackdriver / Log Analytics)
- [ ] `/health` endpoint wired into the LB health check
- [ ] Metrics: request rate, error rate, p50/p95/p99 latency, JWT-
      verify failures, login failures
- [ ] Alerts on: 5xx rate, login-failure rate, anomalous spend on LLM
      providers

### Audit
- [ ] `audit_log` table populated by every admin mutation
- [ ] Logs retained ≥1 year for SOC 2 / similar

### Chatbot
- [ ] Chatbot gated to admins, OR SQL rewriter applies role filters
- [ ] LLM cost cap (per-user / per-day rate limit)
- [ ] Logs sanitized of obvious PII

### Deployment
- [ ] Container images scanned (Trivy / ECR scan-on-push / etc.) on
      every build
- [ ] Pinned (not floating) image tags in production
- [ ] Rolling deploy with health-checked rollback
- [ ] Database migrations run idempotently (Alembic, not auto-create)

---

## Audit / compliance posture

| Framework | Status | Notes |
|---|---|---|
| **SOC 2 Type 1** | Achievable with checklist completion + documented procedures | The control families (CC6 logical access, CC7 system ops, CC8 change mgmt) map cleanly. Need: audit log, formal access-review cadence, change-mgmt process. |
| **SOC 2 Type 2** | Requires 6+ months of evidence collection | Plan: ship `audit_log` early so you accumulate evidence. |
| **GDPR (art. 17 right to erasure)** | Partial | `DELETE auth_users` cascades to roles and OAuth links, BUT does **not** scrub the user's run_as / created_by from `billing_usage` / `clusters` / `warehouses`. Add a per-user redaction job for compliance. |
| **HIPAA** | Not applicable in current scope | No PHI stored. |
| **PCI** | N/A | No card data. |
| **ISO 27001** | Achievable | Mostly people/process; tooling supports it. |

---

## Incident-response runbook stubs

### Suspected leaked JWT secret

1. Generate a new `JWT_SECRET`.
2. Roll the env var on every backend instance.
3. Every issued JWT is now invalid → all users get 401, frontend bounces
   to login. (This is the closest thing to a global revoke we have until
   refresh tokens land.)
4. Audit: search logs for unusual `/me` calls or admin endpoints from
   unfamiliar IPs in the last 24 h.

### Suspected leaked Databricks token

1. **Immediately** revoke the PAT in Databricks UI (Account → Settings
   → Access tokens).
2. Generate a new PAT, scope to `READ` on `system.*` only.
3. Update `DATABRICKS_TOKEN` env var, redeploy.
4. Audit query history in Databricks for the leaked token's window.

### Suspected SQL injection / chatbot abuse

1. Inspect `logs/query_executions.db` (or JSONL) for the offending
   user's recent queries.
2. Disable that user (`PATCH /api/admin/users/{id} {is_active: false}`).
3. If the chatbot is open to non-admins, gate it now (apply
   `Depends(require_admin)` to the chat router and redeploy).
4. Review server logs for any executed SQL that touched
   `auth_*` or `pg_*` tables — if any, treat as confirmed breach.

### Mass account compromise

1. Force-rotate `JWT_SECRET` (above).
2. Force-rotate all bcrypt salts: every user must re-set their password.
   No tooling for this today; needs a one-shot script that nulls
   `password_hash` and emails reset links.
3. Notify users per your jurisdiction's breach-notification rules.
