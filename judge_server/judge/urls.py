from django.urls import path
from .views import *

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('register/', RegisterView.as_view(), name='register'),
    path('user_avatar/', AvatarChangeView.as_view(), name='avatar-change'),
    path('user_bio/', BioChangeView.as_view(), name='bio-change'),
    path('get_user_profile/', GetPersonsProfile.as_view(), name='get-profile'),


    path('submit/', SubmitView.as_view(), name='submit'),
    path('submit_file/', SubmitCodeFileView.as_view(), name='submit-code'),
    path('submission/<int:submission_id>/',
         SubmissionStatusView.as_view(), name='submission-status'),

    path('add_problem/', ProblemUploadView.as_view(), name='add-problem'),
    path('get_problems/', ProblemGetView.as_view(), name='get-problems'),
    path('get_tag_color/', GetTagColor.as_view(), name='get-tag-color'),
    path('problem_detail/', GetProblemDetail.as_view(), name='problem-detail'),

    path('reset_dom/', ResetDomView.as_view(), name='reset-dom'),

    path('add_contest_rate_group/', AddContestGroup.as_view(),
         name='add-contest-rate-group'),
    path('add_contest/', AddCompetitionDesView.as_view(),
         name='add-contest'),
    path('get_all_contests/', GetAllCompetitionView.as_view(),
         name='get-all-contests'),
    path('get_contest/', GetoneContest.as_view(),
         name='get-contest'),
    path('register_contest/', UserRegContestView.as_view(), name='reg-contest'),
    path('add_contest_problem/', AddContestProblem.as_view(),
         name='add-contest-problem'),
    path('get_contest_problem/', GetContestProblem.as_view(),
         name='get-contest-problem'),
    path('submit_contest_problem/', SubmitContestProblem.as_view(),
         name='submit-contest-problem'),
    path('get_contest_submission/', PostGetContestSubmission.as_view(),
         name='get-contest-submission'),
]
