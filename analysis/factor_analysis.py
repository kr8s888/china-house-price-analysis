"""影响因素分析：量化"哪个因素对单价影响最大"，并输出图表。

用法（项目根目录）：python analysis/factor_analysis.py
输出：analysis/output/*.png（6 张图）+ 终端结论

方法说明（面试可讲）：
* 因变量用 log10(单价)：单价是右偏分布，取对数后更接近正态，回归更稳。
* 自变量做**标准化**后再回归，系数（beta）之间才可以直接比较大小 —— 这是回答
  "哪个因素影响最大"的关键；不做标准化的话，量纲不同（面积 vs 是否朝南）没法比。
* 地铁距离的缺失率高达 91.5%（只有 8.5% 的房源带地铁描述），放进回归会丢掉九成样本，
  所以它单独用"分档对比"的方式分析（dws_metro_price），不放进回归。
* 回归只用于描述相关强度，不能解释为因果。
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'etl'))
from load_ods import build_engine  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / 'output'
OUT_DIR.mkdir(exist_ok=True)

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 130
GOLD = '#e0a437'
DARK = '#333333'

FEATURES = {
    'area_sqm': '面积(㎡)',
    'house_age': '房龄(年)',
    'decoration_level': '装修等级',
    'floor_code': '楼层等级',
    'is_south': '是否朝南',
}


def save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT_DIR / name)
    plt.close(fig)
    print(f'  图已保存：{name}')


def main() -> None:
    engine = build_engine()

    # ---------- 1) 城市对比（均价 vs 中位数） ----------
    city = pd.read_sql('SELECT * FROM dws_city_price ORDER BY median_unit_price DESC', engine)
    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(city))
    ax.bar(x - 0.2, city['avg_unit_price'], width=0.4, label='均价', color=GOLD)
    ax.bar(x + 0.2, city['median_unit_price'], width=0.4, label='中位数', color=DARK)
    ax.set_xticks(x)
    ax.set_xticklabels(city['city'], rotation=45, ha='right')
    ax.set_ylabel('单价（元/㎡）')
    ax.set_title('16 城房价对比：均价普遍高于中位数（分布右偏）')
    ax.legend()
    save(fig, '01_city_avg_vs_median.png')

    # ---------- 2) 地铁距离分档 ----------
    metro = pd.read_sql("""
        SELECT * FROM dws_metro_price
        ORDER BY FIELD(metro_band, '0-300m', '300-800m', '800-1500m', '1500m+')
    """, engine)
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(metro['metro_band'], metro['median_unit_price'], color=GOLD)
    for bar, value, count in zip(bars, metro['median_unit_price'], metro['house_count']):
        ax.text(bar.get_x() + bar.get_width() / 2, float(value) + 300,
                f'{float(value):,.0f}\n({count:,} 套)', ha='center', fontsize=9)
    ax.set_ylabel('中位数单价（元/㎡）')
    ax.set_title('地铁距离与房价：越近越贵（最后一档样本少，需谨慎解读）')
    ax.set_ylim(0, float(metro['median_unit_price'].max()) * 1.25)
    save(fig, '02_metro_premium.png')

    # ---------- 3) 行政区 Top20 ----------
    top = pd.read_sql("""
        SELECT city, neighborhood, median_unit_price, house_count
        FROM dws_district_price ORDER BY median_unit_price DESC LIMIT 20
    """, engine)
    labels = [f'{c}·{n}' for c, n in zip(top['city'], top['neighborhood'])]
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.barh(labels[::-1], top['median_unit_price'][::-1], color=GOLD)
    ax.set_xlabel('中位数单价（元/㎡）')
    ax.set_title('最贵的 20 个城区（有效房源 >= 30 套）')
    save(fig, '03_top_districts.png')

    # ---------- 4) 装修等级 vs 单价 ----------
    base = pd.read_sql("""
        SELECT unit_price, area_sqm, house_age, decoration_level, floor_code, is_south,
               subway_distance_m, decoration
        FROM dwd_house WHERE is_valid = 1
    """, engine)
    print(f'\nDWD 有效样本：{len(base):,} 行')

    deco = base.dropna(subset=['decoration_level'])
    groups = [deco[deco['decoration_level'] == i]['unit_price'].values for i in range(5)]
    names = ['毛坯', '简装', '普装', '精装', '豪装']
    fig, ax = plt.subplots(figsize=(9, 5))
    bp = ax.boxplot(groups, tick_labels=names, patch_artist=True, showfliers=False)
    for box in bp['boxes']:
        box.set(facecolor=GOLD, alpha=.7)
    ax.set_ylabel('单价（元/㎡）')
    ax.set_title('装修等级与单价：等级越高单价越高（毛坯→豪装）')
    fig.tight_layout()
    fig.savefig(OUT_DIR / '04_decoration_box.png')
    plt.close(fig)
    print('  图已保存：04_decoration_box.png')

    for i, name in enumerate(names):
        if len(groups[i]):
            print(f'  {name}：中位数 {np.median(groups[i]):,.0f} 元/㎡（{len(groups[i]):,} 套）')

    # ---------- 5) 面积 vs 单价（采样散点 + 拟合） ----------
    sample = base.sample(min(20000, len(base)), random_state=42)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.scatter(sample['area_sqm'], sample['unit_price'], s=4, alpha=.18, color=GOLD)
    z = np.polyfit(sample['area_sqm'], np.log10(sample['unit_price']), 1)
    xs = np.linspace(20, 300, 100)
    ax.plot(xs, 10 ** np.polyval(z, xs), color='#c0392b', lw=2, label='拟合趋势')
    ax.set_xlim(20, 300)
    ax.set_ylim(0, 150000)
    ax.set_xlabel('建筑面积（㎡）')
    ax.set_ylabel('单价（元/㎡）')
    ax.set_title('面积与单价：面积越大，单价越低（总价约束下的"单价递减"）')
    ax.legend()
    save(fig, '05_area_vs_price.png')

    # ---------- 6) 相关系数热图 + 标准化回归 ----------
    reg = base.dropna(subset=list(FEATURES.keys())).copy()
    print(f'\n回归样本（去掉缺失后）：{len(reg):,} 行')
    y = np.log10(reg['unit_price'].values)

    corr_cols = list(FEATURES.keys()) + []
    corr = reg[corr_cols].corrwith(pd.Series(y, index=reg.index))

    fig, ax = plt.subplots(figsize=(7.5, 5))
    data = corr.values.reshape(-1, 1)
    im = ax.imshow(data, cmap='RdYlGn', vmin=-0.6, vmax=0.6, aspect='auto')
    ax.set_xticks([0])
    ax.set_xticklabels(['与 log(单价) 的相关性'])
    ax.set_yticks(range(len(corr_cols)))
    ax.set_yticklabels([FEATURES[c] for c in corr_cols])
    for i, v in enumerate(corr.values):
        ax.text(0, i, f'{v:+.3f}', ha='center', va='center', fontsize=10)
    fig.colorbar(im, ax=ax)
    ax.set_title('各因素与单价的相关系数')
    save(fig, '06_correlation.png')

    # 标准化后做最小二乘回归，比较各自影响强度
    X_raw = reg[list(FEATURES.keys())].values.astype(float)
    X = (X_raw - X_raw.mean(axis=0)) / X_raw.std(axis=0)
    X_design = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X_design, y, rcond=None)
    pred = X_design @ beta
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()

    print(f'\n=== 标准化回归（因变量 log10 单价，R² = {r2:.3f}）===')
    print('  系数绝对值越大 → 对单价影响越强')
    ranking = sorted(zip(FEATURES.values(), beta[1:]), key=lambda kv: -abs(kv[1]))
    for name, coef in ranking:
        direction = '正向' if coef > 0 else '负向'
        print(f'  {name:<10} β = {coef:+.4f}（{direction}）')

    print('\n相关系数（与 log 单价）：')
    for col in corr_cols:
        print(f'  {FEATURES[col]:<10} r = {corr[col]:+.3f}')

    # 地铁（单独分析，因缺失率高）
    sub = base.dropna(subset=['subway_distance_m'])
    print(f'\n地铁子样本：{len(sub):,} 行（占 {len(sub) / len(base):.1%}）')
    near = sub[sub['subway_distance_m'] <= 300]['unit_price']
    far = sub[(sub['subway_distance_m'] > 800) & (sub['subway_distance_m'] <= 1500)]['unit_price']
    if len(near) and len(far):
        diff = np.median(near) / np.median(far) - 1
        print(f'  0-300m 中位数 {np.median(near):,.0f} 元/㎡ vs 800-1500m {np.median(far):,.0f} 元/㎡'
              f' → 高出 {diff:.1%}')

    print(f'\n图表已输出到 {OUT_DIR}')


if __name__ == '__main__':
    main()
