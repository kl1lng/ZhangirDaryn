"""Coordinate-only public snapshot; never exports source videos or identities."""
import argparse
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
import numpy as np

from backend.import_motion import PUBLIC_METADATA
from backend.store import Store


def export_library(source, destination):
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('Choose an empty destination for a new library snapshot.')
    catalog=[]
    files={}
    camera=[]
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT s.id,s.label,s.language,a.payload,a.checksum,a.metadata
            FROM pwa_submissions s JOIN pwa_artifacts a ON a.submission_id=s.id
            WHERE s.moderation_status='approved' AND s.processing_status='ready'
            AND s.rights=1 ORDER BY s.label,s.id''').fetchall()
        for row in rows:
            if not re.fullmatch(r'[a-zA-Z0-9_-]+',row['id']):
                raise ValueError('Invalid public gesture identifier.')
            array,metadata=Store.unpack(row)
            if metadata.get('training_eligible') is False:
                continue
            public={key:value for key,value in metadata.items() if key in PUBLIC_METADATA}
            public.update(fps=metadata['fps'],shape=list(array.shape),schema_version=1)
            motion={'id':row['id'],'label':row['label'],'language':row['language'],
                    'sequence':array.tolist(),'fps':metadata['fps'],
                    'metadata':public,'version':row['checksum']}
            files[row['id']+'.json']=json.dumps(motion,ensure_ascii=False,allow_nan=False,separators=(',',':'))
            catalog.append({'id':row['id'],'label':row['label'],'language':row['language'],
                            'metadata':{'fps':metadata['fps'],'shape':list(array.shape)},'version':row['checksum']})
            positions=np.linspace(0,len(array)-1,16)
            sample=np.stack([np.interp(positions,np.arange(len(array)),array[:,axis]) for axis in range(126)],axis=1)
            camera.append({'id':row['id'],'label':row['label'],'sequence':sample.round(6).tolist()})
    files['catalog.json']=json.dumps(catalog,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    files['camera.json']=json.dumps({'schema':1,'references':camera},ensure_ascii=False,allow_nan=False,separators=(',',':'))
    destination.mkdir(parents=True,exist_ok=True)
    for name,content in files.items():
        (destination/name).write_text(content,encoding='utf-8')
    return {'records':len(catalog),'labels':len(set(row['label'] for row in catalog)),
            'files':len(files),'bytes':sum(len(content.encode('utf-8')) for content in files.values())}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--destination',required=True)
    args=parser.parse_args()
    print(json.dumps(export_library(args.source,args.destination)))
