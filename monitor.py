"""
经济学人 Telegram 推送 Bot
监控 evanbio/The_Economist 仓库，有新期刊时自动推送到 Telegram
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
TELEGRAM_MAX_SIZE = 50 * 1024 * 1024  # Telegram Bot 文件上限 50MB

# 需要下载和发送的文件格式（按优先级排序）
FORMATS = ["jpg", "pdf", "epub", "mobi", "azw3"]


def log(msg):
    """带时间戳的日志"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def get_all_issue_dirs():
    """获取仓库中所有 TE-* 目录，返回按日期排序的列表"""
    log("正在获取仓库目录列表...")
    resp = requests.get(GITHUB_API, headers={"Accept": "application/vnd.github.v3+json"})
    resp.raise_for_status()

    dirs = []
    for item in resp.json():
        if item["type"] == "dir" and item["name"].startswith("TE-"):
            # 解析日期: TE-2026-06-13 -> 2026-06-13
            date_str = item["name"].replace("TE-", "")
            dirs.append({"name": item["name"], "date": date_str})

    dirs.sort(key=lambda d: d["date"], reverse=True)
    log(f"找到 {len(dirs)} 期期刊，最新一期: {dirs[0]['name'] if dirs else '无'}")
    return dirs


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

    # 检查文件大小
    if file_size > TELEGRAM_MAX_SIZE:
        log(f"  文件 {filename} 超过 50MB，跳过发送")
        return None

    log(f"发送文件: {filename} ({file_size / (1024*1024):.1f} MB)")
    with open(filepath, "rb") as f:
        files = {"document": f}
        data = {"chat_id": CHAT_ID}
        return send_to_telegram("sendDocument", files=files, data=data)


def process_new_issue(issue):
    """处理新期刊：下载并发送所有文件"""
    issue_name = issue["name"]
    date_str = issue["date"]

    log(f"\n{'='*60}")
    log(f"发现新期刊: {issue_name} (日期: {date_str})")
    log(f"{'='*60}")

    # 获取该期所有文件
    files = get_issue_files(issue_name)

    if not files:
        log("  错误: 未找到任何文件")
        return False

    # 创建临时目录
    tmpdir = Path(f"/tmp/{issue_name}")
    tmpdir.mkdir(parents=True, exist_ok=True)

    downloaded = []

    # 下载所有文件
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

    # 先发封面图
    log(f"\n📤 发送到 Telegram...")
    for ext, path in downloaded:
        if ext == "jpg":
            # 发送封面，附带说明文字
            caption = (
                f"📰 <b>The Economist</b>\n"
                f"📅 <b>{date_str}</b>\n"
                f"---\n"
                f"正在发送 PDF + EPUB + MOBI + AZW3..."
            )
            try:
                send_photo(path, caption=caption)
            except Exception as e:
                log(f"  发送封面失败: {e}")
            break

    # 发送文档文件（PDF, EPUB, MOBI, AZW3）
    format_emojis = {"pdf": "📕", "epub": "📗", "mobi": "📘", "azw3": "📙"}
    for ext, path in downloaded:
        if ext == "jpg":
            continue  # 封面已发送

        emoji = format_emojis.get(ext, "📄")
        file_size = os.path.getsize(path)

        try:
            if file_size > TELEGRAM_MAX_SIZE:
                # 超过 50MB 上限，发送下载链接
                link = files[ext]["download_url"]
                send_message(f"{emoji} <b>{ext.upper()}</b> 文件过大，下载链接:\n{link}")
            else:
                send_document(path)
        except Exception as e:
            log(f"  发送 {ext.upper()} 失败: {e}")
            # 失败时发送下载链接作为后备
            link = files[ext]["download_url"]
            try:
                send_message(f"{emoji} <b>{ext.upper()}</b> 发送失败，下载链接:\n{link}")
            except:
                pass

    # 发送汇总消息
    summary = (
        f"✅ <b>本期发送完毕</b>\n"
        f"📅 {date_str}\n"
        f"📂 包含格式: {', '.join(f[0].upper() for f in downloaded)}"
    )
    try:
        send_message(summary)
    except:
        pass

    # 清理临时文件
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


def main():
    log("🚀 经济学人 Telegram Bot 启动")

    # 检查环境变量
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

    # 对比
    if latest["date"] == last_processed:
        log("✅ 没有新期刊，无需操作")
        sys.exit(0)

    # 有新期刊——可能有多期（如果之前没运行过）
    new_issues = []
    for issue in all_issues:
        if issue["date"] > last_processed:
            new_issues.append(issue)
        else:
            break

    log(f"\n共发现 {len(new_issues)} 期新期刊")

    if not new_issues:
        log("没有新期刊需要处理")
        sys.exit(0)

    # 从最旧到最新依次处理（这样在 Telegram 里顺序是正的）
    new_issues.reverse()

    success_count = 0
    for issue in new_issues:
        try:
            if process_new_issue(issue):
                success_count += 1
        except Exception as e:
            log(f"处理 {issue['name']} 时出错: {e}")
            # 继续处理下一期

    # 更新状态文件
    save_last_processed(latest["date"])

    log(f"\n{'='*60}")
    log(f"任务完成: 成功处理 {success_count}/{len(new_issues)} 期")
    log(f"{'='*60}")


if __name__ == "__main__":
    main()
