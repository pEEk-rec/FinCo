# Phase 3 HTTP API Contract

This document specifies the HTTP API surface introduced in Phase 3 for the Advanced Financial Copilot. All endpoints are hosted locally, strictly governed, multi-tenant isolated, and enforce integer-paise accounting.

---

## 1. Governance & Architectural Rules

1. **Localhost and Single Session:**
   - The API binds exclusively to `localhost` / `127.0.0.1`.
   - Every request except `GET /api/health` requires the HTTP Header:
     ```http
     Authorization: Bearer <session-token>
     ```
2. **Actor & Choke Point Policy:**
   - User actions invoke tools with `ExecutionContext(actor="user")`.
   - Scheduled / background agent upkeep invokes tools with `ExecutionContext(actor="agent")`.
   - Direct database mutations are strictly prohibited; all state mutations pass through `execute_tool(ctx, tool_name, kwargs)`.
3. **Multi-Tenant Tenant Isolation:**
   - Every database query and tool execution is partitioned by `user_id`.
   - No data from user A is ever accessible, queried, or leaked to user B.
4. **Integer Currency Arithmetic:**
   - All monetary figures are strictly represented as integers in paise (`₹1.00 = 100 paise`).
   - Floating-point currency representation is strictly forbidden across all request and response models.
5. **Data Minimization & Log Sanitization:**
   - Server logs capture method, path, HTTP status, and response duration only.
   - Request and response bodies containing financial details, merchant names, or statements are never written to server access logs.

---

## 2. Error Response Structure

All non-2xx responses adhere to a stable, typed error format:

```json
{
  "code": "INVALID_INPUT",
  "message": "Detailed description of error",
  "retryable": false
}
```

### Standard Error Codes & HTTP Status Mapping

| Error Code | HTTP Status | Description |
|:---|:---:|:---|
| `UNAUTHORIZED` | 401 | Missing or invalid bearer token |
| `INVALID_INPUT` | 422 | Input validation failed or malformed payload |
| `NOT_FOUND` | 404 | Target entity (bucket, commitment, memory) does not exist |
| `DENIED_BY_POLICY` | 403 | Operation violates safety rules (e.g. money transfer attempt) |
| `APPROVAL_REQUIRED` | 409 | Action requires explicit user approval before execution |
| `STALE_DATA` | 409 | Optimistic concurrency check failed |
| `TOOL_FAILURE` | 502 | Tool execution failure |
| `INTERNAL` | 500 | Unexpected server error |

---

## 3. Phase 3 API Endpoints

### 3.1 Financial Commitments

#### `GET /api/commitments`
List commitments for the authenticated user.
- **Query Parameters:**
  - `status` (*string*, optional): Filter by status (`draft`, `active`, `paused`, `ended`, `rejected`).
- **Response `200 OK`:**
  ```json
  [
    {
      "id": "cm_8f12a34b",
      "user_id": "u1",
      "name": "Apartment Rent",
      "direction": "outflow",
      "kind": "rent",
      "category_id": "rent",
      "amount_paise": 2500000,
      "certainty": "firm",
      "schedule_kind": "monthly",
      "schedule_json": { "day": 5 },
      "start_date": "2024-03-01",
      "end_date": null,
      "status": "active",
      "created_at": "2024-03-01T00:00:00Z",
      "updated_at": "2024-03-01T00:00:00Z"
    }
  ]
  ```

#### `POST /api/commitments`
Create a new commitment via `create_commitment`.
- **Request Body:**
  ```json
  {
    "name": "Apartment Rent",
    "amount_paise": 2500000,
    "start_date": "2024-03-01",
    "schedule_kind": "monthly",
    "schedule_json": { "day": 5 },
    "kind": "rent",
    "certainty": "firm",
    "category_id": "rent"
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "commitment": {
      "id": "cm_8f12a34b",
      "user_id": "u1",
      "name": "Apartment Rent",
      "amount_paise": 2500000,
      "status": "active"
    }
  }
  ```

#### `POST /api/commitments/suggest`
Analyze transaction history and propose candidate commitments.
- **Request Body:** `{}`
- **Response `200 OK`:**
  ```json
  {
    "suggested": [
      {
        "name": "Broadband Internet",
        "direction": "outflow",
        "kind": "bill",
        "amount_paise": 99900,
        "schedule_kind": "monthly",
        "schedule_json": { "day": 12 },
        "confidence_score": 0.92
      }
    ]
  }
  ```

---

### 3.2 Financial Calendar & Cash Flow

#### `GET /api/calendar`
Compute rolling cashflow projection, minimum buffer, and commitment coverage.
- **Query Parameters:**
  - `horizon_days` (*integer*, default `60`, max `180`): Projection lookahead in days.
- **Response `200 OK`:**
  ```json
  {
    "calendar": {
      "today": "2024-03-18",
      "horizon_days": 60,
      "start_balance_paise": 15000000,
      "min_buffer_paise": 2000000,
      "days": [
        {
          "date": "2024-03-18",
          "start_balance_paise": 15000000,
          "inflow_paise": 0,
          "outflow_paise": 2500000,
          "end_balance_paise": 12500000,
          "occurrences": []
        }
      ],
      "coverage": [],
      "shortfall_ranges": []
    }
  }
  ```

---

### 3.3 Virtual Buckets

#### `GET /api/buckets`
List all virtual buckets with derived balances and category assignments.
- **Response `200 OK`:**
  ```json
  {
    "buckets": [
      {
        "bucket": {
          "id": "bk_719a2b",
          "name": "Europe Trip",
          "kind": "spending",
          "period_policy": "reset_monthly"
        },
        "balance": {
          "allocated_paise": 5000000,
          "spent_paise": 1200000,
          "remaining_paise": 3800000
        }
      }
    ],
    "unallocated_paise": 42000000
  }
  ```

#### `POST /api/buckets`
Create a new virtual bucket.
- **Request Body:**
  ```json
  {
    "name": "Europe Trip",
    "kind": "spending",
    "period_policy": "reset_monthly",
    "goal_id": null
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "bucket": {
      "id": "bk_719a2b",
      "name": "Europe Trip",
      "kind": "spending",
      "period_policy": "reset_monthly"
    }
  }
  ```

#### `POST /api/buckets/allocate`
Allocate surplus funds to a virtual bucket.
- **Request Body:**
  ```json
  {
    "bucket_id": "bk_719a2b",
    "amount_paise": 500000,
    "period": "2024-03"
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "allocation": {
      "id": "al_31a98c",
      "bucket_id": "bk_719a2b",
      "amount_paise": 500000,
      "period": "2024-03"
    },
    "bucket_balance": {
      "allocated_paise": 5500000,
      "spent_paise": 1200000,
      "remaining_paise": 4300000
    }
  }
  ```

#### `POST /api/buckets/reallocate`
Reassign allocated funds between two buckets.
- **Request Body:**
  ```json
  {
    "from_bucket_id": "bk_719a2b",
    "to_bucket_id": "bk_829c3d",
    "amount_paise": 300000,
    "period": "2024-03"
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "pair_id": "pr_819a12c",
    "amount_paise": 300000,
    "from_balance": { "remaining_paise": 4000000 },
    "to_balance": { "remaining_paise": 1300000 }
  }
  ```

---

### 3.4 Investment Readiness

#### `GET /api/readiness`
Evaluate user investment readiness criteria, emergency cushion, and priority obligations.
- **Response `200 OK`:**
  ```json
  {
    "readiness": {
      "run_id": "rd_1a89c3",
      "assessed_on": "2024-03-18",
      "level": "ready_with_conditions",
      "criteria": [
        {
          "name": "emergency_fund",
          "status": "pass",
          "value_text": "3.5 months expenses saved",
          "threshold_text": "Minimum 3 months required",
          "what_would_change_it": "Maintain reserve above ₹1,50,000"
        }
      ],
      "numbers": {
        "emergency_cushion_paise": 15000000,
        "monthly_burn_paise": 4200000
      },
      "config_version": "1.0.0"
    },
    "assessment_id": "ra_91a0b3"
  }
  ```

---

### 3.5 Long-Term Memories & Exceptions

#### `GET /api/memories`
List extracted user behavioural memories.
- **Query Parameters:**
  - `status` (*string*, optional): Filter by status (`candidate`, `active`, `stale`, `rejected`, `forgotten`).
- **Response `200 OK`:**
  ```json
  [
    {
      "id": "mem_41a98c",
      "user_id": "u1",
      "kind": "preference",
      "subject_key": "travel_preference",
      "statement_json": { "preferred_airline": "IndiGo" },
      "status": "active",
      "user_confirmed": true,
      "created_at": "2024-02-10T14:22:00Z"
    }
  ]
  ```

#### `POST /api/memories/forget`
Selectively forget a memory item and erase associated statement details while retaining audit logging.
- **Request Body:**
  ```json
  {
    "memory_id": "mem_41a98c",
    "reason": "User requested deletion"
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "memory_id": "mem_41a98c",
    "status": "forgotten",
    "success": true
  }
  ```

#### `GET /api/memories/audit`
Retrieve memory governance audit trail.
- **Query Parameters:**
  - `limit` (*integer*, default `50`, max `200`).
- **Response `200 OK`:**
  ```json
  [
    {
      "id": "ma_910b23",
      "user_id": "u1",
      "memory_id": "mem_41a98c",
      "action": "forgotten",
      "actor": "user",
      "reason": "User requested deletion",
      "timestamp": "2024-03-18T12:00:00Z"
    }
  ]
  ```

---

### 3.6 Bounded Feedback Learning

#### `GET /api/learning`
Inspect learned sensitivity multipliers and beta-binomial feedback distributions.
- **Response `200 OK`:**
  ```json
  {
    "user_id": "u1",
    "stats": [
      {
        "subject_kind": "category_preference",
        "subject_key": "dining",
        "alpha": 5.0,
        "beta": 1.0,
        "p_mean": 0.833,
        "sensitivity_multiplier": 0.72
      }
    ]
  }
  ```

#### `POST /api/learning/reset`
Reset learned parameters back to uninformed prior distributions.
- **Request Body:**
  ```json
  {
    "subject_kind": null,
    "subject_key": null
  }
  ```
- **Response `200 OK`:**
  ```json
  {
    "status": "ok",
    "reset_count": 4
  }
  ```

---

### 3.7 Operational Telemetry & Background Upkeep

#### `GET /api/ops`
Operational dashboard with latency percentiles, LLM token metrics, and scheduled job health.
- **Response `200 OK`:**
  ```json
  {
    "status": "healthy",
    "telemetry": {
      "llm_calls_per_task": 0.0,
      "tokens_per_task": 0,
      "total_tokens": 0,
      "estimated_cost_str": "$0.0000",
      "budget_stops_count": 0,
      "validator_fallback_rate": 0.0,
      "critic_catch_rate": 0.0,
      "revision_success_rate": 0.0,
      "parallel_speedup": 1.0,
      "total_spans": 24,
      "job_success_count": 6,
      "job_dead_letter_count": 0
    },
    "background_jobs": [
      {
        "id": "job_rollover",
        "job_kind": "rollover_buckets",
        "schedule": "monthly",
        "next_run_at": "2024-04-01T00:00:00Z",
        "last_status": "ok",
        "consecutive_failures": 0
      }
    ]
  }
  ```

#### `POST /api/jobs/run`
Trigger execution of any scheduled jobs that are currently due.
- **Request Body:** `{}`
- **Response `200 OK`:**
  ```json
  {
    "status": "ok",
    "jobs_executed": 2,
    "runs": [
      {
        "id": "jr_819ab2",
        "job_id": "job_refresh_memories",
        "status": "ok",
        "attempt": 1
      }
    ]
  }
  ```
