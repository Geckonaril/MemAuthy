# Offline detection — 20261120T225112Z-d3-detection-v01-1cec14d2

Exploratory, synthetic snapshots (ADR-0011). Block-level detection only; not trigger-session adoption. Samples: 288; block rows: 110160. Rates with Wilson 95% CI.

## Primary scope (IPI)

| Condition | Attack recall | Precision | False-block rate | User-rule preserved | Uncertain (attack / legit) |
|---|---|---|---|---|---|
| D0 | 0.000 [0.00, 0.02] | - | 0.000 [0.00, 0.00] | 1.000 [0.98, 1.00] | 0 / 0 |
| D2 | 0.750 [0.68, 0.81] | 0.143 | 0.060 [0.06, 0.06] | 0.500 [0.43, 0.57] | 0 / 0 |
| D3 | 0.688 [0.62, 0.75] | 0.216 | 0.033 [0.03, 0.04] | 1.000 [0.98, 1.00] | 0 / 0 |
| D4@P1 | 0.667 [0.60, 0.73] | 1.000 | 0.000 [0.00, 0.00] | 1.000 [0.98, 1.00] | 0 / 0 |
| D4@P2 | 1.000 [0.98, 1.00] | 1.000 | 0.000 [0.00, 0.00] | 1.000 [0.98, 1.00] | 0 / 0 |

### Attack recall by rule surface variant (IPI)

| Condition | fact | payload | target |
|---|---|---|---|
| D0 | 0.000 [0.00, 0.06] | 0.000 [0.00, 0.06] | 0.000 [0.00, 0.06] |
| D2 | 0.250 [0.16, 0.37] | 1.000 [0.94, 1.00] | 1.000 [0.94, 1.00] |
| D3 | 0.375 [0.27, 0.50] | 0.688 [0.57, 0.79] | 1.000 [0.94, 1.00] |
| D4@P1 | 0.000 [0.00, 0.06] | 1.000 [0.94, 1.00] | 1.000 [0.94, 1.00] |
| D4@P2 | 1.000 [0.94, 1.00] | 1.000 [0.94, 1.00] | 1.000 [0.94, 1.00] |

## Boundary analysis (DPI-U; rule arrives through the trusted user channel)

| Condition | Attack recall | Precision | False-block rate | User-rule preserved | Uncertain (attack / legit) |
|---|---|---|---|---|---|
| D0 | 0.000 [0.00, 0.04] | - | 0.000 [0.00, 0.00] | 1.000 [0.96, 1.00] | 0 / 0 |
| D2 | 0.750 [0.65, 0.83] | 0.143 | 0.060 [0.05, 0.07] | 0.500 [0.40, 0.60] | 0 / 0 |
| D3 | 0.812 [0.72, 0.88] | 0.245 | 0.033 [0.03, 0.04] | 1.000 [0.96, 1.00] | 0 / 0 |
| D4@P1 | 0.000 [0.00, 0.04] | - | 0.000 [0.00, 0.00] | 1.000 [0.96, 1.00] | 0 / 0 |
| D4@P2 | 0.000 [0.00, 0.04] | - | 0.000 [0.00, 0.00] | 1.000 [0.96, 1.00] | 0 / 0 |
