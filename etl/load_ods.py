"""把 data/SH-house-dataset.csv 原样灌入 MySQL 的 ODS 层。

用法（项目根目录）：python etl/load_ods.py
数据库连接配置读取项目根目录的 .env（见 .env.example）。

设计要点：
* ODS 层不做清洗，字段原样落库；额外加 source_file / batch_id / etl_time 三个元数据字段，
  便于按批次回溯与增量重跑（重复执行会先 TRUNCATE，保证幂等）。
* 分块读取（2 万行/块）+ 批量插入（500 行/语句），45 万行可控内存、可控耗时。
"""

import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / 'data' / 'SH-house-dataset.csv'
CHUNK_SIZE = 20000

DDL = """
CREATE TABLE IF NOT EXISTS ods_house (
  id              BIGINT        NOT NULL,
  house_id        VARCHAR(32),
  city            VARCHAR(32),
  neighborhood    VARCHAR(64),
  community       VARCHAR(128),
  total_price_w   DECIMAL(12, 2),
  unit_price      DECIMAL(12, 2),
  area_sqm        DECIMAL(10, 2),
  room_num        SMALLINT,
  hall_num        SMALLINT,
  bathroom_num    SMALLINT,
  orientation     VARCHAR(32),
  floor_level     VARCHAR(32),
  floor_total     SMALLINT,
  decoration      VARCHAR(32),
  build_year      DECIMAL(6, 1),
  tags            VARCHAR(255),
  attention_count INT,
  visit_30_days   INT,
  subway_info     TEXT,
  p1_desc         TEXT,
  p2_desc         TEXT,
  source_file     VARCHAR(128),
  batch_id        VARCHAR(32),
  etl_time        DATETIME,
  PRIMARY KEY (id),
  KEY idx_city_district (city, neighborhood),
  KEY idx_batch (batch_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
"""

NUM_COLS = ['total_price_w', 'unit_price', 'area_sqm', 'build_year']
INT_COLS = ['room_num', 'hall_num', 'bathroom_num', 'floor_total',
            'attention_count', 'visit_30_days']


def load_env() -> dict:
    """读取 .env（避免引入额外依赖）。"""
    env = {}
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


ENV = load_env()


def cfg(key: str, default: str = '') -> str:
    return os.environ.get(key) or ENV.get(key) or default


def build_engine(with_db: bool = True):
    host, port = cfg('MYSQL_HOST', '127.0.0.1'), cfg('MYSQL_PORT', '3306')
    user, pwd = cfg('MYSQL_USER', 'root'), cfg('MYSQL_PASSWORD')
    db = cfg('MYSQL_DB', 'house_price')
    tail = f'/{db}' if with_db else '/'
    return create_engine(f'mysql+pymysql://{user}:{pwd}@{host}:{port}{tail}?charset=utf8mb4')


def main() -> None:
    if not CSV_PATH.exists():
        sys.exit(f'找不到数据文件：{CSV_PATH}')

    db_name = cfg('MYSQL_DB', 'house_price')

    # 1) 建库 + 建表（幂等）
    server = build_engine(with_db=False)
    with server.connect() as conn:
        conn.execute(text(f'CREATE DATABASE IF NOT EXISTS {db_name} DEFAULT CHARACTER SET utf8mb4'))
        conn.commit()
    engine = build_engine()
    with engine.connect() as conn:
        conn.execute(text(DDL))
        conn.execute(text('TRUNCATE TABLE ods_house'))
        conn.commit()
    print(f'建库建表完成：{db_name}.ods_house')

    # 2) 分块灌数
    batch_id = datetime.now().strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:6]
    started = time.time()
    total = 0
    reader = pd.read_csv(CSV_PATH, chunksize=CHUNK_SIZE, dtype=str, keep_default_na=False)
    for index, chunk in enumerate(reader, start=1):
        chunk = chunk.rename(columns={'total_price(w)': 'total_price_w'})
        chunk['id'] = pd.to_numeric(chunk['id'], errors='coerce')
        chunk = chunk[chunk['id'].notna()].copy()
        chunk['id'] = chunk['id'].astype('int64')
        for col in NUM_COLS:
            chunk[col] = pd.to_numeric(chunk[col], errors='coerce')
        for col in INT_COLS:
            chunk[col] = pd.to_numeric(chunk[col], errors='coerce').astype('Int64')
        chunk['source_file'] = CSV_PATH.name
        chunk['batch_id'] = batch_id
        chunk['etl_time'] = datetime.now()

        chunk.to_sql('ods_house', engine, if_exists='append', index=False,
                     chunksize=500, method='multi')
        total += len(chunk)
        print(f'  第 {index} 批入库，累计 {total} 行（{time.time() - started:.0f}s）')

    # 3) 验证
    with engine.connect() as conn:
        in_db = conn.execute(text('SELECT COUNT(*) FROM ods_house')).scalar()
        batches = conn.execute(text('SELECT COUNT(DISTINCT batch_id) FROM ods_house')).scalar()
    print(f'\n完成：CSV 读入 {total} 行，库内 {in_db} 行，批次 {batches} 个')
    print(f'batch_id = {batch_id}')
    print(f'耗时 {time.time() - started:.0f}s')
    if in_db == total:
        print('[OK] 行数一致，ODS 层灌数成功')
    else:
        print('[WARN] 行数不一致，请检查')


if __name__ == '__main__':
    main()
