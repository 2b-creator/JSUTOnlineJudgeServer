# judge/tasks.py
import base64
import json
from typing import List
from celery import shared_task
import requests
from .models import Competition, ContestRegistration, DomServerSave, Submission, JudgeUser, MainProblem
from .utils import call_judge_cpp, call_judge_python  # 判题逻辑实现
from .config import *
import logging
import docker
from docker.errors import NotFound, APIError

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
    registration = ContestRegistration.objects.get(
        user=users[0], contest=contest)
    cid = contest.cid
    resp = requests.get(f"{domserver}/api/v4/contests/{cid}/groups")
    get_dic = resp.json()
    org = [{
        "id": "JSUT",
        "name": "JSUT",
        "formal_name": "Jiangsu University of Technology",
        "country": "CHN"
    }]

    json_data = json.dumps(org, ensure_ascii=False).encode('utf-8')
    url = f"{domserver}/api/v4/users/organizations"
    files = {
        "json": ("organizations.json", json_data, "application/json")
    }
    dom_admin = DomServerSave.objects.get(singleton_id=1)
    user_passwd = f"{dom_admin.admin}:{dom_admin.init_passwd}"
    string_bytes = user_passwd.encode('utf-8')
    encoded_string = base64.b64encode(string_bytes).decode('utf-8')
    resp = requests.post(url, files=files, headers={
        "Authorization": f"Basic {encoded_string}"
    })

    print("创建org", resp.text)
    resp = requests.get(f"{domserver}/api/v4/contests/{cid}/organizations")
    print("查询org", resp.text)
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

    json_data = json.dumps(ls_post, ensure_ascii=False).encode('utf-8')
    url = f"{domserver}/api/v4/users/teams"  # 替换实际URL
    files = {
        # 关键：服务端要求字段名为 "teams.json"，类型为二进制
        "json": ("teams.json", json_data, "application/json")
    }
    resp = requests.post(url, files=files, headers={
        "Authorization": f"Basic {encoded_string}"
    })
    print("队伍post", resp.text)

    resp = requests.get(f"{domserver}/api/v4/contests/{cid}/teams")
    print("队伍get", resp)
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
    
    
    json_data = json.dumps(accounts, ensure_ascii=False).encode('utf-8')
    url = f"{domserver}/api/v4/users/accounts"
    files = {
        "json": ("accounts.json", json_data, "application/json")
    }
    resp = requests.post(url, files=files, headers={
        "Authorization": f"Basic {encoded_string}"
    })
    print("账户post", resp.text)


def setup_dom():
    print("🚀开始安装 domserver")
    client = docker.from_env()
    container = client.containers.run(
        # 基础镜像
        "mariadb",

        # 容器名称
        name="dj-mariadb",

        # 环境变量
        environment={
            "MYSQL_ROOT_PASSWORD": "rootpw",
            "MYSQL_USER": "domjudge",
            "MYSQL_PASSWORD": "domserver_password",
            "MYSQL_DATABASE": "domjudge",
            "CONTAINER_TIMEZONE": "Asia/Shanghai"
        },

        # 端口映射（主机端口:容器端口）
        ports={"3306/tcp": 13306},

        # 交互模式参数
        stdin_open=True,  # -i 保持 STDIN 打开
        tty=True,         # -t 分配伪终端

        # MariaDB 特定参数
        command="--max-connections=1000",  # 传递给容器的命令参数

        # 其他选项
        detach=True,  # 在后台运行（类似 docker run -d）

        # 自动删除容器（可选，根据需要启用）
        # auto_remove=True,

        # 重启策略（可选）
        # restart_policy={"Name": "always"}
    )
    try:
        mariadb_container = client.containers.get("dj-mariadb")

    except docker.errors.NotFound:
        print("错误: dj-mariadb 容器不存在，请先创建它")
        exit(1)

    # 运行 domserver 容器
    container = client.containers.run(
        # 基础镜像
        "domjudge/domserver:latest",

        # 容器名称
        name="domserver",

        # 环境变量
        environment={
            "MYSQL_HOST": "mariadb",
            "MYSQL_USER": "domjudge",
            "MYSQL_DATABASE": "domjudge",
            "MYSQL_PASSWORD": "domserver_password",
            "MYSQL_ROOT_PASSWORD": "rootpw"
        },

        # 链接到 MariaDB 容器
        links={"dj-mariadb": "mariadb"},

        # 端口映射（主机端口:容器端口）
        ports={"80/tcp": 12345},

        # 交互模式参数
        stdin_open=True,  # -i 保持 STDIN 打开
        tty=True,         # -t 分配伪终端

        # 其他选项
        detach=True,      # 在后台运行

        # 自动删除容器（可选）
        # auto_remove=True,

        # 重启策略（可选）
        # restart_policy={"Name": "always"}
    )


def get_domjudge_secrets(container_name="domserver"):
    try:
        # 创建 Docker 客户端
        client = docker.from_env()

        # 获取 DomServer 容器
        container = client.containers.get(container_name)

        # 获取初始管理员密码
        print("正在获取初始管理员密码...")
        admin_pass = container.exec_run(
            "cat /opt/domjudge/domserver/etc/initial_admin_password.secret",
            tty=True,
            stdin=True
        ).output.decode().strip()

        # 获取 REST API 密钥
        print("正在获取 REST API 密钥...")
        api_secret: str = container.exec_run(
            "cat /opt/domjudge/domserver/etc/restapi.secret",
            tty=True,
            stdin=True
        ).output.decode().strip()
        api_key = api_secret.split()[-1]
        d, created = DomServerSave.objects.update_or_create(
            singleton_id=1,  # Lookup field (unique)
            defaults={  # Fields to update/create
                'admin': 'admin',
                'init_passwd': admin_pass,
                'api_key': api_key
            }
        )

        # 返回结果
        print("命令成功完成")
        return {
            "admin_password": admin_pass,
            "api_secret": api_secret
        }

    except NotFound:
        print(f"错误: 找不到名为 {container_name} 的容器")
        return None
    except APIError as e:
        print(f"Docker API 错误: {e}")
        return None
    except Exception as e:
        print(f"未知错误: {e}")
        return None


def remove_all_running_containers():
    try:
        # 创建 Docker 客户端
        client = docker.from_env()

        # 获取所有正在运行的容器
        running_containers = client.containers.list(all=True)

        if not running_containers:
            print("没有正在运行的容器")
            return

        print(f"发现 {len(running_containers)} 个正在运行的容器，开始删除...")

        # 删除每个容器
        for container in running_containers:
            try:
                print(f"删除容器: {container.name} ({container.id})")
                container.remove(force=True)  # 强制删除（包括运行中的容器）
            except docker.errors.APIError as e:
                print(f"删除容器 {container.name} 失败: {e}")

        print("所有正在运行的容器已删除")

    except docker.errors.DockerException as e:
        print(f"连接Docker失败: {e}")
    except Exception as e:
        print(f"发生错误: {e}")


# 执行删除操作
if __name__ == "__main__":
    remove_all_running_containers()
