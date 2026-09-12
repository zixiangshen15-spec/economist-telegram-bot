# 经济学人每周 Telegram 自动推送更新

每期《经济学人》出炉时，自动推送到 Telegram 频道，订阅者直接接收。

👉 **订阅链接：https://t.me/the_econimist_weekly**

---

## 订阅方式（只需 1 步）

打开 https://t.me/the_econimist_weekly → 点 **加入频道** → 完事。

按来源实际提供的支持格式推送，不保证每期都有 PDF、AZW3 或封面。2026-09-12 的目录中有 EPUB、MOBI，无 PDF。

来源是第三方仓库 [hehonghui/awesome-english-ebooks](https://github.com/hehonghui/awesome-english-ebooks/tree/master/01_economist)，转载授权尚未核实；公开可下载不等于获得公开传播许可。请在具有相应授权的范围内使用，不绕过登录或付费限制。

---

## 自动运行时间

- 每周六和周日早上 9:07（北京时间），即 01:07 UTC；GitHub 调度可能延迟
- 经济学人通常周五/周六发布新刊

---

## 工作原理

```
hehonghui/awesome-english-ebooks 的 master 分支、01_economist/ 目录更新
        ↓
GitHub Actions 定时检查
        ↓
发现 te_YYYY.MM.DD 新期刊 → 下载实际存在的支持格式
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
├── catalog_msg_ids.txt     # 记录置顶消息 ID
├── source_state.txt        # 首次换源成功后自动生成的来源标记
├── .github/workflows/
│   └── monitor.yml         # GitHub Actions 定时任务配置
└── README.md               # 本文件
```

## 停止服务

在 Actions 中打开本工作流，选择 Disable workflow，可随时停止定时服务。

## 换源及故障处理

- 保留 `last_issue.txt` 的 `YYYY-MM-DD` 日期以及原有 `catalog_msg_ids.txt`。首次没有当前来源标记时，仅处理比已记录日期更新的最新一期，跳过约 10 期历史积压；不清空去重记录，不自动补推旧刊。
- 该期所有文件及汇总发送成功后才保存日期、写入 `source_state.txt`。后续从旧到新处理新刊，遇到失败立即停止，保留已成功期刊的检查点。
- 空来源、无电子书、下载或发送失败都会让工作流失败。超出 Telegram 上传上限的文件以下载链接发送，链接发送也必须成功。
- 新合集所有页发送并置顶成功、ID 安全保存后，才取消旧置顶；失败时保留旧合集。取消旧置顶失败时保留新旧 ID 以便下次重试。部分新页可能留下重复置顶，但不会主动撤掉仍需保留的旧合集。
- Telegram 与 GitHub 状态提交不是一个事务：如果文件已送达但响应丢失，或发送后状态保存/推送失败，下次重试可能重复发送；程序不会将明确失败的期刊记为已发送。
- 公开仓库连续 60 天无活动，GitHub 可能自动停用定时工作流。到 Actions → 本工作流 → Enable workflow 恢复；修改一次代码或 cron 不能永久豁免该规则。本项目不添加保活机器人、PAT 或额外服务。参见 [GitHub 官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)。

## 离线测试

```sh
python -m unittest discover -s tests -v
```

测试使用模拟 GitHub/Telegram 请求和临时状态，不会实际下载或转发期刊。不要用 `python monitor.py` 或 Actions 的 Run workflow 代替测试：它们会真实推送。
