"""
Streak-push A/B experiment: simulation and analysis pipeline.

All data is simulated from the assumptions defined in the configuration
section below. No production data is used.

Usage:
    python ab_analysis.py
"""
import os

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Configuration
SEED = 42
N_INSTALLS = 20000   # top-of-funnel users
FUNNEL = [           # (step, conversion from previous step)
    ("App install",                1.00),
    ("Phone/OTP verified",         0.78),
    ("SMS permission granted",     0.72),
    ("Saving amount set",          0.85),
    ("First payment completed",    0.60),
    ("Autopay mandate approved",   0.45),
]
N_PER_ARM = 3000     # activated users per arm
BASE_D7 = {"T1": 0.28, "T2": 0.30, "T3": 0.33}   # control D7 retention by city tier
REL_LIFT = 0.128     # assumed relative lift from the streak push
OPTOUT = {"A": 0.020, "B": 0.024}                # push opt-out rate (guardrail)
ALPHA, POWER = 0.05, 0.80

rng = np.random.default_rng(SEED)
os.makedirs("data", exist_ok=True)
os.makedirs("charts", exist_ok=True)

# 1. Onboarding funnel
counts, n = [], N_INSTALLS
for step, conv in FUNNEL:
    n = int(round(n * conv))
    counts.append(n)

funnel = pd.DataFrame({"step": [s for s, _ in FUNNEL], "users": counts})
funnel["step_conv"] = funnel.users / funnel.users.shift(1)
funnel["overall_conv"] = funnel.users / funnel.users.iloc[0]
funnel.to_csv("data/funnel.csv", index=False)
print("\n=== FUNNEL (simulated) ===\n", funnel.round(3).to_string(index=False))


# 2. Sample size
def sample_size(p1, rel_mde, alpha=ALPHA, power=POWER):
    """Per-arm sample size for a two-sided two-proportion z-test."""
    p2 = p1 * (1 + rel_mde)
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    return int(np.ceil((za + zb) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2))


base_avg = np.mean(list(BASE_D7.values()))
print(f"\n=== SAMPLE SIZE ===\nbaseline~{base_avg:.1%}, MDE={REL_LIFT:.1%} relative "
      f"-> {sample_size(0.30, REL_LIFT)} users per arm (baseline 30%)")


# 3. Experiment simulation
def make_arm(variant):
    tier = rng.choice(["T1", "T2", "T3"], N_PER_ARM, p=[.35, .40, .25])
    p = np.array([BASE_D7[t] for t in tier]) * (1 + (REL_LIFT if variant == "B" else 0))
    return pd.DataFrame({
        "user_id": [f"{variant}{i:05d}" for i in range(N_PER_ARM)],
        "variant": variant,
        "city_tier": tier,
        "retained_d7": rng.binomial(1, p),
        "push_optout": rng.binomial(1, OPTOUT[variant], N_PER_ARM),
    })


df = pd.concat([make_arm("A"), make_arm("B")], ignore_index=True)

# Data quality checks
assert df.user_id.is_unique, "duplicate user ids"
assert df.variant.isin(["A", "B"]).all(), "null/unknown variant"
assert df.retained_d7.isin([0, 1]).all(), "non-binary retention outcome"
print("\nQA checks passed: unique ids, no null variants, binary outcomes")

# Sample ratio mismatch check (expected split is 50/50)
srm = stats.chisquare(df.variant.value_counts().values)
print(f"SRM check p={srm.pvalue:.3f} (p>0.05 indicates a healthy split)")
df.to_csv("data/experiment_users.csv", index=False)


# 4. Analysis
def two_prop(x_a, n_a, x_b, n_b):
    """Two-proportion z-test. Returns rates, z, p-value and 95% CI of the difference."""
    pa, pb = x_a / n_a, x_b / n_b
    pool = (x_a + x_b) / (n_a + n_b)
    z = (pb - pa) / np.sqrt(pool * (1 - pool) * (1 / n_a + 1 / n_b))
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    se = np.sqrt(pa * (1 - pa) / n_a + pb * (1 - pb) / n_b)
    return pa, pb, z, p, (pb - pa) - 1.96 * se, (pb - pa) + 1.96 * se


def report(metric, label):
    a, b = df[df.variant == "A"][metric], df[df.variant == "B"][metric]
    pa, pb, z, p, lo, hi = two_prop(a.sum(), len(a), b.sum(), len(b))
    print(f"\n--- {label} ---\nA={pa:.2%}  B={pb:.2%}  abs diff={pb - pa:+.2%}  "
          f"relative lift={(pb / pa - 1):+.1%}\nz={z:.2f}  p={p:.4f}  "
          f"95% CI (abs diff)=[{lo:+.2%}, {hi:+.2%}]")
    return pa, pb, p, lo, hi


print("\n=== PRIMARY METRIC & GUARDRAIL ===")
pa, pb, p_primary, lo, hi = report("retained_d7", "PRIMARY: Day-7 retention")
report("push_optout", "GUARDRAIL: push opt-out rate")

# Cross-check against chi-square test
chi = stats.chi2_contingency(pd.crosstab(df.variant, df.retained_d7), correction=False)
print(f"\nChi-square cross-check p={chi[1]:.4f} (z-test p={p_primary:.4f})")

# Segment analysis
seg = df.pivot_table(index="city_tier", columns="variant", values="retained_d7", aggfunc="mean")
seg["lift_rel"] = seg.B / seg.A - 1
print("\n=== SEGMENT: D7 retention by city tier ===\n", seg.round(3))
print("Note: segment results are exploratory and subject to small-sample variance.")

# Power check by repeated simulation
sims, hits = 2000, 0
p_ctrl = base_avg
for _ in range(sims):
    xa = rng.binomial(N_PER_ARM, p_ctrl)
    xb = rng.binomial(N_PER_ARM, p_ctrl * (1 + REL_LIFT))
    hits += two_prop(xa, N_PER_ARM, xb, N_PER_ARM)[3] < ALPHA
print(f"\n=== POWER CHECK === {hits / sims:.0%} of {sims} simulated experiments "
      f"detect the effect at n={N_PER_ARM}/arm")

# 5. Charts
plt.style.use("seaborn-v0_8-whitegrid")

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.barh(funnel.step[::-1], funnel.users[::-1], color="#2a6f97")
for i, (u, c) in enumerate(zip(funnel.users[::-1], funnel.overall_conv[::-1])):
    ax.text(u + 150, i, f"{u:,} ({c:.0%})", va="center", fontsize=9)
ax.set_title("Simulated onboarding funnel (assumed conversion rates)")
ax.set_xlabel("Users")
plt.tight_layout()
plt.savefig("charts/funnel.png", dpi=150)
plt.close()

fig, ax = plt.subplots(figsize=(5.5, 4.5))
se_a = np.sqrt(pa * (1 - pa) / N_PER_ARM)
se_b = np.sqrt(pb * (1 - pb) / N_PER_ARM)
ax.bar(["A: Standard nudge", "B: Streak push"], [pa, pb],
       yerr=[1.96 * se_a, 1.96 * se_b],
       color=["#8d99ae", "#2a6f97"], capsize=6)
ax.set_ylabel("Day-7 retention")
ax.set_title(f"D7 retention with 95% CI (p={p_primary:.4f})")
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
plt.tight_layout()
plt.savefig("charts/retention_ab.png", dpi=150)
plt.close()

print("\nSaved: data/*.csv, charts/*.png")
