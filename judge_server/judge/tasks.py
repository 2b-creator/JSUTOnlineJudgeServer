# judge/tasks.py
import base64
import json
from typing import List
from celery import shared_task
import requests
from .models import Competition, ContestRegistration, Submission, JudgeUser, MainProblem
from .utils import call_judge_cpp, call_judge_python  # 判题逻辑实现
from .config import *
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='judge_submission')
def judge_submission(self, submission_id, lang_mode):
    """
    异步判题任务
    """
    try:
        submission = Submission.objects.get(id=submission_id)
        logger.info(f"Starting judging submission: {submission_id}")
        problem = submission.problem
        user = submission.user
        # user.submit_count += 1
        problem.submit_count += 1
        if problem not in user.tried.all():
            user.tried.add(problem)
        logger.info(f"{problem.title} submit count: {problem.submit_count}")
        # 更新状态为判题中
        submission.status = 'PD'
        submission.save()

        # 调用判题逻辑
        if lang_mode == "python":
            result = call_judge_python(
                code=submission.code,
                test_case=submission.problem.test_case_path,
                std_mode=lang_mode,
                problem=submission.problem,
                submission=submission
            )
        elif lang_mode[:3] == "c++":
            result = call_judge_cpp(
                code=submission.code,
                test_case=submission.problem.test_case_path,
                std_mode=lang_mode,
                problem=submission.problem,
                submission=submission
            )

        # 更新提交状态
        submission.status = result
        submission.save()

        # 如果AC则更新用户计数
        if result == 'AC':
            user = submission.user
            problem.ac_count += 1
            if problem not in user.solved.all():
                user.ac_count += 1
                user.submit_count += 1
                user.solved.add(problem)
                user.save()
                problem.save()
                logger.info(
                    f"User {user.username} solved problem {submission.problem.id}")
            else:
                logger.info(
                    f"User {user.username} had solved problem {submission.problem.id}")
        else:
            if problem not in user.solved.all():
                user.submit_count += 1
        problem.save()
        user.save()

        logger.info(f"Judged submission {submission_id} with result: {result}")
        return {
            'submission_id': submission_id,
            'result': result,
            'user_id': submission.user.id,
            'problem_id': submission.problem.id
        }

    except Submission.DoesNotExist:
        logger.error(f"Submission {submission_id} not found")
        return {'error': 'Submission not found'}

    except Exception as e:
        logger.exception(f"Error judging submission {submission_id}: {str(e)}")
        # 更新状态为错误
        if submission:
            submission.status = 'RJ'  # 新增错误状态
            submission.save()
        return {'error': str(e)}


def import_reg_to_dom(contest: Competition):
    users: List[JudgeUser] = contest.registered.all()
    registration = ContestRegistration.objects.get(user=users, contest=contest)
    cid = contest.cid
    resp = requests.get(f"{domserver}/api/v4/contests/{cid}/groups")
    get_dic = resp.json()
    org = [{
        "id": "JSUT",
        "name": "JSUT",
        "formal_name": "Jiangsu University of Technology",
        "country": "CHN"
    }]
    user_passwd = f"{domadmin}:{domadmin_password}"
    string_bytes = user_passwd.encode('utf-8')
    encoded_string = base64.b64encode(string_bytes)
    resp = requests.post(f"{domserver}/api/v4/contests/{cid}/organizations", json=org, headers={
        "Authorization": f"Basic {encoded_string}"
    })
    resp = requests.get(f"{domserver}/api/v4/contests/{cid}/organizations")
    org_dic = resp.json()
    ls_post = []
    accounts = []
    for user in users:
        group_ids = [group["id"]
                     for group in get_dic if group["name"] == "Participants"]

        # 获取 'JSUT' 组织的ID（单个字符串）
        org_id = next((org["id"]
                      for org in org_dic if org["name"] == "JSUT"), None)
        dic = {
            "id": f"{registration.prefix}-{user.id}",
            "group_ids": group_ids,          # 修正：组ID列表
            "name": user.username,
            "display_name": user.nickname if user.nickname else user.username,
            "organization_id": org_id       # 修正：单个组织ID（非列表）
        }
        ls_post.append(dic)
    resp = requests.get(f"{domserver}/api/v4/contests/{cid}/teams")
    teams = resp.json()
    for user in users:
        team_id = next(
            (team["id"] for team in teams if team["name"] == user.username), None)
        dic = {
            "id": f"{registration.prefix}-{user.id}-account",
            "username": user.username, 
            "password": user.domserver_password,
            "type": "team",
            "team_id": team_id
        }
        accounts.append(dic)
    json_data = json.dumps(ls_post, ensure_ascii=False).encode('utf-8')
    url = f"{domserver}/api/v4/users/teams"  # 替换实际URL
    files = {
        # 关键：服务端要求字段名为 "teams.json"，类型为二进制
        "teams.json": ("teams.json", json_data, "application/json")
    }
    requests.post(url, files=files, headers={
        "Authorization": f"Basic {encoded_string}"
    })
    json_data = json.dumps(dic, ensure_ascii=False).encode('utf-8')
    url = f"{domserver}/api/v4/users/accounts"
    files = {
        "teams.json": ("teams.json", json_data, "application/json")
    }
    requests.post(url, files=files, headers={
        "Authorization": f"Basic {encoded_string}"
    })
