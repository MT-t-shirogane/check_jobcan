from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from slack_sdk import WebClient
from datetime import datetime, date, timezone, timedelta
from time import sleep
import jpholiday
import requests
import os
import random
import sys

# === 非営業日チェック ===
today = date.today()
if today.weekday() >= 5 or jpholiday.is_holiday(today):
    print("本日は非営業日のため処理をスキップします")
    exit()


campany_id = sys.argv[1]
login_id = sys.argv[2]
login_pass = sys.argv[3]
USER_ID = sys.argv[4]
SLACK_BOT_TOKEN = sys.argv[5]

# === Chrome セットアップ ===
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

# === デバッグ用 ===
# options = Options()
# options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
# driver = webdriver.Chrome(options=options)

# === 出勤簿へアクセス、ログイン ===
driver.get("https://ssl.jobcan.jp/client/adit-manage/?search_type=day")
driver.implicitly_wait(5)
sleep(random.randint(8,10))
client_login_id = driver.find_element(By.CSS_SELECTOR, '#client_login_id')
client_login_id.send_keys(campany_id)
client_manager_login_id = driver.find_element(By.CSS_SELECTOR, '#client_manager_login_id')
client_manager_login_id.send_keys(login_id)
client_login_password = driver.find_element(By.CSS_SELECTOR, '#client_login_password')
client_login_password.send_keys(login_pass)

submit_button = driver.find_element(By.CSS_SELECTOR, 'body > div.login-container > div:nth-child(1) > form > div:nth-child(6) > button')
submit_button.click()

driver.implicitly_wait(5)
sleep(random.randint(8,10))

# === 検索ボタン ===
search_button = driver.find_element(By.CSS_SELECTOR, '#search_detail_table > table > tbody > tr:nth-child(6) > th > input')
search_button.click()

driver.implicitly_wait(5)
sleep(random.randint(8,10))

# === 表からデータの刈り取り ===
rows = driver.find_elements(By.CSS_SELECTOR, "table#adit_manage_table_step tr[id^='tr_line_of_']")
results = []

for row in rows:
    tds = row.find_elements(By.CSS_SELECTOR, "td")
    name = tds[0].text.strip()

    # シフト
    try:
        shift_start = tds[4].find_element(By.CSS_SELECTOR, "input[id^='shiftstart']").get_attribute("value")
        shift_end   = tds[4].find_element(By.CSS_SELECTOR, "input[id^='shiftend']").get_attribute("value")
    except:
        shift_start, shift_end = None, None

    # 出勤・退勤
    try:
        actual_start = tds[6].find_element(By.CSS_SELECTOR, "input").get_attribute("value")
    except:
        actual_start = None
    try:
        actual_end = tds[7].find_element(By.CSS_SELECTOR, "input").get_attribute("value")
    except:
        actual_end = None

    # 判定
    if not shift_start or not shift_end:
        continue
    if not actual_start and not actual_end:
        results.append(f"{name}: 出勤記録なし (シフト {shift_start}～{shift_end})")
        continue

    fmt = "%H:%M"
    try:
        s_shift = datetime.strptime(shift_start, fmt)
        e_shift = datetime.strptime(shift_end, fmt)
        s_act   = datetime.strptime(actual_start, fmt) if actual_start else None
        e_act   = datetime.strptime(actual_end, fmt) if actual_end else None
    except ValueError:
        continue

    if s_act and s_act > s_shift:
        results.append(f"{name}: 遅刻 (シフト {shift_start}, 出勤 {actual_start})")
    if e_act and e_act < e_shift:
        results.append(f"{name}: 早退 (シフト {shift_end}, 退勤 {actual_end})")
    if s_act and e_act:
        if not (s_act <= s_shift and e_act >= e_shift):
            results.append(f"{name}: シフト通りでない (シフト {shift_start}-{shift_end}, 実際 {actual_start}-{actual_end})")


# === ファイル名を現在時間で設定 ===
# JST は UTC+9
JST = timezone(timedelta(hours=9))

# 現在時刻を JST で取得
now = datetime.now(JST)
timestamp = now.strftime("%Y%m%d_%H%M%S")
screenshot_path = f"screenshot_{timestamp}.png"

# === テーブルスクリーンショット ===
table = driver.find_element(By.CSS_SELECTOR, "table#adit_manage_table_step")
table.screenshot(screenshot_path)

# === 全ページスクリーンショット ===
# driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
#     "mobile": False,
#     "width": 1200,
#     "height": driver.execute_script("return document.body.scrollHeight"),
#     "deviceScaleFactor": 1
# })
# driver.save_screenshot(screenshot_path)

driver.quit()

# === Slackに送信 ===
if results:
    message = "📢 出勤チェック結果\n" + "\n".join([f"- {r}" for r in results])
else:
    message = "✅ 全員シフト通りに出勤しています"

client = WebClient(token=SLACK_BOT_TOKEN)

# DM の会話を開く
dm_response = client.conversations_open(users=USER_ID)
dm_channel_id = dm_response["channel"]["id"]

# ファイル送信
response = client.files_upload_v2(
    channel=dm_channel_id,
    file=screenshot_path,
    initial_comment=message,
    title=f"スクリーンショット_{timestamp}"
)

print("Slack送信結果:", response.data)

# 送信後に削除
os.remove(screenshot_path)
