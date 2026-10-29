"""Source storage; owner OAuth tokens and resumable URIs never leave this service."""
from pathlib import Path
from contextlib import contextmanager
import os
import threading
import time

import httpx

from backend.store import DomainError


class LocalStorage:
    kind='local'
    def __init__(self, directory):
        self.directory=Path(directory)/'sources'; self.directory.mkdir(parents=True,exist_ok=True)
    def path(self, identifier):
        import uuid
        try: uuid.UUID(identifier)
        except ValueError: raise DomainError('Некорректный материал.',400)
        return self.directory/(identifier+'.video')
    def begin(self,row): return {'session_uri':None,'file_id':None}
    def reconcile(self,row,upload):return upload
    def append(self,row,upload,data,start,end):
        path=self.path(row['id'])
        with path.open('r+b' if path.exists() else 'wb') as output:
            output.seek(start); output.write(data); output.truncate(end+1)
        return {'received':end+1,'file_id':None}
    @contextmanager
    def materialize(self,row): yield self.path(row['id'])
    def delete(self,row): self.path(row['id']).unlink(missing_ok=True)
    def reference(self,row,upload): return 'local:'+row['id']


class DriveStorage:
    kind='drive'
    def __init__(self,directory):
        self.directory=Path(directory); self._token=''; self._expires=0; self._lock=threading.Lock()
        self.folder=os.getenv('GOOGLE_DRIVE_FOLDER_ID','')
        if not self.folder: raise ValueError('Configure GOOGLE_DRIVE_FOLDER_ID before using Drive storage.')

    def headers(self):
        with self._lock:
            if time.time()>self._expires:
                response=httpx.post('https://oauth2.googleapis.com/token',data={
                    'client_id':os.getenv('GOOGLE_CLIENT_ID',''),'client_secret':os.getenv('GOOGLE_CLIENT_SECRET',''),
                    'refresh_token':os.getenv('GOOGLE_REFRESH_TOKEN',''),'grant_type':'refresh_token'},timeout=20)
                if response.status_code!=200: raise DomainError('Доступ к Google Диску отозван или не настроен.',503)
                result=response.json(); self._token=result['access_token']; self._expires=time.time()+result.get('expires_in',3600)-90
        return {'Authorization':'Bearer '+self._token}

    def begin(self,row):
        response=httpx.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
            headers={**self.headers(),'X-Upload-Content-Type':row['mime'],'X-Upload-Content-Length':str(row['size'])},
            json={'name':row['id']+'-'+row['filename'],'parents':[self.folder],
                  'appProperties':{'dosym_submission':row['id']}},timeout=30)
        if response.status_code not in (200,201): raise DomainError('Не удалось начать загрузку на Google Диск. Проверьте доступ и квоту.',503)
        return {'session_uri':response.headers['location'],'file_id':None}

    def reconcile(self,row,upload):
        if upload.get('file_id'):return upload
        response=httpx.put(upload['session_uri'],headers={**self.headers(),'Content-Range':f"bytes */{row['size']}"},content=b'',timeout=30)
        if response.status_code==308:
            value=response.headers.get('range')
            received=int(value.rsplit('-',1)[1])+1 if value else 0
            return {**upload,'received':received}
        if response.status_code in (200,201):return {**upload,'received':row['size'],'file_id':response.json()['id']}
        if response.status_code in (404,410):
            # Recover a completed upload whose final acknowledgement was lost.
            result=httpx.get('https://www.googleapis.com/drive/v3/files',headers=self.headers(),params={
                'q':"trashed = false and appProperties has { key='dosym_submission' and value='"+row['id']+"' }",
                'fields':'files(id,size)','pageSize':2},timeout=30)
            if result.status_code!=200:raise DomainError('Не удалось восстановить состояние загрузки на Диске.',503)
            files=result.json().get('files',[])
            if files:return {**upload,'received':row['size'],'file_id':files[0]['id']}
            return {**upload,**self.begin(row),'received':0}
        raise DomainError('Не удалось проверить позицию загрузки на Google Диске.',503)

    def append(self,row,upload,data,start,end):
        # URI is obtained only from Drive, persisted in a server-only table.
        response=httpx.put(upload['session_uri'],headers={**self.headers(),
            'Content-Range':f"bytes {start}-{end}/{row['size']}",'Content-Type':row['mime']},content=data,timeout=60)
        if response.status_code==308:
            received=int(response.headers.get('range','bytes=0--1').rsplit('-',1)[1])+1
            if received!=end+1: raise DomainError('Диск подтвердил другой диапазон. Обновите состояние загрузки.',409)
            return {'received':received,'file_id':None}
        if response.status_code in (200,201): return {'received':end+1,'file_id':response.json()['id']}
        raise DomainError('Google Диск не принял часть видео. Проверьте сеть, доступ и квоту.',503)

    @contextmanager
    def materialize(self,row):
        import tempfile
        ref=row.get('source_ref') or ''
        identifier=ref.removeprefix('drive:')
        if not ref.startswith('drive:'): raise DomainError('Исходник не найден.',404)
        with tempfile.TemporaryDirectory(dir=self.directory) as directory:
            path=Path(directory)/'source.video'
            with httpx.stream('GET',f'https://www.googleapis.com/drive/v3/files/{identifier}?alt=media',headers=self.headers(),timeout=60) as response:
                if response.status_code!=200: raise DomainError('Не удалось прочитать исходник с Google Диска.',503)
                count=0
                with path.open('wb') as output:
                    for chunk in response.iter_bytes(1024*1024):
                        count+=len(chunk)
                        if count>100*1024*1024: raise DomainError('Исходник превышает допустимый размер.',413)
                        output.write(chunk)
            yield path

    def delete(self,row):
        identifier=(row.get('source_ref') or '').removeprefix('drive:')
        response=httpx.delete(f'https://www.googleapis.com/drive/v3/files/{identifier}',headers=self.headers(),timeout=30)
        if response.status_code not in (204,404): raise DomainError('Удаление на Google Диске пока не завершено. Повторите позже.',503)

    def reference(self,row,upload):
        if not upload['file_id']: raise DomainError('Диск ещё не подтвердил файл.',409)
        return 'drive:'+upload['file_id']


def validate_video(path):
    import cv2
    import math
    with Path(path).open('rb') as source:signature=source.read(16)
    if not (signature[:4]==b'\x1aE\xdf\xa3' or signature[4:8] in (b'ftyp',b'moov',b'mdat',b'wide')):
        raise DomainError('Контейнер видео не соответствует MP4, MOV или WebM.')
    capture=cv2.VideoCapture(str(path))
    try:
        fps=float(capture.get(cv2.CAP_PROP_FPS)); count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)); height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not capture.isOpened() or not math.isfinite(fps) or fps<=0 or count<2 or count/fps>60 or fps>60 or max(width,height)>3840:
            raise DomainError('Нужен читаемый ролик до 60 секунд, 60 кадров/с и 4K.')
        decoded=0
        while True:
            ok,frame=capture.read()
            if not ok: break
            decoded+=1
            if decoded>3600: raise DomainError('Слишком много кадров.')
        if decoded<2 or decoded<count*.98: raise DomainError('Видео повреждено или декодируется не полностью.')
        return {'fps':fps,'frame_count':decoded,'width':width,'height':height,'image_aspect_ratio':width/height}
    finally: capture.release()
