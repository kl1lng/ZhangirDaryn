import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx

from backend.store import DomainError


def google_authorization_url(settings):
    nonce = secrets.token_urlsafe(32)
    state = sign(settings, {'purpose': 'google-oauth-state', 'nonce': nonce}, 600)
    query = urlencode({
        'client_id': settings.google_client_id,
        'redirect_uri': settings.google_redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce,
        'access_type': 'online',
        'prompt': 'select_account',
    })
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + query, state


def exchange_google_code(settings, code):
    response = httpx.post('https://oauth2.googleapis.com/token', data={
        'code': code,
        'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret,
        'redirect_uri': settings.google_redirect_uri,
        'grant_type': 'authorization_code',
    }, timeout=15)
    response.raise_for_status()
    token = response.json().get('id_token')
    if not token:
        raise DomainError('Google не подтвердил вход. Попробуйте ещё раз.', 401)
    return token


def verify_google_id_token(token, client_id):
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, Request(), client_id)


def sign(settings, payload, lifetime=3600):
    body=base64.urlsafe_b64encode(json.dumps({**payload,'exp':time.time()+lifetime},separators=(',',':')).encode()).decode().rstrip('=')
    digest=hmac.new(settings.signing_key.encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+digest


def verify(settings, token, purpose):
    try:
        body,digest=token.split('.')
        expected=hmac.new(settings.signing_key.encode(),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest,expected): raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if data['exp']<time.time() or data['purpose']!=purpose: raise ValueError()
        return data
    except (ValueError,KeyError,TypeError): raise DomainError('Сессия истекла. Войдите снова.',401)


def identity(settings, store, authorization, *, local_request=False):
    if not authorization.startswith('Bearer '): raise DomainError('Войдите через Google для продолжения.',401)
    token=authorization[7:]
    if settings.local_auth and token.startswith('local:'):
        if not local_request:raise DomainError('Тестовая сессия разрешена только на этом компьютере.',403)
        data=verify(settings,token[6:],'local-login')
        return store.user('local-'+data['role'],data['role']+'@local.invalid',
                          'Тестовый модератор' if data['role']=='moderator' else 'Тестовый участник',moderator=data['role']=='moderator')
    if token.startswith('local:'):
        raise DomainError('Тестовая сессия разрешена только на этом компьютере.', 403)
    if settings.auth_provider == 'google':
        data = verify(settings, token, 'session')
        user = store.user_by_id(data.get('user_id', ''))
        if user is None:
            raise DomainError('Аккаунт не найден. Войдите снова.', 401)
        return user
    if not settings.supabase_url or not settings.supabase_key:
        raise DomainError('Google-вход ещё не подключён владельцем приложения.',503)
    try:
        response=httpx.get(settings.supabase_url+'/auth/v1/user',headers={'apikey':settings.supabase_key,'Authorization':'Bearer '+token},timeout=15)
        if response.status_code!=200: raise DomainError('Вход не подтверждён. Войдите заново.',401)
        data=response.json()
    except httpx.HTTPError: raise DomainError('Сервис входа временно недоступен.',503)
    if not data.get('email_confirmed_at') or not any(i.get('provider')=='google' for i in data.get('identities',[])):
        raise DomainError('Нужен подтверждённый Google-аккаунт.',403)
    email=data.get('email','').lower()
    return store.user(data['id'],email,data.get('user_metadata',{}).get('full_name') or 'Участник',
                      moderator=bool(settings.moderator_email and email==settings.moderator_email))
