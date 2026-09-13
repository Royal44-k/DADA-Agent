# -*- coding: utf-8 -*-
from pathlib import Path


root = Path("/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-fg-verify-20260812")

mv = root / "dada/mechanisms/m2_validators.py"
text = mv.read_text(encoding="utf-8")
old = '''        current = ctx.extra.get("current_value")
        if current is None:
            print("M2_SETTING_NO_CURRENT 方向勾稽跳过:未注入现值")
            return None
'''
new = '''        current = ctx.extra.get("current_value")
        if current is None:
            return "方向勾稽失败:未读取到设备当前值，禁止在缺少基准时执行相对设置"
'''
if old not in text:
    raise SystemExit("m2 validator target not found")
mv.write_text(text.replace(old, new, 1), encoding="utf-8")

app = root / "app.py"
text = app.read_text(encoding="utf-8")
if "import os\n" not in text:
    text = text.replace("import sys\n", "import sys\nimport os\n", 1)
old = '''    from dada.agent.scheduler import start_scheduler
    start_scheduler()
'''
new = '''    if os.environ.get("DADA_DISABLE_SCHEDULER") != "1":
        from dada.agent.scheduler import start_scheduler
        start_scheduler()
'''
if old not in text:
    raise SystemExit("scheduler target not found")
app.write_text(text.replace(old, new, 1), encoding="utf-8")

cfg = root / "data/.config.yaml"
text = cfg.read_text(encoding="utf-8")
replacements = {
    "  port: 8010\n": "  port: 8110\n",
    "  http_port: 8013\n": "  http_port: 8113\n",
    "ws://192.168.5.19:8010/xiaozhi/v1/": "ws://192.168.5.19:8110/xiaozhi/v1/",
    "http://192.168.5.19:8013/mcp/vision/explain": "http://192.168.5.19:8113/mcp/vision/explain",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit("config target not found: " + old)
    text = text.replace(old, new, 1)
cfg.write_text(text, encoding="utf-8")

print("PATCHED_ISOLATED_COPY")
