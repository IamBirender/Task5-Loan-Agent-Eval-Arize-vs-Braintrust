-- Loan sample schema for Aurora PostgreSQL (read-only for agents).
-- Seeded from data/loans.duckdb by scripts/seed_loan_data.py.

CREATE SCHEMA IF NOT EXISTS loan;
SET search_path TO loan, public;

CREATE TABLE IF NOT EXISTS loan.loan_static (
    loan_id TEXT PRIMARY KEY,
    channel TEXT,
    state TEXT,
    purpose TEXT,
    property_type TEXT,
    num_units INTEGER,
    num_borrowers INTEGER,
    orig_date TEXT,
    orig_term INTEGER,
    orig_rate DOUBLE PRECISION,
    orig_upb DOUBLE PRECISION,
    ltv INTEGER,
    cltv INTEGER,
    dti INTEGER,
    borrower_score INTEGER,
    co_borrower_score INTEGER,
    min_score INTEGER,
    mi_pct DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS loan.loan_monthly (
    loan_identifier TEXT NOT NULL,
    period_ym TEXT,
    monthly_reporting_period TEXT,
    current_loan_delinquency_status TEXT,
    current_actual_upb DOUBLE PRECISION,
    current_interest_rate DOUBLE PRECISION,
    modification_flag TEXT,
    zero_balance_code TEXT,
    zero_balance_effective_date TEXT,
    loan_payment_history TEXT,
    borrower_assistance_plan TEXT,
    alternative_delinquency_resolution TEXT,
    foreclosure_date TEXT,
    disposition_date TEXT,
    upb_at_the_time_of_removal DOUBLE PRECISION,
    foreclosure_costs DOUBLE PRECISION,
    property_preservation_and_repair_costs DOUBLE PRECISION,
    asset_recovery_costs DOUBLE PRECISION,
    miscellaneous_holding_expenses_and_credits DOUBLE PRECISION,
    associated_taxes_for_holding_property DOUBLE PRECISION,
    net_sales_proceeds DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS loan.loan_features (
    loan_identifier TEXT PRIMARY KEY,
    property_state TEXT,
    original_upb DOUBLE PRECISION,
    original_interest_rate DOUBLE PRECISION,
    ltv INTEGER,
    cltv INTEGER,
    dti INTEGER,
    borrower_credit_score INTEGER,
    co_borrower_credit_score INTEGER,
    borrower_minimum_credit_score INTEGER,
    has_subordinate_financing BOOLEAN,
    monthly_records INTEGER,
    first_period TEXT,
    last_period TEXT,
    peak_months_delinquent INTEGER,
    peak_first_period TEXT,
    delinquent_months INTEGER,
    first_90_plus_period TEXT,
    first_180_plus_period TEXT,
    first_modified_period TEXT,
    outcome TEXT,
    zero_balance_code TEXT,
    zero_balance_effective_date TEXT,
    upb_at_removal DOUBLE PRECISION,
    disposition_costs DOUBLE PRECISION,
    net_sales_proceeds DOUBLE PRECISION,
    indicative_net_loss DOUBLE PRECISION,
    indicative_severity_pct DOUBLE PRECISION,
    max_upb_seen DOUBLE PRECISION,
    last_upb DOUBLE PRECISION,
    last_delinquency_status TEXT,
    last_interest_rate DOUBLE PRECISION
);

CREATE OR REPLACE VIEW loan.default_risk_screen AS
SELECT loan_id, state, purpose, orig_upb, ltv, cltv, dti, min_score,
       CAST(ltv >= 80 AS INTEGER) AS flag_ltv_80,
       CAST(dti >= 43 AS INTEGER) AS flag_dti_43,
       CAST(min_score < 700 AS INTEGER) AS flag_min_score_700,
       CAST(cltv > ltv AS INTEGER) AS flag_cltv_above_ltv,
       CAST(ltv >= 80 AS INTEGER) + CAST(dti >= 43 AS INTEGER)
         + CAST(min_score < 700 AS INTEGER) + CAST(cltv > ltv AS INTEGER) AS flag_count
FROM loan.loan_static;
