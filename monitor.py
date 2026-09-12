"""
经济学人 Telegram 推送 Bot
监控 hehonghui/awesome-english-ebooks 仓库，有新期刊时自动推送到 Telegram 频道
并自动维护置顶的往期合集目录
"""
import os
import sys
import re
import tempfile
from html import escape
from urllib.parse import quote
import requests
from datetime import datetime
from pathlib import Path

# ==================== 配置 ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
SOURCE_ID = "hehonghui/awesome-english-ebooks:master:01_economist"
SOURCE_STATE_FILE = "source_state.txt"
GITHUB_API = "https://api.github.com/repos/hehonghui/awesome-english-ebooks/contents/01_economist"
SOURCE_URL = "https://github.com/hehonghui/awesome-english-ebooks/tree/master/01_economist"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
RAW_BASE = "https://raw.githubusercontent.com/hehonghui/awesome-english-ebooks/master/01_economist"
STATE_FILE = "last_issue.txt"
CATALOG_FILE = "catalog_msg_ids.txt"
TELEGRAM_MAX_SIZE = 50 * 1024 * 1024  # Telegram Bot 文件上限 50MB

# 支持的格式白名单（按优先级排序）；只发送目录里实际存在的文件
FORMATS = ["jpg", "pdf", "epub", "mobi", "azw3"]


def log(msg):
    """带时间戳的日志"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ==================== GitHub API ====================

def github_contents(path=""):
    """只读取目录元数据；认证仅用于 GitHub API。"""
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers = {**headers, "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    resp = requests.get(f"{GITHUB_API}/{quote(path, safe='/')}",
                        params={"ref": "master"}, headers=headers, timeout=30)
    resp.raise_for_status()
    items = resp.json()
    if not isinstance(items, list):
        raise RuntimeError("来源异常：目录响应不是列表")
    return items


def get_all_issue_dirs():
    """读取 te_YYYY.MM.DD 和年度归档，日期统一为 YYYY-MM-DD。"""
    log("正在获取仓库目录列表...")
    root = github_contents()
    archives = [x.get("name", "") for x in root
                if x.get("type") == "dir" and re.fullmatch(r"[0-9]{4}", x.get("name", ""))]
    entries = [("", root)] + [(year, github_contents(year)) for year in archives]
    dirs = {}
    for prefix, items in entries:
        for item in items:
            name = item.get("name", "")
            if item.get("type") != "dir" or not re.fullmatch(r"te_[0-9]{4}\.[0-9]{2}\.[0-9]{2}", name):
                continue
            try:
                date = datetime.strptime(name[3:], "%Y.%m.%d").date().isoformat()
            except ValueError:
                continue
            if date not in dirs:
                dirs = {**dirs, date: {"name": f"{prefix}/{name}" if prefix else name, "date": date}}
    issues = sorted(dirs.values(), key=lambda d: d["date"], reverse=True)
    if not issues:
        raise RuntimeError("来源异常：没有找到任何有效期刊目录")
    log(f"找到 {len(issues)} 期期刊，最新一期: {issues[0]['name']}")
    return issues


def get_issue_files(issue_name):
    """仅处理实际存在的支持格式，不把 README 或封面当成期刊。"""
    files = {}
    for item in github_contents(issue_name):
        name = item.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower()
        if item.get("type") != "file" or ext not in FORMATS:
            continue
        if (not name or "/" in name or "\\" in name or not item.get("download_url")
                or not isinstance(item.get("size"), int) or item["size"] <= 0):
            raise RuntimeError("来源异常：期刊文件元数据无效")
        if ext in files:
            raise RuntimeError(f"来源异常：同一期存在多个 {ext.upper()} 文件，需人工确认")
        files = {**files, ext: {"name": name, "size": item["size"],
                 "download_url": f"{RAW_BASE}/{quote(issue_name, safe='/')}/{quote(name, safe='')}"}}
    if not any(ext != "jpg" for ext in files):
        raise RuntimeError("来源异常：期刊目录没有有效电子书文件")
    return files


# ==================== 状态管理 ====================

def get_last_processed():
    """读取并校验原有去重记录；不清空、不回退。"""
    try:
        value = Path(STATE_FILE).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    try:
        normalized = datetime.strptime(value, "%Y-%m-%d").date().isoformat() if value else ""
    except ValueError:
        normalized = ""
    if value and (not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) or normalized != value):
        raise RuntimeError("状态日期无效，请检查 last_issue.txt")
    return value


def atomic_write(filename, content):
    """同目录临时写入后原子替换，失败时保留旧文件。"""
    target = Path(filename)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def save_last_processed(date_str):
    """仅在该期全部发送成功后调用。"""
    atomic_write(STATE_FILE, date_str)


# ==================== 文件下载 ====================

def download_file(url, local_path):
    """下载文件到本地"""
    log(f"  下载中: {url.split('/')[-1]}")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = os.path.getsize(local_path) / (1024 * 1024)
    log(f"  下载完成: {size_mb:.1f} MB")
    return local_path


# ==================== Telegram API ====================

def send_to_telegram(method, files=None, data=None):
    """检查 HTTP 和 Telegram 结果；异常文本不暴露含 Token 的 URL。"""
    url = f"{TELEGRAM_API}/{method}"
    try:
        if files:
            resp = requests.post(url, data=data, files=files, timeout=120)
        else:
            resp = requests.post(url, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError(f"Telegram {method} 请求失败（网络、HTTP 或响应异常）") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(f"Telegram {method} 返回失败")
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
        raise RuntimeError("文件超过 Telegram 上传上限")

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
        "点击期刊日期 → 查看来源实际提供的格式\n"
        f"🔗 <a href=\"https://t.me/the_econimist_weekly\">订阅频道</a>\n\n"
    )

    messages = []
    current = header

    for issue in issues:
        date_str = issue["date"]
        issue_name = issue["name"]
        folder_url = f"{SOURCE_URL}/{quote(issue_name, safe='/')}"
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
    """全部新页置顶并保存后才取消旧页；失败保留旧合集及 ID。"""
    log("更新往期合集...")
    old_ids = (Path(CATALOG_FILE).read_text(encoding="utf-8").split()
               if Path(CATALOG_FILE).exists() else [])
    if any(not value.isdecimal() for value in old_ids):
        raise RuntimeError("置顶消息 ID 状态无效")
    new_ids = []
    for text in generate_catalog_messages(issues):
        result = send_message(text)
        msg_id = result.get("result", {}).get("message_id")
        if not isinstance(msg_id, int) or msg_id <= 0:
            raise RuntimeError("Telegram 未返回有效消息 ID")
        send_to_telegram("pinChatMessage", data={
            "chat_id": CHAT_ID, "message_id": msg_id, "disable_notification": True})
        new_ids = [*new_ids, str(msg_id)]
    # 先保留新旧 ID；崩溃或取消置顶失败时仍能追踪旧页。
    atomic_write(CATALOG_FILE, "\n".join([*new_ids, *old_ids]))
    for old_id in old_ids:
        send_to_telegram("unpinChatMessage", data={"chat_id": CHAT_ID, "message_id": int(old_id)})
    atomic_write(CATALOG_FILE, "\n".join(new_ids))
    log(f"往期合集更新完成 ({len(new_ids)} 条置顶消息)")
    return True


# ==================== 核心：处理新期刊 ====================

def send_issue_files(issue, files, downloaded):
    """任一发送失败即停止，绝不汇报整期成功。"""
    formats = ", ".join(ext.upper() for ext in FORMATS if ext in files)
    for ext, path in downloaded:
        if ext == "jpg":
            send_photo(path, caption=f"📰 <b>The Economist</b>\n📅 {issue['date']}\n本期格式: {formats}")
        elif os.path.getsize(path) > TELEGRAM_MAX_SIZE:
            link = escape(files[ext]["download_url"])
            send_message(f"<b>{ext.upper()}</b> 文件过大，下载链接:\n{link}")
        else:
            send_document(path)
    send_message(f"✅ <b>本期发送完毕</b>\n📅 {issue['date']}\n📂 包含格式: {formats}")


def process_new_issue(issue):
    """先完整下载，再逐个发送；异常交给主入口报告失败。"""
    log(f"发现新期刊: {issue['name']} (日期: {issue['date']})")
    files = get_issue_files(issue["name"])
    with tempfile.TemporaryDirectory(prefix="economist-") as tmpdir:
        downloaded = []
        for ext in FORMATS:
            if ext not in files:
                continue
            info = files[ext]
            path = Path(tmpdir) / info["name"]
            download_file(info["download_url"], path)
            if path.stat().st_size != info["size"]:
                raise RuntimeError("下载文件大小与来源元数据不符")
            downloaded = [*downloaded, (ext, str(path))]
        send_issue_files(issue, files, downloaded)
    return True


# ==================== 主入口 ====================

def select_new_issues(issues, last_processed, migrated):
    """首次换源仅最新一期；后续按日期从旧到新处理未发送期刊。"""
    newer = sorted((x for x in issues if x["date"] > last_processed), key=lambda x: x["date"])
    return newer if migrated else newer[-1:]


def main():
    log("🚀 经济学人 Telegram Bot 启动")
    if not BOT_TOKEN or not CHAT_ID:
        log("错误: 请设置 BOT_TOKEN 和 CHAT_ID 环境变量")
        return 1
    try:
        all_issues = get_all_issue_dirs()
        if not all_issues:
            raise RuntimeError("来源异常：没有找到任何有效期刊")
        last_processed = get_last_processed()
        source_file = Path(SOURCE_STATE_FILE)
        migrated = source_file.exists() and source_file.read_text(encoding="utf-8").strip() == SOURCE_ID
        selected = select_new_issues(all_issues, last_processed, migrated)
        if not migrated:
            log("首次换源：仅处理最新一期，跳过历史积压，不清空原去重记录")
        if not selected:
            # 即使没有新日期，也检查最新目录仍含电子书，避免再次静默绿灯。
            get_issue_files(all_issues[0]["name"])
            log("没有新期刊")
        for issue in selected:
            if not process_new_issue(issue):
                raise RuntimeError(f"期刊 {issue['date']} 发送失败")
            save_last_processed(issue["date"])
        if not migrated:
            atomic_write(SOURCE_STATE_FILE, SOURCE_ID)
        update_pinned_catalog(all_issues)
    except Exception as error:
        message = str(error).replace(BOT_TOKEN, "[REDACTED]")
        log(f"运行失败: {message}")
        return 1
    log("运行结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
