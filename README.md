# 🛃 De Minimis Compliance Defender

**Low-Value Import Compliance Triage for Trade Operations Teams**

Built by Deekshita Sai Patibandla | Thunderbird School of Global Management, ASU

---

## What it does

Trade teams receive low-value shipment manifests with messy product descriptions, origin data, and declared values. This tool helps identify which SKUs require review because de minimis treatment may not apply, classification is unclear, or duty exposure may be material.

**Input:** CSV shipment manifest  
**Output:** Risk-ranked review queue with HTS classification, duty exposure estimates, and plain-English flag reasons

---

## Risk levels

| Level | Meaning | Action |
|-------|---------|--------|
| 🔴 High Risk | Vague description + high-risk origin, or exceeds $800 threshold | Escalate to customs broker |
| 🟡 Review | Elevated duty exposure or classification uncertainty | Analyst review before clearance |
| 🟢 Clear | Low risk indicators | Proceed, monitor for updates |

---

## Rule engine flags

- **High-risk origin** — China, Hong Kong (de minimis suspended May 2025)
- **De minimis threshold** — declared value ≥ $800 USD
- **Vague description** — insufficient for confident HTS classification
- **Unknown supplier** — provenance verification required
- **Sensitive HTS chapter** — elevated duty rates or agency regulation

---

## Stack

- Python · pandas — manifest processing
- Anthropic Claude Haiku — HTS chapter suggestion + compliance notes
- Streamlit — interactive dashboard, CSV upload, review queue, download

---

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

Add your Anthropic API key in the sidebar or set as a Streamlit secret:
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

---

## Disclaimer

AI-suggested classification only. Not legal advice. Not a licensed customs ruling. Duty rates are illustrative and must be validated against current official tariff schedules (USITC). Reflects a ruleset based on public guidance used for screening and prioritization only. Trade rules change — verify all determinations before booking or clearance.

---

## Policy context

- De minimis exemption suspended for China/Hong Kong shipments: May 2, 2025
- CBP enforcement of global de minimis end began: August 29, 2025
- Statutory repeal pathway: July 1, 2027

*This tool reflects a ruleset based on public guidance as of August 2025.*

---

Part of a supply chain analytics portfolio | [deekshitapatibandla.com](https://deekshitapatibandla.com)
