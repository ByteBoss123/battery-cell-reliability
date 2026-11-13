"""Generate tableau/battery_reliability.twb: 5 worksheets + 1 dashboard on the CSVs in outputs/tables/.

The text connections point at ../outputs/tables relative to this folder. If Tableau cannot find
the files when the workbook is opened, point the data source at outputs/tables/ once.
"""
from pathlib import Path
from xml.sax.saxutils import quoteattr as q

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "outputs" / "tables"
DTYPE = {"int64": ("integer", "measure", "quantitative"), "float64": ("real", "measure", "quantitative"),
         "object": ("string", "dimension", "nominal"), "str": ("string", "dimension", "nominal"),
         "bool": ("boolean", "dimension", "nominal")}
DIMS = {"treated", "seq", "alert", "rule1", "rule2", "rule4", "ewma_alarm", "model", "lot", "metric", "barcode", "policy", "split", "period"}
DATES = {"month"}


def datasource(name, csv, calcs=()):
    df = pd.read_csv(TABLES / csv, nrows=200)
    rel_cols, meta_cols = [], []
    for i, c in enumerate(df.columns):
        if c in DATES:
            dt, role, typ = "date", "dimension", "ordinal"
        else:
            dt, role, typ = DTYPE.get(str(df[c].dtype), ("string", "dimension", "nominal"))
            if c in DIMS:
                role, typ = "dimension", "nominal" if dt == "string" else "ordinal"
        rel_cols.append(f"<column datatype='{dt}' name={q(c)} ordinal='{i}' />")
        meta_cols.append(f"<column datatype='{dt}' name={q('[' + c + ']')} role='{role}' type='{typ}' />")
    calc_xml = "".join(
        f"<column caption={q(cap)} datatype='{dt}' name={q(nm)} role='{role}' type='{typ}'><calculation class='tableau' formula={q(f)} /></column>"
        for nm, cap, dt, role, typ, f in calcs)
    table = "[" + csv.replace(".", "#") + "]"
    return (f"<datasource caption={q(name)} inline='true' name='federated.{name.lower().replace(' ', '_')}' version='18.1'>"
            f"<connection class='federated'><named-connections>"
            f"<named-connection caption={q(csv)} name='textscan.{csv.split('.')[0]}'>"
            f"<connection class='textscan' directory='../outputs/tables' filename={q(csv)} password='' server='' /></named-connection>"
            f"</named-connections><relation connection='textscan.{csv.split('.')[0]}' name={q(csv)} table={q(table)} type='table'>"
            f"<columns character-set='UTF-8' header='yes' locale='en_US' separator=','>{''.join(rel_cols)}</columns></relation></connection>"
            f"{''.join(meta_cols)}{calc_xml}</datasource>")


def ci(col, deriv, typ, short):
    pivot = {"nominal": "nk", "ordinal": "ok", "quantitative": "qk"}[typ]
    return f"[{short}:{col}:{pivot}]", f"<column-instance column='[{col}]' derivation='{deriv}' name='[{short}:{col}:{pivot}]' pivot='key' type='{typ}' />"


def worksheet(name, ds, cols, rows, mark, color=None, lod=None, filt=None):
    """cols/rows: lists of (column, derivation, type, short)."""
    used = {}
    for spec in [*cols, *rows, *([color] if color else []), *([lod] if lod else [])]:
        ref, xml = ci(*spec)
        used[ref] = xml
    shelf = lambda specs: " / ".join(f"[{ds}].{ci(*s)[0]}" for s in specs)  # noqa: E731
    enc = ""
    if color or lod:
        enc = "<encodings>" + (f"<color column='[{ds}].{ci(*color)[0]}' />" if color else "") + \
              (f"<lod column='[{ds}].{ci(*lod)[0]}' />" if lod else "") + "</encodings>"
    filt_xml = ""
    if filt:
        col, val = filt
        filt_xml = (f"<filter class='categorical' column='[{ds}].[none:{col}:nk]'><groupfilter function='member' level='[none:{col}:nk]' "
                    f"member={q(val)} user:ui-domain='database' user:ui-enumeration='inclusive' user:ui-marker='enumerate' /></filter>")
        used.setdefault(f"[none:{col}:nk]", ci(col, "None", "nominal", "none")[1])
    return (f"<worksheet name={q(name)}><table><view><datasources><datasource name='{ds}' /></datasources>"
            f"<datasource-dependencies datasource='{ds}'>{''.join(used.values())}</datasource-dependencies>{filt_xml}"
            f"<aggregation value='true' /></view><style /><panes><pane selection-relaxation-option='selection-relaxation-allow'>"
            f"<view><breakdown value='auto' /></view><mark class='{mark}' />{enc}</pane></panes>"
            f"<rows>{shelf(rows)}</rows><cols>{shelf(cols)}</cols></table><simple-id uuid='{{{uid(name)}}}' /></worksheet>")


def uid(s):
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, s)).upper()


C1_BAND = ("[Calculation_20261113150000_001]", "C1 band", "string", "dimension", "nominal",
           "IF [C1] <= 4.5 THEN 'C1 <= 4.5C' ELSEIF [C1] <= 5.5 THEN '4.5-5.5C' ELSE '> 5.5C' END")
DS = [("Cells", "cells.csv", [C1_BAND]), ("SPC", "spc_cells.csv", []),
      ("Corrective Action", "corrective_action_panel.csv", []), ("P Chart", "pchart_monthly.csv", [])]
ds = {n: f"federated.{n.lower().replace(' ', '_')}" for n, _, _ in DS}

sheets = [
    worksheet("Cycle Life by Test Batch", ds["Cells"], [("lot", "None", "nominal", "none")], [("cycle_life", "Avg", "quantitative", "avg")],
              "Circle", color=("lot", "None", "nominal", "none"), lod=("barcode", "None", "nominal", "none")),
    worksheet("DOE C1 x Q1", ds["Cells"], [("Q1", "Avg", "quantitative", "avg")], [("cycle_life", "Avg", "quantitative", "avg")], "Circle",
              color=("Calculation_20261113150000_001", "None", "nominal", "none"), lod=("barcode", "None", "nominal", "none")),
    worksheet("SPC Initial Capacity", ds["SPC"], [("seq", "None", "ordinal", "none")], [("value", "Avg", "quantitative", "avg")], "Circle",
              color=("ewma_alarm", "None", "ordinal", "none"), filt=("metric", "q2")),
    worksheet("Corrective Action", ds["Corrective Action"], [("month", "Month-Trunc", "quantitative", "tmn")],
              [("n", "Sum", "quantitative", "sum")], "Line", color=("treated", "None", "ordinal", "none")),
    worksheet("Battery Share P Chart", ds["P Chart"], [("month", "Month-Trunc", "quantitative", "tmn")],
              [("model", "None", "nominal", "none"), ("p", "Avg", "quantitative", "avg")], "Circle", color=("alert", "Max", "quantitative", "max")),
]
names = ["Cycle Life by Test Batch", "DOE C1 x Q1", "SPC Initial Capacity", "Corrective Action", "Battery Share P Chart"]
zones = [(4, 0, 40, 600, 380, names[0]), (5, 600, 40, 600, 380, names[1]), (6, 0, 420, 600, 380, names[2]),
         (7, 600, 420, 600, 380, names[3]), (8, 0, 800, 1200, 500, names[4])]
dash = ("<dashboard name='Cell Quality and Field Reliability'><size maxheight='1300' maxwidth='1200' minheight='1300' minwidth='1200' sizing-mode='fixed' />"
        "<datasources /><zones><zone h='1300' id='2' layout-strategy-id='flow' type-v2='layout-basic' w='1200' x='0' y='0'>"
        "<zone h='40' id='3' type-v2='title' w='1200' x='0' y='0' />" +
        "".join(f"<zone h='{h}' id='{i}' name={q(n)} type-v2='visual' w='{w}' x='{x}' y='{y}' />" for i, x, y, w, h, n in zones) +
        f"</zone></zones><simple-id uuid='{{{uid('dash')}}}' /></dashboard>")
windows = "".join(f"<window class='worksheet' maximized='true' name={q(n)}><cards /><simple-id uuid='{{{uid('w' + n)}}}' /></window>" for n in names)
windows += ("<window class='dashboard' maximized='true' name='Cell Quality and Field Reliability'><viewpoints>" +
            "".join(f"<viewpoint name={q(n)} />" for n in names) + f"</viewpoints><active id='-1' /><simple-id uuid='{{{uid('wdash')}}}' /></window>")
twb = ("<?xml version='1.0' encoding='utf-8' ?>\n<!-- build 20262.26.0528.2205 -->\n"
       "<workbook original-version='18.1' source-build='2026.2.0 (20262.26.0528.2205)' source-platform='win' version='18.1' "
       "xmlns:user='http://www.tableausoftware.com/xml/user'><document-format-change-manifest><SheetIdentifierTracking /><SortTagCleanup />"
       "<WindowsPersistSimpleIdentifiers /></document-format-change-manifest><preferences />"
       f"<datasources>{''.join(datasource(n, f, c) for n, f, c in DS)}</datasources>"
       f"<worksheets>{''.join(sheets)}</worksheets><dashboards>{dash}</dashboards><windows>{windows}</windows></workbook>")
out = ROOT / "tableau" / "battery_reliability.twb"
out.write_text(twb, encoding="utf-8")
print(out)
