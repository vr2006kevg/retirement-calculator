import pandas as pd

# Small copy of the default parameter dictionaries so the simulation can be used independently
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

UNIFORM_LIFETIME_TABLE = {
    73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1,
    80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2,
    87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1,
    94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4
}

def calculate_rmd(balance, age):
    divisor = UNIFORM_LIFETIME_TABLE.get(age)
    if divisor is None:
        return 0.0
    return balance / divisor

def determine_stage(year_idx, b_401k, b_taxable, b_roth, w_401k, w_taxable, w_roth, conv_amt, ss, spend, total_initial):
    small = 1.0
    total = b_401k + b_roth + b_taxable
    if total < small:
        return "Depleted"
    if b_401k <= small and b_taxable <= small and b_roth > small:
        return "Roth-Funded"
    if conv_amt > max(1000.0, 0.005 * total_initial):
        return "Conversion Stage"
    if b_401k <= small and b_taxable > small:
        return "401k Run Out"
    if ss >= spend and w_401k == 0 and w_taxable == 0 and w_roth == 0:
        return "SS Only"
    if w_401k > max(w_taxable, w_roth):
        return "401k Withdrawal Stage"
    if w_taxable > max(w_401k, w_roth):
        return "Taxable Withdrawal Stage"
    if w_roth > max(w_401k, w_taxable):
        return "Roth Withdrawal Stage"
    if year_idx <= 5 and total >= 0.5 * total_initial:
        return "Golden Stage"
    return "Sustainable Drawdown"

def _reconstruct_brackets(status, bracket_limits):
    tax_brackets = TAX_DEFAULTS.get(status, TAX_DEFAULTS["Single"])['brackets']
    rates = [rate for rate, _ in tax_brackets]
    return [(rates[i], bracket_limits[i]) for i in range(len(rates))]

def _get_status_params(brackets, std_val, irmaa_val, inflation, ss_cola, years_ahead):
    adj_brackets = []
    for rate, base_limit in brackets:
        adj_limit = base_limit * (1 + inflation) ** years_ahead
        adj_brackets.append((rate, adj_limit))
    std_deduct = std_val * (1 + inflation) ** years_ahead
    irmaa_tier_0 = irmaa_val * (1 + ss_cola) ** years_ahead
    return adj_brackets, std_deduct, irmaa_tier_0

def simulate_plan(start_age, end_age, init_401k, init_roth, init_taxable_acct,
                  growth401k, growthRoth, growthTaxable, annual_spend_base, inflation,
                  ss_start_age, ss_benefit, ss_cola, state_tax_rate, forced_capital_gain,
                  status, bracket_limits, std_val, irmaa_val,
                  ss_base_val, ss_upper_val, ltcg_0_val, ltcg_15_val, basis_pct):
    brackets = _reconstruct_brackets(status, bracket_limits)
    total_initial = init_401k + init_roth + init_taxable_acct

    history = []

    b_401k = init_401k
    b_roth = init_roth
    b_taxable = init_taxable_acct
    basis_amount = basis_pct * init_taxable_acct

    for age in range(start_age, end_age + 1):
        year_idx = age - start_age
        spend = annual_spend_base * (1 + inflation) ** year_idx
        ss = ss_benefit * (1 + ss_cola) ** (age - ss_start_age) if age >= ss_start_age else 0.0

        rmd = calculate_rmd(b_401k, age)

        # Estimate internal turnover (unavoidable realized gains from mutual funds)
        planned_sale_amount = b_taxable * forced_capital_gain
        basis_frac = (basis_amount / b_taxable) if b_taxable > 0 else 0.0
        planned_realized_gain = planned_sale_amount * (1 - basis_frac)
        est_ltcg = planned_realized_gain

        conv_amt = 0.0
        tax_paid = 0.0
        w_401k = 0.0
        w_taxable = 0.0
        w_roth = 0.0
        realized_ltcg = est_ltcg
        converged = True

        # Iterative solver for taxes vs withdrawals
        for _it in range(8):
            adj_brackets, std_deduct, irmaa_cap = _get_status_params(brackets, std_val, irmaa_val, inflation, ss_cola, year_idx)

            # --- [FIXED] Compute Taxable SS Local (removed inflation on thresholds) ---
            def compute_taxable_ss_local(ss_amount, other_income):
                # FIX: Do NOT apply inflation to these base/upper thresholds
                base = ss_base_val 
                upper = ss_upper_val
                
                provisional = other_income + 0.5 * ss_amount
                if status == "Married Filing Separately (MFS)":
                    return 0.85 * ss_amount
                if provisional <= base:
                    return 0.0
                elif provisional <= upper:
                    return min(0.5 * ss_amount, provisional - base)
                else:
                    return min(0.85 * ss_amount, 0.5 * ss_amount + (provisional - upper))

            taxable_ss = compute_taxable_ss_local(ss, rmd + est_ltcg)
            taxable_ordinary_before_conv = max(0.0, rmd + taxable_ss - std_deduct)

            # Determine Room for Roth Conversion (targeting 12% bracket fill)
            twelve_pct_limit = None
            for rate, limit in adj_brackets:
                if abs(rate - 0.12) < 1e-9:
                    twelve_pct_limit = limit
                    break
            if twelve_pct_limit is None:
                # Fallback if 12% not found (unlikely), use 2nd bracket
                twelve_pct_limit = adj_brackets[1][1] if len(adj_brackets) > 1 else adj_brackets[-1][1]

            room_in_12 = max(0.0, twelve_pct_limit - taxable_ordinary_before_conv)
            room_irmaa = max(0.0, irmaa_cap - (rmd + est_ltcg + taxable_ss))

            conv_candidate = max(0.0, min(b_401k - rmd, room_in_12))
            conv_amt_candidate = min(conv_candidate, room_irmaa)

            # --- [FIXED] Tax Calculation Local (Added Standard Deduction Carryover) ---
            def calc_taxes_local(ord_inc, lt_cap_gains):
                taxable_ss_inner = compute_taxable_ss_local(ss, ord_inc + lt_cap_gains)
                
                # Apply Standard Deduction to Ordinary First
                gross_ordinary = ord_inc + taxable_ss_inner
                taxable_ordinary_local = max(0.0, gross_ordinary - std_deduct)
                
                # Apply Excess Deduction to LTCG
                excess_deduct = max(0.0, std_deduct - gross_ordinary)
                taxable_ltcg_local_total = max(0.0, lt_cap_gains - excess_deduct)

                tax_ordinary_local = 0.0
                prev_limit = 0.0
                for rate, limit in adj_brackets:
                    if taxable_ordinary_local > limit:
                        tax_ordinary_local += (limit - prev_limit) * rate
                        prev_limit = limit
                    else:
                        tax_ordinary_local += max(0.0, taxable_ordinary_local - prev_limit) * rate
                        prev_limit = taxable_ordinary_local
                        break
                if taxable_ordinary_local > prev_limit:
                    last_rate = adj_brackets[-1][0]
                    tax_ordinary_local += (taxable_ordinary_local - prev_limit) * last_rate

                th0 = ltcg_0_val * (1 + inflation) ** year_idx
                th15 = ltcg_15_val * (1 + inflation) ** year_idx
                
                # LTCG 0% Bucket
                if taxable_ordinary_local >= th0:
                    ltcg_0 = 0.0
                else:
                    # FIX: Use taxable_ltcg_local_total, not lt_cap_gains
                    ltcg_0 = min(taxable_ltcg_local_total, max(0.0, th0 - taxable_ordinary_local))
                
                remaining_local = max(0.0, taxable_ltcg_local_total - ltcg_0)
                
                # LTCG 15% Bucket
                if taxable_ordinary_local + ltcg_0 >= th15:
                    ltcg_15 = 0.0
                else:
                    ltcg_15 = min(remaining_local, max(0.0, th15 - (taxable_ordinary_local + ltcg_0)))
                
                ltcg_20 = max(0.0, remaining_local - ltcg_15)
                
                tax_ltcg_local = ltcg_15 * 0.15 + ltcg_20 * 0.20
                state_taxable_local = taxable_ordinary_local + ltcg_15 + ltcg_20
                state_tax_local = state_taxable_local * state_tax_rate
                return tax_ordinary_local + tax_ltcg_local + state_tax_local

            tax_paid_candidate = calc_taxes_local(rmd + conv_amt_candidate, est_ltcg)

            # Determine Withdrawals
            total_needed_candidate = spend + tax_paid_candidate - ss
            w_401k_candidate = rmd
            w_taxable_candidate = min(b_taxable, max(0.0, total_needed_candidate - w_401k_candidate))
            w_roth_candidate = max(0.0, total_needed_candidate - w_401k_candidate - w_taxable_candidate)

            # Update Realized LTCG based on actual withdrawals + turnover
            basis_frac_current = (basis_amount / b_taxable) if b_taxable > 0 else 0.0
            if w_taxable_candidate > 0:
                basis_reduced = basis_frac_current * w_taxable_candidate
                realized_from_withdrawal = max(0.0, w_taxable_candidate - basis_reduced)
            else:
                basis_reduced = 0.0
                realized_from_withdrawal = planned_realized_gain

            est_ltcg_new = realized_from_withdrawal

            # Convergence Check
            if abs(est_ltcg_new - est_ltcg) < 1e-6 and abs(conv_amt_candidate - conv_amt) < 1e-6:
                conv_amt = conv_amt_candidate
                tax_paid = tax_paid_candidate
                w_401k = w_401k_candidate
                w_taxable = w_taxable_candidate
                w_roth = w_roth_candidate
                realized_ltcg = est_ltcg_new
                break

            est_ltcg = est_ltcg_new
            conv_amt = conv_amt_candidate
            tax_paid = tax_paid_candidate
            w_401k = w_401k_candidate
            w_taxable = w_taxable_candidate
            w_roth = w_roth_candidate
            realized_ltcg = est_ltcg_new
        else:
            converged = False

        # --- Update Basis ---
        if b_taxable > 0:
            basis_frac_post = basis_amount / b_taxable
            basis_reduction = min(basis_amount, basis_frac_post * w_taxable)
            basis_amount = max(0.0, basis_amount - basis_reduction)
        if planned_sale_amount > 0 and w_taxable == 0:
            sale_basis_reduction = min(basis_amount, basis_frac * planned_sale_amount)
            basis_amount = max(0.0, basis_amount - sale_basis_reduction)

        stage_label = determine_stage(year_idx, b_401k, b_taxable, b_roth, w_401k, w_taxable, w_roth, conv_amt, ss, spend, total_initial)

        history.append({
            "Retirement Stage": stage_label,
            "Age": age,
            "Spending": spend,
            "Tax Paid": tax_paid,
            "Social Security": ss,
            "401k Withdrawal": w_401k,
            "Taxable account Withdrawal": w_taxable,
            "Roth Withdrawal": w_roth,
            "Roth Conversion": conv_amt,
            "401k Bal": b_401k,
            "Taxable account Bal": b_taxable,
            "Roth Bal": b_roth,
            "Net Worth": b_401k + b_roth + b_taxable,
            "Converged": converged,
            "Basis Remaining": basis_amount,
        })

        # --- Update Balances ---
        b_401k = max(0, (b_401k - rmd - conv_amt) * (1 + growth401k))
        
        # FIX: Do NOT add `realized_ltcg` back to balance. 
        # Realizing a gain is a tax event, not a cash deposit.
        b_taxable = max(0, (b_taxable - w_taxable) * (1 + growthTaxable))
        
        b_roth = max(0, (b_roth + conv_amt - w_roth) * (1 + growthRoth))

    return pd.DataFrame(history)
