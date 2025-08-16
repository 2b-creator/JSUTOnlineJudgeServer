from datetime import timedelta
from django.apps import apps
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.views import APIView
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job
from .apps import JudgeConfig
from .models import CompetitionGroup, ContestRegistration, Submission, JudgeUser, MainProblem, ProblemTags
from .models import JudgeUser
from .tasks import get_domjudge_secrets, import_reg_to_dom, judge_submission, remove_all_running_containers, setup_dom
from django.utils import timezone
from django.http import StreamingHttpResponse
from .config import *
from django.core.files.storage import FileSystemStorage
from pathlib import Path
from .utils import *
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import zipfile
import os

logger = logging.getLogger(__name__)


class LoginView(APIView):
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)

        if user:
            refresh = RefreshToken.for_user(user)
            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'avatar': user.avatar,
                'username': user.username,
                'aclist': [i.id for i in user.solved.all()],
                'submit_count': user.submit_count,
                'ac_count': user.ac_count,
                'acrank': getUserRank(user),
                'rating': user.rating,
                'ratingrank': getUserRatingRank(user),
            })
        return Response({'error': 'Invalid credentials'}, status=400)


class AvatarChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        avatar = request.data.get('avatar')
        user = request.user
        user.avatar = avatar
        user.save()
        return Response({"status": "Accept"}, status=201)


class BioChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        bio = request.data.get('bio')
        user = request.user
        user.bio = bio
        user.save()
        return Response({"status": "Accept"}, status=201)


class RegisterView(APIView):
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        stu_id = request.data.get('stu_id')

        if JudgeUser.objects.filter(username=username).exists():
            return Response({'error': 'Username exists'}, status=400)

        user = JudgeUser.objects.create_user(
            username=username, password=password, stu_id=stu_id)
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'ac_count': user.ac_count
        }, status=201)


class SubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        problem_char_id = request.data.get('problem_char_id')
        code = request.data.get('code')
        language = request.data.get('language_mode')

        try:
            problem = MainProblem.objects.get(problem_char_id=problem_char_id)
        except MainProblem.DoesNotExist:
            return Response({'error': 'Problem not found'}, status=status.HTTP_404_NOT_FOUND)

        # 创建提交记录
        submission = Submission.objects.create(
            user=request.user,
            problem=problem,
            code=code,
            language=language,
            status='PD'  # Pending
        )

        logger.info(
            f"Created submission {submission.id} for problem {problem_char_id}")

        # 异步调用判题任务
        try:
            judge_submission.delay(submission.id, language)
            logger.info(f"Started Celery task for submission {submission.id}")

            return Response({
                'message': 'Submission received and queued for judging',
                'submission_id': submission.id,
                'status': 'pending',
                'created_at': timezone.now().isoformat()
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(f"Failed to start Celery task: {str(e)}")
            submission.status = 'ER'
            submission.save()
            return Response({
                'error': 'Failed to queue submission for judging',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# judge/views.py


class SubmitCodeFileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        uploaded_file = request.FILES['file']
        filenamesplit = uploaded_file.name.split('_')
        username = filenamesplit[0]
        charid = filenamesplit[1]
        mode = filenamesplit[2]
        fs = FileSystemStorage()
        saved_file = fs.save(uploaded_file.name, uploaded_file)
        file_path = fs.path(saved_file)
        code = open(file_path, "r").read()
        os.remove(file_path)
        problem = MainProblem.objects.get(problem_char_id=charid)

        submission = Submission.objects.create(
            user=request.user,
            problem=problem,
            code=code,
            language=mode,
            status='PD'  # Pending
        )

        logger.info(
            f"Created submission {submission.id} for problem {charid}")

        try:
            judge_submission.delay(submission.id, mode)
            logger.info(f"Started Celery task for submission {submission.id}")

            return Response({
                'message': 'Submission received and queued for judging',
                'submission_id': submission.id,
                'status': 'pending',
                'created_at': timezone.now().isoformat()
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(f"Failed to start Celery task: {str(e)}")
            submission.status = 'ER'
            submission.save()
            return Response({
                'error': 'Failed to queue submission for judging',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SubmissionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, submission_id):
        try:
            submission = Submission.objects.get(
                id=submission_id, user=request.user)
            return Response({
                'submission_id': submission.id,
                'problem_name': submission.problem.title,
                'status': submission.status,
                'created_at': submission.created_at,
                'language': submission.language
            })
        except Submission.DoesNotExist:
            return Response({'error': 'Submission not found'}, status=status.HTTP_404_NOT_FOUND)


class ProblemUploadView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        uploaded_file = request.FILES['file']
        file_name = uploaded_file.name
        fs = FileSystemStorage()
        saved_file = fs.save(file_name, uploaded_file)
        file_path = fs.path(saved_file)
        file_path = Path(file_path)
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            # 解压文件到指定目录
            zip_ref.extractall(file_path.cwd()/"problems"/file_path.stem)
        logger.info(str(file_path.cwd()/"problems"/file_path.stem))
        os.remove(file_path)
        p = add_problem(file_path.cwd()/"problems"/file_path.stem)

        return Response({'Status': 'Accepted'}, status=status.HTTP_201_CREATED)


class ProblemGetView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request):

        problems = MainProblem.objects.all()
        user = request.user
        dic = {}
        ls = []
        for i in problems:
            if not i.is_public:
                continue
            tags = []
            for tag in i.tags.all():
                tags.append(tag.title)
            if i.submit_count == 0:
                ac_sta = 0
            else:
                ac_sta = str(float('{:.2f}'.format(
                    i.ac_count/i.submit_count*100)))+'%'
            print(i.ac_count, i.submit_count, ac_sta)
            if user.is_authenticated:
                isSolved = (i in user.solved.all())
                dic_one = {
                    "problem_id": i.id,
                    "char_id": i.problem_char_id,
                    "title": i.title,
                    "tags": tags,
                    "ac_sta": ac_sta,
                    "isSolved": isSolved
                }
            else:
                dic_one = {
                    "problem_id": i.id,
                    "char_id": i.problem_char_id,
                    "title": i.title,
                    "tags": tags,
                    "ac_sta": ac_sta,
                    "isSolved": False
                }
            ls.append(dic_one)
        dic["data"] = ls
        return Response(dic, status=status.HTTP_200_OK)


class GetTagColor(APIView):
    def get(self, request):
        tags = ProblemTags.objects.all()
        ls = {}
        for i in tags:
            ls[i.title] = i.color

        return Response(ls, status=status.HTTP_200_OK)


class GetProblemDetail(APIView):
    def post(self, request):
        char_id = request.data.get("char_id")
        problem = MainProblem.objects.get(problem_char_id=char_id)
        sample_path = problem.sample_path
        if not problem.is_public:
            return Response({"status": "404"}, status=status.HTTP_404_NOT_FOUND)
        dic = {
            "title": problem.title,
            "content": render_markdown_to_html(problem.content),
            "timelimit": problem.time_limit,
            "memlimit": problem.mem_limit,
            "submit_count": problem.submit_count,
            "ac_count": problem.ac_count,
            "samples": getTestCasesFromPath(Path(sample_path))
        }
        return Response(dic, status=status.HTTP_200_OK)


class GetPersonsProfile(APIView):
    def post(self, request):
        username = request.data.get('username')
        user = JudgeUser.objects.get(username=username)
        if user:
            dic = {}
            dic["nickname"] = user.nickname
            dic["bio"] = user.bio
            thirty_days_ago = timezone.now() - timedelta(days=30)
            count = Submission.objects.filter(
                user=user,
                created_at__gte=thirty_days_ago
            ).count()
            dic["month_submission_count"] = count
            dic["ac_count"] = user.ac_count
            dic["submit_count"] = user.submit_count
            dic["rating"] = user.rating
            dic["rating_rank"] = getUserRatingRank(user)
            dic["rating_history"] = get_user_rating_history_in_intervals(user)
            dic["tried_detail"] = get_user_problems(user)
            dic["participated_contest"] = get_user_competitions(user)
            dic["submit_data"] = get_user_submission_data(
                user, datetime.now().year)
            return Response(dic, status=status.HTTP_200_OK)
        return Response({"Error": "Not Found"}, status=status.HTTP_404_NOT_FOUND)

# todo


class AddContestGroup(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        name = request.data.get('group')
        basic_rate = request.data.get('basic_rate')
        gp = CompetitionGroup.objects.create(title=name, basic_rate=basic_rate)
        gp.save()
        return Response({"status": "OK"}, status=status.HTTP_201_CREATED)


class AddCompetitionDesView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        cid = request.data.get('cid')
        description = request.data.get('text')
        group = request.data.get("rate_group")
        rate_group = CompetitionGroup.objects.get(title=group)
        resp = requests.get(f"{domserver}/api/v4/contests/{cid}")
        gets = resp.json()
        start_time = gets['start_time']
        finish_time = gets['end_time']
        time_obj = datetime.strptime(
            gets['scoreboard_freeze_duration'], "%H:%M:%S.%f").time()
        frozen_duration = timedelta(
            hours=time_obj.hour,
            minutes=time_obj.minute,
            seconds=time_obj.second,
            microseconds=time_obj.microsecond
        )
        name = gets['name']
        contest = Competition.objects.create(
            cid=cid, group=rate_group, description=description, start_time=start_time, finish_time=finish_time, frozen_duration=frozen_duration, name=name)
        contest.save()
        judge_config = apps.get_app_config('judge')

        # Use existing scheduler or create once
        if not hasattr(judge_config, 'scheduler'):
            scheduler = BackgroundScheduler()
            scheduler.add_jobstore(DjangoJobStore(), "default")
            scheduler.start()
            judge_config.scheduler = scheduler
        else:
            scheduler = judge_config.scheduler
        start_time = datetime.fromisoformat(contest.start_time)
        job_id = f"contest_init_job_{scheduler}_getdom"
        scheduler.add_job(
            get_domjudge_secrets,
            'date',
            run_date=start_time-timedelta(seconds=6),
            # args=[data],  # 传递整个JSON数据到任务
            id=job_id,
        )
        job_id = f"contest_init_job_{scheduler}_regdom"
        scheduler.add_job(
            import_reg_to_dom,
            'date',
            run_date=start_time-timedelta(seconds=5),
            id=job_id,
            kwargs={'contest': contest}
        )
        return Response({"status": "OK", 'create_contest_job_id': job_id}, status=status.HTTP_201_CREATED)


class GetAllCompetitionView(APIView):
    def get(self, request):
        contests = Competition.objects.all()
        current_time = timezone.now()
        ls_res = []
        for i in contests:
            if current_time < i.active_time:
                continue
            else:
                dic = {
                    'id': i.id,
                    'name': i.name,
                    'start_time': i.start_time,
                    'finish_time': i.finish_time,
                    'freeze_time': i.finish_time-i.frozen_duration,
                    'is_past': False if current_time < i.finish_time else True,
                    'can_reg': True if current_time < i.start_time - i.all_register_before_start else False,
                    "is_rated": i.is_rated,
                    'dot_color': 'green' if i.start_time < current_time < i.finish_time else 'dark',
                    'group': i.group.title,
                    'reg_count': len(i.registered.all())
                }
                ls_res.append(dic)
        return Response(ls_res, status=status.HTTP_200_OK)


class UserRegContestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        contest_id = request.data.get('contest_id')
        user = request.user

        # 验证比赛是否存在
        try:
            contest = Competition.objects.get(id=contest_id)
        except Competition.DoesNotExist:
            return self._contest_not_found_response()
        # 检查所有报名条件
        error_response = self._validate_registration(contest, user)
        if error_response:
            return error_response

        # 创建报名记录（使用 through 模型）
        ContestRegistration.objects.create(
            user=user,
            contest=contest,
            prefix='jsut',
            status='accept'  # 可根据需求调整状态
        )

        return Response(
            {"message": "报名成功"},
            status=status.HTTP_201_CREATED
        )

    def _validate_registration(self, contest, user):
        """集中验证所有报名条件"""
        if self._is_already_registered(contest, user):
            return self._already_registered_response()

        current_time = timezone.now()

        if self._is_contest_started(contest, current_time):
            return self._contest_started_response()

        if self._is_registration_closed(contest, current_time):
            return self._registration_closed_response()

        return None

    # 以下为辅助方法（提高代码可读性和复用性）
    def _is_already_registered(self, contest, user):
        return contest.registered.filter(pk=user.pk).exists()

    def _is_contest_started(self, contest, current_time):
        return current_time >= contest.start_time

    def _is_registration_closed(self, contest, current_time):
        latest_reg_time = contest.start_time - contest.all_register_before_start
        return current_time >= latest_reg_time

    # 预定义的错误响应（避免重复代码）
    def _contest_not_found_response(self):
        return Response(
            {"error": "比赛不存在"},
            status=status.HTTP_404_NOT_FOUND
        )

    def _already_registered_response(self):
        return Response(
            {"error": "您已经报名过该比赛"},
            status=status.HTTP_400_BAD_REQUEST
        )

    def _contest_started_response(self):
        return Response(
            {"error": "比赛已经开始，无法报名"},
            status=status.HTTP_400_BAD_REQUEST
        )

    def _registration_closed_response(self):
        return Response(
            {"error": "已超过报名截止时间"},
            status=status.HTTP_400_BAD_REQUEST
        )


class GetoneContest(APIView):
    def post(self, request):
        current_time = timezone.now()
        cid = request.data.get('cid')
        try:
            contest = Competition.objects.get(id=cid)
        except Competition.DoesNotExist:
            return Response({"error": "比赛不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'id': contest.id,
            'name': contest.name,
            'start_time': contest.start_time,
            'finish_time': contest.finish_time,
            'freeze_time': contest.finish_time-contest.frozen_duration,
            'is_started': True if current_time > contest.start_time else False,
            'is_past': False if current_time < contest.finish_time else True,
            'can_reg': True if current_time < contest.start_time - contest.all_register_before_start else False,
            "is_rated": contest.is_rated,
            'dot_color': 'green' if contest.start_time < current_time < contest.finish_time else 'dark',
            'group': contest.group.title,
            'text': render_markdown_to_html(contest.description),
            'reg_count': contest.registered.count(),
        }, status=status.HTTP_200_OK)


class AddContestProblem(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        uploaded_file = request.FILES['file']
        file_name = uploaded_file.name
        fs = FileSystemStorage()
        saved_file = fs.save(file_name, uploaded_file)
        file_path = fs.path(saved_file)
        file_path = Path(file_path)
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            # 解压文件到指定目录
            zip_ref.extractall(
                file_path.cwd()/"contest_problems"/file_path.stem)
        logger.info(str(file_path.cwd()/"contest_problems"/file_path.stem))
        os.remove(file_path)
        p = add_contest_problem(
            file_path.cwd()/"contest_problems"/file_path.stem)

        return Response({'Status': 'Accepted'}, status=status.HTTP_201_CREATED)


class GetContestProblem(APIView):
    # permission_classes = [IsAuthenticatedOrReadOnly]

    def post(self, request):
        user: JudgeUser = request.user
        contest_id = request.data.get('id')
        contest = Competition.objects.get(id=contest_id)
        problems = contest.problems.all().order_by('order_tag')
        if user.is_authenticated:
            problem_data = [{
                'title': problem.title,
                'problem_char_id': problem.problem_char_id,
                'content': problem.content,
                'solved': (problem in user.solved_contest.all()),
                'order_tag': problem.order_tag
            } for problem in problems]
        else:
            problem_data = [{
                'title': problem.title,
                'problem_char_id': problem.problem_char_id,
                'content': problem.content,
                'solved': False,
                'order_tag': problem.order_tag
            } for problem in problems]

        return Response({'problems': problem_data})


class GetContestProblemDetail(APIView):
    def post(self, request):
        char_id = request.data.get('char_id')
        problem = CompetitionProblem.objects.get(problem_char_id=char_id)
        sample_path = problem.sample_path
        dic = {
            "title": problem.title,
            "content": render_markdown_to_html(problem.content),
            "timelimit": problem.time_limit,
            "memlimit": problem.mem_limit,
            "submit_count": problem.submit_count,
            "ac_count": problem.ac_count,
            "samples": getTestCasesFromPath(Path(sample_path))
        }
        return Response(dic, status=status.HTTP_200_OK)


class SubmitContestProblem(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        uploaded_file = request.FILES['file']
        filenamesplit = uploaded_file.name.split('-')
        username = filenamesplit[0]
        charId = filenamesplit[1]

        contest_id = filenamesplit[2]
        lang = filenamesplit[3]
        tagId = Competition.objects.get(
            id=contest_id).problems.get(problem_char_id=charId).order_tag
        fs = FileSystemStorage()
        saved_file = fs.save(uploaded_file.name, uploaded_file)
        contest = Competition.objects.get(id=contest_id)
        finish_time = contest.finish_time
        now = timezone.now()
        if now > finish_time:
            return Response({"sid": -1}, status=200)
        cid = contest.cid
        file_path = Path(fs.path(saved_file))
        resp = requests.get(f"{domserver}/api/v4/contests/{cid}/problems")
        respdic = resp.json()
        for i in respdic:
            if i['short_name'] == tagId:
                submit_id = i['id']
                break
        user = JudgeUser.objects.get(username=username)
        domserver_password = user.domserver_password
        user_passwd = f"{username}:{domserver_password}"
        string_bytes = user_passwd.encode('utf-8')
        encoded_string = base64.b64encode(string_bytes).decode('utf-8')
        payload = {
            'code[]': (file_path.name, open(file_path, 'rb')),
            "language_id": (None, lang),
            "problem_id": (None, submit_id)
        }
        headers = {
            "Authorization": f"Basic {encoded_string}"
        }
        resp = requests.post(
            f"{domserver}/api/v4/contests/{cid}/submissions", files=payload, headers=headers)
        os.remove(file_path)
        print(resp.json())
        sid = resp.json()['id']
        return Response({"sid": sid}, status=200)


class PostGetContestSubmission(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def post(data, request):
        contest_id = request.data.get('contest_id')
        contest = Competition.objects.get(id=contest_id)
        username = request.data.get('username')
        sid = request.data.get('sid', 0)
        char_id = request.data.get('charid', 0)
        current_user: JudgeUser = contest.registered.get(username=username)
        registration = ContestRegistration.objects.get(
            user=current_user, contest=contest)
        prefix = registration.prefix
        team_id = f"{prefix}-{registration.id}"
        domserver_password = current_user.domserver_password
        user_passwd = f"{username}:{domserver_password}"
        string_bytes = user_passwd.encode('utf-8')
        encoded_string = base64.b64encode(string_bytes).decode('utf-8')
        headers = {
            "Authorization": f"Basic {encoded_string}"
        }
        resp = requests.get(
            f"{domserver}/api/v4/contests/{contest.cid}/judgements", headers=headers)
        resp_dic = resp.json()
        if sid == 0 or char_id == 0:
            ls_dic = []
            for i in resp_dic:
                sidone = i['id']
                resp = requests.get(f"{domserver}/api/v4/contests/{contest.cid}/submissions/{sidone}")
                gets = resp.json()['problem_id']
                resp = requests.get(f"{domserver}/api/v4/contests/{contest.cid}/problems/{gets}")
                order_tag = resp.json()['label']
                i["order_tag"] = order_tag
                ls_dic.append(i)
            return Response(ls_dic, status=status.HTTP_200_OK)
        else:
            result = [i["judgement_type_id"]
                      for i in resp_dic if str(sid) == i["id"]]
            if len(result) == 0:
                return Response({"result": "PD"}, status=status.HTTP_200_OK)
            elif result[0] == "AC":
                cp = CompetitionProblem.objects.get(problem_char_id=char_id)
                current_user.solved_contest.add(cp)
                return Response({"result": result[0]}, status=status.HTTP_200_OK)
            else:
                return Response({"result": result[0]}, status=status.HTTP_200_OK)


class ScoreboardGet(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def post(self, request):
        user = request.user
        contest_id = request.data.get('contest_id')
        cid = Competition.objects.get(id=contest_id).cid
        if user.is_authenticated:
            domserver_password = user.domserver_password
            user_passwd = f"{user.username}:{domserver_password}"
            string_bytes = user_passwd.encode('utf-8')
            encoded_string = base64.b64encode(string_bytes).decode('utf-8')
            headers = {
                "Authorization": f"Basic {encoded_string}"
            }
            resp = requests.get(
                f"{domserver}/api/v4/contests/{cid}/scoreboard", headers=headers)
        else:
            resp = requests.get(
                f"{domserver}/api/v4/contests/{cid}/scoreboard")
        resp_dic = resp.json()
        return Response(resp_dic, status=status.HTTP_200_OK)


class ResetDomView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):  # Fix method signature (self, request)
        judge_config = apps.get_app_config('judge')

        # Use existing scheduler or create once
        if not hasattr(judge_config, 'scheduler'):
            scheduler = BackgroundScheduler()
            scheduler.add_jobstore(DjangoJobStore(), "default")
            scheduler.start()
            judge_config.scheduler = scheduler
        else:
            scheduler = judge_config.scheduler

        # Schedule jobs using top-level functions
        remove_job_id = f"remove_dom_{datetime.now().timestamp()}"
        reinstall_job_id = f"reinstall_dom_{datetime.now().timestamp()}"
        get_dom_id = f"get_dom_{datetime.now().timestamp()}"
        scheduler.add_job(
            remove_all_running_containers,
            'date',
            run_date=datetime.now() + timedelta(seconds=1),
            id=remove_job_id
        )

        scheduler.add_job(
            setup_dom,
            'date',
            run_date=datetime.now() + timedelta(seconds=3),
            id=reinstall_job_id
        )
        scheduler.add_job(
            get_domjudge_secrets,
            'date',
            run_date=datetime.now() + timedelta(seconds=10),
            id=get_dom_id
        )
        return Response({"status": "DOM reset scheduled"})


class CheckUserRegContestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        contest_id = request.data.get("contest_id")
        contest = Competition.objects.get(id=contest_id)
        user = request.user
        isreg = False
        if user in contest.registered.all():
            isreg = True
        dic = {
            "isreg": isreg
        }
        return Response(dic)


class GetContestScoreboard(APIView):
    # permission_classes = [IsAuthenticatedOrReadOnly]

    def post(self, request):
        user = request.user
        contest_id = request.data.get('contest_id')
        contest = Competition.objects.get(id=contest_id)
        cid = contest.cid
        if user.is_authenticated:
            judgeuser: JudgeUser = user
            dompwd = judgeuser.domserver_password
            username = judgeuser.username
            user_passwd = f"{username}:{dompwd}"
            string_bytes = user_passwd.encode('utf-8')
            encoded_string = base64.b64encode(string_bytes).decode('utf-8')
            headers = {
                "Authorization": f"Basic {encoded_string}"
            }
            resp = requests.get(
                f"{domserver}/api/v4/contests/{cid}/scoreboard", headers=headers)
        else:
            resp = requests.get(
                f"{domserver}/api/v4/contests/{cid}/scoreboard")
        dic = resp.json()
        return Response(dic, status=200)

        # class ProblemGetView(APIView):
        #     permission_classes = [IsAuthenticatedOrReadOnly]

        #     def get(self, request):

        #         problems = MainProblem.objects.all()
        #         user = request.user
        #         dic = {}
        #         ls = []
        #         for i in problems:
        #             if not i.is_public:
        #                 continue
        #             tags = []
        #             for tag in i.tags.all():
        #                 tags.append(tag.title)
        #             if i.submit_count == 0:
        #                 ac_sta = 0
        #             else:
        #                 ac_sta = str(float('{:.2f}'.format(
        #                     i.ac_count/i.submit_count*100)))+'%'
        #             print(i.ac_count, i.submit_count, ac_sta)
        #             if user.is_authenticated:
        #                 isSolved = (i in user.solved.all())
        #                 dic_one = {
        #                     "problem_id": i.id,
        #                     "char_id": i.problem_char_id,
        #                     "title": i.title,
        #                     "tags": tags,
        #                     "ac_sta": ac_sta,
        #                     "isSolved": isSolved
        #                 }
        #             else:
        #                 dic_one = {
        #                     "problem_id": i.id,
        #                     "char_id": i.problem_char_id,
        #                     "title": i.title,
        #                     "tags": tags,
        #                     "ac_sta": ac_sta,
        #                     "isSolved": False
        #                 }
        #             ls.append(dic_one)
        #         dic["data"] = ls
        #         return Response(dic, status=status.HTTP_200_OK)
