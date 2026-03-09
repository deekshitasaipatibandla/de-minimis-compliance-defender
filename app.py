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
SAMPLE_CSV = """sku_id,description,country_of_origin,declared_value_usd,quantity,supplier
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
SKU-020,Mixed items,China,800.00,1,Various"""

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
        return {"hts_chapter":"??","hts_heading":"????","confidence":"LOW",
                "classification_reason":"No API key — rule engine only","compliance_notes":None}
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            system=CLASSIFICATION_SYSTEM_PROMPT,
            messages=[{"role":"user","content":f"Product: {desc}\nOrigin: {country}\nClassify for US import triage."}]
        )
        raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
        return json.loads(raw)
    except:
        return {"hts_chapter":"??","hts_heading":"????","confidence":"LOW",
                "classification_reason":"Classification error","compliance_notes":None}

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

        if final == "CLEAR" and conf == "LOW":
            final = "REVIEW"
        if hts_ch in SENSITIVE_CHAPTERS and final != "HIGH_RISK":
            final = "REVIEW"
            rule['reasons'].append(SENSITIVE_CHAPTERS[hts_ch])

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
            "HTS Chapter":      hts_ch if hts_ch != "??" else "—",
            "HTS Heading":      claude.get('hts_heading','??') if claude.get('hts_heading') != "??" else "—",
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
        use_sample = st.button("📦 Load sample manifest (20 SKUs)", use_container_width=True)
        st.caption("Covers apparel, electronics, toys, cosmetics, auto parts across 8 countries")

    if use_sample:
        st.session_state['df_input'] = pd.read_csv(StringIO(SAMPLE_CSV))
        st.session_state['results'] = None
        st.success("Sample manifest loaded — 20 SKUs ready")

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
