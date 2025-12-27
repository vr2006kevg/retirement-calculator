import streamlit as st
import pandas as pd
import io

# Page configuration
st.set_page_config(page_title="Retirement Planner Pro", layout="wide")

st.title("🚀 Retirement Cashflow & Tax Simulator")

# --- SIDEBAR: INPUTS ---
with st.sidebar:
    st.header("📋 Filing & Timeline")
    status = st.selectbox(
        "IRS Filing Status", 
        ["Single", "Married Filing Jointly (MFJ)", "Married Filing Separately (MFS)", "Head of Household (HOH)"]
    )
    
    start_age = st.number_input("Retire Age", value=65)
    end_age = st.number_input("Plan Until Age", value=95)
        
    st.header("💰 Starting Balances")
    init_401k = st.number_input("401k Balance ($)", value=1_000_000, step=10000)
    init_roth = st.number_input("Roth Balance ($)", value=500_000, step=10000)
    init_brokerage = st.number_input("Brokerage Balance ($)", value=500_000, step=10000)
    growth = st.slider("Portfolio Growth Rate (%)", 0.0, 15.0, 6.0) / 100

    st.header("📉 Spending & Income")
    annual_spend_base = st.number_input("Target Annual Spending (Today's $)", value=80_000, step=1000)
    inflation = st.slider("Annual Inflation (%)", 0.0, 10.0, 3.0) / 100
    ss_start_age = st.number_input("SS Start Age", value=70)
    ss_benefit = st.number_input("Annual SS Benefit at start age", value=60_000)
    ss_cola = st.slider("SSA Cost-of-Living Adjustment", 0.0, 5.0, 2.0) / 100
    state_tax_rate = st.slider("State Tax Rate (%)", 0.0, 9.0, 1.0) / 100

# --- TAX & STATUS LOGIC ---
def get_status_params(status):
    if status == "Married Filing Jointly (MFJ)":
        brackets = [(0.10, 23850), (0.12, 96950), (0.22, 206700), (0.24, 394600)]
        std_deduct = 31500 + 3200 
        irmaa_tier_0 = 218000
    elif status == "Head of Household (HOH)":
        brackets = [(0.10, 17000), (0.12, 64850), (0.22, 103350), (0.24, 197300)]
        std_deduct = 23625 + 2000
        irmaa_tier_0 = 109000
    elif status == "Married Filing Separately (MFS)":
        brackets = [(0.10, 11925), (0.12, 48475), (0.22, 103350), (0.24, 197300)]
        std_deduct = 15750 + 1600
        irmaa_tier_0 = 109000
    else: # Single
        brackets = [(0.10, 11925), (0.12, 48475), (0.22, 103350), (0.24, 197300)]
        std_deduct = 15750 + 2000
        irmaa_tier_0 = 109000
    return brackets, std_deduct, irmaa_tier_0

def calculate_taxes(ord_inc, ss_total, status_name):
    brackets, deduction, _ = get_status_params(status_name)
    taxable_ss = 0.85 * ss_total
    taxable_inc = max(0.0, ord_inc + taxable_ss - deduction)
    tax = 0
    prev_limit = 0
    for rate, limit in brackets:
        if taxable_inc > limit:
            tax += (limit - prev_limit) * rate
            prev_limit = limit
        else:
            tax += (taxable_inc - prev_limit) * rate
            break
    return tax + (ord_inc * state_tax_rate)

# --- SIMULATION ENGINE ---
def run_simulation():
    _, _, irmaa_cap = get_status_params(status)
    history = []
    b_401k, b_roth, b_broker = init_401k, init_roth, init_brokerage
    
    for age in range(start_age, end_age + 1):
        spend = annual_spend_base * (1 + inflation) ** (age - start_age)
        ss = ss_benefit * (1 + ss_cola) ** (age - ss_start_age) if age >= ss_start_age else 0.0
        
        # RMD based on IRS Uniform Lifetime Table
        rmd = b_401k / (27.4 - (age-72)) if age >= 72 else 0.0
        divs = b_broker * 0.02
        
        current_magi = rmd + divs + (ss * 0.85)
        conv_amt = max(0.0, min(b_401k - rmd, irmaa_cap - current_magi))
        
        tax_paid = calculate_taxes(rmd + conv_amt + divs, ss, status)
        
        total_needed = spend + tax_paid - ss
        w_401k = rmd
        w_broker = min(b_broker, max(0.0, total_needed - w_401k))
        w_roth = max(0.0, total_needed - w_401k - w_broker)
        
        history.append({
            "Age": age, 
            "Spending": spend, 
            "Tax Paid": tax_paid, 
            "Social Security": ss,
            "401k Withdrawal": w_401k, 
            "Brokerage Withdrawal": w_broker,
            "Roth Withdrawal": w_roth, 
            "Roth Conversion": conv_amt,
            "401k Bal": b_401k, 
            "Broker Bal": b_broker, 
            "Roth Bal": b_roth,
            "Net Worth": b_401k + b_roth + b_broker
        })
        
        b_401k = max(0, (b_401k - rmd - conv_amt) * (1 + growth))
        b_broker = max(0, (b_broker - w_broker + divs) * (1 + growth))
        b_roth = max(0, (b_roth + conv_amt - w_roth) * (1 + growth))

    return pd.DataFrame(history)

# --- UI OUTPUT ---
df = run_simulation()

# Summary Metrics
c1, c2, c3 = st.columns(3)
with c1: st.metric("Final Net Worth", f"${df['Net Worth'].iloc[-1]:,.0F}")
with c2: st.metric("Total Tax Paid", f"${df['Tax Paid'].sum():,.0F}")
with c3: st.metric("Ending Roth Bal", f"${df['Roth Bal'].iloc[-1]:,.0F}")

# NEW VISUALIZATIONS
st.markdown("---")
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Portfolio Growth & Composition")
    # Stacked Area Chart for Balances
    st.area_chart(df.set_index("Age")[["401k Bal", "Broker Bal", "Roth Bal"]])
    st.caption("Visualizes the depletion of different account types over time.")

with chart_col2:
    st.subheader("Annual Income vs Spending")
    # Multi-series Bar/Line Chart for Cashflow
    cash_flow_df = df[["Age", "Spending", "Social Security"]].copy()
    cash_flow_df["Total Withdrawals"] = df["401k Withdrawal"] + df["Brokerage Withdrawal"] + df["Roth Withdrawal"]
    st.bar_chart(cash_flow_df.set_index("Age"))
    st.caption("Shows how Spending is met by Social Security and Portfolio Withdrawals.")

# Data Table
st.markdown("---")
st.subheader("Withdrawal Plan Details")
# Compact table styling: smaller font and reduced cell padding
st.markdown(
    """
    <style>
    [data-testid="stDataFrame"] table {
        font-size: 12px;
        border-collapse: collapse;
    }
    [data-testid="stDataFrame"] th, [data-testid="stDataFrame"] td {
        padding: 6px 8px;
    }
    [data-testid="stDataFrame"] tbody tr td {
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.dataframe(df.style.format("{:,.0f}"), width=1500, height=800)

# Excel Download
buffer = io.BytesIO()
#with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
#    df.to_excel(writer, index=False, sheet_name='Retirement Plan')

with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    df.to_excel(writer, sheet_name="Optimized Plan", index=False)
    workbook = writer.book
    worksheet = writer.sheets["Optimized Plan"]

    # Formats
    money_fmt = workbook.add_format({"num_format": "#,##0", "align": "right"})
    hdr_fmt = workbook.add_format({"bold": True, "bg_color": "#CFE2F3", "border": 1})

    # Apply formatting
    worksheet.set_column("A:A", 8)  # Age
    worksheet.set_column("B:L", 18, money_fmt)  # All money columns
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, hdr_fmt)

st.download_button("📥 Download Plan as XLSX", buffer.getvalue(), "RetirementPlan.xlsx")
