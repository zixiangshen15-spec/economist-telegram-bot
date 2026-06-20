"""
经济学人 Telegram 推送 Bot
监控 evanbio/The_Economist 仓库，有新期刊时自动推送到 Telegram 频道
并自动维护置顶的往期合集目录
"""
import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path

# ==================== 配置 ====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GITHUB_API = "https://api.github.com/repos/evanbio/The_Economist/contents"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
RAW_BASE = "https://raw.githubusercontent.com/evanbio/The_Economist/main"
STATE_FILE = "last_issue.txt"
CATALOG_FILE = "catalog_msg_ids.txt"
TELEGRAM_MAX_SIZE = 50 * 1024 * 1024  # Telegram Bot 文件上限 50MB

# 需要下载和发送的文件格式（按优先级排序）
FORMATS = ["jpg", "pdf", "epub", "mobi", "azw3"]


def log(msg):
    """带时间戳的日志"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ==================== GitHub API ====================

def get_all_issue_dirs():
    """获取仓库中所有 TE-* 目录，返回按日期排序的列表"""
    log("正在获取仓库目录列表...")
    resp = requests.get(GITHUB_API, headers={"Accept": "application/vnd.github.v3+json"})
    resp.raise_for_status()

    dirs = []
    for item in resp.json():
        if item["type"] == "dir" and item["name"].startswith("TE-"):
            date_str = item["name"].replace("TE-", "")
            dirs.append({"name": item["name"], "date": date_str})

    dirs.sort(key=lambda d: d["date"], reverse=True)
    log(f"找到 {len(dirs)} 期期刊，最新一期: {dirs[0]['name'] if dirs else '无'}")
    return dirs


def get_issue_files(issue_name):
    """获取某一期期刊的所有文件信息"""
    url = f"{GITHUB_API}/{issue_name}"
    resp = requests.get(url, headers={"Accept": "application/vnd.github.v3+json"})
    resp.raise_for_status()

    files = {}
    for item in resp.json():
        if item["type"] == "file":
            ext = item["name"].split(".")[-1].lower()
            if ext in FORMATS:
                files[ext] = {
                    "name": item["name"],
                    "size": item["size"],
                    "download_url": item["download_url"],
                }
    return files


# ==================== 状态管理 ====================

def get_last_processed():
    """读取上次已处理的期刊日期"""
    try:
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_last_processed(date_str):
    """保存最新已处理的期刊日期"""
    with open(STATE_FILE, "w") as f:
        f.write(date_str)


# ==================== 文件下载 ====================

def download_file(url, local_path):
    """下载文件到本地"""
    log(f"  下载中: {url.split('/')[-1]}")
    resp = requests.get(url, stream=True)
    resp.raise_for_status()

    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = os.path.getsize(local_path) / (1024 * 1024)
    log(f"  下载完成: {size_mb:.1f} MB")
    return local_path


# ==================== Telegram API ====================

def send_to_telegram(method, files=None, data=None):
    """发送请求到 Telegram API"""
    url = f"{TELEGRAM_API}/{method}"

    if files:
        resp = requests.post(url, data=data, files=files, timeout=120)
    else:
        resp = requests.post(url, json=data, timeout=30)

    result = resp.json()
    if not result.get("ok"):
        log(f"  Telegram API 错误: {result}")
    return result


def send_message(text):
    """发送纯文本消息"""
    log(f"发送消息: {text[:50]}...")
    return send_to_telegram("sendMessage", data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def send_photo(filepath, caption=None):
    """发送图片"""
    log(f"发送图片: {os.path.basename(filepath)}")
    with open(filepath, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": CHAT_ID}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        return send_to_telegram("sendPhoto", files=files, data=data)


def send_document(filepath):
    """发送文件"""
    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)

    if file_size > TELEGRAM_MAX_SIZE:
        log(f"  文件 {filename} 超过 50MB，跳过发送")
        return None

    log(f"发送文件: {filename} ({file_size / (1024*1024):.1f} MB)")
    with open(filepath, "rb") as f:
        files = {"document": f}
        data = {"chat_id": CHAT_ID}
        return send_to_telegram("sendDocument", files=files, data=data)


# ==================== 置顶往期合集 ====================

def generate_catalog_messages(issues):
    """生成往期合集消息，自动拆分成多条（每条不超过 3500 字符）"""
    header = (
        "📚 <b>往期合集 · The Economist</b>\n"
        "点击期刊日期 → 查看 PDF / EPUB / MOBI / AZW3\n"
        f"🔗 <a href=\"https://t.me/the_econimist_weekly\">订阅频道</a>\n\n"
    )

    messages = []
    current = header

    for issue in issues:
        date_str = issue["date"]
        issue_name = issue["name"]
        folder_url = f"https://github.com/evanbio/The_Economist/tree/main/{issue_name}"
        line = f"📅 <b>{date_str}</b>  <a href=\"{folder_url}\">查看全部格式</a>\n"

        if len(current) + len(line) > 3500:
            messages.append(current)
            current = line
        else:
            current += line

    if current:
        messages.append(current)

    return messages


def update_pinned_catalog(issues):
    """更新置顶往期合集：发新消息 → 置顶 → 删除旧置顶"""
    log("\n📋 更新往期合集...")

    # 读取旧的置顶消息 ID
    old_ids = []
    if os.path.exists(CATALOG_FILE):
        with open(CATALOG_FILE, "r") as f:
            old_ids = [line.strip() for line in f if line.strip()]

    # 生成并发送新合集
    messages = generate_catalog_messages(issues)
    new_ids = []

    for i, text in enumerate(messages):
        result = send_message(text)
        if result.get("ok"):
            msg_id = result["result"]["message_id"]
            new_ids.append(str(msg_id))

            # 置顶这条消息
            pin_result = send_to_telegram("pinChatMessage", data={
                "chat_id": CHAT_ID,
                "message_id": msg_id,
                "disable_notification": True,
            })
            if pin_result.get("ok"):
                log(f"  合集第 {i+1}/{len(messages)} 页已置顶")
            else:
                log(f"  置顶失败: {pin_result}")
        else:
            log(f"  发送合集失败: {result}")

    # 取消旧的置顶
    for old_id in old_ids:
        try:
            send_to_telegram("unpinChatMessage", data={
                "chat_id": CHAT_ID,
                "message_id": int(old_id),
            })
        except Exception as e:
            log(f"  取消旧置顶失败: {e}")

    # 保存新的置顶消息 ID
    new_id_count = len(new_ids)
    with open(CATALOG_FILE, "w") as f:
        f.write("\n".join(new_ids))

    log(f"  往期合集更新完成 ({new_id_count} 条置顶消息)")
    return True


# ==================== 核心：处理新期刊 ====================

def process_new_issue(issue):
    """处理新期刊：下载并发送所有文件"""
    issue_name = issue["name"]
    date_str = issue["date"]

    log(f"\n{'='*60}")
    log(f"发现新期刊: {issue_name} (日期: {date_str})")
    log(f"{'='*60}")

    files = get_issue_files(issue_name)

    if not files:
        log("  错误: 未找到任何文件")
        return False

    tmpdir = Path(f"/tmp/{issue_name}")
    tmpdir.mkdir(parents=True, exist_ok=True)

    downloaded = []

    # 下载
    log(f"\n📥 下载文件 ({len(files)} 个)...")
    for ext in FORMATS:
        if ext in files:
            info = files[ext]
            local_path = tmpdir / info["name"]
            try:
                download_file(info["download_url"], local_path)
                downloaded.append((ext, str(local_path)))
            except Exception as e:
                log(f"  下载失败 {info['name']}: {e}")

    if not downloaded:
        log("  错误: 所有文件下载失败")
        return False

    # 发送封面
    log(f"\n📤 发送到 Telegram...")
    for ext, path in downloaded:
        if ext == "jpg":
            caption = (
                f"📰 <b>The Economist</b>\n"
                f"📅 <b>{date_str}</b>\n"
                f"🔗 <a href=\"https://t.me/the_econimist_weekly\">订阅频道</a>\n"
                f"---\n"
                f"正在发送 PDF + EPUB + MOBI + AZW3..."
            )
            try:
                send_photo(path, caption=caption)
            except Exception as e:
                log(f"  发送封面失败: {e}")
            break

    # 发送文档
    format_emojis = {"pdf": "📕", "epub": "📗", "mobi": "📘", "azw3": "📙"}
    for ext, path in downloaded:
        if ext == "jpg":
            continue

        emoji = format_emojis.get(ext, "📄")
        file_size = os.path.getsize(path)

        try:
            if file_size > TELEGRAM_MAX_SIZE:
                link = files[ext]["download_url"]
                send_message(f"{emoji} <b>{ext.upper()}</b> 文件过大，下载链接:\n{link}")
            else:
                send_document(path)
        except Exception as e:
            log(f"  发送 {ext.upper()} 失败: {e}")
            link = files[ext]["download_url"]
            try:
                send_message(f"{emoji} <b>{ext.upper()}</b> 发送失败，下载链接:\n{link}")
            except:
                pass

    # 发送汇总
    summary = (
        f"✅ <b>本期发送完毕</b>\n"
        f"📅 {date_str}\n"
        f"📂 包含格式: {', '.join(f[0].upper() for f in downloaded)}"
    )
    try:
        send_message(summary)
    except:
        pass

    # 清理
    for _, path in downloaded:
        try:
            os.remove(path)
        except:
            pass
    try:
        tmpdir.rmdir()
    except:
        pass

    return True


# ==================== 主入口 ====================

def main():
    log("🚀 经济学人 Telegram Bot 启动")

    if not BOT_TOKEN or not CHAT_ID:
        log("错误: 请设置 BOT_TOKEN 和 CHAT_ID 环境变量")
        sys.exit(1)

    # 获取所有期刊目录
    try:
        all_issues = get_all_issue_dirs()
    except Exception as e:
        log(f"获取目录失败: {e}")
        sys.exit(1)

    if not all_issues:
        log("没有找到任何期刊，退出")
        sys.exit(0)

    latest = all_issues[0]
    last_processed = get_last_processed()

    log(f"最新期刊: {latest['name']} ({latest['date']})")
    log(f"上次处理: {last_processed or '(首次运行)'}")

    # 对比，处理新期刊
    if latest["date"] == last_processed:
        log("✅ 没有新期刊")
    else:
        new_issues = []
        for issue in all_issues:
            if issue["date"] > last_processed:
                new_issues.append(issue)
            else:
                break

        log(f"\n共发现 {len(new_issues)} 期新期刊")

        if new_issues:
            new_issues.reverse()  # 从旧到新
            success_count = 0
            for issue in new_issues:
                try:
                    if process_new_issue(issue):
                        success_count += 1
                except Exception as e:
                    log(f"处理 {issue['name']} 时出错: {e}")

            save_last_processed(latest["date"])
            log(f"\n任务完成: 成功处理 {success_count}/{len(new_issues)} 期")

    # 无论有没有新期刊，都更新往期合集（保证置顶始终完整）
    try:
        update_pinned_catalog(all_issues)
    except Exception as e:
        log(f"更新往期合集失败: {e}")

    log(f"\n{'='*60}")
    log("运行结束")
    log(f"{'='*60}")


if __name__ == "__main__":
    main()
