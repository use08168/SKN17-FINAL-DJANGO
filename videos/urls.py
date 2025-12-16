from django.urls import path
from . import views 

app_name = 'videos'

urlpatterns = [
    # 하이라이트(홈)
    path("home", views.home, name="home"),
    path('list/', views.get_video_list_api, name='get_video_list'),
    path('play/<int:video_id>/', views.play, name='play'),

    # 내 영상
    path('myvideos', views.my_videos, name='myvideos'),
    path('upload', views.upload_video, name='upload'),
    path('myvideos/download/<int:video_id>/', views.process_download, name='download'),
    path('myvideos/delete/<int:video_id>/', views.delete_video, name='delete'),
    path('play/user/<int:video_id>/', views.play_user_video, name='play_user_video'),
]