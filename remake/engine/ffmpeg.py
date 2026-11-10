"""Locates ffmpeg (PATH, then the imageio-ffmpeg bundled binary)."""

import glob
import os
import shutil

def has_ffmpeg() -> bool:
    return bool(_find_ffmpeg())


def get_ffmpeg_path() -> str:
    return _find_ffmpeg()


def ffmpeg_missing_message() -> str:
    return _ffmpeg_missing_message()


def _ffmpeg_missing_message() -> str:
    return "ffmpeg is not installed. Install Homebrew+ffmpeg or install the bundled binary via: pip install imageio-ffmpeg"


def _find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    home = os.path.expanduser("~")
    candidates: list[str] = []
    candidates.extend(
        glob.glob(os.path.join(home, "Library", "Python", "*", "lib", "python", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-*"))
    )
    candidates.extend(
        glob.glob(os.path.join(home, ".local", "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-*"))
    )
    candidates.extend(
        glob.glob(os.path.join(home, "Library", "Python", "*", "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-*"))
    )
    for exe in candidates:
        if os.path.exists(exe) and os.path.isfile(exe):
            if os.access(exe, os.X_OK):
                return exe
            try:
                st = os.stat(exe)
                os.chmod(exe, st.st_mode | 0o111)
                if os.access(exe, os.X_OK):
                    return exe
            except Exception:
                continue
    return ""

