from datetime import timedelta
import secrets
import string
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import random


def generate_domserver_password():
    """生成10位随机密码"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(10))


class DomServerSave(models.Model):
    singleton_id = models.IntegerField(default=1, unique=True, editable=False)
    admin = models.CharField(max_length=100)
    init_passwd = models.CharField(max_length=100)
    api_key = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['singleton_id'], name='unique_singleton')
        ]


class MainProblem(models.Model):
    title = models.CharField(max_length=100)
    problem_char_id = models.CharField(max_length=100, unique=True)
    content = models.TextField()
    time_limit = models.IntegerField(default=1)
    mem_limit = models.IntegerField(default=512)
    test_case_path = models.TextField()
    sample_path = models.TextField()
    ac_count = models.IntegerField(default=0)
    submit_count = models.IntegerField(default=0)
    create_at = models.DateTimeField(auto_now_add=True)
    edit_at = models.DateTimeField(auto_now=True)
    special_judge_path = models.TextField(null=True)
    is_public = models.BooleanField(default=True)


class CompetitionProblem(models.Model):
    title = models.CharField(max_length=100)
    problem_char_id = models.CharField(max_length=100, unique=True)
    content = models.TextField()
    time_limit = models.IntegerField(default=1)
    mem_limit = models.IntegerField(default=512)
    test_case_path = models.TextField()
    sample_path = models.TextField()
    ac_count = models.IntegerField(default=0)
    submit_count = models.IntegerField(default=0)
    create_at = models.DateTimeField(auto_now_add=True)
    edit_at = models.DateTimeField(auto_now=True)
    special_judge_path = models.TextField(null=True)
    order_tag = models.CharField(max_length=2)
    # is_public = models.BooleanField(default=False)


class JudgeUser(AbstractUser):
    ac_count = models.IntegerField(default=0)  # AC题目计数
    nickname = models.CharField(max_length=20, blank=True)
    submit_count = models.IntegerField(default=0)
    stu_id = models.TextField()
    solved = models.ManyToManyField(MainProblem, related_name='solved')
    solved_contest = models.ManyToManyField(
        CompetitionProblem, related_name='solved_contest')
    tried = models.ManyToManyField(MainProblem, related_name='tried')
    avatar = models.TextField(null=True)
    rating = models.IntegerField(default=0)
    bio = models.CharField(max_length=100, blank=True)
    email_verified = models.BooleanField(default=False)
    domserver_password = models.TextField(default=generate_domserver_password)

    def save(self, *args, **kwargs):
        if not self.nickname:  # 如果 nickname 为空
            self.nickname = self.username  # 设置为 username
        super().save(*args, **kwargs)


class Submission(models.Model):
    # id = models.IntegerField(serialize=True, default=0)
    STATUS_CHOICES = [
        ('PD', 'Pending'),
        ('AC', 'Accepted'),
        ('WA', 'WrongAnswer'),
        ('RE', 'RunError'),
        ('TLE', 'TimeLimit'),
        ('MLE', 'MemLimit'),
        ('RJ', 'Reject'),
        ('CE', 'ComplieError')
    ]
    user = models.ForeignKey(JudgeUser, on_delete=models.CASCADE)
    problem = models.ForeignKey(MainProblem, on_delete=models.CASCADE)
    code = models.TextField()
    language = models.CharField(max_length=20)
    status = models.CharField(
        max_length=3, choices=STATUS_CHOICES, default='PD')
    created_at = models.DateTimeField(auto_now_add=True)


class ProblemTags(models.Model):
    title = models.CharField(max_length=50, unique=True)
    problem = models.ManyToManyField(MainProblem, related_name='tags')
    color = models.CharField(max_length=16)

    def save(self, *args, **kwargs):
        # 仅当未设置颜色时生成随机颜色
        if not self.color:
            self.color = self.generate_random_color()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_random_color():
        colorls = ["red", "pink", "purple", "deep-purple", "indigo", "blue", "light-blue", "cyan", "teal",
                   "green", "light-green", "lime", "yellow", "amber", "orange", "deep-orange", "brown", "blue-grey"]
        patthen = ["lighten", "darken", "accent"]
        num = random.randint(1, 4)
        ch = random.choice(colorls)
        pt = random.choice(patthen)
        return f"{ch}-{pt}-{num}"


class CompetitionGroup(models.Model):
    title = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=16)
    basic_rate = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        # 仅当未设置颜色时生成随机颜色
        if not self.color:
            self.color = ProblemTags.generate_random_color()
        super().save(*args, **kwargs)


class Competition(models.Model):
    name = models.CharField(max_length=100)
    cid = models.CharField(max_length=100)
    description = models.TextField()
    is_archive = models.BooleanField(default=False)
    active_time = models.DateTimeField(auto_now_add=True)
    start_time = models.DateTimeField(blank=True)
    frozen_duration = models.DurationField(blank=True)
    finish_time = models.DateTimeField(blank=True)
    registered = models.ManyToManyField(
        JudgeUser, through='ContestRegistration', related_name='registered_contest')
    all_register_before_start = models.DurationField(
        default=timedelta(minutes=1))
    problems = models.ManyToManyField(
        CompetitionProblem, related_name='problems')
    submissions = models.ManyToManyField(
        Submission, related_name='submissions')
    group = models.ForeignKey(CompetitionGroup, on_delete=models.CASCADE)
    is_rated = models.BooleanField(default=True)
    scoreboard_final = models.JSONField(null=True)


class UserRatingHistory(models.Model):
    user = models.ForeignKey(
        JudgeUser, on_delete=models.CASCADE, related_name="rating_histories")
    rating = models.IntegerField()  # 变更后的 rating 值
    previous_rating = models.IntegerField()  # 变更前的 rating 值（可选）
    timestamp = models.DateTimeField(default=timezone.now)  # 变更时间
    reason = models.CharField(max_length=100, blank=True)
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)

    class Meta:
        ordering = ["-timestamp"]  # 按时间降序排列


class ContestRegistration(models.Model):
    user = models.ForeignKey('JudgeUser', on_delete=models.CASCADE)
    contest = models.ForeignKey('Competition', on_delete=models.CASCADE)
    registration_time = models.DateTimeField(default=timezone.now)
    prefix = models.CharField(max_length=100)
    # 例如：pending, approved, rejected
    status = models.CharField(max_length=20, default='accept')
    submissions = models.JSONField(null=True)

    class Meta:
        unique_together = ('user', 'contest')  # 确保用户不能重复注册同一比赛


class ContestSubmission(models.Model):
    sid = models.IntegerField()
    contest = models.ForeignKey(Competition, on_delete=models.CASCADE)
    user = models.ForeignKey(JudgeUser, on_delete=models.CASCADE)
    code = models.TextField()
    problem = models.ForeignKey(CompetitionProblem, on_delete=models.CASCADE)
    time = models.CharField(max_length=20)
