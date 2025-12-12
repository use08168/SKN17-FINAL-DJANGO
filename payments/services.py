import requests
import uuid
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from .models import UserInfo, PlanInfo, SubscribeHistory, InvoiceInfo, PaymentHistory

def prepare_kakao_payment(user_id, plan_code):
    """
    1. 결제 준비 (Ready) API 호출 로직
    Returns: (준비 결과 dict, 세션에 저장할 데이터 dict)
    """
    target_plan_id = 2 if plan_code == 'PREMIUM' else 1
    try:
        plan_obj = PlanInfo.objects.get(plan_id=target_plan_id)
    except PlanInfo.DoesNotExist:
        raise ValueError("존재하지 않는 플랜입니다.")

    item_name = f"BAIS {plan_obj.plan_name} 정기결제"
    total_amount = plan_obj.price
    partner_order_id = str(uuid.uuid4())

    admin_key = getattr(settings, 'KAKAO_ADMIN_KEY', None)
    if not admin_key:
        raise EnvironmentError("Kakao Admin Key가 설정되지 않았습니다.")

    url = f"{settings.KAKAO_API_BASE_URL}/v1/payment/ready"
    headers = {
        "Authorization": f"KakaoAK {admin_key}",
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }

    data = {
        "cid": "TCSUBSCRIP",
        "partner_order_id": partner_order_id,
        "partner_user_id": user_id,
        "item_name": item_name,
        "quantity": "1",
        "total_amount": str(total_amount),
        "tax_free_amount": "0",
        "approval_url": "http://54.116.12.113:8080/payments/approve/",
        "cancel_url": "http://54.116.12.113:8080/payments/cancel/",
        "fail_url": "http://54.116.12.113:8080/payments/fail/",
    }

    res = requests.post(url, headers=headers, data=data)
    result = res.json()

    if 'next_redirect_pc_url' not in result:
        raise ConnectionError(f"Kakao API Error: {result}")

    session_data = {
        'partner_order_id': partner_order_id,
        'partner_user_id': user_id,
        'plan_id': target_plan_id,
        'total_amount': total_amount,
        'tid': result.get('tid')
    }
    
    return result.get('next_redirect_pc_url'), session_data


def approve_kakao_payment(pg_token, session_data):
    """
    2. 결제 승인 (Approve) 및 DB 업데이트 로직
    """
    tid = session_data.get('tid')
    partner_order_id = session_data.get('partner_order_id')
    partner_user_id = session_data.get('partner_user_id')
    plan_id = session_data.get('plan_id')
    amount = session_data.get('total_amount')

    url = f"{settings.KAKAO_API_BASE_URL}/v1/payment/approve"
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_ADMIN_KEY}",
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    data = {
        "cid": "TCSUBSCRIP",
        "tid": tid,
        "partner_order_id": partner_order_id,
        "partner_user_id": partner_user_id,
        "pg_token": pg_token,
    }

    res = requests.post(url, headers=headers, data=data)
    result = res.json()

    now = timezone.now()
    is_success = (res.status_code == 200)
    
    if not is_success:
        return False, f"[{result.get('code')}] {result.get('msg')}", None

    try:
        user = UserInfo.objects.get(user_id=partner_user_id)
        target_plan = PlanInfo.objects.get(plan_id=plan_id)
        
        current_sub = SubscribeHistory.objects.filter(
            user=user
        ).filter(
            Q(subscribe_end_dt__isnull=True) | Q(subscribe_end_dt__gte=now)
        ).order_by('-subscribe_start_dt').first()

        new_start_dt = now

        if current_sub:
            if current_sub.subscribe_end_dt:
                cycle_end_date = current_sub.subscribe_end_dt
            else:
                last_pay = PaymentHistory.objects.filter(invoice__subscription=current_sub).order_by('-payment_date').first()
                base_date = last_pay.payment_date if last_pay else current_sub.subscribe_start_dt
                cycle_end_date = base_date + timedelta(days=30)
                
                if cycle_end_date < now:
                    cycle_end_date = now

                current_sub.subscribe_end_dt = cycle_end_date
                current_sub.save()

            new_start_dt = cycle_end_date + timedelta(seconds=1)

        new_sub = SubscribeHistory.objects.create(
            user=user,
            plan=target_plan,
            subscribe_start_dt=new_start_dt,
            subscribe_end_dt=None
        )
        
        new_invoice = InvoiceInfo.objects.create(
            subscription=new_sub,
            invoice_amount=amount,
            issue_date=now.date()
        )

        PaymentHistory.objects.create(
            invoice=new_invoice,
            transaction_id=result.get('sid'),
            payment_amount=amount,
            payment_date=now,
            fail_reason=None 
        )

        plan_name_display = "프리미엄" if target_plan.plan_name == "PREMIUM" else "베이직"
        
        return True, {
            'user': user,
            'plan_name': f"{plan_name_display} 플랜",
            'payment_date': now.strftime('%Y.%m.%d'),
            'payment_amount': f"{int(amount):,}원"
        }, None

    except Exception as e:
        return False, None, str(e)


def cancel_subscription_logic(user_id):
    """ 구독 해지 로직 """
    user = UserInfo.objects.get(user_id=user_id)
    target_sub = SubscribeHistory.objects.filter(
        user=user, 
        subscribe_end_dt__isnull=True
    ).order_by('-subscribe_start_dt').first()
    
    if not target_sub:
        raise ValueError('해지할 구독 정보가 없습니다.')

    now = timezone.now()
    
    if target_sub.subscribe_start_dt > now:
        expiration_date = target_sub.subscribe_start_dt + timedelta(days=30)
    else:
        last_payment = PaymentHistory.objects.filter(invoice__subscription=target_sub).order_by('-payment_date').first()
        base_date = last_payment.payment_date if last_payment else target_sub.subscribe_start_dt
        expiration_date = base_date + timedelta(days=30)
    
    target_sub.subscribe_end_dt = expiration_date
    target_sub.save()
    
    return expiration_date.strftime('%Y.%m.%d')


def renew_subscription_logic(user_id):
    """ 구독 갱신 로직 """
    user = UserInfo.objects.get(user_id=user_id)
    now = timezone.now()

    target_sub = SubscribeHistory.objects.filter(
        user=user, 
        subscribe_end_dt__isnull=False, 
        subscribe_end_dt__gt=now
    ).last()
    
    if not target_sub:
        raise ValueError('갱신할 구독 정보가 없습니다.')

    target_sub.subscribe_end_dt = None
    target_sub.save()