"""Cloud-only browser acceptance test. Uses HTTPS and a disposable data volume."""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

from cryptography.fernet import Fernet
import httpx
from playwright.sync_api import expect, sync_playwright


@contextmanager
def server(workdir, origin, port, env):
    cert, key = workdir / "cert.pem", workdir / "key.pem"
    with subprocess.Popen([
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(port), "--no-access-log",
        "--ssl-certfile", str(cert), "--ssl-keyfile", str(key),
    ], env=env) as proc:
        try:
            with httpx.Client(verify=False, timeout=1, trust_env=False) as client:
                for _ in range(60):
                    if proc.poll() is not None:
                        raise RuntimeError("Web preview exited during startup")
                    try:
                        if client.get(origin + "/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("Web preview failed to become healthy")
            yield
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def browser_check(browser, origin, password, test_key, workdir, restart=False):
    with browser.new_context(ignore_https_errors=True) as ctx:
        assert ctx.request.get(origin + "/api/settings").status == 401
        assert ctx.request.get(origin + "/api/planning/board").status == 401
        assert ctx.request.post(origin + "/api/admin/backup", headers={"Origin": origin}).status == 401
        assert ctx.request.post(origin + "/api/admin/login", data={"password": password},
                                headers={"Origin": "https://unrelated.example"}).status == 403
        page = ctx.new_page()
        page.goto(origin + "/")
        expect(page).to_have_url(origin + "/admin?next=workbench")
        expect(page.get_by_role("heading", name="管理员登录")).to_be_visible()
        page.get_by_label("管理员密码").fill(password)
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page).to_have_url(origin + "/")
        expect(page.get_by_role("link", name="管理后台")).to_be_visible(timeout=15000)
        assert any(c["name"] == "__Host-jianzhou-admin" and c["secure"] and c["httpOnly"]
                   and c["sameSite"] == "Strict" for c in ctx.cookies())
        page.get_by_role("link", name="管理后台").click()
        expect(page).to_have_url(origin + "/admin")
        expect(page.get_by_role("heading", name="TikHub 数据源")).to_be_visible()
        if not restart:
            page.get_by_label("TikHub API 密钥", exact=False).fill(test_key)
            page.get_by_role("button", name="保存TikHub 数据源").click()
            expect(page.get_by_text("TikHub 数据源已保存。")).to_be_visible()
        expect(page.get_by_label("TikHub API 密钥 · 已配置")).to_have_value("")
        config_response = ctx.request.get(origin + "/api/settings")
        assert config_response.ok and test_key not in config_response.text()
        assert ctx.request.put(origin + "/api/settings", headers={"Origin": "https://unrelated.example"},
                               data={"section": "cost", "values": {"daily_budget": 1}}).status == 403
        page.get_by_role("button", name="任务与排期", exact=True).click()
        if not restart:
            page.get_by_role("button", name="新增", exact=True).click()
            page.get_by_label("任务标题").fill("云端浏览器排期验收")
            page.get_by_label("排期", exact=True).fill("2030-04-12")
            page.get_by_role("button", name="保存任务").click()
            expect(page.get_by_text("任务已保存。")).to_be_visible()
        task = page.get_by_role("listitem").filter(has_text="云端浏览器排期验收")
        expect(task).to_contain_text("2030-04-12")
        if not restart:
            page.get_by_role("button", name="模板与提示词").click()
            presets = page.locator("section.adm-panel").filter(has=page.get_by_role("heading", name="提示词预设"))
            presets.get_by_role("button", name="新增", exact=True).click()
            presets.get_by_label("名称").fill("浏览器验收提示词")
            presets.get_by_label("提示词正文").fill("请根据封面标题设计构图，优先考虑视觉层次、清晰度和可读性。")
            presets.get_by_role("button", name="保存提示词").click()
            expect(page.get_by_text("提示词已保存。")).to_be_visible()
        expect(page.get_by_role("button", name="运行与用量")).to_be_enabled()
        page.get_by_role("button", name="运行与用量").click()
        expect(page.get_by_role("heading", name="管理操作记录")).to_be_visible()
        expect(page.get_by_text("/api/planning/tasks", exact=True).first).to_be_visible()
        page.get_by_role("button", name="系统与备份").click()
        expect(page.get_by_role("button", name="下载数据库备份")).to_be_visible()
        if not restart:
            with page.expect_download() as event:
                page.get_by_role("button", name="下载数据库备份").click()
            path = workdir / "snapshot.db"
            event.value.save_as(path)
            with sqlite3.connect(path) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert not db.execute("SELECT * FROM web_sessions").fetchone()
                assert db.execute("SELECT 1 FROM content_tasks WHERE title=?", ("云端浏览器排期验收",)).fetchone()
                ciphertext = db.execute("SELECT ciphertext FROM web_secrets WHERE name='tikhub_api_key'").fetchone()[0]
                assert ciphertext and test_key.encode() not in ciphertext
            assert test_key.encode() not in path.read_bytes()
        page.get_by_role("button", name="退出登录").click()
        expect(page.get_by_role("heading", name="管理员登录")).to_be_visible()
        assert ctx.request.get(origin + "/api/accounts").status == 401


def main():
    with tempfile.TemporaryDirectory(prefix="jianzhou-browser-") as raw:
        workdir = Path(raw)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"https://127.0.0.1:{port}"
        password, test_key = secrets.token_urlsafe(32), "unused-test-" + secrets.token_urlsafe(32)
        env = {**os.environ, "JIANZHOU_WEB_MODE": "1", "JIANZHOU_PREVIEW_ONLY": "1",
               "JIANZHOU_WEB_ORIGIN": origin, "JIANZHOU_DEMO": "1",
               "JIANZHOU_ADMIN_PASSWORD": password, "JIANZHOU_SECRET_KEY": Fernet.generate_key().decode(),
               "JIANZHOU_DATA_DIR": str(workdir / "data")}
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=127.0.0.1", "-keyout", str(workdir / "key.pem"),
                        "-out", str(workdir / "cert.pem")], check=True, capture_output=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            with server(workdir, origin, port, env):
                browser_check(browser, origin, password, test_key, workdir)
            print("Chromium: HTTPS, login, legacy API protection, writes, secret redaction, audit, backup and logout passed")
            with server(workdir, origin, port, env):
                browser_check(browser, origin, password, test_key, workdir, restart=True)
            print("Chromium: re-login, encrypted credential and task persist after restarting the service")


if __name__ == "__main__":
    main()
