import os
import re
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
import threading

# 📌 렌더 웹서버 (24시간 유지용)
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"
def run(): app.run(host='0.0.0.0', port=10000)
def keep_alive(): threading.Thread(target=run).start()
keep_alive()

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

# 📌 알려주신 '스나' 이모지의 고유 숫자 ID 적용
TARGET_EMOJI_ID = 1568913180103675914

# 📌 실시간 반응 시간과 순서를 저장하는 메모리
reaction_records = {}

def clean_nickname(name: str) -> str:
    """닉네임 정제 (년생/특수문자 제거)"""
    cleaned = re.sub(r'[\(\[\{].*?[\)\]\}]', '', name)
    cleaned = re.sub(r'\d{2,4}', '', cleaned)
    cleaned = re.sub(r'[^\w\s가-힣a-zA-R]', '', cleaned)
    return cleaned.strip()

@bot.event
async def on_ready():
    print(f"로그인 성공: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"명령어 동기화 완료: {len(synced)}개")
    except Exception as e:
        print(e)

# 📌 지정된 이모지 ID가 눌리는 순간의 극초 단위 시·분·초 실시간 기록
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    # 오직 지정된 스나 이모지 ID만 정확히 추출
    if payload.emoji.id == TARGET_EMOJI_ID:
        msg_id = payload.message_id
        
        # 한국 시간(KST) 적용
        kst = timezone(timedelta(hours=9))
        click_time = datetime.now(kst)

        guild = bot.get_guild(payload.guild_id)
        member = payload.member
        if not member and guild:
            member = guild.get_member(payload.user_id)

        raw_name = member.display_name if member else (payload.member.name if payload.member else "알수없음")
        cleaned = clean_nickname(raw_name)
        final_name = cleaned if cleaned else raw_name

        if msg_id not in reaction_records:
            reaction_records[msg_id] = []

        if not any(r['user_id'] == payload.user_id for r in reaction_records[msg_id]):
            reaction_records[msg_id].append({
                'user_id': payload.user_id,
                'name': final_name,
                'time': click_time
            })

@bot.tree.command(name="스나명단", description="스나 이모지가 눌린 순서와 정확한 시간을 DM으로 받습니다.")
@app_commands.describe(키워드="특정 단어나 ID (비워두면 최근 메시지)")
async def send_snipe_list(interaction: discord.Interaction, 키워드: str = None):
    await interaction.response.defer(ephemeral=True)
    channel = interaction.channel
    target_message = None

    if 키워드:
        if 키워드.isdigit():
            try: target_message = await channel.fetch_message(int(키워드))
            except Exception: pass
        if not target_message:
            async for msg in channel.history(limit=50):
                if 키워드.strip() in msg.content:
                    target_message = msg; break
    else:
        # 해당 이모지 ID가 달린 최근 메시지 찾기 (다른 이모지가 섞여 있어도 무시)
        async for msg in channel.history(limit=30):
            if msg.id == interaction.id: continue
            if any(getattr(r.emoji, 'id', None) == TARGET_EMOJI_ID for r in msg.reactions):
                target_message = msg; break

    if not target_message:
        await interaction.followup.send("스나 이모지가 달린 최근 메시지를 찾지 못했습니다.", ephemeral=True)
        return

    msg_id = target_message.id
    records = reaction_records.get(msg_id, [])

    # 백업 처리 (봇이 재시작되었거나 이벤트를 놓쳤을 때 기존 메시지 리액션에서 추출)
    if not records:
        for r in target_message.reactions:
            if getattr(r.emoji, 'id', None) == TARGET_EMOJI_ID:
                async for user in r.users():
                    if user.bot: continue
                    m = interaction.guild.get_member(user.id)
                    r_name = m.display_name if m else user.name
                    c_name = clean_nickname(r_name)
                    records.append({
                        'user_id': user.id,
                        'name': c_name if c_name else r_name,
                        'time': target_message.created_at.astimezone(timezone(timedelta(hours=9)))
                    })

    if not records:
        await interaction.followup.send("스나 이모지를 누른 유저가 없습니다.", ephemeral=True)
        return

    # 순서 및 시·분·초 정리 (예: 1. 다후링 11시13분25초)
    result_lines = []
    for idx, r in enumerate(records, 1):
        t_str = r['time'].strftime("%H시%M분%S초")
        result_lines.append(f"{idx}. {r['name']} {t_str}")

    first_line = target_message.content.splitlines()[0] if target_message.content else "스나 명단"
    result_text = f"🎯 **[{first_line}] 스나 명단 (총 {len(records)}명)**\n\n" + "\n".join(result_lines)

    try:
        await interaction.user.send(result_text)
        await interaction.followup.send(f"**[{first_line}]** 스나 명단을 DM으로 전송했습니다!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("DM을 보낼 수 없습니다. 디스코드 설정에서 개인 메시지 허용을 켜주세요.", ephemeral=True)

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)