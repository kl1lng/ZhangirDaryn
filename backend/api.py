from contextlib import ExitStack
import hmac
from pathlib import Path
import re
from urllib.parse import urlencode
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend.settings import Settings
from backend.store import Store, DomainError
from backend.auth import sign, verify, identity, google_authorization_url, exchange_google_code, verify_google_id_token
from backend.storage import LocalStorage, DriveStorage, validate_video


class UploadInput(BaseModel):
    label: str = Field(min_length=1,max_length=160)
    language: str = 'kk-KZ'
    filename: str = Field(max_length=180)
    size: int = Field(gt=0,le=104857600)
    mime: str
    rights: bool
    training: bool = False
    research: bool = False
    idempotency_key: str = Field(min_length=8,max_length=100)


class Decision(BaseModel):
    decision: str
    reason: str = Field(default='',max_length=1000)
    revision: int

class Withdrawal(BaseModel):
    reason: str = Field(min_length=1,max_length=1000)
    revision: int


def create_app(settings=None):
    settings=settings or Settings(); settings.data_dir.mkdir(parents=True,exist_ok=True)
    store=Store(settings.database_url or str(settings.data_dir/'public.sqlite3'))
    storage=DriveStorage(settings.data_dir) if settings.storage=='drive' else LocalStorage(settings.data_dir)
    app=FastAPI(title='DosYm PWA service',docs_url='/docs' if settings.environment=='development' else None)
    app.state.store=store; app.state.settings=settings; app.state.storage=storage
    upload_lock=threading.Lock()
    app.add_middleware(CORSMiddleware,allow_origins=settings.origins,allow_credentials=False,
        allow_methods=['GET','POST','PUT','OPTIONS'],allow_headers=['Authorization','Content-Type','Content-Range'])

    @app.exception_handler(DomainError)
    async def domain_error(request,exc): return JSONResponse({'error':str(exc)},status_code=exc.status)

    import httpx
    @app.exception_handler(httpx.HTTPError)
    async def storage_network_error(request,exc):
        return JSONResponse({'error':'Внешний сервис временно недоступен. Повторите действие, чтобы продолжить.'},status_code=503)

    @app.middleware('http')
    async def private_headers(request,call_next):
        # Gate before Pydantic validation, so malformed guest uploads cannot probe internals.
        if request.method!='OPTIONS' and request.url.path=='/uploads/init' and not request.headers.get('authorization'):
            return JSONResponse({'error':'Войдите через Google для продолжения.'},status_code=401,headers={'Cache-Control':'no-store'})
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    def actor(request): return identity(settings,store,request.headers.get('authorization',''),local_request=local_allowed(request))

    def local_allowed(request):
        origin=request.headers.get('origin')
        return settings.local_auth and request.client and request.client.host in ('127.0.0.1','::1') and request.url.hostname in ('localhost','127.0.0.1','testserver') and (not origin or origin in settings.origins)

    def upload_actor(request,identifier):
        header=request.headers.get('authorization','')
        if not header.startswith('Bearer '): raise DomainError('Нужен билет загрузки.',401)
        data=verify(settings,header[7:],'upload')
        if data['submission_id']!=identifier: raise DomainError('Билет выдан на другой материал.',403)
        with store.transaction() as db:
            row=db.execute('SELECT * FROM pwa_users WHERE id=?',(data['owner_id'],)).fetchone()
            if not row: raise DomainError('Владелец не найден.',403)
            return dict(row)

    @app.get('/health')
    def health(): return {'ok':True,'service':'dosym-pwa-backend','storage':storage.kind,'database':'postgresql' if store.postgres else 'sqlite','environment':settings.environment}

    @app.get('/auth/config')
    def auth_config(request:Request):
        configured = bool(settings.google_client_id and settings.google_client_secret) if settings.auth_provider == 'google' else bool(settings.supabase_url and settings.supabase_key)
        return {'auth_provider':settings.auth_provider,'google_configured':configured,'local_auth':bool(local_allowed(request)),'storage':storage.kind}

    @app.get('/auth/google/start')
    def google_start():
        if settings.auth_provider != 'google': raise DomainError('Вход через Google сейчас обслуживает настроенный провайдер.', 409)
        if not settings.google_client_id or not settings.google_client_secret:
            raise DomainError('Владелец приложения ещё не настроил Google-вход.', 503)
        authorization_url,state=google_authorization_url(settings)
        response=RedirectResponse(authorization_url,status_code=302)
        response.set_cookie('dosym-oauth-state',state,max_age=600,httponly=True,
            secure=settings.google_redirect_uri.startswith('https://'),samesite='lax',path='/auth/google/callback')
        return response

    @app.get('/auth/google/callback')
    def google_callback(request:Request,code:str|None=None,state:str|None=None,error:str|None=None):
        if settings.auth_provider != 'google': raise DomainError('Вход через Google сейчас обслуживает настроенный провайдер.', 409)
        callback_url=settings.frontend_origin+'/auth/callback'
        if error:
            response=RedirectResponse(callback_url+'?'+urlencode({'error':'google_cancelled'}),status_code=303)
            response.delete_cookie('dosym-oauth-state',path='/auth/google/callback')
            return response
        try:
            if not code or not state: raise ValueError('missing OAuth response')
            cookie_state=request.cookies.get('dosym-oauth-state','')
            if not cookie_state or not hmac.compare_digest(state,cookie_state): raise ValueError('state cookie mismatch')
            oauth_state=verify(settings,state,'google-oauth-state')
            id_token=exchange_google_code(settings,code)
            claims=verify_google_id_token(id_token,settings.google_client_id)
            nonce=claims.get('nonce','')
            if not isinstance(nonce,str) or not hmac.compare_digest(nonce,oauth_state.get('nonce','')):
                raise ValueError('nonce mismatch')
            subject=claims.get('sub','')
            email=claims.get('email','').strip().lower()
            if not subject or not email or claims.get('email_verified') is not True:
                raise ValueError('unverified Google identity')
            user=store.user('google:'+subject,email,claims.get('name') or 'Участник',
                moderator=bool(settings.moderator_email and email==settings.moderator_email))
            session=sign(settings,{'purpose':'session','user_id':user['id']},3600)
            response=RedirectResponse(callback_url+'#'+urlencode({'token':session}),status_code=303)
        except Exception:
            response=RedirectResponse(callback_url+'?'+urlencode({'error':'google_login_failed'}),status_code=303)
        response.delete_cookie('dosym-oauth-state',path='/auth/google/callback')
        return response

    @app.post('/auth/local')
    async def local_login(request:Request):
        if not local_allowed(request): raise DomainError('Тестовый вход доступен только локально при явном включении.',403)
        data=await request.json(); role=data.get('role')
        if role not in ('user','moderator'): raise DomainError('Неизвестная тестовая роль.')
        return {'token':'local:'+sign(settings,{'purpose':'local-login','role':role}),'local':True}

    @app.get('/me')
    def me(request:Request): return actor(request)

    @app.post('/uploads/init')
    def begin_upload(data:UploadInput,request:Request):
        user=actor(request)
        row=store.create_submission(user,**data.model_dump())
        with upload_lock,store.transaction() as db:
            upload=db.execute('SELECT * FROM pwa_uploads WHERE submission_id=?',(row['id'],)).fetchone()
            if storage.kind=='drive' and not upload['session_uri'] and row['source_status']=='uploading':
                session=storage.begin(row)
                db.execute('UPDATE pwa_uploads SET session_uri=? WHERE submission_id=?',(session['session_uri'],row['id']))
        return {'submission_id':row['id'],'upload_ticket':sign(settings,{'purpose':'upload','owner_id':user['id'],'submission_id':row['id']},86400),
                'upload_origin':settings.upload_origin,'source_status':row['source_status']}

    @app.get('/uploads/{identifier}/status')
    def upload_status(identifier:str,request:Request):
        user=upload_actor(request,identifier); row=store.submission(user,identifier)
        with upload_lock,store.transaction() as db:
            upload=dict(db.execute('SELECT * FROM pwa_uploads WHERE submission_id=?',(identifier,)).fetchone())
            if storage.kind=='drive' and row['source_status']=='uploading':
                upload=storage.reconcile(row,upload)
                db.execute('UPDATE pwa_uploads SET received=?,session_uri=?,file_id=? WHERE submission_id=?',
                           (upload['received'],upload['session_uri'],upload['file_id'],identifier))
        return {'received':upload['received'],'size':row['size'],'source_status':row['source_status']}

    @app.put('/uploads/{identifier}/chunks')
    async def append_chunk(identifier:str,request:Request):
        user=upload_actor(request,identifier); row=store.submission(user,identifier)
        if row['source_status']!='uploading': raise DomainError('Передача уже завершена.',409)
        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',request.headers.get('content-range',''))
        if not match: raise DomainError('Нужен корректный диапазон байтов.')
        start,end,total=map(int,match.groups())
        if total!=row['size'] or end>=total or end<start or end-start+1>4*1024*1024: raise DomainError('Недопустимый диапазон.')
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4*1024*1024: raise DomainError('Часть превышает 4 МБ.',413)
        if len(body)!=end-start+1: raise DomainError('Длина части не совпала с диапазоном.')
        with upload_lock,store.transaction() as db:
            upload=dict(db.execute('SELECT * FROM pwa_uploads WHERE submission_id=?',(identifier,)).fetchone())
            if upload['received']!=start: raise DomainError('Позиция изменилась. Продолжите с подтверждённого байта.',409)
            result=storage.append(row,upload,bytes(body),start,end)
            db.execute('UPDATE pwa_uploads SET received=?,file_id=COALESCE(?,file_id) WHERE submission_id=?',(result['received'],result['file_id'],identifier))
        return {'received':result['received']}

    @app.post('/uploads/{identifier}/complete')
    def complete(identifier:str,request:Request):
        user=upload_actor(request,identifier); row=store.submission(user,identifier,private=True)
        if row['source_status']!='uploading': return store.submission(user,identifier)
        with store.transaction() as db: upload=dict(db.execute('SELECT * FROM pwa_uploads WHERE submission_id=?',(identifier,)).fetchone())
        if upload['received']!=row['size']: raise DomainError('Видео ещё не передано полностью.',409)
        ref=storage.reference(row,upload); row['source_ref']=ref
        with storage.materialize(row) as path: metadata=validate_video(path)
        return store.complete_upload(user,identifier,ref,metadata)

    @app.get('/submissions')
    def submissions(request:Request): return store.submissions(actor(request))

    @app.get('/submissions/{identifier}')
    def submission(identifier:str,request:Request): return store.submission(actor(request),identifier)

    @app.get('/submissions/{identifier}/source')
    def source(identifier:str,request:Request):
        row=store.submission(actor(request),identifier,private=True)
        if row['source_status'] not in ('available','delete_requested'): raise DomainError('Исходник недоступен.',404)
        stack=ExitStack()
        try:
            path=stack.enter_context(storage.materialize(row))
            return FileResponse(path,media_type=row['mime'],background=BackgroundTask(stack.close))
        except BaseException:
            stack.close(); raise

    @app.post('/submissions/{identifier}/playback')
    def playback_ticket(identifier:str,request:Request):
        user=actor(request);row=store.submission(user,identifier)
        if row['source_status']!='available':raise DomainError('Видео недоступно.',404)
        ticket=sign(settings,{'purpose':'playback','viewer_id':user['id'],'submission_id':identifier},900)
        return {'url':settings.upload_origin+'/playback/'+identifier+'?ticket='+ticket}

    @app.get('/playback/{identifier}')
    def playback(identifier:str,ticket:str,request:Request):
        data=verify(settings,ticket,'playback')
        if data['submission_id']!=identifier:raise DomainError('Билет выдан на другой материал.',403)
        with store.transaction() as db:
            viewer=db.execute('SELECT * FROM pwa_users WHERE id=?',(data['viewer_id'],)).fetchone()
        if viewer is None:raise DomainError('Сессия просмотра недоступна.',403)
        row=store.submission(dict(viewer),identifier,private=True)
        if row['source_status']!='available':raise DomainError('Исходник недоступен.',404)
        from backend.preview import browser_preview
        return FileResponse(browser_preview(settings,storage,row),media_type='video/mp4')

    @app.post('/submissions/{identifier}/delete-source')
    def delete_source(identifier:str,request:Request):
        user=actor(request); row=store.request_source_deletion(user,identifier)
        if row['source_status']!='deleted':
            storage.delete(row); store.finish_source_deletion(identifier)
            (settings.data_dir/'previews'/(identifier+'.mp4')).unlink(missing_ok=True)
        return store.submission(user,identifier)

    @app.post('/submissions/{identifier}/retry')
    def retry(identifier:str,request:Request):
        store.retry(actor(request),identifier); return {'ok':True}

    @app.post('/submissions/{identifier}/withdraw')
    def withdraw(identifier:str,data:Withdrawal,request:Request):
        return store.withdraw(actor(request),identifier,data.reason,data.revision)

    @app.get('/moderation')
    def moderation(request:Request): return store.submissions(actor(request),moderation=True)

    @app.post('/moderation/{identifier}/decision')
    def decision(identifier:str,data:Decision,request:Request):
        return store.decide(actor(request),identifier,data.decision,data.reason,data.revision)

    @app.get('/gestures')
    def gestures():
        import json
        result=[]
        for row in store.gestures():
            metadata=json.loads(row['metadata'])
            result.append({**row,'metadata':{key:metadata[key] for key in ('fps','shape','body_pose_status','schema_version') if key in metadata}})
        return result

    @app.get('/gestures/{identifier}/motion')
    def motion(identifier:str):
        motion=store.motion(identifier)
        motion['metadata']={key:value for key,value in motion['metadata'].items() if key not in ('signer_id','source_mtime_ns','pose_model_mtime_ns')}
        return motion

    @app.get('/training')
    def training(request:Request):
        store.require_mod(actor(request))
        from backend.training import runs
        return {'snapshot':store.training_snapshot(),'runs':runs(store)}

    @app.post('/training')
    def train(request:Request):
        user=actor(request);store.require_mod(user)
        from backend.training import schedule
        return schedule(store)

    return app
