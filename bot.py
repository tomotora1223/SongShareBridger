import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import logging

# ── ログ設定 ──────────────────────────────
logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [%(levelname)s] %(message)s",
  handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ── Bot設定 ───────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ── yt-dlpオプション ──────────────────────
YDL_OPTS = {
  "format": "bestaudio/best",
  "quiet": True,
  "noplaylist": True,
}

FFMPEG_OPTS = {
  "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
  "options": "-vn",
}

# ── イベント ──────────────────────────────
@bot.event
async def on_ready():
  logger.info(f"ボット起動完了: {bot.user} (ID: {bot.user.id})")
  logger.info(f"接続サーバー数: {len(bot.guilds)}")

@bot.event
async def on_message(message):
  if message.author.bot:
    return
  logger.info(f"メッセージ受信 | 送信者: {message.author} | 内容: {message.content}")
  await bot.process_commands(message)

# ── コマンド ──────────────────────────────
@bot.command(name="play")
async def play(ctx, url: str):
  logger.info(f"playコマンド実行 | ユーザー: {ctx.author} | URL: {url}")

  if not ctx.author.voice:
    logger.warning(f"{ctx.author} はボイスチャンネルに未接続")
    await ctx.send("ボイスチャンネルに入ってから使ってね！")
    return

  channel = ctx.author.voice.channel

  try:
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
      info = ydl.extract_info(url, download=False)
      audio_url = info["url"]
      title = info.get("title", "不明")
    logger.info(f"音声取得成功: {title}")
  except Exception as e:
    logger.error(f"yt-dlp エラー: {e}")
    await ctx.send("音声の取得に失敗しました。")
    return

  try:
    vc = await channel.connect()
    logger.info(f"ボイスチャンネル接続: {channel.name}")
  except discord.ClientException:
    vc = ctx.voice_client
    logger.info("既存のボイス接続を再利用")

  vc.play(
    discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTS),
    after=lambda e: logger.error(f"再生エラー: {e}") if e else logger.info("再生完了")
  )
  await ctx.send(f"🎵 再生中: **{title}**")

@bot.command(name="stop")
async def stop(ctx):
