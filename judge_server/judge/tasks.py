# judge/tasks.py
from celery import shared_task
from .models import Submission, JudgeUser, MainProblem
from .utils import call_judge_cpp, call_judge_python  # 判题逻辑实现
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
