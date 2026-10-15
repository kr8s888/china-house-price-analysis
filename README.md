# 中国多城市二手房数据分析（数据管道项目）

一个完整的**数据管道**实践：公开数据集 → 分层数仓（ODS / DWD / DWS）→ 分析 → 可视化看板。

## 数据来源

| 项 | 说明 |
|---|---|
| 数据集 | 中国 **16 个城市**二手房挂牌数据（公开数据集） |
| 来源 | Kaggle: [`xiaopaohadoop/second-hand-housing-dataset`](https://www.kaggle.com/datasets/xiaopaohadoop/second-hand-housing-dataset) |
| 规模 | **455,566 行 × 22 列**（约 170 MB），覆盖北京/上海/深圳等 16 城 |
| 获取方式 | 无需登录，直接下载（见下） |

```bash
mkdir -p data && cd data
curl -L -o sh-house.zip "https://www.kaggle.com/api/v1/datasets/download/xiaopaohadoop/second-hand-housing-dataset"
unzip sh-house.zip
```

> 数据仅用于学习分析，**不随仓库分发**（`data/` 已在 `.gitignore` 中）。
> 使用公开数据集而非自行抓取，是为了避免违反目标站点的用户协议与相关法规。

## 字段

```
id, house_id, city, neighborhood, community, total_price(w), unit_price, area_sqm,
room_num, hall_num, bathroom_num, orientation, floor_level, floor_total,
decoration, build_year, tags, attention_count, visit_30_days,
subway_info, p1_desc, p2_desc
```

关键字段缺失率均为 0%（仅 `neighborhood` 为 0.1%）：户型三列已拆分、含**地铁信息**（可做地铁溢价分析）、含关注数与近 30 天带看量。

## 环境

- Python 3.13：`pandas` / `sqlalchemy` / `pymysql` / `matplotlib`
- MySQL 8.0（本机服务，**不使用 Docker**）

```bash
pip install pandas sqlalchemy pymysql matplotlib
cp .env.example .env    # 然后填写 MySQL 密码
```

## 目录

```
├── data/           # 原始数据（不进 git）
├── sql/            # 分层建模 SQL（01_ods / 02_dwd / 03_dws）
├── etl/            # 分层 ETL 脚本
├── analysis/       # 分析脚本与分析图表（output/）
└── docs/           # 数据质量报告、分析报告
```

## 分层设计

| 层 | 表 | 职责 |
|---|---|---|
| ODS | `ods_house` | 采集数据**原样落库**，附加 `source_file` / `batch_id` / `etl_time`，保证可回溯 |
| DWD | `dwd_house` | 清洗与标准化：数值转换、楼层归一、派生字段（房龄等）、数据质量校验 |
| DWS | `dws_city_price` / `dws_district_price` / `dws_metro_price` | 面向分析问题的聚合（城市 / 城市×行政区 / 地铁距离分档，均含中位数） |

## 分析结论（详见 [docs/analysis.md](docs/analysis.md)）

1. **城市是首要因素**：深圳中位数单价（59,203 元/㎡）是江门（7,891）的 **7.5 倍**；房屋自身属性（面积/房龄/装修/楼层/朝向）合计只能解释约 **10%** 的单价差异（标准化回归 R² = 0.096）。
2. **地铁溢价可量化**：0–300m 的中位数单价比 800–1500m **高 17.2%**。
3. **指标口径很重要**：16 城的均值都比中位数高 4%–32%（房价分布右偏），衡量"典型房源"必须用中位数。
4. **识别出两处"伪相关"**：装修等级里"普装"反常（样本少 + 城市分布不均）、房龄呈正向影响（老房＝市中心地段好，房龄代理了地段）。

## 进度

- [x] 数据集下载与验证（455,566 行 × 22 列，16 城）
- [x] ODS 层建表与灌数（`sql/01_ods.sql` + `etl/load_ods.py`）
- [x] DWD 层清洗与质量校验（通过率 98.6%，报告见 `docs/data-quality.md`）
- [x] DWS 层聚合（城市 / 城市×行政区 / 地铁分档，均含中位数）
- [x] 影响因素分析与图表（`analysis/factor_analysis.py` → 6 张图 + `docs/analysis.md`）
- [ ] 可视化看板（Nuxt + ECharts，可选）

## 许可

- **代码**：[MIT License](LICENSE) © 2026 kr8s888
- **数据**：来自 Kaggle 公开数据集 [`xiaopaohadoop/second-hand-housing-dataset`](https://www.kaggle.com/datasets/xiaopaohadoop/second-hand-housing-dataset)，版权与许可归原数据集所有；本仓库**不包含数据文件**（`data/` 已在 `.gitignore` 中）。
