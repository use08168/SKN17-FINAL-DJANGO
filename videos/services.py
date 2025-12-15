import math
import json
import threading
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from .runpod import runpod_client
from payments.models import SubscribeHistory
from .models import UserInfo, HighlightVideo, UserUploadVideo, FileInfo, CommonCode, SubtitleInfo

# --- [상수 데이터] ---
TEAM_META_DATA = {
    'LG': {'full': 'LG 트윈스', 'mascot': '수타'},
    'HANWHA': {'full': '한화 이글스', 'mascot': '술이'},
    'SSG': {'full': 'SSG 랜더스', 'mascot': '란디'},
    'SAMSUNG': {'full': '삼성 라이온즈', 'mascot': '볼래요'},
    'NC': {'full': 'NC 다이노스', 'mascot': '반비'},
    'KT': {'full': 'KT 위즈', 'mascot': '똘이'},
    'LOTTE': {'full': '롯데 자이언츠', 'mascot': '눌이'},
    'KIA': {'full': 'KIA 타이거즈', 'mascot': '호거리'},
    'DOOSAN': {'full': '두산 베어스', 'mascot': '철'},
    'KIWOOM': {'full': '키움 히어로즈', 'mascot': '턱도리'},
}

# --- [Helper Functions] ---
def get_team_meta(user):
    """헤더 툴팁용 구단 정보 반환"""
    context = {'team_full_name': "KBO 리그", 'team_mascot': "마스코트"}
    if user and user.favorite_code:
        raw_code = user.favorite_code.common_code_value
        code_key = raw_code.replace('FAVORITE - ', '').replace('FAVORITE-', '').strip().upper()
        if code_key in TEAM_META_DATA:
            context['team_full_name'] = TEAM_META_DATA[code_key]['full']
            context['team_mascot'] = TEAM_META_DATA[code_key]['mascot']
    return context

def format_bytes(size):
    """바이트 단위 변환"""
    power = 2**10
    n = 0
    power_labels = {0 : 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

def _get_video_querysets(target_code, search_query='', sort_option='latest'):
    """(내부함수) 조건에 따른 영상 쿼리셋 생성"""
    TEAM_KOREA_MAP = {
        'K-BASEBALL': {'id': 12, 'name': '2025 K-BASEBALL SERIES'},
        'ASIAN': {'id': 13, 'name': 'ASIAN GAMES'},
        'OLYMPIC': {'id': 14, 'name': 'OLYMPICS'},
        'PREMIER': {'id': 15, 'name': 'WBSC PREMIER 12'},
        'WBC': {'id': 16, 'name': 'WORLD BASEBALL CLASSIC'},
    }
    KBO_TEAM_MAP = {
        'LG': 'LG', 'HANWHA': '한화', 'SSG': 'SSG', 'SAMSUNG': '삼성',
        'NC': 'NC', 'KT': 'KT', 'LOTTE': '롯데', 'KIA': 'KIA',
        'DOOSAN': '두산', 'KIWOOM': '키움'
    }

    my_team_qs = HighlightVideo.objects.none()
    other_qs = HighlightVideo.objects.all()
    current_display_name = ''
    is_team_korea = False

    if target_code in TEAM_KOREA_MAP:
        info = TEAM_KOREA_MAP[target_code]
        current_display_name = info['name']
        is_team_korea = True
        my_team_qs = HighlightVideo.objects.filter(video_category_id=info['id']).select_related('video_file').order_by('-match_date')
        other_qs = HighlightVideo.objects.none()
    else:
        korean_name = KBO_TEAM_MAP.get(target_code, '삼성')
        current_display_name = f"{korean_name}"
        is_team_korea = False
        
        my_team_qs = HighlightVideo.objects.filter(
            video_category_id=11,
            highlight_title__icontains=korean_name
        ).select_related('video_file').order_by('-match_date')

        other_qs = HighlightVideo.objects.filter(video_category_id=11).exclude(
            video_file_id__in=my_team_qs.values_list('video_file_id', flat=True)
        ).select_related('video_file')

    if not is_team_korea:
        if search_query:
            other_qs = other_qs.filter(highlight_title__icontains=search_query)
        
        if sort_option == 'oldest':
            other_qs = other_qs.order_by('match_date')
        elif sort_option == 'name':
            other_qs = other_qs.order_by('highlight_title')
        else:
            other_qs = other_qs.order_by('-match_date')

    return my_team_qs, other_qs, is_team_korea, current_display_name


# --- [Business Logics] ---
def get_home_context(user_id, search_query, req_team, sort_option='latest'):
    """홈 화면 데이터 구성 로직"""
    user = UserInfo.objects.get(user_id=user_id)
    has_history = SubscribeHistory.objects.filter(user=user).exists()
    meta_context = get_team_meta(user)
    
    context = {
        'user': user,
        'has_history': has_history,
        'show_plan_modal': not has_history,
        'sort_option': sort_option,
        **meta_context
    }

    # 1. 검색 모드
    if search_query:
        search_highlights = HighlightVideo.objects.filter(
            highlight_title__icontains=search_query
        ).select_related('video_file').order_by('-match_date')

        search_uploads = UserUploadVideo.objects.filter(
            user=user, use_yn=True, upload_title__icontains=search_query
        ).select_related('upload_file').order_by('-upload_date')

        context.update({
            'is_search_mode': True,
            'search_query': search_query,
            'search_highlights': search_highlights,
            'search_uploads': search_uploads,
            'show_plan_modal': False
        })
    
    # 2. 일반 모드
    else:
        if not req_team and user.favorite_code:
            req_team = user.favorite_code.common_code_value.replace('FAVORITE - ', '').replace('FAVORITE-', '').strip().upper()
        target_code = req_team if req_team else 'LG'

        my_team_qs, other_qs, is_team_korea, current_display_name = _get_video_querysets(target_code, '', sort_option)

        context.update({
            'is_search_mode': False,
            'my_team_videos': my_team_qs[:3],
            'other_videos': other_qs[:8],
            'current_team_name': current_display_name,
            'current_team_code': target_code,
            'is_team_korea': is_team_korea,
        })
    
    return context


def get_video_list_api_logic(section_type, page, target_code, search_query, sort_option):
    """영상 더보기 API 로직"""
    my_team_qs, other_qs, _, _ = _get_video_querysets(target_code, search_query, sort_option)

    if section_type == 'my_team':
        limit = 3
        queryset = my_team_qs
    else: 
        limit = 8
        queryset = other_qs

    paginator = Paginator(queryset, limit)
    
    if page > paginator.num_pages:
        return [], False

    videos_page = paginator.get_page(page)
    
    data = []
    for v in videos_page:
        data.append({
            'id': v.video_file_id, 
            'title': v.highlight_title,
            'date': v.match_date.strftime('%Y년 %m월 %d일'),
            'url': v.video_file.file_path.url,
        })
    
    return data, videos_page.has_next()


def get_play_context(user_id, video_id):
    """하이라이트 영상 재생 컨텍스트 (무료체험 로직 포함)"""
    user = UserInfo.objects.get(user_id=user_id)
    has_history = SubscribeHistory.objects.filter(user=user).exists()

    if not has_history: 
        if not user.free_use_yn:
            user.free_use_yn = True
            user.save()
        else:
            raise PermissionError("TRIAL_EXPIRED") 

    video = get_object_or_404(HighlightVideo, video_file_id=video_id)
    meta_context = get_team_meta(user)
    
    subtitle_data = "[]"
    try:
        sub_info = SubtitleInfo.objects.filter(video_file_id=video_id).first()
        if sub_info and sub_info.subtitle:
            subtitle_list = json.loads(sub_info.subtitle.decode('utf-8'))
            subtitle_data = json.dumps(subtitle_list, ensure_ascii=False)
    except Exception:
        pass 

    current_team_code = 'LG'
    if user.favorite_code:
        current_team_code = user.favorite_code.common_code_value.replace('FAVORITE - ', '').replace('FAVORITE-', '').strip().upper()

    return {
        'user': user,
        'video': video,
        'subtitle_data': subtitle_data,
        'current_team_code': current_team_code,
        'has_history': has_history,
        **meta_context
    }


def get_my_videos_context(user_id):
    """내 보관함 데이터 구성"""
    user = UserInfo.objects.get(user_id=user_id)
    
    if not SubscribeHistory.objects.filter(user=user).exists():
        raise PermissionError("NO_SUBSCRIPTION")

    meta_context = get_team_meta(user)
    
    active_sub = SubscribeHistory.objects.select_related('plan').filter(
        user=user
    ).filter(
        Q(subscribe_end_dt__gte=timezone.now()) | Q(subscribe_end_dt__isnull=True)
    ).order_by('-subscribe_start_dt').first()

    limit_bytes = active_sub.plan.storage_limit * 1024 if active_sub else 0
    used_bytes = user.storage_usage * 1024
    remaining_bytes = max(0, limit_bytes - used_bytes)
    
    storage_display = f"{format_bytes(used_bytes)} / {format_bytes(limit_bytes)}"
    used_percentage = (used_bytes / limit_bytes * 100) if limit_bytes > 0 else 100

    user_videos = UserUploadVideo.objects.filter(
        user=user, use_yn=True
    ).select_related('upload_file', 'upload_status_code').order_by('-upload_date', '-upload_file_id')

    video_list = []
    for v in user_videos:
        sub_info = SubtitleInfo.objects.filter(upload_file=v).select_related('commentator_code').first()
        commentator = sub_info.commentator_code.common_code_value if sub_info and sub_info.commentator_code else "미지정"
        
        status_code = v.upload_status_code.common_code if v.upload_status_code else 20
        is_processing = (status_code != 22)

        video_list.append({
            'id': v.upload_file.file_id,
            'title': v.upload_title,
            'date': v.upload_date, 
            'url': v.upload_file.file_path.url,
            'commentator': commentator,
            'is_processing': is_processing,
            'download_count': v.download_count
        })

    return {
        'user': user,
        'has_history': True,
        'limit_bytes': limit_bytes,
        'remaining_bytes': remaining_bytes,
        'storage_display': storage_display,
        'used_percentage': used_percentage,
        'video_list': video_list,
        **meta_context
    }


def process_upload_video(request):
    if request.method == 'POST':
        video_file = request.FILES.get('video_file')
        title = request.POST.get('video_title', 'Untitled')
        commentator_name = request.POST.get('commentator')
        
        if video_file:
            if not video_file.name.lower().endswith('.mp4'):
                return JsonResponse({'success': False, 'message': 'MP4 형식의 파일만 업로드 가능합니다.'})
            
            try:
                analyst_map = {
                    '박찬오': 17,
                    '이순칠': 18,
                    '김선오': 19
                }
                analyst_id = analyst_map.get(commentator_name, 17)
                file_info = FileInfo.objects.create(file_path=video_file)
                status_uploaded = CommonCode.objects.get(common_code=20, common_code_grp='STATUS')
                user_upload = UserUploadVideo.objects.create(
                    upload_file=file_info,
                    user=request.user,
                    upload_status_code=status_uploaded,
                    upload_title=title,
                    upload_date=timezone.now()
                )
                
                task_thread = threading.Thread(
                    target=runpod_client.process_and_monitor,
                    args=(user_upload, None, int(analyst_id))
                )
                task_thread.daemon = True
                task_thread.start()
                
                return JsonResponse({
                    'success': True,
                    'message': '업로드가 완료되었습니다. 분석이 시작됩니다.',
                    'file_id': file_info.file_id
                })
                
            except CommonCode.DoesNotExist:
                 return JsonResponse({'success': False, 'message': '공통코드(상태값) 설정 오류입니다.'})
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'오류 발생: {str(e)}'})

    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def process_download_logic(user_id, video_id):
    """다운로드 처리 로직 (카운트 증가)"""
    user = UserInfo.objects.get(user_id=user_id)
    video = UserUploadVideo.objects.select_related('upload_file').get(
        upload_file__file_id=video_id, 
        user=user, 
        use_yn=True
    )

    if video.download_count >= 10:
        raise PermissionError("LIMIT_EXCEEDED")

    video.download_count += 1
    video.save()

    return {
        'file_url': video.upload_file.file_path.url,
        'current_count': video.download_count,
        'remaining_count': 10 - video.download_count
    }


def delete_video_logic(user_id, video_id):
    """영상 삭제 (Soft Delete)"""
    user = UserInfo.objects.get(user_id=user_id)
    video = UserUploadVideo.objects.get(
        upload_file__file_id=video_id, 
        user=user,
        use_yn=True
    )
    video.use_yn = False
    video.save()


def get_user_play_context(user_id, video_id):
    """유저 업로드 영상 재생 컨텍스트"""
    user = UserInfo.objects.get(user_id=user_id)
    meta_context = get_team_meta(user)
    
    video_obj = get_object_or_404(UserUploadVideo, upload_file__file_id=video_id, user=user, use_yn=True)
    
    subtitle_info = SubtitleInfo.objects.filter(upload_file=video_obj).select_related('commentator_code').first()
    
    commentator_name = "미지정"
    subtitle_data = []
    
    if subtitle_info:
        if subtitle_info.commentator_code:
            commentator_name = subtitle_info.commentator_code.common_code_value
        if subtitle_info.subtitle:
            try:
                subtitle_data = json.loads(subtitle_info.subtitle.decode('utf-8'))
            except:
                pass

    mapped_video = {
        'video_file_id': video_obj.upload_file.file_id,
        'title': video_obj.upload_title, 
        'upload_date': video_obj.upload_date,
        'file_path': video_obj.upload_file.file_path,
        'url': video_obj.upload_file.file_path.url
    }

    return {
        'user': user,
        'video': mapped_video,        
        'subtitle_data': json.dumps(subtitle_data, cls=DjangoJSONEncoder),
        'current_commentator': commentator_name,
        'is_user_upload': True,  
        **meta_context
    }