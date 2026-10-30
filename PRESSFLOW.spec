# PyInstaller 설정: python -m PyInstaller PRESSFLOW.spec  → dist/PRESSFLOW/PRESSFLOW(.exe)
import os
ico = os.path.join("static", "icons", "pressflow.ico")
mods = ["app", "core", "extract", "classify", "proofread", "ai", "blog", "pipeline", "mailer", "backup", "scheduler", "updater", "demo"]
a = Analysis(["pressflow.py"], pathex=["."],
             datas=[("static", "static"), ("update_channel.json", "."), ("README.md", ".")],
             hiddenimports=mods + ["olefile", "pypdf", "PIL", "cryptography"],
             excludes=["tkinter", "matplotlib", "numpy", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PRESSFLOW", console=False, icon=ico if os.path.exists(ico) else None)
coll = COLLECT(exe, a.binaries, a.datas, name="PRESSFLOW")
