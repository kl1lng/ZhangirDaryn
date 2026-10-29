from dataclasses import dataclass, field
from pathlib import Path
import os
import secrets
import json


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DOSYM_DATA_DIR','data/pwa')))
    environment: str = field(default_factory=lambda: os.getenv('DOSYM_ENV','development'))
    local_auth: bool = field(default_factory=lambda: os.getenv('DOSYM_LOCAL_AUTH','0')=='1')
    storage: str = field(default_factory=lambda: os.getenv('DOSYM_STORAGE','local'))
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL',''))
    auth_provider: str = field(default_factory=lambda: os.getenv('DOSYM_AUTH_PROVIDER','supabase').strip().lower())
    supabase_url: str = field(default_factory=lambda: os.getenv('SUPABASE_URL','').rstrip('/'))
    supabase_key: str = field(default_factory=lambda: os.getenv('SUPABASE_ANON_KEY',''))
    google_client_id: str = field(default_factory=lambda: os.getenv('DOSYM_GOOGLE_CLIENT_ID',''))
    google_client_secret: str = field(default_factory=lambda: os.getenv('DOSYM_GOOGLE_CLIENT_SECRET',''))
    google_redirect_uri: str = field(default_factory=lambda: os.getenv('DOSYM_GOOGLE_REDIRECT_URI',os.getenv('DOSYM_PUBLIC_BACKEND','http://127.0.0.1:8765').rstrip('/')+'/auth/google/callback'))
    moderator_email: str = field(default_factory=lambda: os.getenv('DOSYM_MODERATOR_EMAIL','').strip().lower())
    signing_key: str = field(default_factory=lambda: os.getenv('DOSYM_SIGNING_KEY','') or secrets.token_urlsafe(48))
    upload_origin: str = field(default_factory=lambda: os.getenv('DOSYM_PUBLIC_BACKEND','http://127.0.0.1:8765'))
    frontend_origin: str = field(default_factory=lambda: os.getenv('DOSYM_FRONTEND_URL','http://127.0.0.1:3000').rstrip('/'))
    training_epochs: int = field(default_factory=lambda:int(os.getenv('DOSYM_TRAINING_EPOCHS','30')))
    origins: list[str] = field(default_factory=lambda: os.getenv('DOSYM_ALLOWED_ORIGINS','http://127.0.0.1:3000,http://localhost:3000').split(','))

    def __post_init__(self):
        self.data_dir=Path(self.data_dir)
        if not 1<=self.training_epochs<=100:raise ValueError('Training epochs must be between 1 and 100.')
        if self.local_auth and self.environment!='development': raise ValueError('Local test identities are forbidden outside development.')
        if self.storage not in ('local','drive'): raise ValueError('DOSYM_STORAGE must be local or drive.')
        if self.auth_provider not in ('supabase','google'): raise ValueError('DOSYM_AUTH_PROVIDER must be supabase or google.')
        self.origins=[origin.strip().rstrip('/') for origin in self.origins if origin.strip()]
        self.frontend_origin=self.frontend_origin.rstrip('/')
        if self.environment=='production':
            if not self.database_url or self.storage!='drive':
                raise ValueError('Production requires PostgreSQL and Google Drive storage.')
            if self.auth_provider=='supabase' and (not self.supabase_url or not self.supabase_key):
                raise ValueError('Supabase Auth requires SUPABASE_URL and SUPABASE_ANON_KEY.')
            if self.auth_provider=='google' and (not self.google_client_id or not self.google_client_secret):
                raise ValueError('Google Auth requires DOSYM_GOOGLE_CLIENT_ID and DOSYM_GOOGLE_CLIENT_SECRET.')
            if self.auth_provider=='google':
                if not self.google_redirect_uri.startswith('https://') or not self.frontend_origin.startswith('https://'):
                    raise ValueError('Production Google Auth requires HTTPS callback and frontend URLs.')
                if self.frontend_origin not in self.origins:
                    raise ValueError('DOSYM_FRONTEND_URL must be listed in DOSYM_ALLOWED_ORIGINS.')
            if len(os.getenv('DOSYM_SIGNING_KEY',''))<32: raise ValueError('A persistent signing key of at least 32 characters is required.')
        else:
            self.data_dir.mkdir(parents=True,exist_ok=True)
            if not os.getenv('DOSYM_SIGNING_KEY'):
                key_file=self.data_dir/'signing.key'
                if key_file.exists():self.signing_key=key_file.read_text(encoding='utf-8').strip()
                else:
                    try:
                        with key_file.open('x',encoding='utf-8') as output:output.write(self.signing_key)
                    except FileExistsError:self.signing_key=key_file.read_text(encoding='utf-8').strip()
            private=self.data_dir/'private-settings.json'
            if not self.moderator_email and private.exists():
                self.moderator_email=str(json.loads(private.read_text(encoding='utf-8')).get('moderator_email','')).strip().lower()


def load_local_environment():
    """Literal KEY=value only; no evaluation, substitution or shell execution."""
    path=Path(__file__).resolve().parent/'.env.local'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
            key,value=line.split('=',1);key=key.strip().lstrip('\ufeff');value=value.strip()
            if key.startswith(('DOSYM_','SUPABASE_','GOOGLE_')) or key=='DATABASE_URL':
                os.environ.setdefault(key,value.strip('"').strip("'"))
