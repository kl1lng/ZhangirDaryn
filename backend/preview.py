"""Private H.264 previews; extraction still uses the original source."""
from pathlib import Path
import subprocess
import tempfile
import threading
from backend.store import DomainError
_lock=threading.Lock()

def browser_preview(settings,storage,row):
    directory=settings.data_dir/'previews';directory.mkdir(parents=True,exist_ok=True)
    target=directory/(row['id']+'.mp4')
    with _lock:
        if target.exists():return target
        import imageio_ffmpeg
        with storage.materialize(row) as source,tempfile.TemporaryDirectory(dir=directory) as temporary:
            output=Path(temporary)/'preview.mp4'
            command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-nostdin','-y',
                '-i',str(source),'-map','0:v:0','-an','-vf',
                "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                '-c:v','libx264','-preset','fast','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
            try:subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
            except (subprocess.SubprocessError,OSError):raise DomainError('Не удалось подготовить предпросмотр. Попробуйте запись H.264 MP4.',422)
            output.replace(target)
    return target
