"""Plot preserved annual differences; requires the chart matplotlib dependency."""
import csv
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
with (root / 'comparison_by_year.csv').open() as stream:
    rows = list(csv.DictReader(stream))
fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
for column, horizon in enumerate(['5', '20']):
    for axis, metric, scale, title in [
        (axes[0, column], 'roc_auc', 1, 'ROC-AUC difference'),
        (axes[1, column], 'total_return', 100, 'Return difference (percentage points)'),
    ]:
        years = list(range(2019, 2027))
        gaps = []
        for year in years:
            base, flow = [next(x for x in rows if x['horizon'] == horizon and int(x['year']) == year and x['variant'] == variant) for variant in ['base', 'flow']]
            gaps.append((float(flow[metric]) - float(base[metric])) * scale)
        axis.bar(years, gaps, color=['#407d78' if x >= 0 else '#b26354' for x in gaps])
        axis.axhline(0, color='#444444', linewidth=0.7)
        axis.set_title(f'H{horizon}: {title}')
        axis.grid(axis='y', alpha=0.2)
        axis.set_xticks(years, [str(y) if y != 2026 else '2026*' for y in years], rotation=45)
fig.suptitle('170 inputs minus 161 inputs | Same universe and year windows, different eligible rows')
fig.text(0.5, 0.01, '* 2026 ends October 6. Returns use independent annual capital. Source: comparison_by_year.csv', ha='center', fontsize=9)
fig.tight_layout(rect=(0, 0.04, 1, 0.95))
(root / 'figures').mkdir(exist_ok=True)
fig.savefig(root / 'figures/annual_differences.png', dpi=160)
