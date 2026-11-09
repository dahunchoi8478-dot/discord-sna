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

# 📌 스나 이모지 고유 ID
TARGET_EMOJI_ID = 1568913180103675914

# 📌 실시간 반응 순서와 시간을 관리하는 메모리 저장소
# 구조: reaction_records[message_id] = [ { 'user_id': ..., 'name': ..., 'time': ... }, ... ]
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

# 📌 1. 이모지를 새로 누른 경우 (추가)
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    if payload.emoji.id == TARGET_EMOJI_ID:
        msg_id = payload.message_id
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

        # 만약 이미 기록에 있다면 기존 기록을 제거 (취소 후 다시 누른 경우 맨 뒤로 보내기 위함)
        reaction_records[msg_id] = [r for r in reaction_records[msg_id] if r['user_id'] != payload.user_id]

        # 맨 뒤(꼴찌 순서)로 새로 추가
        reaction_records[msg_id].append({
            'user_id': payload.user_id,
            'name': final_name,
            'time': click_time
        })

# 📌 2. 이모지를 취소(제거)한 경우
@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.emoji.id == TARGET_EMOJI_ID:
        msg_id = payload.message_id
        if msg_id in reaction_records:
            # 취소한 유저를 기록에서 즉시 삭제
            reaction_records[msg_id] = [r for r in reaction_records[msg_id] if r['user_id'] != payload.user_id]

@bot.tree.command(name="스나명단", description="현재 스나 이모지를 누른 인원의 순서와 시간을 DM으로 받습니다.")
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
        async for msg in channel.history(limit=30):
            if msg.id == interaction.id: continue
            if any(getattr(r.emoji, 'id', None) == TARGET_EMOJI_ID for r in msg.reactions):
                target_message = msg; break

    if not target_message:
        await interaction.followup.send("스나 이모지가 달린 최근 메시지를 찾지 못했습니다.", ephemeral=True)
        return

    msg_id = target_message.id
    current_records = reaction_records.get(msg_id, [])

    # 📌 안전 장치: 봇이 켜지기 전에 이미 눌려있던 유저들을 불러오되, 
    # 현재 실제 메시지에 남아있는 유저들만 필터링하여 동기화
    active_user_ids = set()
    for r in target_message.reactions:
        if getattr(r.emoji, 'id', None) == TARGET_EMOJI_ID:
            async for user in r.users():
                if user.bot: continue
                active_user_ids.add(user.id)
                # 메모리에 아직 없는 유저라면 최초 기록 추가
                if not any(rec['user_id'] == user.id for rec in current_records):
                    m = interaction.guild.get_member(user.id)
                    r_name = m.display_name if m else user.name
                    c_name = clean_nickname(r_name)
                    current_records.append({
                        'user_id': user.id,
                        'name': c_name if c_name else r_name,
                        'time': target_message.created_at.astimezone(timezone(timedelta(hours=9)))
                    })

    # 현재 메시지 리액션에서 취소된 사람들은 메모리에서도 확실하게 제외
    current_records = [r for r in current_records if r['user_id'] in active_user_ids]
    reaction_records[msg_id] = current_records

    if not current_records:
        await interaction.followup.send("현재 스나 이모지를 누른 유저가 없습니다.", ephemeral=True)
        return

    # 순서 및 시·분·초 정렬 출력
    result_lines = []
    for idx, r in enumerate(current_records, 1):
        t_str = r['time'].strftime("%H시%M분%S초")
        result_lines.append(f"{idx}. {r['name']} {t_str}")

    first_line = target_message.content.splitlines()[0] if target_message.content else "스나 명단"
    result_text = f"🎯 **[{first_line}] 스나 명단 (총 {len(current_records)}명)**\n\n" + "\n".join(result_lines)

    try:
        await interaction.user.send(result_text)
        await interaction.followup.send(f"**[{first_line}]** 스나 명단을 DM으로 전송했습니다!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("DM을 보낼 수 없습니다. 디스코드 설정에서 개인 메시지 허용을 켜주세요.", ephemeral=True)

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)