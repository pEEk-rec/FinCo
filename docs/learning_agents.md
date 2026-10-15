# Bounded Feedback Learning in Personal Financial Copilot

## 1. Overview and Design Philosophy

FinCo's Bounded Feedback Learning engine implements an explainable, parameter-free learning agent based on Bayesian multi-armed bandit principles (Beta conjugate posteriors). 

Unlike model fine-tuning or opaque black-box scoring systems, FinCo's learning mechanism:
1. Operates on explicit user feedback signals (acknowledgments, approvals, dismissals, mutes).
2. Strictly bounds sensitivity multipliers within safe thresholds ($m \in [m_{\min}, m_{\max}]$, default $[0.5, 1.5]$).
3. Enforces **inviolable safety hard floors** so that critical warnings can never be suppressed.
4. Distinguishes contextual life events (festivals, travel, medical emergencies) from negative feedback.
5. Maintains total transparency: every learned multiplier is inspectable via `copilot learning show`, explained in alert why-text only when it shifts severity, and instantly resettable via `copilot learning reset`.

---

## 2. Multi-Armed Bandit Framing

FinCo frames user adaptation as a contextual bandit problem:

- **Context ($x \in \mathcal{X}$):** 
  - For alerts: Alert kind $\times$ Category (e.g., `budget_risk:groceries`, `budget_risk:dining`).
  - For advice: Advice kind $\times$ Subject (e.g., `overspend_pace:utilities`, `recurring_increase:broadband`).
- **Action ($a \in \mathcal{A}$):**
  - For alerts: Scale the multi-signal alert score by sensitivity multiplier $m = \text{clamp}(1 + \eta(2p - 1), m_{\min}, m_{\max})$.
  - For advice: Order proposed advice items within a response by posterior utility $p$ descending.
- **Reward / Feedback Signal ($r \in \{0, 1\}$):**
  - **Useful ($r = 1$):**
    - Alert acknowledged by user (`action = "acknowledge"`).
    - Alert acted upon (e.g., user applies a reallocation draft addressing the overspend).
    - Advice item approved by user (`decision = "approved"`).
  - **Not Useful ($r = 0$):**
    - Alert dismissed without a contextual reason (generic dismissal).
    - Category or alert kind muted by user (`muted = true`).
    - Advice item rejected by user (`decision = "rejected"`).

---

## 3. Mathematical Formulation: Beta Conjugate Posterior

FinCo models the user's usefulness probability $p$ for each subject as a Beta distribution:

$$p \sim \text{Beta}(\alpha, \beta)$$

### Integer Milli-Representation
To guarantee precision and prevent floating-point drift across databases, $\alpha$ and $\beta$ are persisted in SQLite table `feedback_stats` as integer thousandths (`alpha_milli`, `beta_milli`).

- **Prior:** Configured in `config/learning.yaml` (default $\alpha_0 = 2, \beta_0 = 2 \implies \alpha_{\text{milli}} = 2000, \beta_{\text{milli}} = 2000$).
- **Posterior Updates:**
  - Upon useful signal ($r = 1$): $\alpha_{\text{milli}} \leftarrow \alpha_{\text{milli}} + 1000$.
  - Upon not-useful signal ($r = 0$): $\beta_{\text{milli}} \leftarrow \beta_{\text{milli}} + 1000$.
- **Posterior Mean:**
  $$p = \frac{\alpha_{\text{milli}}}{\alpha_{\text{milli}} + \beta_{\text{milli}}}$$

### Sensitivity Multiplier
The sensitivity multiplier $m$ maps $p \in (0, 1)$ linearly into the range $[m_{\min}, m_{\max}]$ around $1.0$:

$$m = \text{clamp}\left(1.0 + \eta \times (2p - 1.0), \; m_{\min}, \; m_{\max}\right)$$

With defaults $\eta = 0.5$, $m_{\min} = 0.5$, $m_{\max} = 1.5$:
- Prior state ($p = 0.5$): $m = 1.0 + 0.5(0) = 1.000$ (neutral).
- High user utility ($p \to 1.0$): $m \to 1.500$ (boosts alert sensitivity up to $+50\%$).
- High user dismissal ($p \to 0.0$): $m \to 0.500$ (damps alert sensitivity down to $-50\%$).

---

## 4. Why No Exploration (Zero Thompson Sampling)

In classic reinforcement learning, algorithms use exploration strategies such as **Thompson Sampling**, $\epsilon$-greedy, or Upper Confidence Bound (UCB) to discover optimal actions by deliberately taking sub-optimal or random actions.

### Why Exploration is Strictly Forbidden in Financial Alerts:
1. **Asymmetric Risk:** The harm of missing an overspend warning or uncovered commitment far exceeds the minor convenience of suppressing an alert.
2. **Determinism and Auditability:** If a user asks "Why didn't I get an alert before my account went negative?", an answer of "The agent was randomly exploring to see if you needed alerts" is completely unacceptable.
3. **Safety Guarantee:** Users must have predictable, stable behavior. Alerts are only damped when the user has consistently dismissed them across multiple historical cycles, and even then, only using the deterministic posterior mean $p$.

---

## 5. Inviolable Safety Hard Floors

Even when a user consistently dismisses alerts for a category (driving $m \to 0.5$), **safety hard floors** ensure critical financial dangers are never suppressed.

Under Section 5.16, the following three conditions trigger an inviolable hard floor:
1. **Exceeded Budgets:** Spend has met or exceeded the allocated budget limit (`spent_paise >= limit_paise`).
2. **Uncovered Commitments:** Scheduled mandatory obligations (rent, EMI, tuition) marked as `not_covered` or `shortfall`.
3. **Off-Track Goals:** Spend causing an active goal to transition to `off_track`.

### Hard Floor Enforcement Rule:
When an alert meets any hard floor condition:
- The effective multiplier is strictly bounded below by 1.0:
  $$m_{\text{eff}} = \max(1.0, m)$$
- The severity tier cannot drop below its base multi-signal severity:
  $$\text{severity}_{\text{adjusted}} \ge \text{severity}_{\text{base}}$$
- Learning can **never** suppress an alert with a hard floor.

---

## 6. Contextual Exceptions vs. Negative Feedback

A critical failure mode of naive learning agents is misinterpreting legitimate, temporary life exceptions as permanent preference shifts.

**Example Scenario:**
In October, during Diwali, a user spends ₹35,000 on gifts and sweets (normally ₹5,000). The copilot surfaces an alert. The user dismisses the alert with reason: `"festival: Diwali shopping"`.

- **Naive Learner Action (Wrong):** Decrements $\beta$, concludes the user does not care about shopping alerts, and permanently suppresses future shopping alerts.
- **FinCo Action (Correct):**
  - Detects contextual keyword (`festival`).
  - Routes the dismissal to the **Long-Term Memory Engine** (`record_contextual_exception`), creating an active memory exception that decays over 365 days.
  - **Does NOT** decrement feedback stats or update $\beta$. Shopping alert sensitivity remains untainted for standard months.

Generic dismissals without a reason (`"User dismissed"`, `""`, `"no reason"`) are treated as true negative feedback, decrementing $\beta$ appropriately.

---

## 7. Why RLHF, RLAIF, and DPO are Out of Scope

Modern LLM alignment often uses **Reinforcement Learning from Human Feedback (RLHF)**, **RL from AI Feedback (RLAIF)**, or **Direct Preference Optimization (DPO)**. Section 1.4 of `PLAN_PHASE3.md` deliberately excludes these paradigms for FinCo:

1. **Weight Modification vs. Invariant Governance:**
   RLHF and DPO adjust model weights. In a high-stakes personal finance system, weights provide zero formal safety guarantees. Financial rules (zero money movement, integer paise, tenant isolation) must be enforced by deterministic code and state machines, not probabilistic model weights.
2. **Data Minimization and Privacy:**
   Fine-tuning or training reward models on real user financial histories creates severe data leakage risks. FinCo operates locally over SQLite; shipping user transactions to an external training cluster violates core privacy invariants.
3. **Scale and Cost:**
   RLHF requires tens of thousands of pairwise comparisons to converge. A personal finance copilot typically has dozens of interactions per month per user. A Beta conjugate prior updates instantaneously with $O(1)$ compute and zero GPU cost.
4. **Future Path for Preference Pairs:**
   In an enterprise or research setting where users explicitly consent to data pooling, FinCo's `advice_items` table (storing `draft`, `evidence_json`, and user decisions `approved`/`rejected`) can be converted into offline preference pairs:
   $$(x, y_w, y_l) = (\text{evidence}, \text{approved\_text}, \text{rejected\_text})$$
   However, FinCo does not train on these now, maintaining a zero-training, 100% deterministic local architecture.

---

## 8. Transparency, Explainability, and User Controls

### Why-Text Learning Notes
FinCo strictly avoids confusing the user with learning notices when learning did not affect the outcome:
- If learning altered the severity tier downward:
  `"... (Shown at lower priority because you usually dismiss these alerts.)"`
- If learning altered the severity tier upward:
  `"... (Shown at higher priority because you usually find these alerts useful.)"`
- If severity was unchanged: no learning text is added.

### CLI Inspection and Reset
Users and administrators have full visibility and control:
```bash
# View all learned posteriors and multipliers
copilot learning show

# Output as structured JSON
copilot learning show --json

# Reset specific subject back to priors (alpha=2, beta=2, m=1.0)
copilot learning reset --subject budget_risk:groceries

# Reset all learned state for user
copilot learning reset --all
```
