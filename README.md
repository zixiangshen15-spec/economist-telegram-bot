# 经济学人 Telegram 自动推送 Bot

每期《经济学人》出炉时，自动推送到你的 Telegram 手机 App。

## 工作原理

```
经济学人仓库更新 → GitHub Actions 定时检查 → 下载所有格式文件 → Telegram Bot 推送到你手机
```

---

## 🚀 一键部署（步骤）

### 第 1 步：创建 GitHub 仓库

1. 打开 https://github.com/new
2. Repository name 填：`economist-telegram-bot`
3. 选 **Private**（私密仓库）
4. 不要勾选 "Add a README file"
5. 点 **Create repository**

### 第 2 步：上传代码

创建仓库后页面会显示「Quick setup」，在电脑上打开终端，复制粘贴下面这些命令（把 `你的GitHub用户名` 替换成你实际的）：

```bash
cd ~/economist-telegram-bot

git init
git add .
git commit -m "init: 经济学人 Telegram Bot"

git remote add origin https://github.com/你的GitHub用户名/economist-telegram-bot.git
git branch -M main
git push -u origin main
```

### 第 3 步：设置密钥（最重要）

1. 打开仓库页面 → 点 **Settings**
2. 左侧菜单 → **Secrets and variables** → **Actions**
3. 点 **New repository secret**，添加两个密钥：

| Name | Secret（你的值） |
|------|------------------|
| `BOT_TOKEN` | `8844255366:AAHYnVDcNT5-Bw_EdLbZu_ff10wSTgeuie8` |
| `CHAT_ID` | `8444551104` |

### 第 4 步：立即测试

1. 仓库页面 → 点 **Actions** 标签
2. 左侧点 **经济学人 Telegram 推送**
3. 点 **Run workflow** → 绿色 **Run workflow** 按钮
4. 等待约 1-2 分钟，查看你的 Telegram！

---

## ⏰ 自动运行时间

- 每周六和周日早上 9:00（北京时间）
- 经济学人通常周五/周六发布新刊

---

## 📁 文件说明

```
economist-telegram-bot/
├── monitor.py              # 核心脚本
├── requirements.txt        # Python 依赖
├── last_issue.txt          # 记录最后处理的期刊日期
├── .github/workflows/
│   └── monitor.yml         # GitHub Actions 定时任务配置
└── README.md               # 本文件
```

## 🛑 停止服务

删除 GitHub 仓库即可停止所有自动推送。
