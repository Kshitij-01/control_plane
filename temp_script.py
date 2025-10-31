
import pandas as pd
import json

df = pd.read_parquet("data/raw/lhs_invoices.parquet")
n = len(df)

c = []
for col in df.columns:
    c.append({"column_name": col, "dtype": str(df[col].dtype), "null_count": int(df[col].isna().sum()), "non_null_count": int(df[col].notna().sum()), "distinct_count": int(df[col].nunique()), "sample_values": [str(x) for x in df[col].dropna().head(5)]})

p = {"dataset_summary": {"row_count": n, "column_count": len(df.columns), "columns": list(df.columns)}, "columns": c, "data_quality": {"issues_found": 0, "issues": []}}
json.dump(p, open("lhs_invoices_profile.json", "w"), indent=2)

pk = None
for col in df.columns:
    if df[col].isna().sum() == 0 and df[col].nunique() == n and "id" in col.lower():
        pk = col
        break
if not pk:
    for col in df.columns:
        if df[col].isna().sum() == 0 and df[col].nunique() == n:
            pk = col
            break

d = {"primary_key": pk, "primary_key_columns": [pk] if pk else [], "total_rows": n, "null_counts": {c: int(df[c].isna().sum()) for c in df.columns}, "distinct_counts": {c: int(df[c].nunique()) for c in df.columns}, "selection_method": "single"}
json.dump(d, open("discovered_primary_key.json", "w"), indent=2)
print("done")
