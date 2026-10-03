import pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
d = pd.read_csv("/home/dell/hackathon/hackathon_data/philips_cpap_reports_2019_2021.csv", dtype=str)
f = d[d.brand_name.fillna("").str.upper().str.contains("DREAMSTATION|REMSTAR|SYSTEM ONE")].copy()
f["month"] = pd.to_datetime(f.date_received, format="%Y%m%d").dt.to_period("M")
idx = pd.period_range("2019-01", "2021-12", freq="M")
counts = f.month.value_counts().reindex(idx, fill_value=0)
x = idx.to_timestamp()

INK, INK2, SURF, BLUE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#2a78d6", "#e6e5e0"
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150, facecolor=SURF)
ax.set_facecolor(SURF)
ax.bar(x, counts.values, width=26, align="edge", color=BLUE, zorder=2)
rec = pd.Timestamp("2021-06-01")
ax.axvline(rec, color=INK, lw=1.5, ls="--", zorder=3)
ax.text(rec - pd.Timedelta(days=12), counts.max() * 0.97, "Recall\n(June 2021)", ha="right", va="top", color=INK, fontsize=10)
ax.set_title("Philips CPAP reports to FDA, 2019-2021", loc="left", fontsize=14, color=INK, pad=12)
ax.set_ylabel("Reports received per month", color=INK2)
ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.tick_params(colors=INK2, length=0)
ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
for s in ["top", "right", "left"]: ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(INK2)
pk = counts.idxmax()
ax.annotate(f"{counts.max()}", (pk.to_timestamp() + pd.Timedelta(days=13), counts.max()), xytext=(0, 4), textcoords="offset points", ha="center", color=INK, fontsize=9)
fig.text(0.01, 0.01, f"DreamStation, REMstar and System One devices, n={len(f)}. Source: FDA MAUDE via openFDA (date received).", color=INK2, fontsize=8)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig("philips_chart.png", facecolor=SURF)

picks = [("12638552","death"),("12916133","death"),
         ("12203262","injury_foam"),("10493677","injury"),("9687125","injury"),
         ("13087410","malfunction"),("12835687","malfunction"),("10540447","malfunction"),
         ("12365433","short_vague"),("12633495","short_vague")]
demo = f.set_index("mdr_report_key").loc[[k for k,_ in picks]].reset_index()
demo["demo_category"] = [c for _,c in picks]
demo = demo[list(d.columns) + ["demo_category"]]
demo.to_csv("demo_set.csv", index=False)
print(counts[counts>0].to_string()); print(demo[["mdr_report_key","event_type","demo_category","brand_name"]])
