# job-hunter

基于 [boss-agent-cli](https://github.com/can4hou6joeng4/boss-agent-cli) 的自动化求职编排引擎。

## 快速开始

### 前提条件

1. 安装 boss-agent-cli 并登录：
```bash
uv tool install boss-agent-cli
boss login
boss ai config --provider deepseek --model deepseek-chat --api-key <your-key>
```

2. 配置 `~/.boss-agent/config.json` 中 `low_risk_mode: false`

3. 安装 Bridge daemon + Chrome 扩展（boss-agent-cli 自带）

4. 创建 watch 预设：
```bash
boss watch add "默认搜索" "Golang" --city 广州 --welfare "双休,五险一金"
```

5. 创建简历：
```bash
boss resume import <简历文件>
```

### 安装 job-hunter

```bash
cd job-hunter
uv tool install -e .
```

### 使用

```bash
# 复制配置文件
cp config.example.yaml ~/.boss-agent/job-hunter/config.yaml

# 编辑配置
vim ~/.boss-agent/job-hunter/config.yaml

# 查看状态
job-hunter status

# 手动运行一次
job-hunter run

# 启动守护进程（持续运行）
job-hunter start
```

## 架构

```
job-hunter
├── scheduler.py    # Bridge 状态监听 + 每日触发
├── matcher.py      # 搜索收集 + L1/L2 评分 + 全局排序
├── applier.py      # 限流自动投递
├── tracker.py      # 对话轮询 + AI 回复
├── reporter.py     # Markdown 日报生成
├── privacy.py      # PII 脱敏
├── feedback.py     # 日报反馈解析 + 配置规则
├── pipeline.py     # 主流程编排
├── config.py       # YAML 配置系统
├── db.py           # SQLite 状态数据库
└── main.py         # CLI 入口
```

## 配置

见 `config.example.yaml`。
