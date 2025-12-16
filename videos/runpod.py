import boto3
import requests
import time
import json
import logging
import os
import tempfile
import datetime
import sys
from botocore.config import Config
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings
from users.models import CommonCode
from .models import SubtitleInfo

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s] %(levelname)s [%(name)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class RunPodClient:
    def __init__(self):
        s3_config = Config(
            connect_timeout=120,    
            read_timeout=120,       
            retries={
                'max_attempts': 10,
                'mode': 'adaptive' 
            },
            signature_version='s3v4'
        )
        self.s3_client = boto3.client(
            's3',
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            config=s3_config
        )
        self.bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        self.runpod_url = settings.RUNPOD_API_URL
        self.session = self._create_resilient_session()
        self.ANALYST_MAPPING = {
            17: 3,
            18: 2,
            19: 1
        }

    def _create_resilient_session(self):
        session = requests.Session()
        retry = Retry(total=10, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_common_code(self, code_val, group_name):
        try:
            return CommonCode.objects.get(common_code=code_val, common_code_grp=group_name)
        except CommonCode.DoesNotExist:
            return None
        
    def _update_status(self, user_upload_instance, code_val):
        code_obj = self._get_common_code(code_val, 'STATUS')
        if code_obj:
            user_upload_instance.upload_status_code = code_obj
            user_upload_instance.save()
            logger.info(f"💾 DB 상태 업데이트: {code_val} (ID: {user_upload_instance.pk})")

    def upload_video_to_s3(self, django_file_field):
        try:
            filename = os.path.basename(django_file_field.name)
        except Exception:
            filename = f"video_{int(time.time())}.mp4"
            
        s3_key = f"inputs/{filename}"
        
        logger.info(f"📤 S3 업로드 시작 (Key: {s3_key})...")

        with tempfile.NamedTemporaryFile(delete=True) as tmp:
            for chunk in django_file_field.chunks():
                tmp.write(chunk)
            tmp.flush()
            tmp.seek(0)
            
            self.s3_client.upload_file(
                tmp.name,
                self.bucket_name,
                s3_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
            
        logger.info(f"✅ S3 업로드 완료: s3://{self.bucket_name}/{s3_key}")
        return s3_key

    def generate_public_urls(self, input_s3_key):
        download_url = self.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket_name, 'Key': input_s3_key},
            ExpiresIn=3600
        )
        
        timestamp = int(time.time())
        output_key = f"outputs/result_{timestamp}.mp4"
        upload_url = self.s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': self.bucket_name, 
                'Key': output_key,
                'ContentType': 'video/mp4'
            },
            ExpiresIn=3600
        )
        
        return {
            'download_url': download_url,
            'upload_url': upload_url,
            'output_key': output_key
        }

    def submit_job(self, download_url, upload_url, analyst_id):
        payload = {
            's3_video_url': download_url,
            's3_upload_url': upload_url,
            'analyst_select': int(analyst_id)
        }
        endpoint = f"{self.runpod_url}/process_video"
        
        logger.info(f"🚀 RunPod 작업 제출 중... (Analyst: {analyst_id})")
        
        response = self.session.post(endpoint, json=payload, timeout=30)
        response.raise_for_status()
        
        job_id = response.json()['job_id']
        logger.info(f"✅ 작업 제출 완료 (Job ID: {job_id})")
        return job_id

    def download_result_from_s3(self, s3_key, original_filename):
        today = datetime.datetime.now()
        relative_path = f"videos/{today.strftime('%Y/%m/%d')}"
        local_dir = Path(settings.MEDIA_ROOT) / relative_path
        local_dir.mkdir(parents=True, exist_ok=True)
        
        safe_name = Path(original_filename).name
        filename = f"processed_{int(time.time())}_{safe_name}"
        local_full_path = local_dir / filename
        
        logger.info(f"📥 결과 다운로드 시작... ({s3_key} -> {local_full_path})")
        
        self.s3_client.download_file(self.bucket_name, s3_key, str(local_full_path))
        
        logger.info("✅ 다운로드 완료")
        return str(relative_path + "/" + filename), str(local_full_path)

    def process_and_monitor(self, user_upload_instance, _, db_analyst_id):
        """
        [백그라운드 스레드]
        1. 상태를 '처리중(21)'으로 변경
        2. S3 업로드 -> RunPod 제출
        3. 완료 시 상태 '처리완료(22)' 변경 및 자막 저장
        """
        try:
            self._update_status(user_upload_instance, 21)
            runpod_analyst_id = self.ANALYST_MAPPING.get(db_analyst_id, 1)

            s3_input_key = self.upload_video_to_s3(user_upload_instance.upload_file.file_path)
            urls = self.generate_public_urls(s3_input_key)
            job_id = self.submit_job(urls['download_url'], urls['upload_url'], runpod_analyst_id)
            self._monitor_loop(user_upload_instance, job_id, db_analyst_id, urls['output_key'])

        except Exception as e:
            logger.error(f"❌ 프로세스 실패: {e}")
            self._update_status(user_upload_instance, 23)

    def _monitor_loop(self, user_upload_instance, job_id, db_analyst_id, output_s3_key):
        poll_interval = 5

        max_wait_time = 20 * 60 
        start_time = time.time()

        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > max_wait_time:
                logger.error(f"⏰ 타임아웃 발생! ({max_wait_time}초 초과)")
                self._update_status(user_upload_instance, 23)
                break

            try:
                response = self.session.get(f"{self.runpod_url}/status/{job_id}", timeout=15)
                status_data = response.json()
                raw_status = status_data.get('status', '').upper()
                
                progress = status_data.get('progress', 0)
                step = status_data.get('step', '')
                if step:
                     logger.info(f"Job Status: {raw_status} | Progress: {progress}% | Step: {step}")

                if raw_status in ['COMPLETED', 'SUCCESS']:
                    logger.info("✅ 작업 완료! 결과 다운로드 시작...")
                    
                    try:
                        original_name = user_upload_instance.upload_file.file_path.name
                        saved_rel_path = self.download_result_from_s3(output_s3_key, original_name)

                        user_upload_instance.upload_file.file_path = saved_rel_path
                        user_upload_instance.save()
                        
                        output_data = status_data.get('output', {})
                        script_data = output_data.get('script') if isinstance(output_data, dict) else None

                        if script_data:
                            commentator_code_obj = self._get_common_code(db_analyst_id, 'COMMENTATOR')
                            script_bytes = json.dumps(script_data, ensure_ascii=False).encode('utf-8')
                            
                            SubtitleInfo.objects.create(
                                upload_file=user_upload_instance,
                                video_file=None, 
                                subtitle=script_bytes,
                                commentator_code=commentator_code_obj 
                            )

                        self._update_status(user_upload_instance, 22)
                        
                    except Exception as download_error:
                        logger.error(f"❌ 결과 다운로드/저장 중 치명적 오류: {download_error}")
                        self._update_status(user_upload_instance, 23)
                    
                    break 
                
                elif raw_status == 'FAILED':
                    logger.error(f"❌ 작업 실패: {status_data.get('error')}")
                    self._update_status(user_upload_instance, 23)
                    break
                
                time.sleep(poll_interval)
            
            except Exception as e:
                logger.error(f"⚠️ 모니터링 중 에러 발생: {e}")
                time.sleep(poll_interval)

runpod_client = RunPodClient()