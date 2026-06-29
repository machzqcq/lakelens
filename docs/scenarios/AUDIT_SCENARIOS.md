# Audit & Assistant Events — Enterprise Scenarios & Questions

A field guide to what every role can learn from `system.access.audit` and
`system.access.assistant_events` — the platform's two security and
adoption ledgers. These are the tables behind **Meta Explorer → Audit**.

This catalog is grouped by role so a security analyst can jump straight
to "Investigation", a compliance officer to "Retention & reporting", an
exec to "AI adoption", and a platform engineer to "Error-class trends".

---

## 1. Which app pages back these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Meta Explorer → Audit** | KPI strip (event counts, distinct users, distinct actions, distinct services, error count, last event), service / audit-level / status-class breakdown, top actions, top users, top assistant users, full-text search box, recent-events table with status filtering and error-only toggle. | `audit_events`, `assistant_events` |

Endpoints live under `/api/meta/audit/*` — see
`backend/routers/audit.py`. The extractor lives in
`backend/extract/audit.py` and is documented in
`docs/features_grouped/AUDIT.md`.

> **About the schema name.** Databricks exposes audit fields in
> `snake_case`: `status_code` (not `statusCode`), `error_message` (not
> `errorMessage`), `user_identity_email`, `service_name`, `action_name`.
> If you see a `statusCode` reference in older code or docs, it's stale.

---

## 2. Why these tables are a goldmine

`system.access.audit` is the **only authoritative log of who did what**
on the workspace and account control planes — every cluster create,
every job run, every grant, every login. It is simultaneously:

- A **security investigation log** (who tried what, from where, with what outcome)
- A **compliance feed** (privileged action audit; export, retention)
- A **change-management trail** (config, ACL, cluster lifecycle)
- A **product-mix adoption stream** for the platform's own admin surfaces
- An **error-rate sensor** for the platform itself

`system.access.assistant_events` is the **AI / Genie adoption ledger** —
every interaction with Genie, AI/BI Assistant, Notebook Assistant. It is:

- An **AI-adoption KPI** at the team and individual level
- A **quality probe** (which assistant interactions ended in user copy / dismiss)
- A **safety probe** (which prompts touched sensitive tables)

---

## 3. Column cheat sheet

### `system.access.audit`

| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `user_identity_email`, `user_identity_id`, `account_id`, `workspace_id` | Who, where. |
| **Action** | `service_name` (e.g. `accounts`, `workspace`, `clusters`, `jobs`, `sqlAnalytics`, `unityCatalog`, `genie`), `action_name` (e.g. `login`, `createCluster`, `grantPermission`, `genieAsk`) | What. |
| **Level** | `audit_level` (`ACCOUNT_LEVEL` vs `WORKSPACE_LEVEL`) | Which control plane. Account-level events are rarer and almost always require investigation. |
| **Outcome** | `response_status_code`, `response_error_message` | Success (2xx), client-error (4xx — usually permissions), server-error (5xx). |
| **Network** | `source_ip_address`, `user_agent` | Where the request came from. |
| **Identifiers** | `request_id`, `event_id`, `session_id` | Cross-correlate with other audit lines from the same call. |
| **Detail** | `request_params` (open JSON), `response_result` (open JSON) | The action's payload — full forensic. |
| **Time** | `event_time` | When. |
| **Isolation** | `data_origin`, `deleted_at` | demo vs real partition + soft-delete. |

### `system.access.assistant_events`

| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `user_identity_email`, `workspace_id`, `genie_space_id` | Who, where, which Genie space. |
| **Interaction** | `assistant_type` (Genie / AI/BI / Notebook), `interaction_type` (ask / accept / reject / copy_sql / refine), `prompt_text` | The conversation turn. |
| **Outcome** | `was_accepted`, `was_copied`, `was_dismissed` | Did the user use the response? |
| **Resource** | `referenced_tables`, `referenced_columns` (when the assistant generated SQL) | Lineage / privacy traces. |
| **Time** | `event_time` | When. |

> Tip: `service_name` + `action_name` is the standard 2-dimensional roll-up. The Audit overview page renders this as the top-actions bar chart.

---

## 4. How to read the scenarios

> **Q.** The question, phrased the way the persona would ask it.
> *App page:* where to click. *Needs:* columns / joins required.
> *Why it matters:* what the answer changes.

---

## 5. Security / Compliance / Privacy

### 5.1 Login forensics

**Q.** Who logged in from new / unusual IPs this week?
*App page:* Meta Explorer → Audit → recent + search.
*Needs:* `action_name='login'`, group by `(user_identity_email, source_ip_address)`, flag new pairs.
*Why it matters:* the front line of credential-compromise detection.

```sql
WITH baseline AS (
  SELECT user_identity_email, source_ip_address
  FROM audit_events
  WHERE action_name='login'
    AND event_time < CURRENT_DATE - INTERVAL '30 days'
    AND deleted_at IS NULL
  GROUP BY 1,2
), recent AS (
  SELECT user_identity_email, source_ip_address, COUNT(*) cnt, MIN(event_time) first_seen
  FROM audit_events
  WHERE action_name='login'
    AND event_time >= CURRENT_DATE - INTERVAL '7 days'
    AND deleted_at IS NULL
  GROUP BY 1,2
)
SELECT r.* FROM recent r LEFT JOIN baseline b USING (user_identity_email, source_ip_address)
WHERE b.user_identity_email IS NULL ORDER BY first_seen;
```

### 5.2 Permission denials

**Q.** Who got denied access, to what, when?
*App page:* Audit → recent → toggle "errors only" + filter by `service_name='unityCatalog'`.
*Needs:* `response_status_code BETWEEN 400 AND 499`, `response_error_message LIKE '%INSUFFICIENT_PERMISSIONS%'`.
*Why it matters:* recurring denial pairs (`user, object`) are a routable backlog for the UC governance team.

### 5.3 Grant / Revoke storms

**Q.** Who is changing permissions, on what, when?
*App page:* Audit → search "grant" or "revoke".
*Needs:* `action_name IN ('grantPermission','revokePermission','updateAclEntry')`, `event_time` window.
*Why it matters:* permission changes outside of change-management windows deserve a review.

### 5.4 Service-principal activity

**Q.** What did service principal X do this week?
*App page:* Audit → recent → filter `user_email = <SP email>`.
*Needs:* `user_identity_email` like `…@*.iam.gserviceaccount.com` or matching the SP convention; group by action.
*Why it matters:* SPs accumulate broad privilege; periodic review prevents creep.

### 5.5 Account-level actions

**Q.** What's happening at the *account* control plane (vs workspace)?
*App page:* Audit → filter `audit_level='ACCOUNT_LEVEL'`.
*Needs:* `audit_level='ACCOUNT_LEVEL'`.
*Why it matters:* account-level actions are rare and high-impact — IAM, network rules, billing. Every one deserves a glance.

### 5.6 Bulk-export detection

**Q.** Did anyone export an unusually large set of rows via DBSQL / API?
*App page:* cross-ref Query Profiler → Security → Bulk Export.
*Needs:* `qi_statements.rows_returned > threshold` + `audit_events.action_name LIKE '%download%'`. See CROSS_DOMAIN.

### 5.7 Off-hours human access to sensitive surfaces

**Q.** Which human accounts (not SPs) ran admin actions outside business hours?
*App page:* Audit → recent → custom date+hour filter via search.
*Needs:* time-of-day filter; user heuristic; `audit_level='ACCOUNT_LEVEL'` or `service_name='unityCatalog' AND action_name LIKE '%grant%'`.

---

## 6. Platform / IT / Lakehouse Admin

### 6.1 Service-level error rates

**Q.** Which Databricks services have the worst error rate this week?
*App page:* Audit → KPI + status-class breakdown.
*Needs:* `service_name` × `status_code` class (2xx/4xx/5xx).
*Why it matters:* concentrated 5xx in `unityCatalog` is very different from concentrated 5xx in `genie`. The mix tells you where to dig.

### 6.2 Action volume

**Q.** Top 25 most frequent actions across the platform — what dominates the log?
*App page:* Audit → "Top actions" bar.
*Needs:* `action_name` count.
*Why it matters:* discovering that 60% of audit volume is `getCluster` polling from a misbehaving integration is the kind of finding that justifies a config fix.

### 6.3 Active workspaces

**Q.** Which workspaces saw activity at all today?
*App page:* Audit → recent grouped by `workspace_id`.
*Needs:* `workspace_id` distinct count by day.
*Why it matters:* idle workspaces with no audit activity for 30+ days are deprecation candidates.

### 6.4 Cluster-lifecycle churn

**Q.** How many cluster creates / starts / deletes per day? Per workspace?
*App page:* Audit → search "Cluster".
*Needs:* `service_name='clusters'`, `action_name IN ('createCluster','startCluster','deleteCluster','restartCluster')`.
*Why it matters:* high churn = ad-hoc usage style; low churn = scheduled-job style. Both have FinOps implications.

---

## 7. AI / Genie / Adoption (assistant_events)

### 7.1 Adoption volume

**Q.** How many distinct users used a Genie / AI/BI Assistant this month?
*App page:* Audit → "Top assistant users" + the assistant KPI strip.
*Needs:* `COUNT(DISTINCT user_identity_email)` filtered to assistant events.
*Why it matters:* the board-deck AI-adoption number.

### 7.2 Quality proxy

**Q.** What share of assistant interactions were accepted (copied / clicked Run) vs dismissed?
*Needs:* `was_accepted` / `was_copied` / `was_dismissed` rollup.
*Why it matters:* the only first-party signal for "is the AI useful". Pair with statement-history to see if the accepted SQL was actually executed.

### 7.3 Top Genie spaces

**Q.** Which Genie spaces see the most asks? Which had the highest acceptance rate?
*App page:* Audit → top assistant users + cross-ref Query Profiler → Data Science → Genie Adoption.
*Needs:* `genie_space_id` group by + quality ratios.

### 7.4 Prompt safety

**Q.** Did any assistant prompts reference PII tables in their generated SQL?
*Needs:* `referenced_tables` ∩ PII-tagged list from meta. See CROSS_DOMAIN §5.

### 7.5 First-touch adoption

**Q.** Who first used Genie this month?
*Needs:* per-user `MIN(event_time)` over assistant events, filtered to current month.
*Why it matters:* track adoption funnels and pilot expansion.

---

## 8. Executive / Data Office

### 8.1 Reliability KPI

**Q.** What's the platform's audit success rate (2xx %) over the last 30 days?
*App page:* Audit → status-class strip.
*Needs:* `2xx_count / total_count` by day.

### 8.2 AI adoption KPI

**Q.** What share of analysts touched an AI assistant this month? Trend?
*App page:* Audit → assistant top users + count.
*Needs:* MoM `COUNT(DISTINCT user_identity_email)` over assistant events ÷ MoM distinct `executed_by` in `qi_statements`.

### 8.3 Compliance attestations

**Q.** Did we observe any account-level grant changes outside the change-window?
*Needs:* `audit_level='ACCOUNT_LEVEL'`, `action_name LIKE '%grant%'`, time window outside policy.

---

## 9. Audit / Internal Risk

### 9.1 User-window reconstruction

**Q.** Reconstruct everything user U did between time T1 and T2.
*App page:* Audit → search by email, optional date filter.
*Needs:* `user_identity_email=U`, `event_time BETWEEN T1 AND T2`.
*Why it matters:* the regulator-facing forensic.

### 9.2 Privileged-action review

**Q.** List of statements / actions executed as service principal X this quarter.
*Needs:* `user_identity_email=X` + cross-ref `qi_statements.executed_as`.

### 9.3 Retention compliance

**Q.** Confirm we retain audit lines per policy.
*Needs:* `MIN(event_time)` overall, vs policy minimum.
*Why it matters:* if extractor retention dips below the policy floor, escalate.

---

## 10. Cross-cutting

### 10.1 Audit ⨯ Lineage

**Q.** Who triggered the job that wrote into PII table T last night?
*Needs:* lineage `target=T` → entity_id → audit_events action where entity launched.

### 10.2 Audit ⨯ Query Profiler

**Q.** Who keeps getting denied access to a specific table? Bridge the SQL-side `INSUFFICIENT_PERMISSIONS` to the access-side `unityCatalog` denial.
*Needs:* `qi_statements.execution_status='FAILED' AND error_message LIKE '%INSUFFICIENT_PERMISSIONS%'` ⨯ `audit_events.action_name` on the same object.

### 10.3 Audit ⨯ Billing

**Q.** Is there cost in a workspace that has *no* audit activity? (Phantom workspace.)
*Needs:* `billing_usage` grouped by `workspace_id` ⨯ anti-join `audit_events` for the same period.
*Why it matters:* spend with no auditable usage almost always means a non-deletable demo workspace or an orphaned scheduled job — both deserve attention.

---

## 11. Limitations & gotchas

- **`response_error_message` is free-form.** Don't grep too loosely; the same logical denial can phrase itself five ways.
- **The schema is `snake_case`** (`status_code`, not `statusCode`). Older docs and integrations sometimes use camelCase; the extractor handles both transparently.
- **Account-level rows have NULL `workspace_id`** — when you group by workspace, decide whether to filter or fold into a synthetic "ACCOUNT" bucket.
- **`request_params` and `response_result` are open JSON.** They contain the action payload but the schema is per-action — expand carefully.
- **Audit volume is high.** Even a small org sees 10K–100K events / day. Always restrict the time window before opening the table.
- **`event_time` may lag UC writes by minutes.** Don't treat as real-time.
- **Some services emit dozens of fine-grained sub-actions for one user action.** Use `request_id` to de-duplicate per user-facing call.
- **assistant_events were added later** — older extracts may lack the table; check Meta Explorer → Audit stats for `assistant_events: 0`.
- **`INSUFFICIENT_PERMISSIONS` from `instance_pools` is tolerated** by the extractor (some orgs don't expose them) — it's not a true error and won't show up in the audit error count.

---

## 12. How to add a new audit scenario

1. Name the **role** (security / IT / exec / audit / compliance / AI lead).
2. State the question in their words.
3. Decide whether it's a **service+action filter** (most common) or a **deeper request_params parse** (forensic).
4. Specify the **time window** — many audit scenarios are window-bounded.
5. Note the **app page** that should serve it; if there's a missing filter, log a UX request.

---

## See also

- `docs/features_grouped/AUDIT.md` — technical deep-dive on the audit extractor and event schema
- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) §11 — security questions from the SQL side (complementary)
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — audit × billing / query / lineage
