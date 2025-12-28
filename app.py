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
        ["Single", "Married Filing Jointly (MFJ)",
         "Married Filing Separately (MFS)", "Head of Household (HOH)"]
    )

    start_age = st.number_input("Retirement Age", value=65)
    end_age = st.number_input("Plan Until Age", value=95)

    st.header("💰 Starting Balances")
    init_401k = st.number_input(
        "401k Balance ($)", value=1_000_000, step=10000)
    init_roth = st.number_input("Roth Balance ($)", value=500_000, step=10000)
    init_brokerage = st.number_input(
        "Brokerage Balance ($)", value=500_000, step=10000)
    growth = st.slider("Portfolio Growth Rate (%)", 0.0, 15.0, 5.0) / 100

    st.header("📉 Spending & Income")
    annual_spend_base = st.number_input(
        "Target Annual Spending (Today's $)", value=100_000, step=1000)
    inflation = st.slider("Annual Inflation (%)", 0.0, 10.0, 3.0) / 100
    ss_start_age = st.number_input("SS Start Age", value=70)
    ss_benefit = st.number_input(
        "Annual SS Benefit at start age", value=60_000)
    ss_cola = st.slider("SSA Cost-of-Living Adjustment", 0.0, 5.0, 3.0) / 100
    state_tax_rate = st.slider("State Tax Rate (%)", 0.0, 9.0, 2.0) / 100

# --- TAX & STATUS LOGIC ---


def get_status_params(status, exponential):
    if status == "Married Filing Jointly (MFJ)":
        brackets = [(0.10, 24800 * (1 + inflation) ** exponential), (0.12, 100800 * (1 + inflation) ** exponential),
                    (0.22, 211100 * (1 + inflation) ** exponential), (0.24, 403550 * (1 + inflation) ** exponential)]
        std_deduct = (32200 + 3300) * (1 + inflation) ** exponential
        irmaa_tier_0 = 218000 * (1 + inflation) ** exponential
    elif status == "Head of Household (HOH)":
        brackets = [(0.10, 17700 * (1 + inflation) ** exponential), (0.12, 67450 * (1 + inflation) ** exponential),
                    (0.22, 105700 * (1 + inflation) ** exponential), (0.24, 201750 * (1 + inflation) ** exponential)]
        std_deduct = (24150 + 2050) * (1 + inflation) ** exponential
        irmaa_tier_0 = 109000 * (1 + inflation) ** exponential
    elif status == "Married Filing Separately (MFS)":
        brackets = [(0.10, 12400 * (1 + inflation) ** exponential), (0.12, 50400 * (1 + inflation) ** exponential),
                    (0.22, 105700 * (1 + inflation) ** exponential), (0.24, 201775 * (1 + inflation) ** exponential)]
        std_deduct = (16100 + 1650) * (1 + inflation) ** exponential
        irmaa_tier_0 = 109000 * (1 + inflation) ** exponential
    else:  # Single
        brackets = [(0.10, 12400 * (1 + inflation) ** exponential), (0.12, 50400 * (1 + inflation) ** exponential),
                    (0.22, 105700 * (1 + inflation) ** exponential), (0.24, 255225 * (1 + inflation) ** exponential)]
        std_deduct = (16100 + 2050) * (1 + inflation) ** exponential
        irmaa_tier_0 = 109000 * (1 + inflation) ** exponential
    return brackets, std_deduct, irmaa_tier_0


def calculate_taxes(ord_inc, lt_cap_gains, ss_total, status_name, exponential):
    # ord_inc: ordinary taxable events (RMD + conversions)
    # lt_cap_gains: long-term capital gains (preferential rates)
    brackets, deduction, _ = get_status_params(status_name, exponential)
    taxable_ss = 0.85 * ss_total

    # Taxable ordinary income after deduction
    taxable_ordinary = max(0.0, ord_inc + taxable_ss - deduction)

    # Compute ordinary income tax using progressive brackets
    tax_ordinary = 0.0
    prev_limit = 0.0
    for rate, limit in brackets:
        if taxable_ordinary > limit:
            tax_ordinary += (limit - prev_limit) * rate
            prev_limit = limit
        else:
            tax_ordinary += (taxable_ordinary - prev_limit) * rate
            break

    # 3. Enhanced LTCG Logic: The 0% Bracket check
    # MFJ 0% LTCG limit is roughly $94k taxable income.
    # This checks if there is 'room' under that limit after ordinary income.
    ltcg_0_limit = 94050 * (1 + inflation) ** exponential
    taxable_ltcg = max(0.0, lt_cap_gains -
                       max(0.0, ltcg_0_limit - taxable_ordinary))
    tax_ltcg = taxable_ltcg * 0.15

    # State tax approximation applied to taxable ordinary + LTCG
    state_taxable = taxable_ordinary + lt_cap_gains
    state_tax = state_taxable * state_tax_rate

    return tax_ordinary + tax_ltcg + state_tax


UNIFORM_LIFETIME_TABLE = {
    73: 26.5,
    74: 25.5,
    75: 24.6,
    76: 23.7,
    77: 22.9,
    78: 22.0,
    79: 21.1,
    80: 20.2,
    81: 19.4,
    82: 18.5,
    83: 17.7,
    84: 16.8,
    85: 16.0,
    86: 15.2,
    87: 14.4,
    88: 13.7,
    89: 12.9,
    90: 12.2,
    91: 11.5,
    92: 10.8,
    93: 10.1,
    94: 9.5,
    95: 8.9,
    96: 8.4,
    97: 7.8,
    98: 7.3,
    99: 6.8,
    100: 6.4
    # … continue as needed …
}


def calculate_rmd(balance, age):
    divisor = UNIFORM_LIFETIME_TABLE.get(age)
    if divisor is None:
        return 0.0
    return balance / divisor

# --- SIMULATION ENGINE ---


def run_simulation():
    history = []
    b_401k, b_roth, b_broker = init_401k, init_roth, init_brokerage

    for age in range(start_age, end_age + 1):
        spend = annual_spend_base * (1 + inflation) ** (age - start_age)
        ss = ss_benefit * (1 + ss_cola) ** (age -
                                            ss_start_age) if age >= ss_start_age else 0.0

        # RMD based on IRS Uniform Lifetime Table
        rmd = calculate_rmd(b_401k, age)
        long_term_capital_gain = b_broker * 0.02
        # Recompute tax parameters for this year (inflation-adjusted)
        brackets, deduction, irmaa_cap = get_status_params(
            status, age - start_age)

        # Plan Roth conversions to use low tax brackets (fill 12% bracket) and avoid IRMAA
        taxable_ss = 0.85 * ss
        taxable_ordinary_before_conv = max(0.0, rmd + taxable_ss - deduction)

        # Find the top of the 12% bracket (if present)
        twelve_pct_limit = None
        for rate, limit in brackets:
            if abs(rate - 0.12) < 1e-9:
                twelve_pct_limit = limit
                break
        if twelve_pct_limit is None:
            twelve_pct_limit = brackets[1][1] if len(
                brackets) > 1 else brackets[-1][1]

        room_in_12 = max(0.0, twelve_pct_limit - taxable_ordinary_before_conv)
        room_irmaa = max(0.0, irmaa_cap -
                         (rmd + long_term_capital_gain + taxable_ss))

        conv_candidate = max(0.0, min(b_401k - rmd, room_in_12))
        conv_amt = min(conv_candidate, room_irmaa)

        tax_paid = calculate_taxes(
            rmd + conv_amt, long_term_capital_gain, ss, status, age - start_age)

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
        b_broker = max(0, (b_broker - w_broker +
                       long_term_capital_gain) * (1 + growth))
        b_roth = max(0, (b_roth + conv_amt - w_roth) * (1 + growth))

    return pd.DataFrame(history)


# --- UI OUTPUT ---
df = run_simulation()

# Summary Metrics
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Final Net Worth", f"${df['Net Worth'].iloc[-1]:,.0F}")
with c2:
    st.metric("Total Tax Paid", f"${df['Tax Paid'].sum():,.0F}")
with c3:
    st.metric("Ending Roth Bal", f"${df['Roth Bal'].iloc[-1]:,.0F}")

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
    cash_flow_df["Total Withdrawals"] = df["401k Withdrawal"] + \
        df["Brokerage Withdrawal"] + df["Roth Withdrawal"]
    st.bar_chart(cash_flow_df.set_index("Age"))
    st.caption(
        "Shows how Spending is met by Social Security and Portfolio Withdrawals.")

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
# with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
#    df.to_excel(writer, index=False, sheet_name='Retirement Plan')

with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    df.to_excel(writer, sheet_name="Optimized Plan", index=False)
    workbook = writer.book
    worksheet = writer.sheets["Optimized Plan"]

    # Formats
    money_fmt = workbook.add_format({"num_format": "#,##0", "align": "right"})
    hdr_fmt = workbook.add_format(
        {"bold": True, "bg_color": "#CFE2F3", "border": 1})

    # Apply formatting
    worksheet.set_column("A:A", 8)  # Age
    worksheet.set_column("B:L", 18, money_fmt)  # All money columns
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, hdr_fmt)

st.download_button("📥 Download Plan as XLSX",
                   buffer.getvalue(), "RetirementPlan.xlsx")

