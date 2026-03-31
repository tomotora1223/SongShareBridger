import discord
import os
import re
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# --- 簡易HTTPサーバー（Renderの無料Web Service用） ---
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass  # アクセスログを抑制

def run_server():
    HTTPServer(("0.0.0.0", 10000), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# --- Discord Bot 設定 ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

MUSIC_URL_PATTERN = re.compile(
    r'https?://(open\.spotify\.com|music\.apple\.com|music\.youtube\.com|tidal\.com|deezer\.com)/\S+'
)

PLATFORM_INFO = {
    "spotify": {
        "name": "Spotify",
        "icon": "https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png",
        "color": 0x1DB954,
        "label": "Spotifyで開く",
    },
    "appleMusic": {
        "name": "Apple Music",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5f/Apple_Music_icon.svg/240px-Apple_Music_icon.svg.png",
        "color": 0xFC3C44,
        "label": "Apple Musicで開く",
    },
    "youtubeMusic": {
        "name": "YouTube Music",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Youtube_Music_icon.svg/240px-Youtube_Music_icon.svg.png",
        "color": 0xFF0000,
        "label": "YouTube Musicで開く",
    },
    "tidal": {
        "name": "TIDAL",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c7/Tidal_%28service%29_logo.svg/240px-Tidal_%28service%29_logo.svg.png",
        "color": 0x000000,
        "label": "TIDALで開く",
    },
    "deezer": {
        "name": "Deezer",
        "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/Deezer_logo.svg/240px-Deezer_logo.svg.png",
        "color": 0xA238FF,
        "label": "Deezerで開く",
    },
}


def get_odesli_data(url: str) -> dict | None:
    try:
        res = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": url, "userCountry": "JP"},
            timeout=10,
        )
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Odesli APIエラー: {e}")
    return None


def build_embed_and_view(data: dict):
    entity_data = data.get("entitiesByUniqueId", {})
    links_by_platform = data.get("linksByPlatform", {})

    title = "不明なタイトル"
    artist = ""
    thumbnail = None

    for entity in entity_data.values():
        title = entity.get("title") or title
        artist = entity.get("artistName") or artist
        thumbnail = entity.get("thumbnailUrl") or thumbnail
        break

    embed_color = 0x5865F2
    for platform_key, info in PLATFORM_INFO.items():
        if platform_key in links_by_platform:
            embed_color = info["color"]
            break

    embed = discord.Embed(title=title, description=artist, color=embed_color)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    embed.set_footer(text="Powered by Odesli (song.link)")

    view = discord.ui.View()
    for platform_key, info in PLATFORM_INFO.items():
        if platform_key in links_by_platform:
            platform_url = links_by_platform[platform_key].get("url")
            if platform_url:
                view.add_item(
                    discord.ui.Button(
                        label=info["label"],
                        url=platform_url,
                        style=discord.ButtonStyle.link,
                    )
                )

    return embed, view


@client.event
async def on_ready():
    print(f"ログイン完了: {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    match = MUSIC_URL_PATTERN.search(message.content)
    if not match:
        return

    url = match.group(0)

    async with message.channel.typing():
        data = get_odesli_data(url)

    if not data:
        await message.channel.send("リンクの変換に失敗しました 😢")
        return

    embed, view = build_embed_and_view(data)

    if not view.children:
        await message.channel.send("対応するプラットフォームのリンクが見つかりませんでした。")
        return

    await message.channel.send(embed=embed, view=view)


client.run(TOKEN)