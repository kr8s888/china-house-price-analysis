"""ODS -> DWD：字段标准化、派生字段、数据质量校验。

用法（项目根目录）：python etl/clean_dwd.py

输出的质量报告同时写入 docs/data-quality.md，可直接作为项目产出物。
"""

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# 复用 ODS 脚本里的连接配置读取逻辑
sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_ods import build_engine, cfg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CURRENT_YEAR = 2026
DOCS = ROOT / 'docs'
DOCS.mkdir(exist_ok=True)

DECORATION_MAP = {'毛坯': 0, '简装': 1, '普装': 2, '精装': 3, '豪装': 4}
FLOOR_MAP = {'低楼层': 1, '中楼层': 2, '高楼层': 3}

DWD_COLUMNS = [
    'id', 'city', 'neighborhood', 'community', 'total_price_w', 'unit_price', 'area_sqm',
    'room_num', 'hall_num', 'bathroom_num', 'orientation', 'decoration', 'build_year',
    'attention_count', 'visit_30_days',
    'house_age', 'is_south', 'decoration_level', 'floor_code', 'has_subway', 'subway_distance_m',
    'is_valid', 'quality_flag', 'batch_id', 'etl_time',
]


def parse_subway_distance(value) -> float | None:
    """从地铁描述文本中提取"最近地铁站距离（米）"。

    文本格式不统一，这里取"所有以'米'结尾的数字中的最小值"，并过滤掉明显不合理的值（>5000 米）。
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    numbers = [float(n) for n in re.findall(r'(\d+(?:\.\d+)?)\s*米', str(value))]
    numbers = [n for n in numbers if 0 < n <= 5000]
    return int(min(numbers)) if numbers else None


def main() -> None:
    engine = build_engine()

    # ---------- 1) 读 ODS ----------
    df = pd.read_sql('SELECT * FROM ods_house', engine)
    raw_rows = len(df)
    print(f'ODS 读入 {raw_rows} 行')

    # ---------- 2) 派生字段 ----------
    df['house_age'] = (CURRENT_YEAR - df['build_year']).where(df['build_year'].between(1900, CURRENT_YEAR))

    df['is_south'] = df['orientation'].fillna('').str.contains('南').astype(int)

    df['decoration_level'] = df['decoration'].map(DECORATION_MAP)
    df['floor_code'] = df['floor_level'].map(FLOOR_MAP)

    subway_text = df['subway_info'].fillna('').astype(str)
    df['has_subway'] = subway_text.str.strip().ne('').astype(int)
    df['subway_distance_m'] = df['subway_info'].map(parse_subway_distance)

    # ---------- 3) 数据质量校验（标记而不删除，保证可回溯） ----------
    area, unit_price, total_price = df['area_sqm'], df['unit_price'], df['total_price_w']

    # 3.1 单价一致性：unit_price 应约等于 总价(万)*10000/面积，容差 5%
    expected = total_price * 10000 / area
    df['f_price_mismatch'] = ((unit_price - expected).abs() / unit_price.replace(0, pd.NA) > 0.05).fillna(False)
    # 3.2 面积合理区间
    df['f_area_outlier'] = ~area.between(10, 1000)
    # 3.3 单价合理区间
    df['f_price_outlier'] = ~unit_price.between(1000, 500000)
    # 3.4 建成年份区间
    df['f_year_outlier'] = ~df['build_year'].between(1900, CURRENT_YEAR)
    # 3.5 必填字段
    df['f_missing_required'] = df[['city', 'neighborhood', 'area_sqm', 'unit_price', 'total_price_w']].isna().any(axis=1)

    flag_cols = ['f_year_outlier', 'f_price_mismatch', 'f_area_outlier', 'f_price_outlier', 'f_missing_required']
    flag_names = {
        'f_year_outlier': 'year_outlier',
        'f_price_mismatch': 'price_mismatch',
        'f_area_outlier': 'area_outlier',
        'f_price_outlier': 'price_outlier',
        'f_missing_required': 'missing_required',
    }

    def join_flags(row) -> str | None:
        hit = [flag_names[c] for c in flag_cols if row[c]]
        return ','.join(hit) if hit else None

    df['quality_flag'] = df[flag_cols].apply(join_flags, axis=1)
    df['is_valid'] = (~df[flag_cols].any(axis=1)).astype(int)

    # ---------- 4) 质量报告 ----------
    valid_rows = int(df['is_valid'].sum())
    invalid_rows = raw_rows - valid_rows
    lines = [
        '# 数据质量报告（ODS -> DWD）',
        '',
        f'- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}',
        f'- 数据来源：`ods_house`（Kaggle 公开数据集 `xiaopaohadoop/second-housing-dataset`）',
        f'- ODS 行数：**{raw_rows:,}**',
        f'- 通过全部校验：**{valid_rows:,}**（{valid_rows / raw_rows:.1%}）',
        f'- 存在异常（已标记未删除）：**{invalid_rows:,}**（{invalid_rows / raw_rows:.1%}）',
        '',
        '## 各类校验命中情况',
        '',
        '| 校验项 | 含义 | 命中行数 | 占比 |',
        '|---|---|---|---|',
    ]
    descriptions = {
        'f_year_outlier': '建成年份不在 1900–2026',
        'f_price_mismatch': '单价与「总价×10000÷面积」偏差超过 5%',
        'f_area_outlier': '建筑面积不在 10–1000 ㎡',
        'f_price_outlier': '单价不在 1000–500000 元/㎡',
        'f_missing_required': '城市/行政区/面积/单价/总价存在空值',
    }
    for col in flag_cols:
        hits = int(df[col].sum())
        lines.append(f'| `{flag_names[col]}` | {descriptions[col]} | {hits:,} | {hits / raw_rows:.2%} |')

    lines += [
        '',
        '## 派生字段质量',
        '',
        '| 字段 | 有效值覆盖 |',
        '|---|---|',
        f'| `house_age`（房龄） | {df["house_age"].notna().mean():.1%} |',
        f'| `decoration_level`（装修等级） | {df["decoration_level"].notna().mean():.1%} |',
        f'| `floor_code`（楼层等级） | {df["floor_code"].notna().mean():.1%} |',
        f'| `has_subway`（有地铁信息） | {df["has_subway"].mean():.1%} |',
        f'| `subway_distance_m`（可解析出距离） | {df["subway_distance_m"].notna().mean():.1%} |',
        '',
        '## 处理原则',
        '',
        '1. **标记而非删除**：异常行保留在 DWD 中，通过 `is_valid = 1` 过滤使用，保证可回溯。',
        '2. **口径写进字段注释**：每个派生字段的计算方式都在 `sql/02_dwd.sql` 中注明，可直接作数据字典。',
        '',
    ]
    (DOCS / 'data-quality.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    print('\n=== 数据质量报告 ===')
    for col in flag_cols:
        print(f'  {flag_names[col]:<18} {int(df[col].sum()):>8,} 行')
    print(f'  {"通过全部校验":<18} {valid_rows:>8,} 行（{valid_rows / raw_rows:.1%}）')
    print(f'  {"存在异常":<18} {invalid_rows:>8,} 行（{invalid_rows / raw_rows:.1%}）')
    print(f'\n  地铁距离解析成功：{df["subway_distance_m"].notna().sum():,} 行'
          f'（其中带地铁信息的 {int(df["has_subway"].sum()):,} 行）')
    print(f'  房龄覆盖：{df["house_age"].notna().mean():.1%}'
          f' ｜ 装修等级覆盖：{df["decoration_level"].notna().mean():.1%}'
          f' ｜ 楼层等级覆盖：{df["floor_code"].notna().mean():.1%}')

    # ---------- 5) 写入 DWD ----------
    out = df[DWD_COLUMNS].copy()
    for col in ['room_num', 'hall_num', 'bathroom_num', 'attention_count', 'visit_30_days',
                'house_age', 'decoration_level', 'floor_code', 'subway_distance_m', 'is_valid']:
        out[col] = pd.to_numeric(out[col], errors='coerce')
    out['etl_time'] = datetime.now()

    # 内联 DDL（与 sql/02_dwd.sql 保持一致）。
    # 早先版本从 sql 文件按 ";" 拆分执行，第一个分片以注释行开头被整条跳过，
    # 导致表没按设计创建、字段类型退化为 pandas 推断的 text/bigint。
    ddl = """
CREATE TABLE dwd_house (
  id                 BIGINT        NOT NULL COMMENT '房源行号（同 ODS）',
  city               VARCHAR(32)            COMMENT '城市',
  neighborhood       VARCHAR(64)            COMMENT '行政区',
  community          VARCHAR(128)           COMMENT '小区',
  total_price_w      DECIMAL(12, 2)         COMMENT '总价（万元）',
  unit_price         DECIMAL(12, 2)         COMMENT '单价（元/㎡）',
  area_sqm           DECIMAL(10, 2)         COMMENT '建筑面积（㎡）',
  room_num           SMALLINT               COMMENT '室',
  hall_num           SMALLINT               COMMENT '厅',
  bathroom_num       SMALLINT               COMMENT '卫',
  orientation        VARCHAR(32)            COMMENT '朝向（原始值）',
  decoration         VARCHAR(32)            COMMENT '装修（原始值）',
  build_year         DECIMAL(6, 1)          COMMENT '建成年份（原始值）',
  attention_count    INT                    COMMENT '关注人数',
  visit_30_days      INT                    COMMENT '近 30 天带看次数',
  house_age          INT                    COMMENT '房龄 = 2026 - 建成年份',
  is_south           TINYINT                COMMENT '是否朝南：朝向含南为 1',
  decoration_level   TINYINT                COMMENT '装修等级：毛坯0 简装1 普装2 精装3 豪装4',
  floor_code         TINYINT                COMMENT '楼层等级：低1 中2 高3（未知为 NULL）',
  has_subway         TINYINT                COMMENT '是否带地铁信息：1/0',
  subway_distance_m  INT                    COMMENT '最近地铁站距离（米）',
  is_valid           TINYINT        NOT NULL COMMENT '是否通过全部质量校验：1 通过',
  quality_flag       VARCHAR(255)            COMMENT '异常原因（逗号分隔）',
  batch_id           VARCHAR(32)            COMMENT '来源批次',
  etl_time           DATETIME               COMMENT 'DWD 加工时间',
  PRIMARY KEY (id),
  KEY idx_city (city),
  KEY idx_city_district (city, neighborhood),
  KEY idx_valid (is_valid),
  KEY idx_price (unit_price)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
"""

    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text('DROP TABLE IF EXISTS dwd_house'))
        conn.exec_driver_sql(ddl)
        conn.commit()

    out.to_sql('dwd_house', engine, if_exists='append', index=False, chunksize=500, method='multi')

    with engine.connect() as conn:
        from sqlalchemy import text
        in_db = conn.execute(text('SELECT COUNT(*) FROM dwd_house')).scalar()
        valid_in_db = conn.execute(text('SELECT COUNT(*) FROM dwd_house WHERE is_valid = 1')).scalar()
    print(f'\nDWD 写入完成：{in_db:,} 行（其中 is_valid=1 的 {valid_in_db:,} 行）')
    print(f'质量报告已写入 docs/data-quality.md')
    print('[OK] ODS -> DWD 完成' if in_db == raw_rows else '[WARN] 行数与 ODS 不一致，请检查')


if __name__ == '__main__':
    main()
