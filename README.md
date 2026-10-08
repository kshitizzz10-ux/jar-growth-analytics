# Jar App: In-App Engagement & A/B Experimentation Teardown

**Author:** _your name_ | **Tools:** Python (Pandas, SciPy, Matplotlib), Excel, Mixpanel/CleverTap (event design)
**Type:** External product-level analysis. **All data is simulated from stated assumptions. No Jar data was used.**

---

## 1. Business problem
Jar's growth depends on turning a first micro-saving into a *habit*. Daily push notifications are the main re-engagement lever. **Question: does a gamified streak push ("You're on a 3-day streak, save ₹X to keep it alive") retain more users at Day 7 than the standard daily nudge?**

## 2. Funnel audit (product-level)
Sources: hands-on walkthrough of the app plus published product teardowns. *(Verify each step against the live app and add your screenshots in `/screenshots`.)*

```
Splash & value pitch → Phone auth (Truecaller / OTP) → SMS permission priming (round-off engine)
→ Choose saving mode (round-off / daily save) & amount (preset chips) → First payment via UPI intent
→ Optional UPI Autopay mandate → "Spin the wheel" reward → Home (gold balance, streak counter)
```

**Observations that shape the analysis**
- **Two-step permission priming** (in-app explainer, then OS dialog) means *prompt shown* and *permission granted* must be tracked as separate events.
- **KYC is deferred** (per published teardowns), so it is not a signup-funnel drop-off; it becomes a withdrawal-stage event.
- **Payment and mandate are separate:** intent (clicked), completion (approved), and outcome (debit succeeded) must be separate events, because UPI handoff is a classic leak.
- **Gamified reward screen** right after payment is the first retention hook; the streak push extends that same mechanic.

Simulated funnel (assumed rates, see `Funnel` tab): 20,000 installs → 12.9% end with an approved autopay mandate. The largest absolute drop is at phone/OTP verification, and the largest *relative* drops are at first payment (60%) and mandate approval (45%).

![funnel](charts/funnel.png)

## 3. Event taxonomy
Naming: `object_action`, snake_case, past tense. Full 19-event plan with trigger, properties, source (client/server/CleverTap) is in `Jar_AB_Experiment_Tracker.xlsx` → `Tracking_Plan`.

Key design rules: server-side events for money (`mandate_approved`, `first_saving_completed`); `variant` and `campaign_id` on every push event; guardrail event `push_optout`. QA checklist (duplicates, null properties, ordering, identity merge, UTC timestamps, sample-ratio mismatch) is in the `QA_Checklist` tab.

## 4. Experiment design
| Item | Choice |
|---|---|
| Hypothesis | Streak push raises D7 retention vs standard nudge |
| Unit / split | Newly activated users (first saving done), randomized 50/50 |
| Primary metric | D7 retention = ≥1 successful saving on day 7 |
| Guardrails | Push opt-out rate, uninstall rate, average saving amount |
| Baseline (assumed) | 30% |
| MDE | 12.8% relative (30% → 33.84%), chosen as the smallest lift worth the effort |
| α / power | 0.05 two-sided / 80% |
| Sample size | **2,310 per arm** (formula below) |

`n = (Zα/2 + Zβ)² × [p₁(1−p₁) + p₂(1−p₂)] / (p₂−p₁)²` = 7.85 × 0.4339 / 0.001475 ≈ 2,310

Run 3,000 per arm to leave headroom. Pre-register the metric definition and stopping rule (fixed sample, no peeking) before launch.

## 5. Results (simulated; produced by `ab_analysis.py`, reproduced in Excel)
| Metric | A (Control) | B (Streak) | Difference | p-value |
|---|---|---|---|---|
| **D7 retention** | 28.5% | 33.7% | +5.3 pp (+18.5% relative), 95% CI [+2.9, +7.6] pp | < 0.001 |
| **Push opt-out (guardrail)** | 1.80% | 2.73% | +0.9 pp (+52% relative), 95% CI [+0.2, +1.7] pp | 0.015 |

Cross-checks: chi-square test agrees with the z-test; sample-ratio check passed; Excel formulas match Python output.

![ab](charts/retention_ab.png)

**Segment cut (exploratory):** T1 +41%, T2 +5%, T3 +18% relative lift. These are noisy small-n subgroups; treat as hypotheses, not findings.

**Power check:** at 3,000/arm, 89% of 2,000 repeated simulated experiments detect the effect. The observed lift (18.5%) is higher than the planted 12.8% purely through sampling noise, which is why the confidence interval matters more than the point estimate.

## 6. Recommendation memo
**To:** Product & Growth | **Decision:** Roll out streak push in stages, do not go 100% yet.

1. **Retention gain is statistically clear** (+5.3 pp, CI excludes zero).
2. **But opt-outs rose ~0.9 pp.** Each opt-out permanently loses a re-engagement channel, so the retention gain must be weighed against that.
3. **Action:** ship to 20% of new users, watch opt-out and uninstall rate for 2 weeks; if opt-out increase stays below an agreed ceiling (e.g. +0.5 pp), scale up.
4. **Follow-up tests:** (a) cap streak pushes to ≤1/day and test softer copy to reduce opt-outs; (b) test timing of the push; (c) validate T1 vs T2 difference with a dedicated test.
5. **Instrumentation prerequisite:** confirm `variant`/`campaign_id` populated on 100% of push events before launch.

## 7. Limitations (state these upfront)
- Data is simulated; the effect was planted, so this validates the **method and pipeline**, not the real-world impact of streak pushes.
- Baselines, funnel rates, and opt-out rates are assumptions, not Jar figures.
- Real tests need novelty-effect checks (run ≥2 weeks) and multiple-comparison care when cutting segments.

## 8. Likely interview questions
**Q: Where did your data come from?** "Simulated. I stated my assumptions (30% baseline, 12.8% lift) and used the simulation to build and validate the pipeline, sample-size logic, and recommendation framework I'd apply to real data."
**Q: Why does the observed lift (18.5%) differ from 12.8%?** "Sampling noise. Any single experiment lands around the true effect; the CI [+2.9, +7.6] pp shows the plausible range. That's why I report intervals."
**Q: What's a p-value?** "If streak and standard pushes truly performed the same, the chance of seeing a gap this large by luck. Small p means luck is an unlikely explanation."
**Q: Why not just ship since it's significant?** "The guardrail moved the wrong way. Opt-outs are permanent channel loss, so I'd stage the rollout."
**Q: How do you know the data is correct?** "Event QA: client vs server comparison, duplicate and null checks, ordering rules, identity merge test, sample-ratio check."
**Q: Why sample size matters?** "Too few users and a real effect is indistinguishable from noise; I sized for 80% power at the smallest lift worth detecting."
**Q: Tool mapping?** "CleverTap delivers pushes and holds the variant; Mixpanel stores events for funnels/retention; Plotline for in-app nudges; Python/Excel for analysis."

## 9. Repo structure
```
ab_analysis.py                  # simulation + analysis (run: python ab_analysis.py)
Jar_AB_Experiment_Tracker.xlsx  # funnel, tracking plan, QA, raw data, live-formula analysis
data/                           # funnel.csv, experiment_users.csv
charts/                         # funnel.png, retention_ab.png
```
Requirements: `pip install numpy pandas scipy matplotlib openpyxl`
