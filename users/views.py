import json
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from . import services
from .models import UserInfo


@ensure_csrf_cookie
def index(request):
    return render(request, 'main.html')


@csrf_exempt
def send_verification_code(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            if not email: return JsonResponse({'success': False, 'message': '이메일을 입력해주세요.'})

            code = services.send_code_email_logic(email)
            
            request.session['auth_code'] = code
            request.session['auth_email'] = email
            request.session.set_expiry(300)

            return JsonResponse({'success': True, 'message': '인증코드가 발송되었습니다.'})

        except ValueError as e:
            if str(e) == "DUPLICATE":
                return JsonResponse({'success': False, 'message': '이미 가입된 이메일입니다.', 'code': 'DUPLICATE'})
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def verify_code(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            try:
                services.verify_code_logic(data.get('code'), request.session.get('auth_code'))
                
                if data.get('email') == request.session.get('auth_email'):
                    del request.session['auth_code']
                    return JsonResponse({'success': True, 'message': '인증되었습니다.'})
                else:
                    return JsonResponse({'success': False, 'message': '이메일 정보가 불일치합니다.'})

            except (TimeoutError, ValueError) as e:
                return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def save_password_temp(request):
    if request.method == 'POST':
        try:
            if not request.session.get('auth_email'):
                return JsonResponse({'success': False, 'message': '이메일 인증을 먼저 진행해주세요.'})
            
            data = json.loads(request.body)
            hashed_pw = services.validate_password_logic(data.get('password'))
            request.session['auth_password'] = hashed_pw
            
            return JsonResponse({'success': True, 'message': '비밀번호가 임시 저장되었습니다.'})
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def complete_signup(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = request.session.get('auth_email')
            password = request.session.get('auth_password')

            if not email or not password:
                return JsonResponse({'success': False, 'message': '잘못된 접근입니다.'})

            services.create_user_logic(email, password, data.get('team'))
            
            del request.session['auth_email']
            del request.session['auth_password']
            if 'auth_code' in request.session: del request.session['auth_code']

            return JsonResponse({'success': True, 'message': '회원가입이 완료되었습니다.'})
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '회원가입 중 오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def login_user(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_id = services.login_user_logic(data.get('email'), data.get('password'))
            request.session['user_id'] = user_id
            return JsonResponse({'success': True, 'message': '로그인 성공'})

        except PermissionError as e:
            msg = '5회 이상 로그인에 실패하였습니다.' if str(e) == 'LOCKED_5' else '로그인이 제한된 상태입니다.'
            return JsonResponse({'success': False, 'code': 'LOCKED', 'message': msg})
        except ValueError as e:
            msg = str(e)
            res_code = 'FAIL' if msg == 'FAIL' else 'Error'
            res_msg = '비밀번호가 일치하지 않습니다.' if msg == 'FAIL' else msg
            return JsonResponse({'success': False, 'code': res_code, 'message': res_msg})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def send_reset_code(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            if not email: return JsonResponse({'success': False, 'message': '이메일을 입력해주세요.'})

            code = services.send_reset_code_logic(email)
            request.session['reset_code'] = code
            request.session['reset_email'] = email
            request.session.set_expiry(300)
            return JsonResponse({'success': True, 'message': '인증코드가 발송되었습니다.'})

        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def verify_reset_code(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            services.verify_code_logic(data.get('code'), request.session.get('reset_code'))
            
            if data.get('email') == request.session.get('reset_email'):
                request.session['is_reset_verified'] = True
                return JsonResponse({'success': True, 'message': '인증되었습니다.'})
            else:
                return JsonResponse({'success': False, 'message': '이메일 정보가 불일치합니다.'})

        except (TimeoutError, ValueError) as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def reset_password(request):
    if request.method == 'POST':
        try:
            if not request.session.get('is_reset_verified'):
                return JsonResponse({'success': False, 'message': '인증을 먼저 진행해주세요.'})
            
            email = request.session.get('reset_email')
            if not email: return JsonResponse({'success': False, 'message': '세션이 만료되었습니다.'})

            data = json.loads(request.body)
            services.reset_password_logic(email, data.get('password'))
            
            keys = ['reset_code', 'reset_email', 'is_reset_verified']
            for k in keys:
                if k in request.session: del request.session[k]

            return JsonResponse({'success': True, 'message': '비밀번호가 변경되었습니다.'})
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류가 발생했습니다.'})
    return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})


def logout(request):
    request.session.flush()
    return redirect('/')


def setting(request):
    user_id = request.session.get('user_id')
    if not user_id: return redirect('/')
    
    try:
        context = services.get_setting_context(user_id)
        return render(request, 'setting.html', context)
    except UserInfo.DoesNotExist:
        request.session.flush()
        return redirect('/')
    except Exception as e:
        print(e)
        return redirect('/')


def update_team(request):
    if request.method == 'POST':
        try:
            user_id = request.session.get('user_id')
            if not user_id: return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'})

            data = json.loads(request.body)
            services.update_team_logic(user_id, data.get('team_code'))
            return JsonResponse({'success': True, 'message': '구단이 변경되었습니다.'})
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류 발생'})
    return JsonResponse({'success': False, 'message': '잘못된 요청'})


def update_password(request):
    if request.method == 'POST':
        try:
            user_id = request.session.get('user_id')
            if not user_id: return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'})

            data = json.loads(request.body)
            services.update_password_logic(user_id, data.get('current_pw'), data.get('new_pw'), data.get('confirm_pw'))
            
            request.session.flush()
            return JsonResponse({'success': True, 'message': '비밀번호가 변경되었습니다. 다시 로그인해주세요.'})
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류 발생'})
    return JsonResponse({'success': False, 'message': '잘못된 요청'})


def delete_account(request):
    if request.method == 'POST':
        try:
            user_id = request.session.get('user_id')
            if not user_id: return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'})
            
            data = json.loads(request.body)
            services.delete_account_logic(user_id, data.get('password'))
            
            request.session.flush()
            return JsonResponse({'success': True, 'message': '회원 탈퇴가 완료되었습니다.'})
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})
        except UserInfo.DoesNotExist:
            return JsonResponse({'success': False, 'message': '사용자 정보를 찾을 수 없습니다.'})
        except Exception:
            return JsonResponse({'success': False, 'message': '서버 오류 발생'})
    return JsonResponse({'success': False, 'message': '잘못된 요청'})