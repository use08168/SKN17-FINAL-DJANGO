import boto3
import requests
import time, datetime
import json
import logging
import os
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings
from users.models import CommonCode  
from .models import SubtitleInfo   

logger = logging.getLogger(__name__)

class RunPodClient:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        self.bucket_name = settings.AWS_S3_BUCKET_NAME
        self.runpod_url = settings.RUNPOD_API_URL
        self.session = self._create_resilient_session()
        self.ANALYST_MAPPING = {
            17: 3,
            18: 2,
            19: 1
        }

    def _create_resilient_session(self):
        session = requests.Session()
        retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_common_code(self, code_val, group_name):
        try:
            return CommonCode.objects.get(common_code=code_val, common_code_grp=group_name)
        except CommonCode.DoesNotExist:
            logger.error(f"CommonCode {code_val} (GRP: {group_name}) not found!")
            return None
        
    def get_s3_url(self, file_path_field):
        return file_path_field.url

    def submit_job(self, download_url, upload_url, runpod_analyst_id):
        payload = {
            "input": {
                's3_video_url': download_url,
                's3_upload_url': upload_url,
                'analyst_select': runpod_analyst_id 
            }
        }
        endpoint = f"{self.runpod_url}/process_video"

        response = self.session.post(endpoint, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()['job_id']
    
    def download_result_from_s3(self, s3_key, original_file_name=None):
        try:
            today = datetime.now()
            relative_path = f"videos/{today.strftime('%Y/%m/%d')}"
            local_dir = Path(settings.MEDIA_ROOT) / relative_path
            local_dir.mkdir(parents=True, exist_ok=True)

            if original_file_name:
                safe_name = Path(original_file_name).name
                filename = f"processed_{safe_name}"
            else:
                filename = f"processed_{int(time.time())}.mp4"

            local_full_path = local_dir / filename
            
            logger.info(f"Downloading to {local_full_path}...")
            self.s3_client.download_file(self.bucket_name, s3_key, str(local_full_path))
            
            return f"{relative_path}/{filename}"
            
        except Exception as e:
            logger.error(f"S3 Download Failed: {e}")
            raise

    def process_and_monitor(self, user_upload_instance, _, db_analyst_id):
        """
        [백그라운드 스레드]
        1. 상태를 '처리중(21)'으로 변경
        2. S3 업로드 -> RunPod 제출
        3. 완료 시 상태 '처리완료(22)' 변경 및 자막 저장
        """
        try:
            processing_code = self._get_common_code(21, 'STATUS')
            if processing_code:
                user_upload_instance.upload_status_code = processing_code
                user_upload_instance.save()

            runpod_analyst_id = self.ANALYST_MAPPING.get(db_analyst_id, 1)

            download_url = user_upload_instance.upload_file.file_path.url
            
            timestamp = int(time.time())
            output_key = f"outputs/result_{timestamp}.mp4"
            upload_url = f"https://{self.bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{output_key}"

            logger.info(f"S3 Input URL: {download_url}")
            job_id = self.submit_job(download_url, upload_url, runpod_analyst_id)
            self._monitor_loop(user_upload_instance, job_id, db_analyst_id, output_key)

        except Exception as e:
            logger.error(f"Process Error: {e}")
            failed_code = self._get_common_code(23, 'STATUS')
            if failed_code:
                user_upload_instance.upload_status_code = failed_code
                user_upload_instance.save()

    def _monitor_loop(self, user_upload_instance, job_id, db_analyst_id, output_s3_key):
        poll_interval = 5
        while True:
            try:
                response = self.session.get(f"{self.runpod_url}/status/{job_id}", timeout=15)
                status_data = response.json()
                status = status_data.get('status')

                if status == 'COMPLETED':
                    logger.info("RunPod Completed! Starting download...")

                    original_name = user_upload_instance.upload_file.file_path.name
                    saved_relative_path = self.download_result_from_s3(output_s3_key, original_name)
                    original_file_info = user_upload_instance.upload_file
                    if os.path.exists(original_file_info.file_path.path):
                        os.remove(original_file_info.file_path.path)
                    original_file_info.file_path = saved_relative_path
                    original_file_info.save()
                    
                    script_data = status_data.get('output', {}).get('script')
                    if script_data:
                        commentator_code_obj = self._get_common_code(db_analyst_id, 'COMMENTATOR')
                        script_bytes = json.dumps(script_data, ensure_ascii=False).encode('utf-8')
                        
                        SubtitleInfo.objects.create(
                            upload_file=user_upload_instance,
                            video_file=None,
                            subtitle=script_bytes,
                            commentator_code=commentator_code_obj 
                        )

                    completed_code = self._get_common_code(22, 'STATUS')
                    if completed_code:
                        user_upload_instance.upload_status_code = completed_code
                        user_upload_instance.save()
                    
                    logger.info("Processing Completed & Saved to DB")
                    break
                
                elif status == 'FAILED':
                    logger.error("RunPod Job Failed")
                    failed_code = self._get_common_code(23, 'STATUS')
                    if failed_code:
                        user_upload_instance.upload_status_code = failed_code
                        user_upload_instance.save()
                    break
                
                time.sleep(poll_interval)
            
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                time.sleep(poll_interval)

runpod_client = RunPodClient()