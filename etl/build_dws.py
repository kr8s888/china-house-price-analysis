"""DWD -> DWS：构建三张汇总表（城市 / 城市×行政区 / 地铁距离分档）。

用法（项目根目录）：python etl/build_dws.py

说明：
* MySQL 没有 PERCENTILE_CONT，中位数用窗口函数 CUME_DIST 实现
  （累计分布首次跨过 0.5 的那个值）。
* 只统计 dwd_house.is_valid = 1 的数据；行政区聚合要求有效房源数 >= 30。
* 建表 DDL 与聚合 SQL 都内联在本脚本中（设计文档见 sql/03_dws.sql），
  避免"拆分 SQL 文件执行"带来的坑。
"""

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_ods import build_engine  # noqa: E402

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dws_city_price (
      city                  VARCHAR(32)   NOT NULL,
      house_count           INT,
      avg_unit_price        DECIMAL(12, 2),
      median_unit_price     DECIMAL(12, 2),
      avg_total_price_w     DECIMAL(12, 2),
      median_total_price_w  DECIMAL(12, 2),
      avg_area_sqm          DECIMAL(10, 2),
      avg_house_age         DECIMAL(6, 1),
      updated_at            DATETIME,
      PRIMARY KEY (city)
    ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dws_district_price (
      city                VARCHAR(32)   NOT NULL,
      neighborhood        VARCHAR(64)   NOT NULL,
      house_count         INT,
      avg_unit_price      DECIMAL(12, 2),
      median_unit_price   DECIMAL(12, 2),
      avg_total_price_w   DECIMAL(12, 2),
      avg_area_sqm        DECIMAL(10, 2),
      updated_at          DATETIME,
      PRIMARY KEY (city, neighborhood),
      KEY idx_median (median_unit_price)
    ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dws_metro_price (
      metro_band          VARCHAR(16)   NOT NULL,
      house_count         INT,
      avg_unit_price      DECIMAL(12, 2),
      median_unit_price   DECIMAL(12, 2),
      avg_area_sqm        DECIMAL(10, 2),
      updated_at          DATETIME,
      PRIMARY KEY (metro_band)
    ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
    """,
]

# ① 城市维度
SQL_CITY = """
INSERT INTO dws_city_price
  (city, house_count, avg_unit_price, median_unit_price,
   avg_total_price_w, median_total_price_w, avg_area_sqm, avg_house_age, updated_at)
WITH ranked AS (
  SELECT city, unit_price, total_price_w,
         CUME_DIST() OVER (PARTITION BY city ORDER BY unit_price)    AS cd_unit,
         CUME_DIST() OVER (PARTITION BY city ORDER BY total_price_w) AS cd_total
  FROM dwd_house WHERE is_valid = 1
),
med AS (
  SELECT city,
         MIN(CASE WHEN cd_unit  >= 0.5 THEN unit_price    END) AS median_unit_price,
         MIN(CASE WHEN cd_total >= 0.5 THEN total_price_w END) AS median_total_price_w
  FROM ranked GROUP BY city
)
SELECT a.city, a.house_count, ROUND(a.avg_unit_price, 2), ROUND(m.median_unit_price, 2),
       ROUND(a.avg_total_price_w, 2), ROUND(m.median_total_price_w, 2),
       ROUND(a.avg_area_sqm, 2), ROUND(a.avg_house_age, 1), :now
FROM (
  SELECT city, COUNT(*) AS house_count, AVG(unit_price) AS avg_unit_price,
         AVG(total_price_w) AS avg_total_price_w, AVG(area_sqm) AS avg_area_sqm,
         AVG(house_age) AS avg_house_age
  FROM dwd_house WHERE is_valid = 1 GROUP BY city
) a
JOIN med m ON a.city = m.city
"""

# ② 城市 × 行政区（要求有效房源数 >= 30）
SQL_DISTRICT = """
INSERT INTO dws_district_price
  (city, neighborhood, house_count, avg_unit_price, median_unit_price,
   avg_total_price_w, avg_area_sqm, updated_at)
WITH ranked AS (
  SELECT city, neighborhood, unit_price,
         CUME_DIST() OVER (PARTITION BY city, neighborhood ORDER BY unit_price) AS cd
  FROM dwd_house WHERE is_valid = 1
),
med AS (
  SELECT city, neighborhood, MIN(CASE WHEN cd >= 0.5 THEN unit_price END) AS median_unit_price
  FROM ranked GROUP BY city, neighborhood
)
SELECT a.city, a.neighborhood, a.house_count, ROUND(a.avg_unit_price, 2),
       ROUND(m.median_unit_price, 2), ROUND(a.avg_total_price_w, 2),
       ROUND(a.avg_area_sqm, 2), :now
FROM (
  SELECT city, neighborhood, COUNT(*) AS house_count, AVG(unit_price) AS avg_unit_price,
         AVG(total_price_w) AS avg_total_price_w, AVG(area_sqm) AS avg_area_sqm
  FROM dwd_house WHERE is_valid = 1
  GROUP BY city, neighborhood
  HAVING COUNT(*) >= 30
) a
JOIN med m ON a.city = m.city AND a.neighborhood = m.neighborhood
"""

# ③ 地铁距离分档
SQL_METRO = """
INSERT INTO dws_metro_price
  (metro_band, house_count, avg_unit_price, median_unit_price, avg_area_sqm, updated_at)
WITH banded AS (
  SELECT CASE
           WHEN subway_distance_m <= 300  THEN '0-300m'
           WHEN subway_distance_m <= 800  THEN '300-800m'
           WHEN subway_distance_m <= 1500 THEN '800-1500m'
           ELSE '1500m+'
         END AS metro_band,
         unit_price, area_sqm
  FROM dwd_house
  WHERE is_valid = 1 AND subway_distance_m IS NOT NULL
),
ranked AS (
  SELECT metro_band, unit_price,
         CUME_DIST() OVER (PARTITION BY metro_band ORDER BY unit_price) AS cd
  FROM banded
),
med AS (
  SELECT metro_band, MIN(CASE WHEN cd >= 0.5 THEN unit_price END) AS median_unit_price
  FROM ranked GROUP BY metro_band
)
SELECT a.metro_band, a.house_count, ROUND(a.avg_unit_price, 2),
       ROUND(m.median_unit_price, 2), ROUND(a.avg_area_sqm, 2), :now
FROM (
  SELECT metro_band, COUNT(*) AS house_count, AVG(unit_price) AS avg_unit_price,
         AVG(area_sqm) AS avg_area_sqm
  FROM banded GROUP BY metro_band
) a
JOIN med m ON a.metro_band = m.metro_band
"""


def main() -> None:
    engine = build_engine()
    now = datetime.now()

    with engine.connect() as conn:
        for ddl in DDL_STATEMENTS:
            conn.exec_driver_sql(ddl)
        for table in ['dws_city_price', 'dws_district_price', 'dws_metro_price']:
            conn.exec_driver_sql(f'TRUNCATE TABLE {table}')
        conn.execute(text(SQL_CITY), {'now': now})
        conn.execute(text(SQL_DISTRICT), {'now': now})
        conn.execute(text(SQL_METRO), {'now': now})
        conn.commit()

    with engine.connect() as conn:
        city_rows = conn.exec_driver_sql('SELECT COUNT(*) FROM dws_city_price').scalar()
        district_rows = conn.exec_driver_sql('SELECT COUNT(*) FROM dws_district_price').scalar()
        metro_rows = conn.exec_driver_sql('SELECT COUNT(*) FROM dws_metro_price').scalar()

    print(f'DWS 构建完成：城市 {city_rows} 行｜城市×行政区 {district_rows} 行｜地铁分档 {metro_rows} 行')

    # ---------- 直接打印关键结论（分析的第一步） ----------
    with engine.connect() as conn:
        print('\n【城市对比】按中位数单价排序')
        print(f'  {"城市":<6}{"房源数":>9}{"均价":>10}{"中位数":>10}{"均值/中位数":>13}')
        rows = conn.exec_driver_sql("""
            SELECT city, house_count, avg_unit_price, median_unit_price,
                   ROUND(avg_unit_price / median_unit_price, 3)
            FROM dws_city_price ORDER BY median_unit_price DESC
        """).fetchall()
        for city, cnt, avg_p, med_p, ratio in rows:
            print(f'  {city:<6}{cnt:>9,}{float(avg_p):>10,.0f}{float(med_p):>10,.0f}{float(ratio):>13.3f}')

        print('\n【行政区 Top10】按中位数单价（有效房源 >= 30）')
        rows = conn.exec_driver_sql("""
            SELECT city, neighborhood, house_count, median_unit_price, avg_unit_price
            FROM dws_district_price ORDER BY median_unit_price DESC LIMIT 10
        """).fetchall()
        for city, district, cnt, med_p, avg_p in rows:
            print(f'  {city} {district:<8} 房源 {cnt:>5,}  中位数 {float(med_p):>8,.0f}  均价 {float(avg_p):>8,.0f}')

        print('\n【地铁距离分档】')
        rows = conn.exec_driver_sql("""
            SELECT metro_band, house_count, avg_unit_price, median_unit_price
            FROM dws_metro_price
            ORDER BY FIELD(metro_band, '0-300m', '300-800m', '800-1500m', '1500m+')
        """).fetchall()
        for band, cnt, avg_p, med_p in rows:
            print(f'  {band:<12} 房源 {cnt:>7,}  均价 {float(avg_p):>8,.0f}  中位数 {float(med_p):>8,.0f}')

    print('\n[OK] DWS 层构建完成')


if __name__ == '__main__':
    main()
