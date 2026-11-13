"""DuckDB warehouse: raw -> staging (typed, validated, quarantined) -> marts."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .quality import Check, run_checks

MODEL_NAMES = {"B": "Chevrolet Bolt EV/EUV", "K": "Hyundai Kona Electric", "L": "Nissan Leaf",
               "3": "Tesla Model 3", "Y": "Tesla Model Y", "I": "VW ID.4"}


def build(raw: Path, db_path: Path, cells: pd.DataFrame, min_incident_year: int, age_origin_month: int):
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    # ---------------- raw (as delivered, all text) ----------------
    con.execute(f"""CREATE TABLE raw_complaints AS SELECT * FROM read_csv('{raw / "nhtsa_complaints_compact.csv"}',
                    all_varchar=true, header=true)""")
    con.execute(f"CREATE TABLE raw_recalls AS SELECT * FROM read_csv('{raw / 'nhtsa_recalls.csv'}', all_varchar=true, header=true)")
    con.execute(f"CREATE TABLE raw_recall_units AS SELECT * FROM read_csv('{raw / 'nhtsa_battery_recall_units.csv'}', header=true)")
    con.register("cells_df", cells)
    con.execute("CREATE TABLE raw_cells AS SELECT * FROM cells_df")
    con.execute("CREATE TABLE dim_model AS SELECT * FROM (VALUES " +
                ",".join(f"('{k}','{v}')" for k, v in MODEL_NAMES.items()) + ") t(model, model_name)")
    # ---------------- staging ----------------
    con.execute(f"""
    CREATE TABLE stg_complaints AS
    WITH t AS (
      SELECT model, 2000 + CAST(my AS INT) AS my, CAST(odi AS BIGINT) AS odi,
             TRY_STRPTIME(incident_ym || '01', '%Y%m%d')::DATE AS incident_raw,
             TRY_STRPTIME(filed_ym || '01', '%Y%m%d')::DATE AS filed,
             lpad(flags, 4, '0') AS flags, CAST(injuries AS INT) AS injuries
      FROM raw_complaints)
    SELECT model, my, odi, filed, injuries, flags,
           CAST(substr(flags,1,1) AS INT) AS comp_batt, CAST(substr(flags,2,1) AS INT) AS text_batt,
           CAST(substr(flags,3,1) AS INT) AS fire, CAST(substr(flags,4,1) AS INT) AS crash,
           greatest(CAST(substr(flags,1,1) AS INT), CAST(substr(flags,2,1) AS INT)) AS batt_broad,
           CASE WHEN incident_raw IS NULL OR year(incident_raw) < {min_incident_year} OR incident_raw > filed
                THEN NULL ELSE incident_raw END AS incident,
           incident_raw
    FROM t""")
    con.execute("""CREATE TABLE quarantine_incident_dates AS
                   SELECT odi, my, incident_raw, filed, 'invalid or after filing date' AS reason
                   FROM stg_complaints WHERE incident IS NULL""")
    con.execute(f"""ALTER TABLE stg_complaints ADD COLUMN age_months INT;
                    UPDATE stg_complaints SET age_months =
                      CASE WHEN incident IS NULL THEN NULL
                           ELSE greatest((year(incident) - (my - 1)) * 12 + month(incident) - {age_origin_month}, -1) END;
                    UPDATE stg_complaints SET age_months = NULL WHERE age_months < 0;""")
    con.execute("""CREATE TABLE stg_recalls AS
                   SELECT canon AS model, CAST(my AS INT) AS my, campaign,
                          STRPTIME(report_date, '%d/%m/%Y')::DATE AS report_date, component,
                          CAST(batt_text AS INT) AS batt_text, summary FROM raw_recalls""")
    # ---------------- quality gates ----------------
    checks = [
        Check("complaints_unique_odi_my", "SELECT count(*) - count(DISTINCT (odi, my)) FROM stg_complaints"),
        Check("complaints_flags_domain", "SELECT count(*) FROM stg_complaints WHERE NOT regexp_full_match(flags, '[01]{4}')"),
        Check("complaints_model_known", "SELECT count(*) FROM stg_complaints WHERE model NOT IN (SELECT model FROM dim_model)"),
        Check("complaints_filed_parsed", "SELECT count(*) FROM stg_complaints WHERE filed IS NULL"),
        Check("complaints_my_range", "SELECT count(*) FROM stg_complaints WHERE my NOT BETWEEN 2011 AND 2023"),
        Check("recalls_report_date_parsed", "SELECT count(*) FROM stg_recalls WHERE report_date IS NULL"),
        Check("recall_units_positive", "SELECT count(*) FROM raw_recall_units WHERE units_affected <= 0"),
        Check("recall_units_campaigns_exist",
              "SELECT count(*) FROM raw_recall_units u WHERE campaign NOT IN (SELECT campaign FROM stg_recalls)"),
        Check("cells_unique_barcode", "SELECT count(*) - count(DISTINCT barcode) FROM raw_cells"),
        Check("cells_count_124", "SELECT abs(count(*) - 124) FROM raw_cells"),
        Check("cells_positive_life", "SELECT count(*) FROM raw_cells WHERE cycle_life <= 0"),
        Check("incident_dates_quarantined", "SELECT count(*) FROM quarantine_incident_dates", severity="warn"),
    ]
    results = run_checks(con, checks)
    # ---------------- marts ----------------
    con.execute("""CREATE TABLE mart_battery_monthly_incident AS
                   SELECT model, my, date_trunc('month', incident) AS month,
                          sum(comp_batt) AS batt, sum(batt_broad) AS batt_broad, sum(fire * batt_broad) AS batt_fire,
                          count(*) AS complaints
                   FROM stg_complaints WHERE incident IS NOT NULL GROUP BY ALL""")
    con.execute("""CREATE TABLE mart_battery_monthly_filed AS
                   SELECT model, date_trunc('month', filed) AS month, count(*) AS complaints,
                          sum(comp_batt) AS batt, sum(batt_broad) AS batt_broad
                   FROM stg_complaints GROUP BY ALL""")
    con.execute("""CREATE TABLE mart_nameplate_summary AS
                   SELECT d.model_name, count(*) AS complaints, sum(comp_batt) AS batt, sum(batt_broad) AS batt_broad,
                          sum(comp_batt * fire) AS batt_fire, min(my) AS my_min, max(my) AS my_max,
                          round(100.0 * sum(comp_batt) / count(*), 1) AS batt_share_pct
                   FROM stg_complaints c JOIN dim_model d USING (model) GROUP BY 1 ORDER BY complaints DESC""")
    return con, results
