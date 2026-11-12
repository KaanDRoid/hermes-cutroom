"""Platform delivery profiles: one place for every platform specification.

Every numeric value carries the URL it was taken from and the date it was
checked, so a platform change is a one-place update. Fractions in a safe
zone are of the full frame (top/bottom of the height, left/right of the
width) and describe the area the platform's own interface may cover.

`custom` is the 0.1 behaviour: no profile frame, safe zone or limits.
"""

import copy

CHECKED = "2026-11-12"
FINAL_RESOLUTIONS = ("1080", "2160")

_INSTAGRAM_REELS_HELP = "https://help.instagram.com/1038071743007909/"
_INSTAGRAM_REELS_LENGTH = "https://about.instagram.com/features/reels"
_META_REELS_ADS = (
    "https://www.facebook.com/business/ads-guide/update/video/instagram-reels"
)
_INSTAGRAM_MEDIA_API = (
    "https://developers.facebook.com/docs/instagram-platform/"
    "instagram-graph-api/reference/ig-user/media"
)
_SHORTS_LENGTH = "https://support.google.com/youtube/answer/15424877"
_SHORTS_UPLOAD = "https://support.google.com/youtube/answer/12779649"
_GOOGLE_VERTICAL_ADS = "https://support.google.com/google-ads/answer/9128498"
_YOUTUBE_ENCODING = "https://support.google.com/youtube/answer/1722171"
_YOUTUBE_VIDEOS_API = "https://developers.google.com/youtube/v3/docs/videos"
_YOUTUBE_THUMBNAIL = "https://support.google.com/youtube/answer/72431"
_YOUTUBE_END_SCREEN = "https://support.google.com/youtube/answer/6388789"
_TIKTOK_LENGTH = (
    "https://support.tiktok.com/en/using-tiktok/creating-videos/camera-tools"
)
_TIKTOK_IN_FEED_ADS = "https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads"
_TIKTOK_POST_API = (
    "https://developers.tiktok.com/doc/content-posting-api-reference-direct-post"
)
_AES_TD1008 = "https://www.aes.org/wp-content/uploads/2024/01/20210924_TD1008_v3.13.pdf"
_EBU_R95 = "https://tech.ebu.ch/publications/r095"


def _spec(source, **values):
    return {**values, "source": source, "checked": CHECKED}


def _vertical_frame(source):
    return _spec(
        source,
        preview=[1080, 1920],
        final={"1080": [1080, 1920], "2160": [2160, 3840]},
        default_final="1080",
    )


_LOUDNESS = _spec(
    _AES_TD1008,
    integrated_lufs=-14,
    true_peak_db=-1,
    note=(
        "Cutroom's delivery target for every profile. The -1 dBTP ceiling follows "
        "AES TD1008; none of the four platforms publishes an upload loudness "
        "requirement, and -14 LUFS is the common playback normalisation level."
    ),
)

PROFILES = {
    "custom": {
        "label": "Custom",
        "short_label": "Custom",
        "orientation": None,
        "frame": None,
        "min_fps": None,
        "max_duration_s": None,
        "recommended_max_s": None,
        "safe_zone": None,
        "loudness": None,
        "text": None,
        "cover": None,
    },
    "instagram_reels": {
        "label": "Instagram Reels",
        "short_label": "Reels",
        "orientation": "portrait",
        "frame": _vertical_frame(_INSTAGRAM_REELS_HELP),
        "min_fps": _spec(_INSTAGRAM_REELS_HELP, value=30),
        "max_duration_s": _spec(_INSTAGRAM_REELS_LENGTH, value=1200),
        "recommended_max_s": _spec(
            _INSTAGRAM_REELS_LENGTH,
            value=180,
            note="Reels over 3 minutes are not recommended to new audiences.",
        ),
        "safe_zone": _spec(
            _META_REELS_ADS,
            top=0.14,
            bottom=0.35,
            left=0.06,
            right=0.06,
            note="Meta's Reels safe-zone guidance: keep text and faces clear of "
            "the top 14 %, bottom 35 % and 6 % on each side.",
        ),
        "loudness": _LOUDNESS,
        "text": _spec(_INSTAGRAM_MEDIA_API, caption_chars=2200, hashtags=30),
        "cover": _spec(
            _INSTAGRAM_REELS_HELP,
            width=1080,
            height=1920,
            grid_ratio="1:1.55",
            note="The profile grid shows the centre 1:1.55 area of the cover.",
        ),
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "short_label": "Shorts",
        "orientation": "portrait",
        "frame": _vertical_frame(_SHORTS_UPLOAD),
        "min_fps": _spec(_YOUTUBE_ENCODING, value=None, note="Source frame rate."),
        "max_duration_s": _spec(
            _SHORTS_LENGTH,
            value=180,
            note="Longer vertical uploads become regular videos, not Shorts.",
        ),
        "recommended_max_s": None,
        "safe_zone": _spec(
            _GOOGLE_VERTICAL_ADS,
            top=0.15,
            bottom=0.35,
            left=0.05,
            right=0.18,
            note="Google's vertical video safe zone on 1080x1920 (288 px top, "
            "672 px bottom, 48 px left, 192 px right), rounded up. Google "
            "publishes it for vertical ads, which run in Shorts; there is no "
            "separate figure for ordinary Shorts.",
        ),
        "loudness": _LOUDNESS,
        "text": _spec(_YOUTUBE_VIDEOS_API, title_chars=100, description_bytes=5000),
        "cover": _spec(
            _SHORTS_UPLOAD,
            width=1080,
            height=1920,
            note="Shorts use a frame chosen from the video as the cover.",
        ),
    },
    "tiktok": {
        "label": "TikTok",
        "short_label": "TikTok",
        "orientation": "portrait",
        "frame": _vertical_frame(_TIKTOK_IN_FEED_ADS),
        "min_fps": _spec(_TIKTOK_IN_FEED_ADS, value=None, note="Source frame rate."),
        "max_duration_s": _spec(
            _TIKTOK_LENGTH,
            value=3600,
            note="Uploaded videos can be up to 60 minutes long.",
        ),
        "recommended_max_s": None,
        "safe_zone": _spec(
            _TIKTOK_IN_FEED_ADS,
            top=0.13,
            bottom=0.35,
            left=0.12,
            right=0.28,
            note="TikTok's In-Feed safe-zone template, linked from the cited "
            "page, scaled to 1080x1920 (240 px top, 660 px bottom, 120 px each "
            "side, 300 px on the right from 840 px down), rounded up. The page "
            "itself prints no numbers. The right action rail is applied to the "
            "full height so the zone stays one rectangle.",
        ),
        "loudness": _LOUDNESS,
        "text": _spec(
            _TIKTOK_POST_API,
            caption_chars=2200,
            note="Video caption limit of the Content Posting API, counted in "
            "UTF-16 code units. TikTok does not publish an in-app limit.",
        ),
        "cover": _spec(
            _TIKTOK_POST_API,
            width=1080,
            height=1920,
            note="TikTok uses a frame chosen from the video as the cover.",
        ),
    },
    "youtube": {
        "label": "YouTube",
        "short_label": "YouTube",
        "orientation": "landscape",
        "frame": _spec(
            _YOUTUBE_ENCODING,
            preview=[1920, 1080],
            final={"1080": [1920, 1080], "2160": [3840, 2160]},
            default_final="1080",
        ),
        "min_fps": _spec(_YOUTUBE_ENCODING, value=None, note="Source frame rate."),
        "max_duration_s": _spec(
            _YOUTUBE_ENCODING, value=None, note="No practical length limit."
        ),
        "recommended_max_s": None,
        "safe_zone": _spec(
            _EBU_R95,
            top=0.05,
            bottom=0.05,
            left=0.05,
            right=0.05,
            note="Graphics-safe margins of EBU R 95. YouTube publishes no overlay "
            "safe zone for regular videos.",
        ),
        "end_screen": _spec(
            _YOUTUBE_END_SCREEN,
            min_s=5,
            max_s=20,
            note="End screens can cover the last 5 to 20 seconds; keep that "
            "time free of essential text.",
        ),
        "loudness": _LOUDNESS,
        "text": _spec(_YOUTUBE_VIDEOS_API, title_chars=100, description_bytes=5000),
        "cover": _spec(_YOUTUBE_THUMBNAIL, width=1280, height=720),
    },
}
PLATFORMS = tuple(PROFILES)


def profile(name):
    """Return a copy of one profile; unknown names are rejected."""
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError(
            "Unsupported platform; expected one of: " + ", ".join(PLATFORMS)
        )
    return copy.deepcopy(PROFILES[name])


def public_profiles():
    """JSON-safe copies in display order, for the REST API and Desktop page."""
    return [{"name": name, **profile(name)} for name in PLATFORMS]


def frame_size(name, preset, final_resolution=None):
    """Exact output frame for a profile, or None for `custom`."""
    frame = profile(name)["frame"]
    if frame is None:
        return None
    if preset == "preview":
        return tuple(frame["preview"])
    resolution = final_resolution or frame["default_final"]
    if resolution not in FINAL_RESOLUTIONS:
        raise ValueError("final_resolution must be '1080' or '2160'")
    return tuple(frame["final"][resolution])
