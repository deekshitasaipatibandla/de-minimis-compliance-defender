# ============================================================
# DE MINIMIS COMPLIANCE DEFENDER
# Low-Value Import Compliance Triage for Trade Operations Teams
# Built by Deekshita Sai Patibandla | Thunderbird School of Global Management, ASU
#
# DISCLAIMER: AI-suggested classification only. Not legal advice.
# Not a licensed customs ruling. Rates are illustrative and must
# be validated against current official tariff schedules.
# Reflects a ruleset based on public guidance used for screening
# and prioritization only.
# ============================================================

# ── CELL 1: Install dependencies ────────────────────────────
# !pip install anthropic pandas -q

# ── CELL 2: Imports ─────────────────────────────────────────
import os
import json
import time
import pandas as pd
from io import StringIO

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("anthropic not installed — run: pip install anthropic")

# ── CELL 3: Sample manifest (20 SKUs) ───────────────────────
# Covers a realistic mix: apparel, electronics, toys,
# cosmetics, auto parts — across high-risk and low-risk origins

SAMPLE_MANIFEST_CSV = """sku_id,description,country_of_origin,declared_value_usd,quantity,supplier
SKU-001,Women's polyester blouse,China,18.00,50,Guangzhou Textile Co.
SKU-002,USB-C charging cable 1m,China,4.50,200,Shenzhen ElecParts Ltd.
SKU-003,Ceramic coffee mug with logo,Portugal,12.00,100,Porto Gifts S.A.
SKU-004,Children's plastic toy building blocks set,China,9.99,150,Dongguan Toys Factory
SKU-005,Stainless steel water bottle 500ml,Vietnam,14.00,80,Hanoi Goods Co.
SKU-006,Wireless Bluetooth earbuds,China,28.00,60,Shenzhen Audio Tech
SKU-007,Men's cotton t-shirt,Bangladesh,8.50,200,Dhaka Garments Ltd.
SKU-008,Lipstick set 6 colors,China,11.00,120,Shanghai Beauty Supply
SKU-009,Automotive brake pad set,China,38.00,25,Guangzhou Auto Parts
SKU-010,Decorative scented candle,Mexico,16.00,90,Guadalajara Candles
SKU-011,Laptop stand aluminum,China,22.00,40,Shenzhen Office Gear
SKU-012,Yoga mat non-slip 6mm,China,19.50,70,Ningbo Sports Goods
SKU-013,Electric kettle 1.5L,China,31.00,35,Zhejiang Appliances Co.
SKU-014,Cotton canvas tote bag printed,India,7.00,300,Mumbai Eco Bags
SKU-015,Parts,China,45.00,10,Unknown supplier
SKU-016,Assorted goods,Hong Kong,24.00,30,HK General Trading
SKU-017,Phone case silicone,China,3.50,500,Shenzhen Cases Ltd.
SKU-018,Wooden picture frame 5x7,Indonesia,13.00,60,Bali Crafts Co.
SKU-019,Supplement capsules 60ct,China,26.00,45,Guangdong Health Products
SKU-020,Mixed items,China,800.00,1,Various
"""

df_manifest = pd.read_csv(StringIO(SAMPLE_MANIFEST_CSV))
print(f"Manifest loaded: {len(df_manifest)} SKUs")
print(df_manifest[['sku_id','description','country_of_origin','declared_value_usd']].to_string(index=False))


# ── CELL 4: Rule engine ──────────────────────────────────────

# Countries with elevated de minimis risk (post-2025 policy changes)
HIGH_RISK_ORIGINS = {
    "China": "Section 301 tariffs apply; de minimis suspended for PRC shipments per May 2025 executive action",
    "Hong Kong": "Treated as China for tariff purposes per 2020 executive order; de minimis suspended",
}

# HTS chapters known to carry elevated duty rates or be tariff-sensitive
SENSITIVE_CHAPTERS = {
    "61": "Knitted apparel — MFN duties typically 16–32%",
    "62": "Woven apparel — MFN duties typically 8–28%",
    "64": "Footwear — MFN duties typically 8–37%",
    "87": "Automotive parts — Section 301 tariffs may apply",
    "85": "Electronics/electrical — Section 301 tariffs may apply",
    "95": "Toys and games — Section 301 tariffs may apply",
    "30": "Pharmaceuticals/supplements — FDA review may apply",
    "33": "Cosmetics — FDA review may apply",
}

# Vague description flags — trigger manual review
VAGUE_TERMS = [
    "parts", "goods", "items", "misc", "miscellaneous", "assorted",
    "various", "mixed", "other", "accessories", "products", "stuff"
]

# Value thresholds
DE_MINIMIS_THRESHOLD = 800.0   # USD — US statutory threshold (19 USC 1321)
HIGH_VALUE_FLAG = 500.0        # USD — flag for elevated scrutiny even if under threshold

def check_vague_description(description: str) -> bool:
    desc_lower = description.lower().strip()
    # Flag if description is very short
    if len(desc_lower.split()) <= 1:
        return True
    # Flag if it contains only vague terms
    words = set(desc_lower.split())
    vague_set = set(VAGUE_TERMS)
    return len(words - vague_set) == 0

def estimate_duty_band(hts_chapter: str, country: str, declared_value: float) -> dict:
    """
    Returns an illustrative duty band based on HTS chapter + origin.
    NOT a legal determination. Must be validated against current official schedules.
    """
    base_rate = 0.0
    section_301 = 0.0
    notes = []

    chapter_rates = {
        "61": 20.0, "62": 15.0, "63": 10.0, "64": 20.0,
        "84": 2.0,  "85": 3.5,  "87": 5.0,  "39": 5.5,
        "94": 5.0,  "95": 0.0,  "33": 5.0,  "30": 0.0,
        "44": 3.5,  "73": 4.5,  "90": 2.0,  "42": 7.0,
        "48": 2.0,  "49": 0.0,
    }
    base_rate = chapter_rates.get(hts_chapter[:2] if hts_chapter else "", 5.0)

    if country in ("China", "Hong Kong"):
        section_301 = 25.0
        notes.append("Section 301 tariff (25%) likely applies — verify current rate")

    total_low  = base_rate
    total_high = base_rate + section_301

    estimated_duty_low  = round(declared_value * total_low  / 100, 2)
    estimated_duty_high = round(declared_value * total_high / 100, 2)

    return {
        "base_rate_pct": base_rate,
        "section_301_pct": section_301,
        "duty_band": f"{total_low:.0f}–{total_high:.0f}%",
        "estimated_duty_usd_low":  estimated_duty_low,
        "estimated_duty_usd_high": estimated_duty_high,
        "duty_notes": "; ".join(notes) if notes else "Standard MFN rate estimated",
    }

def apply_rule_engine(row: pd.Series) -> dict:
    """
    Apply rule-based pre-screening before Claude classification.
    Returns flags, reasons, and initial risk level.
    """
    flags = []
    reasons = []
    risk_score = 0

    origin = str(row['country_of_origin']).strip()
    value  = float(row['declared_value_usd'])
    desc   = str(row['description']).strip()
    supplier = str(row.get('supplier', '')).strip().lower()

    # Rule 1: High-risk origin
    if origin in HIGH_RISK_ORIGINS:
        flags.append("HIGH_RISK_ORIGIN")
        reasons.append(HIGH_RISK_ORIGINS[origin])
        risk_score += 40

    # Rule 2: De minimis threshold
    if value >= DE_MINIMIS_THRESHOLD:
        flags.append("EXCEEDS_DE_MINIMIS")
        reasons.append(f"Declared value ${value:.2f} meets or exceeds $800 de minimis threshold")
        risk_score += 35
    elif value >= HIGH_VALUE_FLAG:
        flags.append("ELEVATED_VALUE")
        reasons.append(f"Declared value ${value:.2f} is elevated — verify accuracy")
        risk_score += 15

    # Rule 3: Vague description
    if check_vague_description(desc):
        flags.append("VAGUE_DESCRIPTION")
        reasons.append("Description too vague for confident classification — manual review required")
        risk_score += 25

    # Rule 4: Unknown supplier
    if "unknown" in supplier or supplier == "" or supplier == "nan":
        flags.append("UNKNOWN_SUPPLIER")
        reasons.append("Supplier not identified — provenance verification required")
        risk_score += 10

    # Determine risk level
    if risk_score >= 50:
        risk_level = "HIGH_RISK"
    elif risk_score >= 20:
        risk_level = "REVIEW"
    else:
        risk_level = "CLEAR"

    return {
        "flags": flags,
        "reasons": reasons,
        "risk_score": risk_score,
        "rule_risk_level": risk_level,
    }

print("Rule engine loaded.")
print(f"High-risk origins tracked: {list(HIGH_RISK_ORIGINS.keys())}")
print(f"Sensitive HTS chapters tracked: {len(SENSITIVE_CHAPTERS)}")


# ── CELL 5: Claude classifier ────────────────────────────────

CLASSIFICATION_SYSTEM_PROMPT = """You are a trade compliance assistant helping triage import shipment manifests.

For each product description, provide:
1. The most likely HTS chapter (2-digit number, e.g. "61" for knitted apparel)
2. A candidate HTS heading (4-digit, best effort, e.g. "6109")
3. Confidence level: HIGH, MEDIUM, or LOW
4. A brief reason for your classification (1 sentence)
5. Any compliance notes (e.g. FDA-regulated, dual-use concern, restricted material)

CRITICAL INSTRUCTIONS:
- This is for screening and prioritization ONLY — not a legal customs determination
- If the description is too vague to classify confidently, say so and give LOW confidence
- If the product may be regulated by agencies beyond CBP (FDA, FTC, etc.), flag it
- Keep responses concise and structured

Respond ONLY in this exact JSON format:
{
  "hts_chapter": "XX",
  "hts_heading": "XXXX",
  "confidence": "HIGH|MEDIUM|LOW",
  "classification_reason": "one sentence explanation",
  "compliance_notes": "any additional flags, or null"
}"""

def classify_with_claude(description: str, country: str, api_key: str) -> dict:
    """Call Claude to suggest HTS classification for a product description."""
    if not api_key:
        return {
            "hts_chapter": "??",
            "hts_heading": "????",
            "confidence": "LOW",
            "classification_reason": "No API key provided — classification skipped",
            "compliance_notes": None
        }

    client = anthropic.Anthropic(api_key=api_key)

    user_message = f"""Product description: {description}
Country of origin: {country}

Classify this product for US import compliance triage."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=CLASSIFICATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )
        raw = response.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "hts_chapter": "??",
            "hts_heading": "????",
            "confidence": "LOW",
            "classification_reason": "Parse error on Claude response",
            "compliance_notes": None
        }
    except Exception as e:
        return {
            "hts_chapter": "??",
            "hts_heading": "????",
            "confidence": "LOW",
            "classification_reason": f"API error: {str(e)[:80]}",
            "compliance_notes": None
        }

print("Claude classifier loaded.")


# ── CELL 6: Main pipeline ────────────────────────────────────

def run_compliance_pipeline(df: pd.DataFrame, api_key: str = "", delay: float = 0.3) -> pd.DataFrame:
    """
    Full pipeline:
    1. Rule engine pre-screening
    2. Claude HTS classification
    3. Duty band estimation
    4. Final risk scoring and output assembly
    """
    results = []
    total = len(df)

    print(f"\nProcessing {total} SKUs...\n")

    for i, row in df.iterrows():
        print(f"  [{i+1}/{total}] {row['sku_id']} — {row['description'][:45]}...")

        # Step 1: Rule engine
        rule_result = apply_rule_engine(row)

        # Step 2: Claude classification
        claude_result = classify_with_claude(
            str(row['description']),
            str(row['country_of_origin']),
            api_key
        )
        if delay and api_key:
            time.sleep(delay)

        # Step 3: Duty band
        duty = estimate_duty_band(
            claude_result.get('hts_chapter', ''),
            str(row['country_of_origin']),
            float(row['declared_value_usd'])
        )

        # Step 4: Final risk — merge Claude confidence into rule score
        final_risk = rule_result['rule_risk_level']
        confidence = claude_result.get('confidence', 'LOW')

        # Downgrade CLEAR to REVIEW if Claude has LOW confidence
        if final_risk == "CLEAR" and confidence == "LOW":
            final_risk = "REVIEW"

        # Add HTS sensitivity flag if applicable
        hts_ch = claude_result.get('hts_chapter', '')
        if hts_ch in SENSITIVE_CHAPTERS:
            if final_risk != "HIGH_RISK":
                final_risk = "REVIEW"
            rule_result['reasons'].append(SENSITIVE_CHAPTERS[hts_ch])

        # Emoji label
        risk_emoji = {"HIGH_RISK": "🔴 High Risk", "REVIEW": "🟡 Review", "CLEAR": "🟢 Clear"}.get(final_risk, "🟡 Review")

        # Recommended action
        action_map = {
            "HIGH_RISK": "Do not clear without manual review. Escalate to customs broker.",
            "REVIEW":    "Analyst review required before booking or clearance.",
            "CLEAR":     "Proceed. Monitor for classification updates.",
        }

        # Total duty exposure estimate
        total_qty = int(row.get('quantity', 1))
        duty_exposure_low  = round(duty['estimated_duty_usd_low']  * total_qty, 2)
        duty_exposure_high = round(duty['estimated_duty_usd_high'] * total_qty, 2)

        results.append({
            "SKU":                  row['sku_id'],
            "Description":          row['description'],
            "Origin":               row['country_of_origin'],
            "Declared Value":       f"${float(row['declared_value_usd']):.2f}",
            "Qty":                  total_qty,
            "HTS Chapter":          claude_result.get('hts_chapter', '??'),
            "HTS Heading":          claude_result.get('hts_heading', '????'),
            "Classification":       claude_result.get('classification_reason', ''),
            "Confidence":           confidence,
            "Duty Band":            duty['duty_band'],
            "Est. Duty/Unit":       f"${duty['estimated_duty_usd_low']:.2f}–${duty['estimated_duty_usd_high']:.2f}",
            "Est. Total Exposure":  f"${duty_exposure_low:,.2f}–${duty_exposure_high:,.2f}",
            "Risk Level":           risk_emoji,
            "Flag Reasons":         " | ".join(rule_result['reasons']) if rule_result['reasons'] else "No flags",
            "Compliance Notes":     claude_result.get('compliance_notes') or "None",
            "Recommended Action":   action_map[final_risk],
            "_risk_raw":            final_risk,  # keep for sorting
        })

    results_df = pd.DataFrame(results)
    # Sort: High Risk first, then Review, then Clear
    order = {"HIGH_RISK": 0, "REVIEW": 1, "CLEAR": 2}
    results_df['_sort'] = results_df['_risk_raw'].map(order)
    results_df = results_df.sort_values('_sort').drop(columns=['_sort', '_risk_raw']).reset_index(drop=True)

    return results_df


# ── CELL 7: Run the pipeline ─────────────────────────────────
# Set your Anthropic API key here (or leave blank to run rule-engine-only mode)

API_KEY = ""  # ← paste your key: "sk-ant-..."

results_df = run_compliance_pipeline(df_manifest, api_key=API_KEY)

print("\n" + "="*60)
print("PIPELINE COMPLETE")
print("="*60)
print(f"Total SKUs processed: {len(results_df)}")
print(f"🔴 High Risk:  {(results_df['Risk Level'].str.contains('High')).sum()}")
print(f"🟡 Review:     {(results_df['Risk Level'].str.contains('Review')).sum()}")
print(f"🟢 Clear:      {(results_df['Risk Level'].str.contains('Clear')).sum()}")


# ── CELL 8: Results summary ───────────────────────────────────

print("\n── TOP RISK SKUs ──────────────────────────────────────")
top_risk = results_df[results_df['Risk Level'].str.contains('High|Review')]
display_cols = ['SKU', 'Description', 'Origin', 'Declared Value', 'Risk Level', 'Est. Total Exposure']
print(top_risk[display_cols].to_string(index=False))

print("\n── FLAG REASON BREAKDOWN ──────────────────────────────")
all_reasons = []
for reasons_str in results_df['Flag Reasons']:
    if reasons_str != "No flags":
        all_reasons.extend([r.strip() for r in reasons_str.split("|")])

from collections import Counter
reason_counts = Counter(all_reasons)
for reason, count in reason_counts.most_common():
    short = reason[:70] + "..." if len(reason) > 70 else reason
    print(f"  {count}x  {short}")

print("\n── DUTY EXPOSURE ESTIMATE ─────────────────────────────")
print("(Illustrative only — must be validated against current tariff schedules)")
flagged = results_df[results_df['Risk Level'].str.contains('High|Review')]
print(f"  Flagged SKUs: {len(flagged)} of {len(results_df)}")
print(f"  Flagged SKU descriptions: {list(flagged['SKU'].values)}")


# ── CELL 9: Save output CSV ───────────────────────────────────

output_path = "de_minimis_compliance_results.csv"
results_df.drop(columns=[]).to_csv(output_path, index=False)
print(f"\nResults saved to: {output_path}")
print("Download from Colab Files panel or mount Google Drive to save.")

# Google Drive save (uncomment if running in Colab with Drive mounted):
# from google.colab import drive
# drive.mount('/content/drive')
# results_df.to_csv('/content/drive/MyDrive/de-minimis/de_minimis_compliance_results.csv', index=False)
# print("Saved to Google Drive.")


# ── CELL 10: Preview full results table ──────────────────────

pd.set_option('display.max_columns', None)
pd.set_option('display.max_colwidth', 40)
pd.set_option('display.width', 200)
print("\n── FULL RESULTS TABLE ─────────────────────────────────")
print(results_df[['SKU','Description','Origin','HTS Chapter','Confidence','Duty Band','Risk Level','Recommended Action']].to_string(index=False))
