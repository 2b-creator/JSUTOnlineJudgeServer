import base64
from collections import defaultdict
from io import BytesIO
import zipfile
from django.utils import timezone
import numpy as np
from datetime import datetime, timedelta
from .models import Competition, CompetitionProblem, JudgeUser, Submission, MainProblem, ProblemTags, UserRatingHistory
from django.template.loader import render_to_string
from django.template import Template, Context
import markdown
from django.db.models import Case, When, Value, BooleanField, Exists, OuterRef, Count
from markdown.extensions.toc import TocExtension
from markdown_katex.extension import KatexExtension
import markdown
import subprocess
import os
import tempfile
import shutil
import logging
import json
import requests
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)


def call_judge_cpp(code, test_case, submission: Submission, std_mode: str, problem: MainProblem) -> str:
    test_case = getTestCasesFromPath(Path(test_case))
    ls_res = []
    for i in test_case:
        dic = {
            "cmd": [{
                "args": ["/usr/bin/g++", f"-std={std_mode}", f"{submission.id}.cpp", "-o", f"{submission.id}"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "name": "stdout",
                    "max": 10240
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000,
                "memoryLimit": 1048576*1024,
                "procLimit": 50,
                "copyIn": {
                    f"{submission.id}.cpp": {
                        "content": f"{code}"
                    }
                },
                "copyOut": ["stdout", "stderr"],
                "copyOutCached": [f"{submission.id}"]
            }]
        }

        resp = requests.post(
            url="http://localhost:5050/run", json=dic)
        resp_dic = resp.json()

        if resp_dic[0]["exitStatus"] != 0:
            return "CE"
        fileid = resp_dic[0]["fileIds"][str(submission.id)]
        mb = 1048576
        cpuLimit = int(1e9)*int(problem.time_limit)
        clockLimit = cpuLimit*2
        memLimit = int(problem.mem_limit)*mb
        run_dic = {
            "cmd": [{
                "args": [f"{submission.id}"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": f"{i['in']}"
                }, {
                    "name": "stdout",
                    "max": 10240
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": cpuLimit,
                "clockLimit": clockLimit,
                "memoryLimit": memLimit,
                "procLimit": 50,
                "copyIn": {
                    f"{submission.id}": {
                        "fileId": f"{fileid}"
                    }
                }
            }
            ]
        }
        resp = requests.post(url="http://localhost:5050/run",
                             json=run_dic)
        resp_dic = resp.json()
        print(resp_dic)
        if resp_dic[0]["status"] == "Time Limit Exceeded":
            return "TLE"

        if resp_dic[0]["status"] == "Memory Limit Exceeded":
            ls_res.append("MLE")
            continue
        if resp_dic[0]["exitStatus"] != 0:
            ls_res.append("RE")
            continue
        if problem.special_judge_path:
            spj = import_spj_from_path(problem.special_judge_path)
            res = spj.check(resp_dic[0]["files"]["stdout"], i["ans"])
            ls_res.append(res)
            continue
        elif resp_dic[0]["files"]["stdout"].strip() != i["ans"].strip():
            ls_res.append("WA")
            continue
        ls_res.append("AC")
    if "MLE" in ls_res:
        return "MLE"
    if "RE" in ls_res:
        return "RE"
    if "WA" in ls_res:
        return "WA"
    return "AC"


def call_judge_python(code, test_case, submission: Submission, std_mode: str, problem: MainProblem) -> str:
    test_case = getTestCasesFromPath(Path(test_case))
    ls_res = []
    for i in test_case:
        mb = 1048576
        cpuLimit = int(1e9)*int(problem.time_limit)
        clockLimit = cpuLimit*2
        memLimit = int(problem.mem_limit)*mb
        run_dic = {
            "cmd": [{
                "args": ["/usr/bin/python3", f"{submission.id}.py"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": f"{i['in']}"
                }, {
                    "name": "stdout",
                    "max": 10240
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": cpuLimit,
                "clockLimit": clockLimit,
                "memoryLimit": memLimit,
                "procLimit": 50,
                "copyIn": {
                    f"{submission.id}.py": {
                        "content": f"{code}"
                    }
                },
            }]
        }
        resp = requests.post(url="http://localhost:5050/run",
                             json=run_dic)
        resp_dic = resp.json()
        logger.info(f"resp: {resp.json()}")
        if resp_dic[0]["status"] == "Time Limit Exceeded":
            return "TLE"
        if resp_dic[0]["status"] == "Memory Limit Exceeded":
            ls_res.append("MLE")
            continue
        if resp_dic[0]["exitStatus"] != 0:
            ls_res.append("RE")
            continue
        if problem.special_judge_path:
            spj = import_spj_from_path(problem.special_judge_path)
            res = spj.check(resp_dic[0]["files"]["stdout"], i["ans"])
            ls_res.append(res)
            continue
        elif resp_dic[0]["files"]["stdout"].strip() != i["ans"].strip():
            ls_res.append("WA")
            continue
        ls_res.append("AC")
    if "MLE" in ls_res:
        return "MLE"
    if "RE" in ls_res:
        return "RE"
    if "WA" in ls_res:
        return "WA"
    return "AC"


def add_problem(path: Path) -> MainProblem:
    confpath = path/"config.toml"
    with open(confpath, "r") as f:
        se = f.read()
        dic = tomllib.loads(se)
    title = dic["title"]
    time_limit = dic['timelimit']
    mem_limit = dic["memlimit"]
    tags = dic["tags"]
    is_public = dic['public']
    char_id = Path(path).stem
    content = open(path/"content.md").read()
    test_case_path = str(path/"tests")
    sample_path = str(path/"samples")
    checker_file = path/"checker.py"
    if checker_file.is_file():
        problem = MainProblem.objects.create(
            title=title,
            time_limit=time_limit,
            mem_limit=mem_limit,
            problem_char_id=char_id,
            content=content,
            test_case_path=test_case_path,
            sample_path=sample_path,
            special_judge_path=str(path/"checker.py"),
            is_public=is_public
        )
    else:
        problem = MainProblem.objects.create(
            title=title,
            time_limit=time_limit,
            mem_limit=mem_limit,
            problem_char_id=char_id,
            content=content,
            test_case_path=test_case_path,
            sample_path=sample_path,
            is_public=is_public
        )

    for i in tags:
        alltags = ProblemTags.objects.all()
        alltitles = [j.title for j in alltags]
        if i in alltitles:
            t = ProblemTags.objects.get(title=i)
        else:
            t = ProblemTags.objects.create(title=i)
        t.problem.add(problem)
    problem.save()

    return problem


def add_contest_problem(path: Path) -> CompetitionProblem:
    confpath = path/"config.toml"
    with open(confpath, "r") as f:
        se = f.read()
        dic = tomllib.loads(se)
    title = dic["title"]
    time_limit = dic['timelimit']
    mem_limit = dic["memlimit"]
    tags = dic["tags"]
    is_public = dic['public']
    order_char = dic['order_char']
    contest_name = dic['contest_name']
    contest = Competition.objects.get(name=contest_name)
    char_id = Path(path).stem
    content = open(path/"content.md").read()
    test_case_path = str(path/"tests")
    sample_path = str(path/"samples")
    checker_file = path/"checker.py"
    if checker_file.is_file():
        problem = CompetitionProblem.objects.create(
            title=title,
            time_limit=time_limit,
            mem_limit=mem_limit,
            problem_char_id=char_id,
            content=content,
            test_case_path=test_case_path,
            sample_path=sample_path,
            special_judge_path=str(path/"checker.py"),
            # is_public=is_public,
            order_tag=order_char
        )
    else:
        problem = CompetitionProblem.objects.create(
            title=title,
            time_limit=time_limit,
            mem_limit=mem_limit,
            problem_char_id=char_id,
            content=content,
            test_case_path=test_case_path,
            sample_path=sample_path,
            # is_public=is_public,
            order_tag=order_char
        )

    # for i in tags:
    #     alltags = ProblemTags.objects.all()
    #     alltitles = [j.title for j in alltags]
    #     if i in alltitles:
    #         t = ProblemTags.objects.get(title=i)
    #     else:
    #         t = ProblemTags.objects.create(title=i)
    #     t.problem.add(problem)
    problem.save()
    contest.problems.add(problem)

    return problem


def getTestCasesFromPath(path: Path):
    ls = []
    for i in path.glob("*.in"):
        ins = open(i, "r").read()
        ans = open(i.parent/(i.stem+".ans"), "r").read()
        print(i)
        dic = {"in": ins, "ans": ans}
        ls.append(dic)
    return ls


def render_markdown_to_html(text: str) -> str:
    html = markdown.markdown(
        text,
        extensions=['mdx_math'],
        extension_configs={
            'mdx_math': {
                'enable_dollar_delimiter': True
            }
        }
    )

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
    </head>
    <body>
    {html}
    </body>
    </html>
    """
    return full_html


def getUserRank(user: JudgeUser) -> int:
    # 获取当前用户的 ac_count 值
    user_ac = user.ac_count

    # 统计 ac_count 严格大于当前用户的用户数量
    higher_count = JudgeUser.objects.filter(ac_count__gt=user_ac).count()

    # 当前用户的位次 = 大于其 ac_count 的用户数量 + 1
    return higher_count + 1


def getUserRatingRank(user: JudgeUser) -> int:
    """
    获取用户在评分(rating)上的排名
    排名规则: 按rating降序排列，相同rating的用户共享相同名次
    (例如: rating=[1200, 1100, 1100, 1000] -> 排名=[1, 2, 2, 4])
    """
    # 统计rating严格大于当前用户的用户数量
    higher_count = JudgeUser.objects.filter(rating__gt=user.rating).count()

    # 当前用户的位次 = 大于其rating的用户数量 + 1
    return higher_count + 1


def import_spj_from_path(absolute_path, module_name=None):
    """
    从绝对路径导入 Python 模块

    参数:
        absolute_path: Python 文件的绝对路径
        module_name: 自定义模块名（可选）

    返回:
        导入的模块对象
    """
    import importlib.util
    import os
    import sys

    # 自动生成模块名（如果未提供）
    if module_name is None:
        module_name = os.path.splitext(os.path.basename(absolute_path))[0]

    # 验证文件
    if not os.path.isfile(absolute_path):
        raise FileNotFoundError(f"文件不存在: {absolute_path}")
    if not absolute_path.endswith('.py'):
        raise ValueError("仅支持 .py 文件")

    # 创建并加载模块
    spec = importlib.util.spec_from_file_location(module_name, absolute_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


def get_user_rating_history_in_intervals(user):
    # 获取用户的所有rating记录，按时间升序排列
    histories = UserRatingHistory.objects.filter(
        user=user).order_by('timestamp')

    if not histories.exists():
        return [0] * 10  # 没有记录则返回10个0

    # 获取第一条记录的时间和当前时间
    first_record_time = histories.first().timestamp
    now = timezone.now()

    # 如果所有记录都在同一时间点（不太可能但需要处理）
    if first_record_time == now:
        latest_rating = histories.last().rating
        return [latest_rating] * 10

    # 计算10个等分时间点
    total_duration = now - first_record_time
    interval = total_duration / 10
    time_points = [first_record_time + i *
                   interval for i in range(11)]  # 11个点产生10个区间

    # 初始化结果列表
    result = []
    current_rating = histories.first().previous_rating if histories.first(
    ).previous_rating is not None else 0

    # 遍历每个时间区间
    for i in range(10):
        start_time = time_points[i]
        end_time = time_points[i+1]

        # 找出该时间区间内的所有记录
        interval_records = histories.filter(
            timestamp__gt=start_time, timestamp__lte=end_time)

        if interval_records.exists():
            # 取区间最后一条记录的rating作为该区间的rating
            current_rating = interval_records.last().rating
            result.append(current_rating)
        else:
            # 如果没有记录，保持上一个rating值
            result.append(current_rating)

    return result


def get_user_problems(user):
    # Get all distinct problems the user has submitted
    submissions = Submission.objects.filter(user=user)

    # Annotate each problem with whether it has an AC submission
    problems = submissions.values('problem').distinct().annotate(
        accepted=Exists(
            submissions.filter(problem_id=OuterRef('problem'), status='AC')
        )
    )

    return [{
        'problem_id': p['problem'],
        'submitted': True,
        'accepted': p['accepted'],
        'color': 'green' if p['accepted'] else 'red'
    } for p in problems]


def get_user_competitions(user):
    # Get all competitions where the user is in the registered field
    competitions = Competition.objects.filter(registered=user).annotate(
        total_participants=Count('registered')
    ).order_by('start_time')

    result = []
    for competition in competitions:
        # Get all registered users for this competition
        registered_users = competition.registered.all()

        # Create a list of user IDs to determine ranks
        user_ids = list(registered_users.values_list('id', flat=True))

        # Get the user's rank (index + 1 since lists are 0-indexed)
        try:
            rank = user_ids.index(user.id) + 1
        except ValueError:
            rank = 0  # Shouldn't happen since we filtered by registered users

        result.append({
            'competition_id': competition.id,
            'name': competition.name,
            'start_time': competition.start_time,
            'rank': rank,
            'total_participants': competition.total_participants,
        })

    return result


def get_user_submission_data(user_id, year):
    # Calculate date range for the requested year
    start_date = datetime(int(year), 1, 1)
    end_date = datetime(int(year) + 1, 1, 1)

    # Query submissions for this user within the date range
    submissions = Submission.objects.filter(
        user_id=user_id,
        created_at__gte=start_date,
        created_at__lt=end_date
    ).order_by('created_at')

    # Initialize a dictionary to count submissions per day
    daily_counts = defaultdict(int)

    # Count submissions per day
    for sub in submissions:
        day_str = sub.created_at.strftime('%Y-%m-%d')
        daily_counts[day_str] += 1

    # Generate data for every day in the year, even if no submissions
    current_date = start_date
    data = []

    while current_date < end_date:
        day_str = current_date.strftime('%Y-%m-%d')
        count = daily_counts.get(day_str, 0)
        data.append([day_str, count])
        current_date += timedelta(days=1)

    return data

def file_to_base64_zip(file_path):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(file_path, arcname=os.path.basename(file_path))  # 确保 ZIP 内文件名不含路径

    # 从内存缓冲区获取字节并 Base64 编码
    zip_bytes = zip_buffer.getvalue()
    return base64.b64encode(zip_bytes).decode('utf-8')