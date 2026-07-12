import configparser
import os

from jobcan_checker import run_check

script_dir = os.path.dirname(os.path.abspath(__file__))
# ローカルでテストする場合は環境変数 JOBCAN_CONFIG=test_config.ini を指定する
config_name = os.environ.get("JOBCAN_CONFIG", "config.ini")

config = configparser.ConfigParser()
config.read(os.path.join(script_dir, config_name))

run_check(
    campany_id=config['jobcan_login']['campany_id'],
    login_id=config['jobcan_login']['login_id'],
    login_pass=config['jobcan_login']['login_pass'],
    user_id=config['slack']['send_user_id'],
    slack_token=config['slack']['slack_api'],
)
