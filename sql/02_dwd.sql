-- DWD 明细层：清洗 + 字段标准化 + 派生字段 + 数据质量标记
--
-- 设计说明（面试可讲）：
-- 1) 不直接删除异常行，而是用 is_valid / quality_flag 标记 —— 保留可回溯性，
--    分析时用 WHERE is_valid = 1 过滤，需要排查时仍能看到脏数据长什么样。
-- 2) 长文本字段（p1_desc / p2_desc / tags）留在 ODS 层，DWD 只保留分析用得到的字段，
--    这是分层的价值：下游查询更快、语义更清晰。
-- 3) 所有派生字段的计算口径写在注释里，方便作为数据字典使用。

CREATE TABLE IF NOT EXISTS dwd_house (
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

  -- ===== 派生字段 =====
  house_age          INT                    COMMENT '房龄 = 2026 - 建成 年份（年份异常时为 NULL）',
  is_south           TINYINT                COMMENT '是否朝南：朝向含"南"记 1',
  decoration_level   TINYINT                COMMENT '装修等级：毛坯0 简装1 普装2 精装3 豪装4（无法识别为 NULL）',
  floor_code         TINYINT                COMMENT '楼层等级：低楼层1 中楼层2 高楼层3（"未知"为 NULL）',
  has_subway         TINYINT                COMMENT '是否带地铁信息：1/0',
  subway_distance_m  INT                    COMMENT '最近地铁站距离（米，从地铁描述文本提取的最小值）',

  -- ===== 数据质量标记 =====
  is_valid           TINYINT        NOT NULL COMMENT '是否通过全部质量校验：1 通过，0 存在异常',
  quality_flag       VARCHAR(255)            COMMENT '异常原因（逗号分隔）：year_outlier/price_mismatch/area_outlier/price_outlier/missing_required',

  batch_id           VARCHAR(32)            COMMENT '来源批次',
  etl_time           DATETIME               COMMENT 'DWD 加工时间',
  PRIMARY KEY (id),
  KEY idx_city (city),
  KEY idx_city_district (city, neighborhood),
  KEY idx_valid (is_valid),
  KEY idx_price (unit_price)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '二手房房源 DWD 明细层';
