from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from slack_sdk import WebClient
from datetime import datetime, date, timezone, timedelta
import jpholiday
import os

JST = timezone(timedelta(hours=9))
WAIT_TIMEOUT = 15
TIME_FMT = "%H:%M"


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and not jpholiday.is_holiday(day)


def build_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


def login_and_search(driver, campany_id, login_id, login_pass):
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    driver.get("https://ssl.jobcan.jp/client/adit-manage/?search_type=day")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '#client_login_id'))).send_keys(campany_id)
    driver.find_element(By.CSS_SELECTOR, '#client_manager_login_id').send_keys(login_id)
    driver.find_element(By.CSS_SELECTOR, '#client_login_password').send_keys(login_pass)

    submit_button = driver.find_element(
        By.CSS_SELECTOR, 'body > div.login-container > div:nth-child(1) > form > div:nth-child(6) > button'
    )
    submit_button.click()

    search_button = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '#search_detail_table > table > tbody > tr:nth-child(6) > th > input')
        )
    )
    search_button.click()

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table#adit_manage_table_step")))


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, TIME_FMT)
    except ValueError:
        return None


def judge_attendance(name, shift_start, shift_end, actual_start, actual_end):
    if not shift_start or not shift_end:
        return []
    if not actual_start and not actual_end:
        return [f"{name}: 出勤記録なし (シフト {shift_start}～{shift_end})"]

    s_shift = _parse_time(shift_start)
    e_shift = _parse_time(shift_end)
    s_act = _parse_time(actual_start)
    e_act = _parse_time(actual_end)
    if s_shift is None or e_shift is None:
        return []

    # 日をまたぐシフト(例 22:00-翌6:00)は終了時刻が開始時刻以前になるため、
    # 終了側の時刻に1日加算して比較する
    if e_shift <= s_shift:
        e_shift += timedelta(days=1)
        if e_act is not None and e_act < s_shift:
            e_act += timedelta(days=1)

    messages = []
    if s_act and s_act > s_shift:
        messages.append(f"{name}: 遅刻 (シフト {shift_start}, 出勤 {actual_start})")
    if e_act and e_act < e_shift:
        messages.append(f"{name}: 早退 (シフト {shift_end}, 退勤 {actual_end})")
    if s_act and e_act and not (s_act <= s_shift and e_act >= e_shift):
        messages.append(f"{name}: シフト通りでない (シフト {shift_start}-{shift_end}, 実際 {actual_start}-{actual_end})")
    return messages


def collect_results(driver):
    rows = driver.find_elements(By.CSS_SELECTOR, "table#adit_manage_table_step tr[id^='tr_line_of_']")
    results = []

    for row in rows:
        tds = row.find_elements(By.CSS_SELECTOR, "td")
        name = tds[0].text.strip()

        try:
            shift_start = tds[4].find_element(By.CSS_SELECTOR, "input[id^='shiftstart']").get_attribute("value")
            shift_end = tds[4].find_element(By.CSS_SELECTOR, "input[id^='shiftend']").get_attribute("value")
        except NoSuchElementException:
            shift_start, shift_end = None, None

        try:
            actual_start = tds[6].find_element(By.CSS_SELECTOR, "input").get_attribute("value")
        except NoSuchElementException:
            actual_start = None
        try:
            actual_end = tds[7].find_element(By.CSS_SELECTOR, "input").get_attribute("value")
        except NoSuchElementException:
            actual_end = None

        results.extend(judge_attendance(name, shift_start, shift_end, actual_start, actual_end))

    return results


def send_slack_report(slack_token, user_id, message, screenshot_path=None, title=None):
    client = WebClient(token=slack_token)
    dm_response = client.conversations_open(users=user_id)
    dm_channel_id = dm_response["channel"]["id"]

    if screenshot_path:
        response = client.files_upload_v2(
            channel=dm_channel_id,
            file=screenshot_path,
            initial_comment=message,
            title=title or message,
        )
    else:
        response = client.chat_postMessage(channel=dm_channel_id, text=message)

    print("Slack送信結果:", response.data)


def run_check(campany_id, login_id, login_pass, user_id, slack_token):
    today = date.today()
    if not is_business_day(today):
        print("本日は非営業日のため処理をスキップします")
        return

    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"screenshot_{timestamp}.png"

    driver = build_driver()
    try:
        login_and_search(driver, campany_id, login_id, login_pass)
        results = collect_results(driver)
        table = driver.find_element(By.CSS_SELECTOR, "table#adit_manage_table_step")
        table.screenshot(screenshot_path)
    except Exception as e:
        send_slack_report(slack_token, user_id, f"⚠️ 出勤チェックでエラーが発生しました: {e}")
        raise
    finally:
        driver.quit()

    try:
        if results:
            message = "📢 出勤チェック結果\n" + "\n".join([f"- {r}" for r in results])
        else:
            message = "✅ 全員シフト通りに出勤しています"
        send_slack_report(slack_token, user_id, message, screenshot_path, title=f"スクリーンショット_{timestamp}")
    finally:
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)
