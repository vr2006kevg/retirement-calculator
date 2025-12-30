import streamlit as st
import pandas as pd
import io

# Pure simulation engine (cached & testable)
from simulation import simulate_plan

# Page configuration
st.set_page_config(page_title="Retirement Planner Pro", layout="wide")

st.title("🚀 Retirement Cashflow & Tax Simulator")

# Usage instructions and disclaimer (moved to top for visibility)
with st.expander("ℹ️ How to use & Disclaimer", expanded=False):
    st.subheader("How to use this application")
    st.markdown(
        "- **Adjust inputs in the left sidebar** to set filing status, starting balances, growth rates, spending, Social Security start age, and tax assumptions.\n"
        "- **Open the 'Edit Tax Brackets & Parameters' expander** to tune brackets, standard deduction, IRMAA thresholds, Social Security and LTCG thresholds for your filing status.\n"
        "- Use the **'Taxable account realized LTCG (%)'** slider to control the assumed annual realized LTCG from the taxable account.\n"
        "- Review the charts and the **Withdrawal Plan Details** table for year-by-year results. Use the **Download Plan as XLSX** button to export the full table.\n"
        "- Change inputs anytime to re-run the simulation — the app recalculates instantly."
    )
    st.markdown("---")
    st.subheader("Disclaimer")
    st.markdown(
        "**This tool provides estimates for educational purposes only and is *not* financial, tax, or legal advice.**\n"
        "Results are approximate: the app uses simplified tax rules and assumptions (e.g., provisional Social Security taxation, tiered LTCG approximations, and a heuristic for realized gains).\n"
        "Always consult a qualified tax or financial professional before making decisions based on these results."
    )

# Default tax parameters (base year values). These populate editable inputs in the sidebar.
TAX_DEFAULTS = {
    "Married Filing Jointly (MFJ)": {
        "brackets": [(0.10, 24800), (0.12, 100800), (0.22, 211100), (0.24, 403550)],
        "std_deduct": 32200 + 3300,
        "irmaa_tier_0": 218000,
    },
    "Head of Household (HOH)": {
        "brackets": [(0.10, 17700), (0.12, 67450), (0.22, 105700), (0.24, 201750)],
        "std_deduct": 24150 + 2050,
        "irmaa_tier_0": 109000,
    },
    "Married Filing Separately (MFS)": {
        "brackets": [(0.10, 12400), (0.12, 50400), (0.22, 105700), (0.24, 201775)],
        "std_deduct": 16100 + 1650,
        "irmaa_tier_0": 109000,
    },
    "Single": {
        "brackets": [(0.10, 12400), (0.12, 50400), (0.22, 105700), (0.24, 255225)],
        "std_deduct": 16100 + 2050,
        "irmaa_tier_0": 109000,
    },
}

# Approximate Social Security taxable thresholds (base-year values). These are editable defaults.
SS_TAX_THRESHOLDS = {
    "Single": (25000, 34000),
    "Married Filing Jointly (MFJ)": (32000, 44000),
    "Head of Household (HOH)": (25000, 34000),
    "Married Filing Separately (MFS)": (0, 0),
}

# Long-term capital gains thresholds (base-year taxable income levels for 0% and 15% breakpoints).
LTCG_THRESHOLDS = {
    "Married Filing Jointly (MFJ)": {"0": 96700, "15": 518900},
    "Single": {"0": 48350, "15": 459750},
    "Head of Household (HOH)": {"0": 64700, "15": 489925},
    "Married Filing Separately (MFS)": {"0": 48350, "15": 259400},
}


def _sanitize_status_key(s: str) -> str:
    return s.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")

# --- SIDEBAR: INPUTS ---
with st.sidebar:
    st.header("📋 Filing & Timeline")
    status = st.selectbox(
        "IRS Filing Status",
        ["Single", "Married Filing Jointly (MFJ)",
         "Married Filing Separately (MFS)", "Head of Household (HOH)"]
    )

    # Editable tax parameters for the selected filing status
    with st.expander("Edit Tax Brackets & Parameters", expanded=False):
        key_base = _sanitize_status_key(status)
        tax_brackets = TAX_DEFAULTS.get(status, TAX_DEFAULTS["Single"]) 

        st.write("Bracket tops (taxable income) — edit as needed")
        # Render bracket limit number_inputs; keep rates fixed per defaults
        bracket_limits = []
        for i, (rate, lim) in enumerate(tax_brackets["brackets"]):
            lim_key = f"{key_base}_bracket_{i}"
            val = st.number_input(f"{int(rate*100)}% bracket top", value=lim, step=1000, key=lim_key)
            # Persist the widget's value (Streamlit stores widget values automatically; use setdefault to avoid assignment-time errors)
            st.session_state.setdefault(lim_key, val)
            bracket_limits.append((rate, val))

        # Keys are namespaced per-filing-status so values don't collide
        std_key = f"{key_base}_std_deduct"
        irmaa_key = f"{key_base}_irmaa_tier_0"
        std_val = st.number_input("Standard Deduction", value=tax_brackets["std_deduct"], step=1000, key=std_key)
        irmaa_val = st.number_input("IRMAA Tier 0 Threshold", value=tax_brackets["irmaa_tier_0"], step=1000, key=irmaa_key)

        # Ensure widget values are present under the canonical keys in session_state
        # (Streamlit automatically stores widget values by `key`; use setdefault to be safe during initialization)
        st.session_state.setdefault(std_key, std_val)
        st.session_state.setdefault(irmaa_key, irmaa_val)

        # Also store compact captures for UI or later reference
        st.session_state.setdefault(f"{key_base}_brackets_captured", bracket_limits)
        st.session_state.setdefault(f"{key_base}_std_captured", std_val)
        st.session_state.setdefault(f"{key_base}_irmaa_captured", irmaa_val)

        # --- Editable Social Security & LTCG thresholds (base-year values) ---
        ss_defaults = SS_TAX_THRESHOLDS.get(status, SS_TAX_THRESHOLDS["Single"])
        ss_base_key = f"{key_base}_ss_base"
        ss_upper_key = f"{key_base}_ss_upper"
        ss_base_val = st.number_input("SS Tax Threshold — lower (base-year)", value=ss_defaults[0], step=1000, key=ss_base_key)
        ss_upper_val = st.number_input("SS Tax Threshold — upper (base-year)", value=ss_defaults[1], step=1000, key=ss_upper_key)
        st.session_state.setdefault(ss_base_key, ss_base_val)
        st.session_state.setdefault(ss_upper_key, ss_upper_val)
        st.session_state.setdefault(f"{key_base}_ss_captured", (ss_base_val, ss_upper_val))

        ltcg_defaults = LTCG_THRESHOLDS.get(status, LTCG_THRESHOLDS["Single"])
        ltcg_0_key = f"{key_base}_ltcg_0"
        ltcg_15_key = f"{key_base}_ltcg_15"
        ltcg_0_val = st.number_input("LTCG 0% Threshold (base-year)", value=ltcg_defaults["0"], step=1000, key=ltcg_0_key)
        ltcg_15_val = st.number_input("LTCG 15% Threshold (base-year)", value=ltcg_defaults["15"], step=1000, key=ltcg_15_key)
        st.session_state.setdefault(ltcg_0_key, ltcg_0_val)
        st.session_state.setdefault(ltcg_15_key, ltcg_15_val)
        st.session_state.setdefault(f"{key_base}_ltcg_captured", (ltcg_0_val, ltcg_15_val))

        def reset_defaults():
            # Restore base defaults for this filing status
            for i, (rate, lim) in enumerate(tax_brackets["brackets"]):
                st.session_state[f"{key_base}_bracket_{i}"] = lim
            st.session_state[std_key] = tax_brackets["std_deduct"]
            st.session_state[irmaa_key] = tax_brackets["irmaa_tier_0"]
            st.session_state[ss_base_key] = ss_defaults[0]
            st.session_state[ss_upper_key] = ss_defaults[1]
            st.session_state[ltcg_0_key] = ltcg_defaults["0"]
            st.session_state[ltcg_15_key] = ltcg_defaults["15"]

        st.button("Reset tax defaults for this status", on_click=reset_defaults)

    start_age = st.number_input("Retirement Age", value=65)
    end_age = st.number_input("Plan Until Age", value=95)

    st.header("💰 Starting Balances")
    init_401k = st.number_input(
        "401k Balance ($)", value=1_000_000, step=10000)
    growth401k = st.slider("401k Growth Rate (%)", 0.0, 15.0, 5.0) / 100

    init_roth = st.number_input("Roth Balance ($)", value=500_000, step=10000)
    growthRoth = st.slider("Roth Growth Rate (%)", 0.0, 15.0, 5.0) / 100

    init_taxable_acct = st.number_input(
        "Taxable account Balance ($)", value=500_000, step=10000)
    growthTaxable = st.slider("Taxable account Growth Rate (%)", 0.0, 15.0, 5.0) / 100
    # Taxable account cost basis fraction (used to compute realized LTCG from withdrawals)
    basis_pct = st.slider("Taxable account initial cost basis (%)", 0.0, 100.0, 80.0) / 100

    # Active mutual funds or ETFs may generate unavoidable LTCG each year due to turnover or distributions.
    # ETF investors can often keep this near zero by choosing tax-efficient funds.
    
    forced_capital_gain = st.slider("Annual forced capital gain realization (%)", 
        0.0, 10.0, 1.0, 
        help=(
        "Represents unavoidable long-term capital gains generated internally "
        "by the taxable account each year (e.g., fund turnover or capital gain "
        "distributions), even without withdrawals. "
        "Use near 0% for tax-efficient ETFs; higher for active funds."
        )                                    
    ) / 100
    
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
def get_status_params(status, years_ahead):
    """Return (brackets, std_deduct, irmaa_tier_0) using editable sidebar inputs when present.

    `exponential` is used to inflation-adjust the base-year values provided by the user.
    """
    key_base = _sanitize_status_key(status)

    # Build brackets from session_state if available; otherwise fall back to TAX_DEFAULTS
    tax_brackets = TAX_DEFAULTS.get(status, TAX_DEFAULTS["Single"]) 
    brackets = []
    for i, (rate, default_limit) in enumerate(tax_brackets["brackets"]):
        lim_key = f"{key_base}_bracket_{i}"
        base_limit = st.session_state.get(lim_key, default_limit)
        adj_limit = base_limit * (1 + inflation) ** years_ahead
        brackets.append((rate, adj_limit))

    std_key = f"{key_base}_std_deduct"
    irmaa_key = f"{key_base}_irmaa_tier_0"
    base_std = st.session_state.get(std_key, tax_brackets["std_deduct"])
    base_irmaa = st.session_state.get(irmaa_key, tax_brackets["irmaa_tier_0"])

    std_deduct = base_std * (1 + inflation) ** years_ahead
    irmaa_tier_0 = base_irmaa * (1 + ss_cola) ** years_ahead

    return brackets, std_deduct, irmaa_tier_0



# --- SIMULATION ENGINE ---
def run_simulation():
    # Capture editable parameters and call the pure, cached simulation function
    key_base = _sanitize_status_key(status)
    captured = st.session_state.get(f"{key_base}_brackets_captured")
    if captured:
        bracket_limits = tuple(lim for _, lim in captured)
    else:
        bracket_limits = tuple(lim for _, lim in TAX_DEFAULTS.get(status, TAX_DEFAULTS["Single"])['brackets'])

    std_val = st.session_state.get(f"{key_base}_std_deduct", TAX_DEFAULTS.get(status, TAX_DEFAULTS['Single'])['std_deduct'])
    irmaa_val = st.session_state.get(f"{key_base}_irmaa_tier_0", TAX_DEFAULTS.get(status, TAX_DEFAULTS['Single'])['irmaa_tier_0'])
    ss_base_val = st.session_state.get(f"{key_base}_ss_base", SS_TAX_THRESHOLDS.get(status, SS_TAX_THRESHOLDS['Single'])[0])
    ss_upper_val = st.session_state.get(f"{key_base}_ss_upper", SS_TAX_THRESHOLDS.get(status, SS_TAX_THRESHOLDS['Single'])[1])
    ltcg_0_val = st.session_state.get(f"{key_base}_ltcg_0", LTCG_THRESHOLDS.get(status, LTCG_THRESHOLDS['Single'])['0'])
    ltcg_15_val = st.session_state.get(f"{key_base}_ltcg_15", LTCG_THRESHOLDS.get(status, LTCG_THRESHOLDS['Single'])['15'])

    df = simulate_plan(
        start_age, end_age, init_401k, init_roth, init_taxable_acct,
        growth401k, growthRoth, growthTaxable, annual_spend_base, inflation,
        ss_start_age, ss_benefit, ss_cola, state_tax_rate, forced_capital_gain,
        status, bracket_limits, std_val, irmaa_val,
        ss_base_val, ss_upper_val, ltcg_0_val, ltcg_15_val, basis_pct,
    )
    return df

# --- UI OUTPUT ---
df = run_simulation()

tab_summary, tab_cashflow, tab_details = st.tabs(["📈 Summary", "💵 Cashflow", "📋 Details"])

with tab_summary:
    st.subheader("Key Metrics")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Final Net Worth", f"${df['Net Worth'].iloc[-1]:,.0F}")
    with c2:
        st.metric("Total Tax Paid", f"${df['Tax Paid'].sum():,.0F}")
    with c3:
        st.metric("Ending Roth Bal", f"${df['Roth Bal'].iloc[-1]:,.0F}")

    st.markdown("---")
    st.subheader("Portfolio Growth & Composition")
    st.area_chart(df.set_index("Age")[["401k Bal", "Taxable account Bal", "Roth Bal"]])
    st.caption("Visualizes the depletion of different account types over time.")

with tab_cashflow:
    st.subheader("Annual Income vs Spending")
    cash_flow_df = df[["Age", "Spending", "Social Security"]].copy()
    cash_flow_df["Total Withdrawals"] = df["401k Withdrawal"] + \
        df["Taxable account Withdrawal"] + df["Roth Withdrawal"]
    st.bar_chart(cash_flow_df.set_index("Age"))
    st.caption("Shows how Spending is met by Social Security and Portfolio Withdrawals.")

with tab_details:
    st.subheader("Withdrawal Plan Details")
    st.markdown("**Stage Legend:**  ")
    st.markdown("- **Golden Stage**: Early years with healthy assets; minimal withdrawals required.  \n- **Conversion Stage**: Active Roth conversions are happening.  \n- **401k Withdrawal Stage**: Largest withdrawals are from the 401(k).  \n- **Taxable Withdrawal Stage**: Largest withdrawals are from the taxable account.  \n- **Roth Withdrawal Stage**: Largest withdrawals are from the Roth account.  \n- **SS Only**: Social Security alone covers spending.  \n- **Depleted**: Portfolio is exhausted.")
    
    # Compact table styling
    st.markdown(
        """
        <style>
        [data-testid="stDataFrame"] table { font-size: 12px; border-collapse: collapse; }
        [data-testid="stDataFrame"] th, [data-testid="stDataFrame"] td { padding: 6px 8px; }
        [data-testid="stDataFrame"] tbody tr td { white-space: nowrap; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    # Column header colors
    color_map = {
        "Spending": "red", "Tax Paid": "red", "Social Security": "blue",
        "401k Withdrawal": "blue", "Taxable account Withdrawal": "blue", "Roth Withdrawal": "blue",
        "Roth Conversion": "blue", "401k Bal": "green", "Taxable account Bal": "green",
        "Roth Bal": "green", "Net Worth": "green",
    }
    styles = [
        {"selector": f"th.col_heading.level0.col{i}", "props": [("color", color_map.get(col)), ("font-weight", "bold")]}
        for i, col in enumerate(df.columns) if col in color_map
    ]

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    formatters = {col: "{:,.0f}" for col in numeric_cols}
    styled = df.style.format(formatters).set_table_styles(styles).set_table_attributes('class="withdrawal-plan-table"')
    html = styled.to_html()
    st.markdown(
        '<style>.withdrawal-plan-table tbody tr:hover{background-color:#fff2cc; cursor:pointer}</style>' + html,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    
    # Excel Download
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Withdrawal Plan", index=False)
        workbook = writer.book
        worksheet = writer.sheets["Withdrawal Plan"]
        money_fmt = workbook.add_format({"num_format": "#,##0", "align": "right"})
        hdr_fmt = workbook.add_format({"bold": True, "bg_color": "#CFE2F3", "border": 1})
        worksheet.set_column("A:A", 24)
        worksheet.set_column("B:B", 8)
        worksheet.set_column("C:L", 18, money_fmt)
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, hdr_fmt)

    st.download_button("📥 Download Plan as XLSX", buffer.getvalue(), "RetirementPlan.xlsx")

    with st.expander("Download Notes"):
        st.markdown("- The XLSX file contains the full yearly simulation table including balances, withdrawals, conversions, and taxes.")
        st.markdown("- Values are presented in rounded whole dollars; use the dataframe in the app for interactive inspection.")
        st.markdown("- To update the exported plan, change assumptions in the sidebar (growth, spending, taxes) and re-download.")

with st.expander("📚 References & Source Links"):
    st.markdown("- [Federal income tax rates and brackets](https://www.irs.gov/filing/federal-income-tax-rates-and-brackets)")
    st.markdown("- [IRS — Standard Deduction (overview)](https://apps.irs.gov/app/vita/content/00/00_13_005.jsp)")
    st.markdown("- [IRS Publication 590-B — Required Minimum Distributions (RMDs)](https://www.irs.gov/publications/p590b)")
    st.markdown("- [IRS — Capital Gains and Losses (long-term capital gains guidance)](https://www.irs.gov/taxtopics/tc409)")
    st.markdown("- [IRS reminds taxpayers their Social Security benefits may be taxable](https://www.irs.gov/newsroom/irs-reminds-taxpayers-their-social-security-benefits-may-be-taxable)")
    st.markdown("- [Social Security Administration — Medicare costs & IRMAA information](https://www.ssa.gov/benefits/medicare/medicare-premiums.html)")
