import pandas as pd
from simulation import simulate_plan


def test_simulate_basic():
    # Basic smoke test: two-year simulation with simple inputs
    start_age = 65
    end_age = 66
    init_401k = 100_000
    init_roth = 50_000
    init_taxable = 0
    growth401k = 0.05
    growthRoth = 0.03
    growthTaxable = 0.04
    annual_spend_base = 50_000
    inflation = 0.02
    ss_start_age = 70
    ss_benefit = 0
    ss_cola = 0.03
    state_tax_rate = 0.02
    ltcg_real_rate = 0.0
    status = 'Single'

    # Base-year bracket tops matching TAX_DEFAULTS Single
    bracket_limits = (12400, 50400, 105700, 255225)
    std_val = 16100 + 2050
    irmaa_val = 109000
    ss_base_val = 25000
    ss_upper_val = 34000
    ltcg_0_val = 48350
    ltcg_15_val = 459750
    basis_pct = 0.0

    df = simulate_plan(start_age, end_age, init_401k, init_roth, init_taxable,
                       growth401k, growthRoth, growthTaxable, annual_spend_base, inflation,
                       ss_start_age, ss_benefit, ss_cola, state_tax_rate, ltcg_real_rate,
                       status, bracket_limits, std_val, irmaa_val,
                       ss_base_val, ss_upper_val, ltcg_0_val, ltcg_15_val, basis_pct)

    assert isinstance(df, pd.DataFrame)
    assert list(df['Age']) == [65, 66]
    # No taxable account started -> basis remains zero
    assert all(df['Basis Remaining'] == 0)
    # Convergence should be achieved for small case
    assert df['Converged'].all()
