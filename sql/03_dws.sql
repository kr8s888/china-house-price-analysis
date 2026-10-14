-- DWS 汇总层：面向分析问题的聚合表
--
-- 设计说明（面试可讲）：
-- 1) 每张 DWS 表都**同时给出均价和中位数**。房价是右偏分布（少数豪宅抬高均值），
--    中位数才代表"典型房源"；两个指标一起看，才能发现"均值被拉高"这种结论。
-- 2) MySQL 没有 PERCENTILE_CONT，中位数用窗口函数 CUME_DIST 实现：
--    累计分布首次跨过 0.5 的那个单价，即中位数。
-- 3) 行政区聚合加了"有效房源数 >= 30"的门槛，避免小样本（如只有 2 套房）拉出离谱均价。
-- 4) 所有聚合只统计 dwd_house.is_valid = 1 的行（即通过质量校验的数据）。

-- ========== ① 城市维度 ==========
CREATE TABLE IF NOT EXISTS dws_city_price (
  city                  VARCHAR(32)   NOT NULL COMMENT '城市',
  house_count           INT                    COMMENT '有效房源数',
  avg_unit_price        DECIMAL(12, 2)         COMMENT '均价（元/㎡）',
  median_unit_price     DECIMAL(12, 2)         COMMENT '中位数单价（元/㎡）',
  avg_total_price_w     DECIMAL(12, 2)         COMMENT '平均总价（万元）',
  median_total_price_w  DECIMAL(12, 2)         COMMENT '中位数总价（万元）',
  avg_area_sqm          DECIMAL(10, 2)         COMMENT '平均建筑面积（㎡）',
  avg_house_age         DECIMAL(6, 1)          COMMENT '平均房龄（年）',
  updated_at            DATETIME               COMMENT '加工时间',
  PRIMARY KEY (city)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'DWS 城市维度房价聚合';

-- ========== ② 城市 × 行政区维度 ==========
CREATE TABLE IF NOT EXISTS dws_district_price (
  city                VARCHAR(32)   NOT NULL COMMENT '城市',
  neighborhood        VARCHAR(64)   NOT NULL COMMENT '行政区',
  house_count         INT                    COMMENT '有效房源数（>=30）',
  avg_unit_price      DECIMAL(12, 2)         COMMENT '均价（元/㎡）',
  median_unit_price   DECIMAL(12, 2)         COMMENT '中位数单价（元/㎡）',
  avg_total_price_w   DECIMAL(12, 2)         COMMENT '平均总价（万元）',
  avg_area_sqm        DECIMAL(10, 2)         COMMENT '平均面积（㎡）',
  updated_at          DATETIME               COMMENT '加工时间',
  PRIMARY KEY (city, neighborhood),
  KEY idx_median (median_unit_price)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'DWS 城市×行政区聚合';

-- ========== ③ 地铁距离分档 ==========
CREATE TABLE IF NOT EXISTS dws_metro_price (
  metro_band          VARCHAR(16)   NOT NULL COMMENT '地铁距离分档',
  house_count         INT                    COMMENT '有效房源数',
  avg_unit_price      DECIMAL(12, 2)         COMMENT '均价（元/㎡）',
  median_unit_price   DECIMAL(12, 2)         COMMENT '中位数单价（元/㎡）',
  avg_area_sqm        DECIMAL(10, 2)         COMMENT '平均面积（㎡）',
  updated_at          DATETIME               COMMENT '加工时间',
  PRIMARY KEY (metro_band)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'DWS 地铁距离分档聚合';

-- ========== 聚合语句（实际执行见 etl/build_dws.py，两处保持一致） ==========

-- ① 城市：中位数用 CUME_DIST 求
-- INSERT INTO dws_city_price (...)
-- WITH ranked AS (
--   SELECT city, unit_price, total_price_w,
--          CUME_DIST() OVER (PARTITION BY city ORDER BY unit_price) AS cd_unit,
--          CUME_DIST() OVER (PARTITION BY city ORDER BY total_price_w) AS cd_total
--   FROM dwd_house WHERE is_valid = 1
-- ), med AS (
--   SELECT city,
--          MIN(CASE WHEN cd_unit  >= 0.5 THEN unit_price    END) AS median_unit_price,
--          MIN(CASE WHEN cd_total >= 0.5 THEN total_price_w END) AS median_total_price_w
--   FROM ranked GROUP BY city
-- )
-- SELECT a.city, a.house_count, ..., m.median_unit_price
-- FROM (SELECT city, COUNT(*) house_count, AVG(unit_price) avg_unit_price, ...
--       FROM dwd_house WHERE is_valid = 1 GROUP BY city) a
-- JOIN med m ON a.city = m.city;

-- ② 行政区：同上，外加 HAVING COUNT(*) >= 30
-- ③ 地铁分档：CASE WHEN subway_distance_m <= 300 THEN '0-300m' ... 分组后同上
