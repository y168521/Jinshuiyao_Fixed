---
name: database-sql
description: 数据库与SQL技能，SQLite/MySQL选型、表结构设计、聚合统计、性能优化、彩票数据专用SQL模板。使用场景：数据库设计、SQL查询编写、性能优化、数据统计分析、数据迁移。
---

# 数据库与SQL技能

## 数据库选型

### SQLite vs MySQL
| 特性 | SQLite | MySQL |
|------|--------|-------|
| 部署 | 单文件，零配置 | 需要安装服务 |
| 并发 | 读好，写差 | 读写都好 |
| 适用 | 单机/小项目 | 多用户/大项目 |
| 大小 | 几百KB | 几百MB |

**选择建议**：
- 本地单机软件 → SQLite（推荐，金水谣用这个）
- 多人同时用 → MySQL
- 数据量10万以内 → SQLite足够

## 表结构设计

### 设计原则
1. 每个表只存一类信息
2. 主键必须有（自增ID）
3. 字段名见名知意
4. 适当加索引
5. 避免冗余存储

### 彩票开奖表示例
```sql
CREATE TABLE lottery_3d (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT NOT NULL UNIQUE,   -- 期号
    draw_date TEXT NOT NULL,       -- 开奖日期
    num1 INTEGER NOT NULL,         -- 百位
    num2 INTEGER NOT NULL,         -- 十位
    num3 INTEGER NOT NULL,         -- 个位
    sum_val INTEGER,               -- 和值
    span INTEGER,                  -- 跨度
    morphology TEXT,               -- 形态：组三/组六/豹子
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_period ON lottery_3d(period);
CREATE INDEX idx_draw_date ON lottery_3d(draw_date);
CREATE INDEX idx_morphology ON lottery_3d(morphology);
```

## 常用SQL查询

### 基础查询
```sql
-- 查最近10期
SELECT * FROM lottery_3d ORDER BY period DESC LIMIT 10;

-- 按日期范围查
SELECT * FROM lottery_3d 
WHERE draw_date BETWEEN '2024-01-01' AND '2024-06-30'
ORDER BY period;
```

### 聚合统计
```sql
-- 各形态出现次数
SELECT morphology, COUNT(*) as cnt
FROM lottery_3d
GROUP BY morphology
ORDER BY cnt DESC;

-- 每个号码出现次数（百位）
SELECT num1, COUNT(*) as cnt
FROM lottery_3d
GROUP BY num1
ORDER BY cnt DESC;
```

### 窗口函数（高级）
```sql
-- 计算每个号码的当前遗漏
-- （需要子查询实现，SQLite窗口函数支持有限）
```

## 性能优化

### 索引优化
- where 条件里的字段加索引
- 排序的字段加索引
- 联合索引注意最左前缀
- 不要在索引列上用函数

### 查询优化
1. **避免 SELECT ***：只查需要的字段
2. **LIMIT 分页**：大数据量分页用游标分页
3. **EXPLAIN 分析**：看查询计划，有没有走索引
4. **批量操作**：批量插入比循环插入快很多

### SQLite 优化
```sql
-- 开启WAL模式，并发更好
PRAGMA journal_mode = WAL;

-- 开启同步正常（速度更快）
PRAGMA synchronous = NORMAL;

-- 缓存大小
PRAGMA cache_size = -20000;  -- 20MB
```

## 彩票数据专用SQL模板

### 冷热号统计
```sql
-- 近30期各号码出现次数（百位）
SELECT 
    num1 as number,
    COUNT(*) as freq
FROM (
    SELECT * FROM lottery_3d ORDER BY period DESC LIMIT 30
)
GROUP BY num1
ORDER BY freq DESC;
```

### 形态统计
```sql
-- 近100期组三出现次数和占比
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN morphology = '组三' THEN 1 ELSE 0 END) as zu3_cnt,
    ROUND(SUM(CASE WHEN morphology = '组三' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as zu3_pct
FROM (
    SELECT * FROM lottery_3d ORDER BY period DESC LIMIT 100
);
```

### 和值分布
```sql
SELECT 
    sum_val,
    COUNT(*) as cnt
FROM lottery_3d
GROUP BY sum_val
ORDER BY sum_val;
```

## 数据导入导出

### 导入CSV
```sql
-- SQLite
.mode csv
.import data.csv table_name

-- MySQL
LOAD DATA INFILE 'data.csv' 
INTO TABLE table_name
FIELDS TERMINATED BY ',' 
ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 ROWS;
```

### 导出
```sql
-- 导出为CSV
.mode csv
.output output.csv
SELECT * FROM table_name;
.output stdout
```

## 参考资料

