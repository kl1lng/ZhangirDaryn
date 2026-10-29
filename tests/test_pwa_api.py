import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.settings import Settings


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.settings=Settings(data_dir=Path(self.tmp.name), local_auth=True)
        self.client=TestClient(create_app(self.settings), client=('127.0.0.1', 50000))

    def tearDown(self): self.tmp.cleanup()

    def login(self, role='user'):
        r=self.client.post('/auth/local',json={'role':role})
        self.assertEqual(r.status_code,200)
        return {'Authorization':'Bearer '+r.json()['token']}

    def test_guests_cannot_create_upload(self):
        self.assertEqual(self.client.post('/uploads/init',json={}).status_code,401)

    def test_research_permission_is_recorded_independently(self):
        headers=self.login()
        self.client.post('/uploads/init',headers=headers,json={
            'label':'Исследование','language':'kk-KZ','filename':'test.mp4','size':1024,
            'mime':'video/mp4','rights':True,'training':False,'research':True,
            'idempotency_key':'research-api-test'}).raise_for_status()
        rows=self.client.get('/submissions',headers=headers).json()
        self.assertEqual(rows[0]['training'],0)
        self.assertEqual(rows[0]['research'],1)

    def test_upload_preflight_reaches_cors_before_guest_auth_gate(self):
        response=self.client.options('/uploads/init',headers={
            'Origin':'http://127.0.0.1:3000',
            'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'authorization,content-type',
        })
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['access-control-allow-origin'],'http://127.0.0.1:3000')

    def test_local_login_is_explicit_and_disabled_in_production(self):
        with self.assertRaises(ValueError): Settings(data_dir=Path(self.tmp.name),local_auth=True,environment='production')
        foreign=TestClient(create_app(self.settings),client=('203.0.113.1',50000))
        self.assertEqual(foreign.post('/auth/local',json={'role':'moderator'}).status_code,403)

    def test_user_cannot_enter_moderation(self):
        self.assertEqual(self.client.get('/moderation',headers=self.login()).status_code,403)

    def test_upload_ticket_does_not_allow_other_material_or_bad_offset(self):
        headers=self.login()
        r=self.client.post('/uploads/init',headers=headers,json={
            'label':'Тест','language':'kk-KZ','filename':'test.mp4','size':1024,
            'mime':'video/mp4','rights':True,'training':True,'idempotency_key':'0123456789'})
        self.assertEqual(r.status_code,200)
        row=r.json(); ticket={'Authorization':'Bearer '+row['upload_ticket'],'Content-Range':'bytes 1-4/1024'}
        response=self.client.put('/uploads/'+row['submission_id']+'/chunks',headers=ticket,content=b'test')
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.put('/uploads/other/chunks',headers=ticket,content=b'test').status_code,403)

    def test_untrusted_host_cannot_mint_local_moderator(self):
        response=self.client.post('/auth/local',headers={'host':'attacker.example'},json={'role':'moderator'})
        self.assertEqual(response.status_code,403)

    def test_no_store_for_private_api(self):
        r=self.client.get('/me',headers=self.login())
        self.assertEqual(r.headers['cache-control'],'no-store')

    def test_local_identity_cannot_be_used_by_remote_client(self):
        headers=self.login('moderator')
        foreign=TestClient(create_app(self.settings),client=('203.0.113.1',50000))
        self.assertEqual(foreign.get('/me',headers=headers).status_code,403)

    def test_real_video_upload_moderation_and_direct_range_playback(self):
        import cv2,numpy as np
        path=Path(self.tmp.name)/'fixture.mp4'
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),15,(64,64))
        for _ in range(5):writer.write(np.full((64,64,3),180,dtype=np.uint8))
        writer.release();content=path.read_bytes()
        user=self.login();mod=self.login('moderator')
        created=self.client.post('/uploads/init',headers=user,json={
            'label':'Тестовая запись','language':'kk-KZ','filename':'fixture.mp4','size':len(content),
            'mime':'video/mp4','rights':True,'training':False,'idempotency_key':'real-video-upload'}).json()
        identifier=created['submission_id'];ticket={'Authorization':'Bearer '+created['upload_ticket']}
        chunk=self.client.put(f'/uploads/{identifier}/chunks',headers={**ticket,'Content-Range':f'bytes 0-{len(content)-1}/{len(content)}'},content=content)
        self.assertEqual(chunk.status_code,200)
        completed=self.client.post(f'/uploads/{identifier}/complete',headers=ticket)
        self.assertEqual(completed.status_code,200)
        self.assertEqual(completed.json()['moderation_status'],'pending')
        playback=self.client.post(f'/submissions/{identifier}/playback',headers=mod)
        self.assertEqual(playback.status_code,200)
        from urllib.parse import urlsplit
        url=urlsplit(playback.json()['url'])
        response=self.client.get(url.path+'?'+url.query,headers={'Range':'bytes=0-15'})
        self.assertEqual(response.status_code,206)
        self.assertEqual(len(response.content),16)
        self.assertIn(b'ftyp',response.content)
        decision=self.client.post(f'/moderation/{identifier}/decision',headers=mod,json={'decision':'approved','reason':'','revision':completed.json()['revision']})
        self.assertEqual(decision.json()['processing_status'],'queued')
        self.assertEqual(self.client.get('/gestures').json(),[])


if __name__=='__main__': unittest.main()
