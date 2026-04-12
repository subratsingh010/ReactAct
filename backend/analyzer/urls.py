from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    HealthView,
    JobRoleListCreateView,
    ProfileView,
    ResumeAnalysisListView,
    ResumeDetailView,
    ResumeParseView,
    ResumeListCreateView,
    RunAnalysisView,
    SignupView,
    TailorResumeView,
    OptimizeResumeQualityView,
    ExportAtsPdfLocalView,
    AutofillAnswersView,
    TailoredJobRunListView,
)

urlpatterns = [
    path('health/', HealthView.as_view()),
    path('signup/', SignupView.as_view()),
    path('parse-resume/', ResumeParseView.as_view()),
    path('token/', TokenObtainPairView.as_view()),
    path('token/refresh/', TokenRefreshView.as_view()),
    path('profile/', ProfileView.as_view()),
    path('job-roles/', JobRoleListCreateView.as_view()),
    path('resumes/', ResumeListCreateView.as_view()),
    path('resumes/<int:resume_id>/', ResumeDetailView.as_view()),
    path('analyses/', ResumeAnalysisListView.as_view()),
    path('run-analysis/', RunAnalysisView.as_view()),
    path('tailor-resume/', TailorResumeView.as_view()),
    path('optimize-resume-quality/', OptimizeResumeQualityView.as_view()),
    path('export-ats-pdf-local/', ExportAtsPdfLocalView.as_view()),
    path('autofill-answers/', AutofillAnswersView.as_view()),
    path('tailored-job-runs/', TailoredJobRunListView.as_view()),
]
