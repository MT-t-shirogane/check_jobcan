import os

from jobcan_checker import run_check

run_check(
    campany_id=os.environ["CAMPANY_ID"],
    login_id=os.environ["LOGIN_ID"],
    login_pass=os.environ["LOGIN_PASS"],
    user_id=os.environ["SEND_USER_ID"],
    slack_token=os.environ["SLACK_API"],
)
