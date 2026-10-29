"""python -m backend.run --local-demo (loopback only, no cloud calls)."""
import argparse
import os
import threading
import uvicorn

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--local-demo',action='store_true');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='127.0.0.1');args=parser.parse_args()
    if args.local_demo:
        if args.host not in ('127.0.0.1','::1','localhost'):parser.error('Local demo must bind to loopback.')
        os.environ['DOSYM_LOCAL_AUTH']='1';os.environ['DOSYM_STORAGE']='local'
    from backend.settings import Settings,load_local_environment
    load_local_environment()
    from backend.api import create_app
    from backend.worker import loop
    settings=Settings()
    if settings.local_auth and args.host not in ('127.0.0.1','::1','localhost'):parser.error('Local identities require loopback binding.')
    app=create_app(settings);stop=threading.Event()
    worker=threading.Thread(target=loop,args=(app.state.store,app.state.storage,settings,stop),daemon=True);worker.start()
    try:uvicorn.run(app,host=args.host,port=args.port,access_log=False)
    finally:stop.set();worker.join(timeout=3)

if __name__=='__main__':main()
