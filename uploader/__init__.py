"""shorts_automated_uploader — OO browser-automation uploader for short videos.

Public API:
    Settings        — tunable knobs + resolved paths
    Ledger          — JSON record of uploaded videos (content-hash keyed)
    StealthBrowser  — real-Chrome persistent context as a context manager
    LoginManager    — one-time manual login per platform
    VideoUploader   — abstract template-method base
    TikTokUploader / InstagramUploader / YouTubeUploader — platform implementations
"""
from .config import Settings
from .ledger import Ledger
from .browser import StealthBrowser, Monitor
from .auth import LoginManager
from .uploaders import (
    VideoUploader, TikTokUploader, InstagramUploader, YouTubeUploader,
    UploadSkipped, AlreadyUploaded, LoginRequired,
)

__all__ = [
    "Settings", "Ledger", "StealthBrowser", "Monitor", "LoginManager",
    "VideoUploader", "TikTokUploader", "InstagramUploader", "YouTubeUploader",
    "UploadSkipped", "AlreadyUploaded", "LoginRequired",
]
