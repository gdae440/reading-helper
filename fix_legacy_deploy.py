import os

# 定义两个路径
ROOT_REQ_FILE = "requirements.txt"
LEGACY_REQ_FILE = os.path.join("legacy_v18", "requirements.txt")

print("🔧 正在执行【双重保险】依赖修复...")

# 1. 定义一份最全的依赖清单 (包含新版和旧版所需的所有库)
# 这样无论运行哪个版本，环境都是齐全的
full_requirements = [
    "streamlit",
    "openai",
    "streamlit-option-menu",
    "edge-tts",
    "gtts",
    "genanki",
    "Pillow",
    "fastapi",
    "uvicorn",
    "python-multipart",
    "httpx",
    "watchdog"
]

# 去重并排序
final_reqs_list = sorted(list(set(full_requirements)))
req_content = "\n".join(final_reqs_list)

# 2. 写入根目录 requirements.txt
with open(ROOT_REQ_FILE, "w", encoding="utf-8") as f:
    f.write(req_content)
print(f"✅ 已更新根目录: {ROOT_REQ_FILE}")

# 3. 写入旧版目录 legacy_v18/requirements.txt (如果有这个文件夹)
if os.path.exists("legacy_v18"):
    with open(LEGACY_REQ_FILE, "w", encoding="utf-8") as f:
        f.write(req_content)
    print(f"✅ 已更新旧版目录: {LEGACY_REQ_FILE}")
else:
    print("⚠️ 未找到 legacy_v18 文件夹，跳过子目录更新。")

print("-" * 40)

# 4. 强制推送到 GitHub
print("📦 正在推送到 GitHub...")
os.system("git add .")
os.system('git commit -m "Fix: Force update requirements for Streamlit Cloud"')
push_code = os.system("git push")

if push_code == 0:
    print("🎉 推送成功！")
else:
    print("⚠️ 自动推送失败，请尝试手动 git push")