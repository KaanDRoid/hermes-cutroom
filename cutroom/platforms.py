"""Platform delivery profiles: one place for every platform specification.

Every numeric value carries the URL it was taken from and the date it was
checked, so a platform change is a one-place update. Fractions in a safe
zone are of the full frame (top/bottom of the height, left/right of the
width) and describe the area the platform's own interface may cover.

`custom` is the 0.1 behaviour: no profile frame, safe zone or limits.
"""

import copy

CHECKED = "2026-11-12"
# Long-form YouTube rules (chapters, thumbnail, end screens) were rechecked for F6.
LONGFORM_CHECKED = "2026-11-13"
# Post text limits were rechecked on the cited pages for F7 delivery packages.
TEXT_CHECKED = "2026-11-13"
FINAL_RESOLUTIONS = ("1080", "2160")

_INSTAGRAM_REELS_HELP = "https://help.instagram.com/1038071743007909/"
# Rendered with JavaScript; the static HTML still carries an older
# "up to 3 minutes" description. The rendered article states the values used.
_INSTAGRAM_REELS_LENGTH = "https://help.instagram.com/2720958398006062"
_META_REELS_ADS = (
    "https://www.facebook.com/business/ads-guide/update/video/instagram-reels"
)
_INSTAGRAM_MEDIA_API = (
    "https://developers.facebook.com/documentation/instagram-platform/"
    "instagram-graph-api/reference/ig-user/media"
)
_SHORTS_LENGTH = "https://support.google.com/youtube/answer/15424877"
_SHORTS_UPLOAD = "https://support.google.com/youtube/answer/12779649"
_GOOGLE_VERTICAL_ADS = "https://support.google.com/google-ads/answer/9128498"
_YOUTUBE_ENCODING = "https://support.google.com/youtube/answer/1722171"
_YOUTUBE_VIDEOS_API = (
    "https://developers.google.com/youtube/data/reference/rest/v3/videos"
)
_YOUTUBE_THUMBNAIL = "https://support.google.com/youtube/answer/72431"
_YOUTUBE_END_SCREEN = "https://support.google.com/youtube/answer/6388789"
_YOUTUBE_CHAPTERS = "https://support.google.com/youtube/answer/9884579"
_YOUTUBE_HASHTAGS = "https://support.google.com/youtube/answer/6390658"
# The former support.tiktok.com "camera tools" address redirects here.
_TIKTOK_LENGTH = "https://www.tiktok.com/support/faq_detail?id=7581821547946580492"
_TIKTOK_IN_FEED_ADS = (
    "https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads"
)
_TIKTOK_POST_API = (
    "https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post"
)
# The AES landing page for the document is
# https://aes.org/community/technical-council/technical-document-aestd1008/
_AES_TD1008 = "https://aes.org/wp-content/uploads/2026/10/20210924_TD1008_v3.13.pdf"
_EBU_R95 = "https://tech.ebu.ch/docs/r/r095.pdf"


def _spec(source, **values):
    return {"checked": CHECKED, **values, "source": source}


def _vertical_frame(source, rule):
    return _spec(
        source,
        preview=[1080, 1920],
        final={"1080": [1080, 1920], "2160": [2160, 3840]},
        default_final="1080",
        chosen_by="cutroom",
        platform_rule=rule,
        note="1080x1920 (and the opt-in 2160x3840) is Cutroom's choice within "
        "the platform rule; the cited page does not prescribe this exact frame.",
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
        "frame": _vertical_frame(
            _INSTAGRAM_REELS_HELP,
            "Aspect ratio between 1.91:1 and 9:16, minimum resolution 720 pixels. "
            "Meta's Reels ads guide recommends 1440x2560.",
        ),
        "min_fps": _spec(
            _INSTAGRAM_REELS_HELP,
            value=30,
            note="Cutroom treats the NTSC rate 30000/1001 (29.97) as meeting 30.",
        ),
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
        "text": _spec(
            _INSTAGRAM_MEDIA_API,
            checked=TEXT_CHECKED,
            caption_chars=2200,
            hashtags=30,
            mentions=20,
            note="Maximum 2,200 characters, 30 hashtags and 20 @ tags per caption.",
        ),
        "cover": _spec(
            _INSTAGRAM_REELS_HELP,
            width=420,
            height=654,
            ratio="1:1.55",
            note="Recommended cover photo size; it cannot be edited after upload.",
        ),
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "short_label": "Shorts",
        "orientation": "portrait",
        "frame": _vertical_frame(
            _SHORTS_UPLOAD,
            "Square or vertical aspect ratio, up to 3 minutes.",
        ),
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
        "text": _spec(
            _YOUTUBE_VIDEOS_API,
            checked=TEXT_CHECKED,
            title_chars=100,
            description_bytes=5000,
            forbidden="<>",
            hashtags=60,
            hashtags_source=_YOUTUBE_HASHTAGS,
            note="Title at most 100 characters and description at most 5,000 "
            "bytes, neither containing < or >. With more than 60 hashtags YouTube "
            "ignores every hashtag on the video (YouTube Help).",
        ),
        "cover": _spec(
            _YOUTUBE_THUMBNAIL,
            width=2160,
            height=3840,
            min_height=640,
            ratio="9:16",
            note="Recommended custom Shorts thumbnail. Custom Shorts thumbnails "
            "are uploaded in YouTube Studio on a computer by verified accounts; "
            "otherwise a frame from the video is used.",
        ),
    },
    "tiktok": {
        "label": "TikTok",
        "short_label": "TikTok",
        "orientation": "portrait",
        "frame": _vertical_frame(
            _TIKTOK_IN_FEED_ADS,
            "Vertical 9:16 recommended, at least 540x960 pixels.",
        ),
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
            checked=TEXT_CHECKED,
            caption_chars=2200,
            hashtags=None,
            note="Video caption limit of the Content Posting API, counted in "
            "UTF-16 code units. TikTok does not publish an in-app limit or a "
            "hashtag limit.",
        ),
        "cover": _spec(
            _TIKTOK_POST_API,
            note="TikTok uses a frame chosen from the video as the cover "
            "(video_cover_timestamp_ms in the Content Posting API).",
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
            chosen_by="cutroom",
            platform_rule="16:9 is the standard aspect ratio on a computer; "
            "the recommended bitrates cover uploads up to 2160p.",
            note="1920x1080 (and the opt-in 3840x2160) is Cutroom's choice of "
            "16:9 frame.",
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
            checked=LONGFORM_CHECKED,
            min_s=5,
            max_s=20,
            min_video_s=25,
            note="End screens can cover the last 5 to 20 seconds of a video of at "
            "least 25 seconds; elements can be dragged anywhere in the frame, so "
            "Cutroom keeps that time free of burned text.",
        ),
        "chapters": _spec(
            _YOUTUBE_CHAPTERS,
            checked=LONGFORM_CHECKED,
            first_s=0,
            min_count=3,
            min_length_s=10,
            title_chars=100,
            note="The first timestamp starts at 00:00, at least three timestamps "
            "in ascending order, each chapter at least 10 seconds. YouTube "
            "publishes no title length; 100 characters is Cutroom's limit, and "
            "the whole list must fit the 5,000-byte description.",
        ),
        "loudness": _LOUDNESS,
        "text": _spec(
            _YOUTUBE_VIDEOS_API,
            checked=TEXT_CHECKED,
            title_chars=100,
            description_bytes=5000,
            forbidden="<>",
            hashtags=60,
            hashtags_source=_YOUTUBE_HASHTAGS,
            note="Title at most 100 characters and description at most 5,000 "
            "bytes, neither containing < or >. With more than 60 hashtags YouTube "
            "ignores every hashtag on the video (YouTube Help).",
        ),
        "cover": _spec(
            _YOUTUBE_THUMBNAIL,
            checked=LONGFORM_CHECKED,
            width=3840,
            height=2160,
            min_width=640,
            ratio="16:9",
            max_bytes=2_000_000,
            note="Recommended custom video thumbnail; make it as large as possible. "
            "Uploads may be up to 2 MB from a phone and 50 MB from a computer; "
            "Cutroom keeps thumbnails under 2 MB so both work.",
        ),
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
