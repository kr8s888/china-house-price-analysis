-- ODS 原始层：采集到的数据原样落库，不做任何清洗，保证可回溯
-- 字段与 data/SH-house-dataset.csv 一一对应（csv 里的 total_price(w) 改名为 total_price_w）

CREATE DATABASE IF NOT EXISTS house_price DEFAULT CHARACTER SET utf8mb4;

USE house_price;

CREATE TABLE IF NOT EXISTS ods_house (
  id              BIGINT        NOT NULL COMMENT '原始行号',
  house_id        VARCHAR(32)            COMMENT '房源编号',
  city            VARCHAR(32)            COMMENT '城市',
  neighborhood    VARCHAR(64)            COMMENT '行政区',
  community       VARCHAR(128)           COMMENT '小区',
  total_price_w   DECIMAL(12, 2)         COMMENT '总价（万元）',
  unit_price      DECIMAL(12, 2)         COMMENT '单价（元/㎡）',
  area_sqm        DECIMAL(10, 2)         COMMENT '建筑面积（㎡）',
  room_num        SMALLINT               COMMENT '室',
  hall_num        SMALLINT               COMMENT '厅',
  bathroom_num    SMALLINT               COMMENT '卫',
  orientation     VARCHAR(32)            COMMENT '朝向',
  floor_level     VARCHAR(32)            COMMENT '楼层位置（低/中/高楼层）',
  floor_total     SMALLINT               COMMENT '总楼层',
  decoration      VARCHAR(32)            COMMENT '装修',
  build_year      DECIMAL(6, 1)          COMMENT '建成年份',
  tags            VARCHAR(255)           COMMENT '标签',
  attention_count INT                    COMMENT '关注人数',
  visit_30_days   INT                    COMMENT '近 30 天带看次数',
  subway_info     TEXT                   COMMENT '地铁信息',
  p1_desc         TEXT                   COMMENT '房源描述 1',
  p2_desc         TEXT                   COMMENT '房源描述 2',
  source_file     VARCHAR(128)           COMMENT '来源文件',
  batch_id        VARCHAR(32)            COMMENT '采集批次（用于增量与回溯）',
  etl_time        DATETIME               COMMENT '入库时间',
  PRIMARY KEY (id),
  KEY idx_city_district (city, neighborhood),
  KEY idx_batch (batch_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '二手房房源 ODS 原始层';
