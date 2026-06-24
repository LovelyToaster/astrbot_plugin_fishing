# AstrBot 钓鱼插件 (Fishing Another!) - 开发者指南

## 项目概述
这是一个为 AstrBot 机器人设计的全功能钓鱼休闲游戏系统。它不仅包含核心的钓鱼玩法，还集成了复杂的经济系统、装备系统、社交互动以及基于 Quart 的 Web 管理后台。

- **核心技术栈**: Python 3.8+, SQLite (数据库), Quart (Web 后台), NumPy (数值计算), AstrBot API。
- **架构模式**: 采用经典的 Service-Repository 模式。
  - `core/database`: 数据库管理与迁移系统。
  - `core/domain`: 领域模型定义。
  - `core/repositories`: 仓储层，处理所有数据库持久化操作。
  - `core/services`: 业务逻辑层，包含钓鱼算法、经济模拟、成就系统等核心逻辑。
  - `handlers/`: 指令处理器，负责解析用户消息并调用服务层。
  - `draw/`: 图形生成模块，用于输出图片化的游戏状态和图鉴。
  - `manager/`: 基于 Quart 的 Web 管理端。

## 部署说明
- **远程服务器**: `VerdantGem@10.0.0.4`
- **目标根路径**: `/vol2/1000/Docker/astrbot/data/plugins/astrbot_plugin_fishing`
- **身份验证**: 使用本地私钥 `astrbot_fishing` (当前目录)。
- **操作规范**: 
  - 使用 `scp` 传输文件。
  - 同步后务必执行 `md5sum` 校验以确保文件完整性。
  - 若涉及敏感操作，优先同步单个受影响的文件。

### scp 上传命令模板

```bash
# 上传单个文件
scp -i ./astrbot_fishing <本地路径> VerdantGem@10.0.0.4:<远程目标路径>

# 上传多个文件
scp -i ./astrbot_fishing \
  _conf_schema.json \
  core/domain/models.py \
  core/services/user_service.py \
  VerdantGem@10.0.0.4:/vol2/1000/Docker/astrbot/data/plugins/astrbot_plugin_fishing/

# md5sum 校验
ssh -i ./astrbot_fishing VerdantGem@10.0.0.4 "md5sum <远程目标路径>/<文件名>" && md5sum <文件名>
```

### 多文件上传（使用 tar + ssh）

```bash
tar czf - <文件1> <文件2> ... | ssh -i ./astrbot_fishing VerdantGem@10.0.0.4 "tar xzf - -C /vol2/1000/Docker/astrbot/data/plugins/astrbot_plugin_fishing/"
```

## 关键目录说明
- `core/database/migrations`: 包含所有数据库版本迁移脚本，系统启动时会自动执行。
- `core/services/item_effects`: 动态加载的道具效果模块。
- `draw/resource`: 字体、图标等图形资源。
- `manager/templates`: Web 后台的 HTML 模板。

## 开发与运行

### 环境准备
1. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```
2. 确保已安装 AstrBot 环境，并将此插件放置在 `data/plugins/` 目录下。

### 运行与调试
- **启动**: 插件随 AstrBot 启动。
- **数据库**: 默认数据库文件位于 `data/astrbot_plugin_fishing_again/fish.db`。
- **Web 后台**: 默认端口 `7777`（可在配置中修改）。使用 `/开启钓鱼后台管理` 指令启动。

### 常用管理指令
- `/同步初始设定`: 强制从 `core/initial_data.py` 同步基础数据。
- `/代理上线 @用户`: 管理员模式，以特定用户身份执行操作进行调试。
- `/补充鱼池`: 重置稀有鱼配额。

## 核心机制
### 钓鱼算法 (`FishWeightService`)
- 引入 EV (Expected Value) 拟合算法，确保装备加成能精确反映在收益期望上。
- 使用 `OrderedDict` 内存缓存配合线程锁优化高并发下的权重计算。

### 经济系统
- **税收**: 包含起征点、阶梯税率以及每日自动清算。
- **交易所**: 动态价格波动系统，支持技术分析指标（RSI, MA）。
- **银行**: 区分活期与定期存款，利率随资金池规模动态波动。

### 签到与补签系统 (`UserService`)

#### 签到 (`daily_sign_in`)
- **奖励结构**: 基础保底 + 连续天数线性加成 + 里程碑奖励（金币/高级货币各独立计算）。
- **连续天数**: 依赖数据库签到记录，通过 `_recalculate_consecutive_days()` 从今天往前遍历 `check_ins` 表计算，不依赖 `last_login_time`。
- **每日免费抽卡**: 签到成功后可触发每日免费补给抽卡。

#### 补签 (`makeup_sign_in`)
- **指令**: `/补签` — 自动从昨天往前找最近未签到的一天（可配置范围内，默认7天）。
- **消耗**: 高级货币，递增消耗。第1次=base，第2次=base+increment，依次类推。
- **限制**: 每月可配置上限（默认3次）；仅能补签过去N天内（默认7天）。
- **连续天数恢复**: 补签后自动重算连续天数，`daily_sign_in` 的跨月检查也改为查库重算，确保补签恢复的连续天数持久有效。
- **计数字段**: 存储在 `User.makeup_count_month`（YYYYMM格式）和 `User.makeup_count` 中，跨月自动重置。

### 抽卡保底系统 (`GachaService`)
- **全局硬保底**: 通过 `_conf_schema.json` 的 `gacha.pity_threshold` 配置（默认80抽），0=关闭。
- **保底机制**: 连续 N 抽未出卡池最稀有物品时，下一抽必出（硬保底，无概率递增）。
- **保底目标**: 自动适配卡池中最高稀有度物品，不同卡池各自独立计数。
- **数据存储**: `user_gacha_pity` 表持久化保底计数器。
- **性能优化**:
  - 模板查询使用 `(type, id)` 字典缓存，避免重复查库。
  - 日志批量写入 `add_gacha_records_batch`（`executemany` + 单次清理）。
  - 金币奖励合并后一次性 `user_repo.update`。
  - 多次十连（`multi_ten_gacha`）改为单次 `perform_draw(total_draws)` 调用。

### 道具效果扩展
若要添加新道具效果，在 `core/services/item_effects/` 目录下创建继承自 `AbstractEffect` 的类即可，系统会自动扫描并注册。

### 消息通知系统 (`NotificationService`)
- **被动通知收件箱**: 偷鱼/电鱼成功后，系统自动为被操作方写入通知记录，存储在 `notifications` 表中。
- **命令**: `/消息` 查看未读通知，`/消息 全部` 查看全部，`/消息 已读` 全部标记已读。
- **状态提示**: `/状态` 图片中新增"未读通知"行，有未读时高亮显示。
- **数据存储**: `core/repositories/sqlite_notification_repo.py`，迁移脚本 `047_add_notification_system.py`。
- **通知类型**: `steal`（偷鱼）、`electric_fish`（电鱼），详情以 JSON 存储在 `details` 字段。

## 贡献规范
- **代码风格**: 遵循 PEP 8。
- **提交信息**: 必须包含规范的前缀（如 `feat:`, `fix:`, `docs:`）。

## 配置文件
- `_conf_schema.json`: 定义了插件在 AstrBot 仪表盘中的配置结构。
- `metadata.yaml`: 插件元数据。

---
