# Retirement Planner Pro 🚀

A sophisticated retirement simulation engine built with Python and Streamlit. Unlike simple calculators, this tool handles:
- **US Tax Logic**: Progressive brackets, Standard Deduction carryover, and Capital Gains stacking.
- **Social Security**: Accurate "Tax Torpedo" calculations (Provisional Income).
- **Roth Conversions**: Simulates filling the 12% bracket with conversions.
- **Sequence of Returns**: Year-by-year cashflow simulation.

## How to Run

1. **Clone the repository**
   ```bash
   git clone https://github.com/vr2006kevg/retirement-calculator.git
   cd retirement-calculator
   
python -m pip install -r requirements.txt   
python -m streamlit run app.py
python -m pytest test_simulation.py
