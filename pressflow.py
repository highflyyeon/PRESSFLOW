#!/usr/bin/env python3
"""PRESSFLOW 실행 도구.

  python pressflow.py run [--open]      서버 시작(이미 켜져 있으면 창만 열기)
  python pressflow.py open              앱 창 열기
  python pressflow.py install           바탕화면 바로가기 + 로그인 시 자동 시작 등록
  python pressflow.py uninstall         자동 시작·바로가기 제거(데이터는 그대로)
  python pressflow.py backup [종류]     db | files | full | pre-update
  python pressflow.py restore 파일 폴더 [--key 복구키]
  python pressflow.py demo              체험용 예시 보도자료 넣기(실제 메일과 별개)
  python pressflow.py update            새 버전 확인·설치
  python pressflow.py status
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if sys.stdout is None:  # pythonw.exe(콘솔 없음)
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
FROZEN = bool(getattr(sys, "frozen", False))  # 설치 파일(.exe)로 실행 중
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
PORT = int(os.environ.get("PRESSFLOW_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}"
SYSTEM = platform.system()


def is_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1.5) as r:
            return b"PRESSFLOW" in r.read()
    except Exception:
        return False


def find_chrome() -> str | None:
    cands = []
    if SYSTEM == "Windows":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [Path(base) / "Google/Chrome/Application/chrome.exe", Path(base) / "Microsoft/Edge/Application/msedge.exe"]
    elif SYSTEM == "Darwin":
        cands = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                 Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    else:
        for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            w = shutil.which(n)
            if w:
                return w
    for c in cands:
        if c.exists():
            return str(c)
    return None


def open_window():
    chrome = find_chrome()
    if chrome:  # 주소창 없는 '앱 창'으로 열기(설치형 앱처럼 보임)
        subprocess.Popen([chrome, f"--app={URL}", "--window-size=1440,900"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import webbrowser
        webbrowser.open(URL)


def cmd_run(open_after: bool):
    if is_running():
        if open_after:
            open_window()
        return
    import threading

    import updater
    updater.guard()  # 방금 업데이트한 버전이 계속 시작에 실패하면 이전 버전으로 복귀
    try:
        import app as appmod
    except Exception:
        if updater.rollback():
            os.execv(sys.executable, [sys.executable, str(ROOT / "pressflow.py")] + sys.argv[1:])
        raise
    if open_after:
        def _later():
            for _ in range(60):
                if is_running():
                    open_window()
                    return
                time.sleep(0.5)
        threading.Thread(target=_later, daemon=True).start()
    try:
        appmod.serve(PORT)
    except OSError:  # 다른 PRESSFLOW가 방금 켜진 경우(자동 시작과 겹침) → 그쪽을 사용
        for _ in range(40):
            if is_running():
                if open_after:
                    open_window()
                return
            time.sleep(0.5)
        raise


def pyw() -> str:
    exe = sys.executable
    if FROZEN:
        return exe
    if SYSTEM == "Windows" and exe.lower().endswith("python.exe"):
        w = exe[:-10] + "pythonw.exe"
        if Path(w).exists():
            return w
    return exe


def desktop_dir() -> Path:
    d = Path.home() / "Desktop"
    if SYSTEM == "Windows":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"], capture_output=True, text=True)
            if r.stdout.strip():
                return Path(r.stdout.strip())
        except Exception:
            pass
    return d


def _win_shortcut(lnk: Path, args: str, icon: Path):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='%s';"
          "$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.WindowStyle=7;$s.Description='PRESSFLOW';$s.Save()"
          % (lnk, pyw(), args, ROOT, icon))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def cmd_install():
    icon = ROOT / "static" / "icons" / "pressflow.ico"
    script = str(ROOT / "pressflow.py")
    sc = "" if FROZEN else f'"{script}" '  # 설치형(.exe)은 실행 파일이 곧 프로그램
    if SYSTEM == "Windows":
        startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
        _win_shortcut(startup / "PRESSFLOW 자동시작.lnk", f'{sc}run', icon)
        dd = desktop_dir()
        _win_shortcut(dd / "PRESSFLOW.lnk", f'{sc}run --open', icon)
        sm = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
        _win_shortcut(sm / "PRESSFLOW.lnk", f'{sc}run --open', icon)
        print("바탕화면·시작 메뉴 바로가기와 로그인 시 자동 시작을 등록했습니다.")
    elif SYSTEM == "Darwin":
        la = Path.home() / "Library/LaunchAgents"
        la.mkdir(parents=True, exist_ok=True)
        plist = la / "kr.pressflow.app.plist"
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>kr.pressflow.app</string>
<key>ProgramArguments</key><array><string>{sys.executable}</string><string>{script}</string><string>run</string></array>
<key>WorkingDirectory</key><string>{ROOT}</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>{Path.home()}/PRESSFLOW/logs/launchd.log</string>
<key>StandardErrorPath</key><string>{Path.home()}/PRESSFLOW/logs/launchd.err</string>
</dict></plist>""", encoding="utf-8")
        (Path.home() / "PRESSFLOW/logs").mkdir(parents=True, exist_ok=True)
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
        cmd = desktop_dir() / "PRESSFLOW.command"
        cmd.write_text(f'#!/bin/bash\n"{sys.executable}" "{script}" run --open\n', encoding="utf-8")
        cmd.chmod(0o755)
        print("자동 시작(LaunchAgent)과 바탕화면 PRESSFLOW.command 를 만들었습니다.")
    else:
        ad = Path.home() / ".config/autostart"
        ad.mkdir(parents=True, exist_ok=True)
        entry = (f"[Desktop Entry]\nType=Application\nName=PRESSFLOW\nExec={sys.executable} {script} run\n"
                 f"Icon={ROOT / 'static/icons/icon-512.png'}\nTerminal=false\n")
        (ad / "pressflow.desktop").write_text(entry, encoding="utf-8")
        dd = desktop_dir()
        dd.mkdir(parents=True, exist_ok=True)
        (dd / "PRESSFLOW.desktop").write_text(entry.replace(" run\n", " run --open\n"), encoding="utf-8")
        print("자동 시작과 바탕화면 실행 아이콘을 만들었습니다.")


def cmd_uninstall():
    if SYSTEM == "Windows":
        for p in (Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/PRESSFLOW 자동시작.lnk",
                  desktop_dir() / "PRESSFLOW.lnk", Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/PRESSFLOW.lnk"):
            p.unlink(missing_ok=True)
    elif SYSTEM == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/kr.pressflow.app.plist"
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
        (desktop_dir() / "PRESSFLOW.command").unlink(missing_ok=True)
    else:
        (Path.home() / ".config/autostart/pressflow.desktop").unlink(missing_ok=True)
        (desktop_dir() / "PRESSFLOW.desktop").unlink(missing_ok=True)
    print("자동 시작과 바로가기를 제거했습니다. 수집한 자료(데이터 폴더)는 그대로 남아 있습니다.")


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    c = argv[1]
    if c == "run":
        cmd_run("--open" in argv)
    elif c == "open":
        if not is_running():
            cmd_run(True)
        else:
            open_window()
    elif c == "install":
        cmd_install()
    elif c == "uninstall":
        cmd_uninstall()
    elif c == "backup":
        import backup
        import core
        core.init_db()
        kind = argv[2] if len(argv) > 2 else "db"
        print(backup.run_backup(kind, "cli"))
    elif c == "restore":
        import backup
        import core
        core.ensure_dirs()
        key = argv[argv.index("--key") + 1] if "--key" in argv else None
        print("복원 위치:", backup.restore(argv[2], argv[3], key))
    elif c == "demo":
        import demo
        demo.seed()
    elif c == "_restart":  # 업데이트 후 재시작 도우미(내부용)
        for _ in range(60):
            if not is_running():
                break
            time.sleep(0.5)
        time.sleep(1)
        cmd_run(False)
    elif c == "update":
        import core
        import updater
        core.init_db()
        r = updater.check()
        print(r)
        if r.get("available"):
            print(updater.apply(user="cli")["message"])
            print("실행 중이던 PRESSFLOW는 다시 시작해 주세요.")
    elif c == "status":
        print("실행 중" if is_running() else "꺼져 있음", URL)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
