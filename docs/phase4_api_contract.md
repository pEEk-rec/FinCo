# Phase 4 API Contract: Behavioral Engagement & Gamification

This document defines the REST API contract for Phase 4 of FinCo (Behavioral Engagement & Gamification).
All endpoints run on localhost, require authentication via session Bearer token, and strictly operate through FinCo's governed `execute_tool` choke point.

---

## 1. Experiments API

### 1.1 List Experiments
- **Endpoint:** `GET /api/experiments`
- **Query Params:**
  - `status` (optional): Filter by `offered`, `active`, `paused`, `completed`, `abandoned`, `expired`, `reviewed`.
- **Response:** Array of `Experiment` objects.

### 1.2 Get Experiment Details
- **Endpoint:** `GET /api/experiments/{id}`
- **Response:** Detailed `Experiment` object with frozen baseline and metric definition.

### 1.3 Mid-Experiment Progress & Pace
- **Endpoint:** `GET /api/experiments/{id}/progress`
- **Response:**
  ```json
  {
    "experiment_id": "exp_123",
    "elapsed_days": 7,
    "total_days": 14,
    "observed_value": 180000,
    "expected_to_date": 250000,
    "target_value": 500000,
    "pace_status": "ahead",
    "recent_checkin": {
      "checkin_date": "2026-10-18",
      "user_response": "going_well"
    }
  }
  ```

### 1.4 Design Experiment (Hypothesis Formulator)
- **Endpoint:** `POST /api/experiments/design`
- **Request Body:**
  ```json
  {
    "template_code": "weekday_home_cooking",
    "metric_code": "category_spend",
    "categories": ["dining", "delivery"],
    "duration_days": 14,
    "difficulty": "medium",
    "target_value": 250000
  }
  ```
- **Response:** Designed experiment hypothesis with baseline range (low, median, high), K windows, and formal hypothesis statement.

### 1.5 Start Experiment (User Opt-in Only)
- **Endpoint:** `POST /api/experiments/start`
- **Request Body:**
  ```json
  {
    "title": "Weekday Home Cooking Challenge",
    "metric_code": "category_spend",
    "categories": ["dining", "delivery"],
    "duration_days": 14,
    "difficulty": "medium",
    "target_value": 250000,
    "baseline_median": 500000
  }
  ```
- **Response:** Created active experiment with frozen baseline and window bounds.

### 1.6 Pause / Resume Experiment
- **Endpoints:**
  - `POST /api/experiments/{id}/pause`
  - `POST /api/experiments/{id}/resume`
- **Response:** Updated experiment status (`paused` or `active`).

### 1.7 Abandon Experiment (No Shame, No Loss)
- **Endpoint:** `POST /api/experiments/{id}/abandon`
- **Request Body:** `{"reason": "traveling for work"}`
- **Response:** Experiment marked as `abandoned`. Learning XP is still preserved upon review.

### 1.8 Submit Check-in
- **Endpoint:** `POST /api/experiments/{id}/checkin`
- **Request Body:** `{"user_response": "going_well"}` (or `"hard"`, `"want_to_pause"`, `"skip"`)
- **Response:** Recorded check-in confirmation and updated pace status.

### 1.9 Get Experiment Review (Honest Measurement)
- **Endpoint:** `GET /api/experiments/{id}/review`
- **Response:**
  ```json
  {
    "experiment_id": "exp_123",
    "observed_value": 180000,
    "outcome": "beyond_usual_range",
    "rank_p_bp": 1428,
    "effect_value": 320000,
    "target_met": true,
    "integrity_notes": []
  }
  ```

### 1.10 Submit Post-Review Feedback
- **Endpoint:** `POST /api/experiments/{id}/feedback`
- **Request Body:**
  ```json
  {
    "user_difficulty": 3,
    "user_helpful": true,
    "user_would_repeat": true
  }
  ```
- **Response:** Confirmation of feedback logged; Beta posteriors and behavioral memory updated.

---

## 2. Challenges & Weekly Offers API

### 2.1 List Active Offers
- **Endpoint:** `GET /api/challenges/offers`
- **Query Params:** `status` (default `shown`)
- **Response:** List of personalized offers with rationale, propensity, and difficulty.

### 2.2 Generate Weekly Offers
- **Endpoint:** `POST /api/challenges/offers/suggest`
- **Request Body:** `{"week_start": "2026-10-19"}`
- **Response:** List of new challenge offers selected via Thompson sampling policy.

### 2.3 Accept Offer
- **Endpoint:** `POST /api/challenges/offers/{id}/accept`
- **Response:** Starts an active experiment and marks offer `accepted`.

### 2.4 Dismiss Offer (No Penalty)
- **Endpoint:** `POST /api/challenges/offers/{id}/dismiss`
- **Request Body:** `{"reason": "not interested this week"}`
- **Response:** Marks offer `dismissed` with neutral acknowledgement.

---

## 3. Adaptive Challenges API

### 3.1 List Adjustment Proposals
- **Endpoint:** `GET /api/adjustments`
- **Query Params:** `experiment_id` (optional)
- **Response:** List of active adjustment proposals (`ease_target`, `extend`, `pause`, etc.).

### 3.2 Accept Adjustment
- **Endpoint:** `POST /api/adjustments/{id}/accept`
- **Response:** Applies the proposal to the experiment target/dates.

### 3.3 Reject Adjustment
- **Endpoint:** `POST /api/adjustments/{id}/reject`
- **Request Body:** `{"reason": "want to stick to original target"}`
- **Response:** Marks proposal `rejected`. Original target remains in force.

---

## 4. Progress & Gamification API

### 4.1 User Progress Overview
- **Endpoint:** `GET /api/progress`
- **Response:**
  ```json
  {
    "user_id": "u1",
    "level": 3,
    "level_name": "Consistent Planner",
    "total_xp": 450,
    "current_level_xp": 150,
    "next_level_threshold_xp": 300,
    "badges": [
      {
        "badge_code": "first_experiment_reviewed",
        "name": "First Review",
        "awarded_at": "2026-10-15T12:00:00Z"
      }
    ],
    "streaks": [
      {
        "streak_code": "checkin_streak",
        "current_length": 4,
        "longest_length": 6
      }
    ],
    "personal_bests": [
      {
        "metric_code": "category_spend",
        "window_days": 14,
        "best_value": 180000,
        "achieved_date": "2026-10-15"
      }
    ]
  }
  ```

### 4.2 Personal Bests
- **Endpoint:** `GET /api/progress/bests`
- **Response:** Array of historical personal bests across catalogue metrics.

---

## 5. Goal Gap Decomposition API

### 5.1 Decompose Goal Gap
- **Endpoint:** `POST /api/goals/{id}/decompose`
- **Response:**
  ```json
  {
    "target_goal": {"id": "g_trip", "name": "Goa Trip"},
    "deficit_paise": 1500000,
    "required_monthly_paise": 500000,
    "candidate_experiments": [
      {
        "template_code": "weekday_home_cooking",
        "title": "Weekday Home Cooking",
        "difficulty": "medium",
        "expected_savings_paise": 200000,
        "share_of_gap_bp": 4000
      }
    ],
    "caveat": "All candidate experiments are optional behavioral suggestions and do not guarantee goal completion."
  }
  ```

## Additions made while closing Stage 4.11

### Confirm integrity
- **Endpoint:** `POST /api/experiments/{id}/review/confirm-integrity`
- Marks the review as checked after payments were recategorised during the window. Returns the updated review. User-only; the agent cannot call it (`confirm_review_integrity` is `agent: deny`).

### Review wording
- `GET /api/experiments/{id}/review` includes `wording`: the ready-to-show sentences (comparison, "says nothing about the reason", target met or not) so a client never composes its own comparison text.

### `llm` block on agent answers
- `llm.path` is one of `model`, `rules`, `cache`; `llm.path_reason` says why (for example `model_unavailable`). A client can show "answered without the model" honestly.

### Dated exceptions (tool `record_contextual_exception`)
- Input: `category`, `reason`, and either `period` (`YYYY-MM`) or `from_date` and `to_date` (`YYYY-MM-DD`, inclusive, at most 93 days). User-only.
