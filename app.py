"""
De Minimis Compliance Defender
Low-Value Import Compliance Triage for Trade Operations Teams
Built by Deekshita Sai Patibandla | Thunderbird School of Global Management, ASU

DISCLAIMER: AI-suggested classification only. Not legal advice. Not a licensed
customs ruling. Rates are illustrative and must be validated against current
official tariff schedules. Reflects a ruleset based on public guidance used
for screening and prioritization only.
"""

import streamlit as st
import pandas as pd
import json
import time
from io import StringIO, BytesIO

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="De Minimis Compliance Defender",
    page_icon="🛃",
    layout="wide",
)

# ── Styles ────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2.2rem; font-weight: 700; }
.risk-high   { color: #ef4444; font-weight: 700; }
.risk-review { color: #f59e0b; font-weight: 700; }
.risk-clear  { color: #22c55e; font-weight: 700; }
.disclaimer-box {
    background: #1e293b; border: 1px solid #334155;
    border-left: 4px solid #f59e0b;
    padding: 10px 16px; border-radius: 4px;
    font-size: 0.8rem; color: #94a3b8; margin-bottom: 1rem;
}
</style>
""", unsafe_allow_html=True)

# ── Sample manifest ───────────────────────────────────────────
# 25 SKUs across 3 expected buckets:
#   High Risk (3):  vague descriptions, $800 threshold, HK/PRC origin
#   Review   (10):  China origin with clear descriptions — Section 301
#   Clear    (12):  non-PRC origin, named supplier, clear description
SAMPLE_CSV = """sku_id,description,country_of_origin,declared_value_usd,quantity,supplier
SKU-001,Women's polyester woven blouse,China,18.00,50,Guangzhou Textile Co.
SKU-002,USB-C charging cable 1m,China,4.50,200,Shenzhen ElecParts Ltd.
SKU-003,Ceramic coffee mug with logo print,Portugal,12.00,100,Porto Gifts S.A.
SKU-004,Children's plastic toy building blocks set,China,9.99,150,Dongguan Toys Factory
SKU-005,Stainless steel insulated water bottle 500ml,Vietnam,14.00,80,Hanoi Goods Co.
SKU-006,Wireless Bluetooth earbuds with charging case,China,28.00,60,Shenzhen Audio Tech
SKU-007,Men's cotton crew neck t-shirt,Bangladesh,8.50,200,Dhaka Garments Ltd.
SKU-008,Lipstick set 6 colors cosmetic kit,China,11.00,120,Shanghai Beauty Supply
SKU-009,Automotive disc brake pad set front axle,China,38.00,25,Guangzhou Auto Parts
SKU-010,Decorative soy wax scented candle 200g,Mexico,16.00,90,Artesanias del Norte
SKU-011,Aluminum foldable laptop stand adjustable,China,22.00,40,Shenzhen Office Gear
SKU-012,Non-slip yoga mat 6mm TPE,China,19.50,70,Ningbo Sports Goods
SKU-013,Stainless steel electric kettle 1.5L 1500W,China,31.00,35,Zhejiang Appliances Co.
SKU-014,Cotton canvas tote bag screen printed,India,7.00,300,Mumbai Eco Bags
SKU-015,Parts,China,45.00,10,
SKU-016,Assorted goods,Hong Kong,24.00,30,HK General Trading
SKU-017,Phone case silicone,China,3.50,500,Shenzhen Cases Ltd.
SKU-018,Wooden picture frame 5x7 natural pine,Indonesia,13.00,60,Bali Crafts Co.
SKU-019,Supplement capsules 60ct,China,26.00,45,Guangdong Health Products
SKU-020,Mixed items,China,800.00,1,
SKU-021,Handwoven wool throw blanket 130x180cm,Peru,45.00,3,Andean Textiles SAC
SKU-022,Borosilicate glass food storage container set 3pc,Germany,32.00,4,Bayern Glassware GmbH
SKU-023,Organic cotton baby onesie 3-pack,India,14.00,8,Chennai Organic Textiles
SKU-024,Stainless steel travel cutlery set fork knife spoon,South Korea,18.00,6,Seoul Housewares Co.
SKU-025,Hand-painted ceramic serving bowl 25cm,Portugal,28.00,5,Alentejo Pottery Studio"""

# ── Rule engine data ──────────────────────────────────────────
HIGH_RISK_ORIGINS = {
    "China": "Section 301 tariffs apply; de minimis suspended for PRC shipments per May 2025 executive action",
    "Hong Kong": "Treated as China for tariff purposes per 2020 executive order; de minimis suspended",
}

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

VAGUE_TERMS = ["parts","goods","items","misc","miscellaneous","assorted",
               "various","mixed","other","accessories","products","stuff"]

CHAPTER_RATES = {
    "61":20.0,"62":15.0,"63":10.0,"64":20.0,"84":2.0,"85":3.5,
    "87":5.0,"39":5.5,"94":5.0,"95":0.0,"33":5.0,"30":0.0,
    "44":3.5,"73":4.5,"90":2.0,"42":7.0,"48":2.0,"49":0.0,
}

CLASSIFICATION_SYSTEM_PROMPT = """You are a U.S. Customs HTS classification assistant helping triage import manifests.

For each product, provide the most likely HTS chapter and heading for U.S. import purposes.

CONFIDENCE LEVELS — use exactly one:
- HIGH:   Description is specific enough for confident 4-digit heading assignment
- MEDIUM: Chapter is clear; heading is a strong candidate but not certain
- LOW:    Chapter is your best estimate; description is somewhat vague

ABSOLUTE RULES — never break these:
1. ALWAYS return valid JSON. Never return plain text or markdown outside the JSON.
2. NEVER leave hts_chapter or hts_heading blank or null.
3. NEVER use "????" or "unknown" or "N/A" for hts_chapter or hts_heading.
4. When a description is vague, use the fallback: assign the most likely chapter and
   set hts_heading to that chapter + "XX" (e.g. "84XX" for unspecified machinery parts).
5. ALWAYS provide a classification_reason — even for vague items.

COMMON MAPPINGS (use as reference):
- Apparel knitted (t-shirts, onesies, blouses): chapter 61, headings 6109/6106/6110
- Apparel woven (woven blouses, shirts): chapter 62, headings 6206/6205
- Footwear: chapter 64
- Ceramics/porcelain (mugs, bowls): chapter 69, headings 6912/6911
- Glass articles (containers, tableware): chapter 70, headings 7013/7010
- Iron/steel articles (water bottles, cutlery): chapter 73/82, headings 7323/8215
- Electronics/electrical (cables, earbuds, kettles): chapter 85, headings 8544/8518/8516
- Machinery/mechanical (laptop stands, parts): chapter 84/94, headings 9403/84XX
- Plastics (phone cases, yoga mats): chapter 39, headings 3926/3926
- Toys/games: chapter 95, heading 9503
- Cosmetics/beauty: chapter 33, headings 3304/3305
- Automotive parts: chapter 87, heading 8708
- Candles/wax: chapter 34, heading 3406
- Wood articles (frames): chapter 44, heading 4414
- Textile articles (tote bags, blankets): chapter 63, headings 6305/6301
- Supplements/pharma capsules: chapter 21/30, headings 2106/3004

Respond ONLY in this exact JSON — no text before or after:
{
  "hts_chapter": "two-digit string e.g. 62",
  "hts_heading": "four-char string e.g. 6206 or 84XX",
  "confidence": "HIGH or MEDIUM or LOW",
  "classification_reason": "one sentence plain-English explanation",
  "compliance_notes": "FDA-regulated / Section 301 risk / dual-use concern, or null"
}"""

# ── Helper functions ──────────────────────────────────────────
def check_vague(desc):
    words = set(desc.lower().strip().split())
    if len(words) <= 1: return True
    return len(words - set(VAGUE_TERMS)) == 0

def apply_rules(row):
    flags, reasons, score = [], [], 0
    origin  = str(row['country_of_origin']).strip()
    value   = float(row['declared_value_usd'])
    desc    = str(row['description']).strip()
    supplier= str(row.get('supplier','')).strip().lower()

    if origin in HIGH_RISK_ORIGINS:
        flags.append("HIGH_RISK_ORIGIN")
        reasons.append(HIGH_RISK_ORIGINS[origin])
        score += 40
    if value >= 800:
        flags.append("EXCEEDS_DE_MINIMIS")
        reasons.append(f"Declared value ${value:.2f} meets/exceeds $800 de minimis threshold")
        score += 35
    elif value >= 500:
        flags.append("ELEVATED_VALUE")
        reasons.append(f"Declared value ${value:.2f} is elevated — verify accuracy")
        score += 15
    if check_vague(desc):
        flags.append("VAGUE_DESCRIPTION")
        reasons.append("Description too vague for confident classification — manual review required")
        score += 25
    if "unknown" in supplier or supplier in ("","nan"):
        flags.append("UNKNOWN_SUPPLIER")
        reasons.append("Supplier not identified — provenance verification required")
        score += 10

    level = "HIGH_RISK" if score >= 50 else "REVIEW" if score >= 20 else "CLEAR"
    return {"flags": flags, "reasons": reasons, "score": score, "level": level}

def duty_band(hts_chapter, country, value, qty):
    base = CHAPTER_RATES.get((hts_chapter or "")[:2], 5.0)
    s301 = 25.0 if country in ("China","Hong Kong") else 0.0
    lo = round(value * base / 100, 2)
    hi = round(value * (base + s301) / 100, 2)
    return {
        "band": f"{base:.0f}–{base+s301:.0f}%",
        "unit_lo": lo, "unit_hi": hi,
        "total_lo": round(lo*qty,2), "total_hi": round(hi*qty,2),
    }

def classify_claude(desc, country, api_key):
    if not api_key:
        return {"hts_chapter":"??","hts_heading":"??XX","confidence":"LOW",
                "classification_reason":"No API key — rule engine only","compliance_notes":None}
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=350,
            system=CLASSIFICATION_SYSTEM_PROMPT,
            messages=[{"role":"user","content":
                f"Product description: {desc}\n"
                f"Country of origin: {country}\n"
                f"Classify for U.S. import triage. Return only the JSON object."}]
        )
        raw = resp.content[0].text.strip()
        # Strip accidental markdown fences
        raw = raw.replace("```json","").replace("```","").strip()
        result = json.loads(raw)

        # Safety net — enforce fallback if model still returns blanks
        ch = str(result.get("hts_chapter","")).strip()
        hd = str(result.get("hts_heading","")).strip()
        if not ch or ch in ("??","????","unknown","N/A",""):
            result["hts_chapter"] = "99"
            result["hts_heading"] = "9999"
            result["confidence"] = "LOW"
            result["classification_reason"] = (
                result.get("classification_reason") or
                "Description too vague for confident classification — manual review required"
            )
        elif not hd or hd in ("??","????","unknown","N/A",""):
            result["hts_heading"] = ch + "XX"

        return result

    except Exception as e:
        # Hard fallback — never crash the UI or show "Classification error"
        return {
            "hts_chapter": "99",
            "hts_heading": "9999",
            "confidence": "LOW",
            "classification_reason": "Description too vague for confident classification — manual review required",
            "compliance_notes": None,
        }

def run_pipeline(df, api_key=""):
    results = []
    progress = st.progress(0, text="Starting classification...")
    total = len(df)

    for i, row in df.iterrows():
        progress.progress((i+1)/total, text=f"Classifying {row['sku_id']} ({i+1}/{total})...")
        rule  = apply_rules(row)
        claude = classify_claude(str(row['description']), str(row['country_of_origin']), api_key)
        if api_key: time.sleep(0.25)

        hts_ch = claude.get('hts_chapter','')
        conf   = claude.get('confidence','LOW')
        final  = rule['level']

        # Only bump CLEAR→REVIEW when confidence is LOW *and* the item has
        # a classification-relevant flag (vague desc or sensitive chapter).
        # Non-PRC items with clear descriptions should be allowed to clear
        # even at MEDIUM confidence.
        has_vague = "VAGUE_DESCRIPTION" in rule['flags']
        if final == "CLEAR" and conf == "LOW" and has_vague:
            final = "REVIEW"
        if hts_ch in SENSITIVE_CHAPTERS and final != "HIGH_RISK":
            final = "REVIEW"
            rule['reasons'].append(SENSITIVE_CHAPTERS[hts_ch])

        # Display helpers — don't show catch-all 99/9999 as if they're real chapters
        display_ch = hts_ch if hts_ch not in ("??","","99") else "—"
        raw_hd = claude.get('hts_heading','')
        display_hd = raw_hd if raw_hd not in ("??","????","9999","","None") else "—"
        qty  = int(row.get('quantity',1))
        val  = float(row['declared_value_usd'])
        d    = duty_band(hts_ch, str(row['country_of_origin']), val, qty)
        origin = str(row['country_of_origin']).strip()

        emoji = {"HIGH_RISK":"🔴 High Risk","REVIEW":"🟡 Review","CLEAR":"🟢 Clear"}.get(final,"🟡 Review")
        action = {
            "HIGH_RISK": "Do not clear without manual review. Escalate to customs broker.",
            "REVIEW":    "Analyst review required before booking or clearance.",
            "CLEAR":     "Proceed. Monitor for classification updates.",
        }[final]

        results.append({
            "SKU":              row['sku_id'],
            "Description":      row['description'],
            "Origin":           origin,
            "Declared Value":   f"${val:.2f}",
            "Qty":              qty,
            "HTS Chapter":      display_ch,
            "HTS Heading":      display_hd,
            "Classification":   claude.get('classification_reason',''),
            "Confidence":       conf,
            "Duty Band":        d['band'],
            "Est. Duty/Unit":   f"${d['unit_lo']:.2f}–${d['unit_hi']:.2f}",
            "Est. Total Exposure": f"${d['total_lo']:,.2f}–${d['total_hi']:,.2f}",
            "Risk Level":       emoji,
            "Flag Reasons":     " | ".join(rule['reasons']) if rule['reasons'] else "No flags",
            "Compliance Notes": claude.get('compliance_notes') or "None",
            "Recommended Action": action,
            "_raw":             final,
        })

    progress.empty()
    out = pd.DataFrame(results)
    order = {"HIGH_RISK":0,"REVIEW":1,"CLEAR":2}
    out['_sort'] = out['_raw'].map(order)
    return out.sort_values('_sort').drop(columns=['_sort','_raw']).reset_index(drop=True)

# ── Header ────────────────────────────────────────────────────
st.markdown("# 🛃 De Minimis Compliance Defender")
st.markdown("**Low-Value Import Compliance Triage for Trade Operations Teams**")
st.markdown("*Built by Deekshita Sai Patibandla | Thunderbird School of Global Management, ASU*")
st.markdown('<div class="disclaimer-box">⚠️ <strong>Disclaimer:</strong> AI-suggested classification only. Not legal advice. Not a licensed customs ruling. Duty rates are illustrative and must be validated against current official tariff schedules (USITC). Reflects a ruleset based on public guidance used for screening and prioritization only. Trade rules change — verify all determinations before booking or clearance.</div>', unsafe_allow_html=True)
st.markdown("---")

# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")

    _secret = ""
    try:
        _secret = st.secrets.get("ANTHROPIC_API_KEY","")
    except: pass

    if _secret:
        api_key = _secret
        st.success("AI classification active", icon="🤖")
    else:
        api_key = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")
        if api_key:
            st.success("AI classification active", icon="🤖")
        else:
            st.info("Rule engine only without API key")

    st.markdown("---")
    st.caption("**Rule engine covers:**")
    st.caption("• High-risk origins (China, HK)")
    st.caption("• De minimis threshold ($800)")
    st.caption("• Vague descriptions")
    st.caption("• Unknown suppliers")
    st.markdown("---")
    st.caption("Data: USITC HTS Schedule · CBP guidance · Anthropic Claude Haiku")
    st.caption("Policy snapshot: August 2025")

# ── Main tabs ─────────────────────────────────────────────────
tab_upload, tab_results, tab_queue, tab_flags = st.tabs([
    "📂 Upload Manifest", "📊 Results", "🔍 Review Queue", "📋 Flag Summary"
])

with tab_upload:
    st.subheader("Upload a shipment manifest CSV")
    st.markdown("**Required columns:** `sku_id`, `description`, `country_of_origin`, `declared_value_usd`, `quantity`")
    st.markdown("Optional: `supplier`")

    col1, col2 = st.columns([1, 1])
    with col1:
        uploaded = st.file_uploader("Upload CSV", type=["csv"])
    with col2:
        use_sample = st.button("📦 Load sample manifest (25 SKUs)", use_container_width=True)
        st.caption("Covers apparel, electronics, ceramics, auto parts across 10 countries — shows all 3 risk tiers")

    if use_sample:
        st.session_state['df_input'] = pd.read_csv(StringIO(SAMPLE_CSV))
        st.session_state['results'] = None
        st.success("Sample manifest loaded — 25 SKUs ready")

    if uploaded:
        try:
            st.session_state['df_input'] = pd.read_csv(uploaded)
            st.session_state['results'] = None
            st.success(f"Uploaded: {len(st.session_state['df_input'])} SKUs")
        except Exception as e:
            st.error(f"Could not read CSV: {e}")

    if 'df_input' in st.session_state:
        st.markdown("**Preview:**")
        st.dataframe(st.session_state['df_input'], use_container_width=True, height=280)

        if st.button("🚀 Run Compliance Triage", type="primary", use_container_width=True):
            with st.spinner("Running compliance pipeline..."):
                st.session_state['results'] = run_pipeline(
                    st.session_state['df_input'], api_key=api_key
                )
            st.success("Done! Go to Results tab.")
            st.balloons()

# ── Results tab ───────────────────────────────────────────────
with tab_results:
    if 'results' not in st.session_state or st.session_state['results'] is None:
        st.info("Upload a manifest and run triage to see results.")
    else:
        df = st.session_state['results']
        n_high   = (df['Risk Level'].str.contains('High')).sum()
        n_review = (df['Risk Level'].str.contains('Review')).sum()
        n_clear  = (df['Risk Level'].str.contains('Clear')).sum()
        n_total  = len(df)
        pct_flag = round((n_high + n_review) / n_total * 100) if n_total else 0

        # Metric strip
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("SKUs Processed", n_total)
        c2.metric("🔴 High Risk", n_high)
        c3.metric("🟡 Needs Review", n_review)
        c4.metric("% Flagged", f"{pct_flag}%")

        st.markdown("---")

        # Full results table
        st.subheader("📊 Full Results")
        display_cols = ['SKU','Description','Origin','Declared Value','HTS Chapter',
                        'Confidence','Duty Band','Est. Total Exposure','Risk Level','Recommended Action']
        st.dataframe(df[display_cols], use_container_width=True, height=480)

        # Download
        csv_out = df.drop(columns=[c for c in df.columns if c.startswith('_')]).to_csv(index=False)
        st.download_button(
            "⬇️ Download Full Results CSV",
            data=csv_out,
            file_name="de_minimis_compliance_results.csv",
            mime="text/csv",
            use_container_width=True
        )

# ── Review Queue tab ─────────────────────────────────────────
with tab_queue:
    if 'results' not in st.session_state or st.session_state['results'] is None:
        st.info("Run triage first.")
    else:
        df = st.session_state['results']

        # High Risk
        high = df[df['Risk Level'].str.contains('High')]
        st.markdown(f"### 🔴 High Risk — {len(high)} SKUs")
        st.caption("Do not clear without manual review. Escalate to customs broker.")
        if len(high):
            for _, row in high.iterrows():
                with st.expander(f"**{row['SKU']}** — {row['Description']} ({row['Origin']})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Declared Value:** {row['Declared Value']}  ·  **Qty:** {row['Qty']}")
                        st.markdown(f"**HTS Chapter:** {row['HTS Chapter']}  ·  **Heading:** {row['HTS Heading']}")
                        st.markdown(f"**Classification:** {row['Classification']}")
                        st.markdown(f"**Confidence:** {row['Confidence']}")
                    with col2:
                        st.markdown(f"**Duty Band:** {row['Duty Band']}")
                        st.markdown(f"**Est. Total Exposure:** {row['Est. Total Exposure']}")
                        st.markdown(f"**Compliance Notes:** {row['Compliance Notes']}")
                    st.markdown(f"**⚠️ Why flagged:** {row['Flag Reasons']}")
                    st.error(f"**Action:** {row['Recommended Action']}")
        else:
            st.success("No HIGH RISK SKUs in this manifest.")

        st.markdown("---")

        # Review
        review = df[df['Risk Level'].str.contains('Review')]
        st.markdown(f"### 🟡 Needs Review — {len(review)} SKUs")
        st.caption("Analyst review required before booking or clearance.")
        if len(review):
            for _, row in review.iterrows():
                with st.expander(f"**{row['SKU']}** — {row['Description']} ({row['Origin']})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Declared Value:** {row['Declared Value']}  ·  **Qty:** {row['Qty']}")
                        st.markdown(f"**HTS Chapter:** {row['HTS Chapter']}  ·  **Heading:** {row['HTS Heading']}")
                        st.markdown(f"**Classification:** {row['Classification']}")
                        st.markdown(f"**Confidence:** {row['Confidence']}")
                    with col2:
                        st.markdown(f"**Duty Band:** {row['Duty Band']}")
                        st.markdown(f"**Est. Total Exposure:** {row['Est. Total Exposure']}")
                        st.markdown(f"**Compliance Notes:** {row['Compliance Notes']}")
                    st.markdown(f"**Why flagged:** {row['Flag Reasons']}")
                    st.warning(f"**Action:** {row['Recommended Action']}")

        st.markdown("---")

        # Clear
        clear = df[df['Risk Level'].str.contains('Clear')]
        st.markdown(f"### 🟢 Clear — {len(clear)} SKUs")
        if len(clear):
            st.dataframe(clear[['SKU','Description','Origin','Declared Value','HTS Chapter','Duty Band']], use_container_width=True)
        else:
            st.info("No SKUs cleared in this run.")

# ── Flag Summary tab ──────────────────────────────────────────
with tab_flags:
    if 'results' not in st.session_state or st.session_state['results'] is None:
        st.info("Run triage first.")
    else:
        df = st.session_state['results']
        st.subheader("📋 Flag Reason Breakdown")

        from collections import Counter
        all_reasons = []
        for r in df['Flag Reasons']:
            if r != "No flags":
                all_reasons.extend([x.strip() for x in r.split("|")])
        counts = Counter(all_reasons)

        if counts:
            reason_df = pd.DataFrame(counts.most_common(), columns=["Flag Reason","Count"])
            reason_df["Flag Reason"] = reason_df["Flag Reason"].str[:90]

            for _, row in reason_df.iterrows():
                pct = round(row['Count'] / len(df) * 100)
                st.markdown(f"**{row['Count']} SKUs ({pct}%)** — {row['Flag Reason']}")
                st.progress(row['Count'] / len(df))

        st.markdown("---")
        st.subheader("🌍 Risk by Origin")
        origin_risk = df.groupby('Origin')['Risk Level'].apply(
            lambda x: pd.Series({
                '🔴 High': x.str.contains('High').sum(),
                '🟡 Review': x.str.contains('Review').sum(),
                '🟢 Clear': x.str.contains('Clear').sum(),
            })
        ).unstack(fill_value=0).reset_index()
        st.dataframe(origin_risk, use_container_width=True)

        st.markdown("---")
        st.subheader("💰 Estimated Duty Exposure Summary")
        st.caption("Illustrative only — must be validated against current official tariff schedules")
        flagged = df[~df['Risk Level'].str.contains('Clear')]
        st.markdown(f"- **{len(flagged)} of {len(df)} SKUs** flagged for review or escalation")
        st.markdown(f"- **Most common origin flagged:** {df[df['Risk Level'].str.contains('High|Review')]['Origin'].mode()[0] if len(flagged) else '—'}")

        china_hk = df[df['Origin'].isin(['China','Hong Kong'])]
        st.markdown(f"- **China/HK SKUs:** {len(china_hk)} of {len(df)} — de minimis treatment suspended per May 2025 executive action")

# ── Footer ────────────────────────────────────────────────────
st.markdown("---")
st.caption("Data: USITC HTS Schedule · CBP Public Guidance · Anthropic Claude Haiku · Policy snapshot: August 2025")
st.caption("Deekshita Sai Patibandla | Thunderbird School of Global Management, ASU")
