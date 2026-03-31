import os
import re
import time
import base64
import aiohttp
import discord
import jwt
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN           = os.getenv("DISCORD_TOKEN")
ODESLI_KEY_1            = os.getenv("ODESLI_KEY_1")
ODESLI_KEY_2            = os.getenv("ODESLI_KEY_2")
SPOTIFY_CLIENT_ID       = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET   = os.getenv("SPOTIFY_CLIENT_SECRET")
APPLE_TEAM_ID           = os.getenv("APPLE_TEAM_ID")
APPLE_KEY_ID            = os.getenv("APPLE_KEY_ID")
APPLE_PRIVATE_KEY       = os.getenv("APPLE_PRIVATE_KEY", "").replace("\\n", "\n")

URL_PATTERN = re.compile(
    r'https?://(?:'
    r'open.spotify.com|'
    r'music.apple.com|'
    r'music.youtube.com|'
    r'(?:www.)?youtube.com|'
    r'youtu.be|'
    r'tidal.com|'
    r'deezer.com|'
    r'soundcloud.com|'
    r'music.amazon(?:.co.jp)?'
    r')[^s]*'
)

PLATFORM_LABELS = {
    "spotify":      "Spotify",
    "appleMusic":   "Apple Music",
    "youtubeMusic": "YouTube Music",
    "youtube":      "YouTube",
    "amazonMusic":  "Amazon Music",
    "tidal":        "TIDAL",
    "deezer":       "Deezer",
    "soundcloud":   "SoundCloud",
    "lineMusic":    "LINE MUSIC",
}

# ── Spotify トークンキャッシュ ────────────────────────────
_spotify_token: str | None = None
_spotify_token_expires: float = 0.0


async def get_spotify_token(session: aiohttp.ClientSession) -> str | None:
    global _spotify_token, _spotify_token_expires
    if _spotify_token and time.time() < _spotify_token_expires:
        return _spotify_token
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    credentials = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    async with session.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {credentials}"},
        data={"grant_type": "client_credentials"},
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            _spotify_token = data["access_token"]
            _spotify_token_expires = time.time() + data["expires_in"] - 60
            return _spotify_token
    return None


# ── Apple Music Developer Token キャッシュ ──────────────
_apple_token: str | None = None
_apple_token_expires: float = 0.0


def get_apple_developer_token() -> str | None:
    global _apple_token, _apple_token_expires
    if _apple_token and time.time() < _apple_token_expires:
        return _apple_token
    if not APPLE_TEAM_ID or not APPLE_KEY_ID or not APPLE_PRIVATE_KEY:
        return None
    now = int(time.time())
    exp = now + 15_777_000  # 約6ヶ月
    payload = {"iss": APPLE_TEAM_ID, "iat": now, "exp": exp}
    try:
        _apple_token = jwt.encode(
            payload,
            APPLE_PRIVATE_KEY,
            algorithm="ES256",
            headers={"kid": APPLE_KEY_ID},
        )
        _apple_token_expires = exp - 300
        return _apple_token
    except Exception:
        return None


# ── Odesli (song.link) ───────────────────────────────────
async def fetch_odesli(session: aiohttp.ClientSession, url: str) -> dict | None:
    keys = [k for k in [ODESLI_KEY_1, ODESLI_KEY_2] if k]
    params = {"url": url, "userCountry": "JP"}

    async def _try(key: str | None) -> dict | None:
        p = dict(params)
        if key:
            p["key"] = key
        try:
            async with session.get(
                "https://api.song.link/v1-alpha.1/links",
                params=p,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    for key in (keys or [None]):
        result = await _try(key)
        if result:
            return result
    return None


# ── Spotify API（補完用）────────────────────────────────
async def fetch_spotify_track(session: aiohttp.ClientSession, spotify_url: str) -> dict | None:
    token = await get_spotify_token(session)
    if not token:
        return None
    m = re.search(r'spotify.com/track/([A-Za-z0-9]+)', spotify_url)
    if not m:
        return None
    try:
        async with session.get(
            f"https://api.spotify.com/v1/tracks/{m.group(1)}",
            headers={"Authorization": f"Bearer {token}"},
            params={"market": "JP"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None


# ── Apple Music API（補完用）────────────────────────────
def _extract_apple_song_id(url: str) -> str | None:
    # ?i=SONG_ID 形式（アルバムURLに曲IDが付く場合）
    m = re.search(r'[?&]i=(d+)', url)
    if m:
        return m.group(1)
    # /song/SONG_NAME/SONG_ID 形式
    m = re.search(r'/song/[^/]+/(d+)', url)
    if m:
        return m.group(1)
    return None


async def fetch_apple_music_track(session: aiohttp.ClientSession, apple_url: str) -> dict | None:
    token = get_apple_developer_token()
    if not token:
        return None
    song_id = _extract_apple_song_id(apple_url)
    if not song_id:
        return None
    # ストアフロント判定（URLに /jp/ があればJP、なければUSにフォールバック）
    storefront = "jp" if "/jp/" in apple_url else "us"
    try:
        async with session.get(
            f"https://api.music.apple.com/v1/catalog/{storefront}/songs/{song_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("data", [])
                return items[0] if items else None
    except Exception:
        pass
    return None


# ── Embed 構築 ───────────────────────────────────────────
def build_embed(
    title: str,
    artist: str,
    thumbnail: str | None,
    links: dict[str, str],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎵 {title}",
        description=f"**{artist}**",
        color=0x1DB954,
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    link_lines = [
        f"[{label}]({links[key]})"
        for key, label in PLATFORM_LABELS.items()
        if links.get(key)
    ]
    if link_lines:
        embed.add_field(
            name="各プラットフォームで聴く",
            value="\n".join(link_lines),
            inline=False,
        )

    embed.set_footer(text="SongShareBridger (SSB)")
    return embed


# ── URL 1件の処理 ────────────────────────────────────────
async def process_url(message: discord.Message, session: aiohttp.ClientSession, url: str) -> None:
    title = artist = thumbnail = None
    links: dict[str, str] = {}

    # Step 1: Odesli
    odesli = await fetch_odesli(session, url)
    if odesli:
        entity_id = odesli.get("entityUniqueId", "")
        entity = odesli.get("entitiesByUniqueId", {}).get(entity_id, {})
        title     = entity.get("title")
        artist    = entity.get("artistName")
        thumbnail = entity.get("thumbnailUrl")
        for platform, info in odesli.get("linksByPlatform", {}).items():
            if info.get("url"):
                links[platform] = info["url"]

    # Step 2: Spotify 補完
    if "spotify.com/track/" in url and (not title or not links.get("spotify")):
        sp = await fetch_spotify_track(session, url)
        if sp:
            title     = title     or sp.get("name")
            artist    = artist    or ", ".join(a["name"] for a in sp.get("artists", []))
            thumbnail = thumbnail or (sp.get("album", {}).get("images") or [{}])[0].get("url")
            links.setdefault("spotify", sp.get("external_urls", {}).get("spotify", ""))

    # Step 3: Apple Music 補完
    if "music.apple.com" in url and (not title or not links.get("appleMusic")):
        ap = await fetch_apple_music_track(session, url)
        if ap:
            attrs = ap.get("attributes", {})
            title     = title     or attrs.get("name")
            artist    = artist    or attrs.get("artistName")
            # サムネイルURLの {w}x{h} プレースホルダーを実サイズに展開
            raw_art = attrs.get("artwork", {}).get("url", "")
            thumbnail = thumbnail or raw_art.replace("{w}", "300").replace("{h}", "300")
            links.setdefault("appleMusic", url)

    if not title:
        return  # 情報が取れなければスキップ

    embed = build_embed(title, artist or "Unknown Artist", thumbnail, links)
    await message.channel.send(embed=embed)


# ── Bot 本体 ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    print(f"✅ Logged in as {bot.user}  (ID: {bot.user.id})")


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    urls = URL_PATTERN.findall(message.content)
    if urls:
        async with aiohttp.ClientSession() as session:
            for url in urls:
                await process_url(message, session, url)

    await bot.process_commands(message)


bot.run(DISCORD_TOKEN)