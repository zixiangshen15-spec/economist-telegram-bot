# 经济学人 Telegram 自动推送频道

每期《经济学人》出炉时，自动推送到 Telegram 频道，订阅者直接接收。

👉 **订阅链接：https://t.me/the_econimist_weekly**

---

## 订阅方式（只需 1 步）

打开 https://t.me/the_econimist_weekly → 点 **加入频道** → 完事。

以后每期经济学人发布后，频道会自动推送 PDF + EPUB + MOBI + AZW3 + 封面，直接在 Telegram 里下载阅读。

---

## 自动运行时间

- 每周六和周日早上 9:00（北京时间）
- 经济学人通常周五/周六发布新刊

---

## 工作原理

```
evanbio/The_Economist 仓库更新
        ↓
GitHub Actions 定时检查
        ↓
发现有新期刊 → 下载所有格式
        ↓
推送到 Telegram 频道
        ↓
所有订阅者手机收到通知 📱
```

---

## 自行部署

想自己搭一个？Fork 这个仓库：

### 前置准备
1. 创建 Telegram Bot（@BotFather → `/newbot`）→ 拿到 Token
2. 创建 Telegram 公开频道 → 把 Bot 加为管理员
3. 拿到频道用户名（如 `@my_channel`）

### 部署步骤
1. 创建 GitHub 仓库，上传代码
2. Settings → Secrets and variables → Actions → 添加两个密钥：

| Name | Secret |
|------|--------|
| `BOT_TOKEN` | 你的 Bot Token |
| `CHAT_ID` | 频道用户名（如 `@my_channel`） |

3. Actions → 经济学人 Telegram 推送 → Run workflow

---

## 文件说明

```
economist-telegram-bot/
├── monitor.py              # 核心脚本
├── requirements.txt        # Python 依赖
├── last_issue.txt          # 记录最后处理的期刊日期
├── .github/workflows/
│   └── monitor.yml         # GitHub Actions 定时任务配置
└── README.md               # 本文件
```

## 停止服务

删除 GitHub 仓库即可。
