from django.urls import path

from .views import MemberDeleteView, MemberListCreateView, ProjectDetailView, ProjectListCreateView

urlpatterns = [
    path("", ProjectListCreateView.as_view(), name="project-list"),
    path("<int:pk>/", ProjectDetailView.as_view(), name="project-detail"),
    path("<int:project_id>/members/", MemberListCreateView.as_view(), name="member-list"),
    path("<int:project_id>/members/<int:pk>/", MemberDeleteView.as_view(), name="member-detail"),
]
