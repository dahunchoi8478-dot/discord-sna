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

# 📌 1. 이모지를 새로 누른 경우 (밀리초 단위까지 정밀 기록 및 꼴찌 갱신)
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

        # 기존 기록이 있다면 제거 후 맨 뒤로 추가 (취소 후 재클릭 시 꼴찌 이동)
        reaction_records[msg_id] = [r for r in reaction_records[msg_id] if r['user_id'] != payload.user_id]

        reaction_records[msg_id].append({
            'user_id': payload.user_id,
            'name': final_name,
            'time': click_time
        })

# 📌 2. 이모지를 취소한 경우 (목록에서 즉시 지움)
@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.emoji.id == TARGET_EMOJI_ID:
        msg_id = payload.message_id
        if msg_id in reaction_records:
            reaction_records[msg_id] = [r for r in reaction_records[msg_id] if r['user_id'] != payload.user_id]

@bot.tree.command(name="스나명단", description="모바시 채널의 최근 스나 이모지 신청 명단을 밀리초 단위로 DM으로 받습니다.")
@app_commands.describe(키워드="특정 단어나 ID (비워두면 모바시 채널 최근 메시지)")
async def send_snipe_list(interaction: discord.Interaction, 키워드: str = None):
    # 📌 타임아웃(응답 없음) 방지를 위해 가장 먼저 응답 지연 처리 실행
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    # 📌 '모바시' 채널 정확히 탐색
    target_channel = interaction.channel
    for ch in guild.text_channels:
        if "모바시" in ch.name and "전용" not in ch.name:
            target_channel = ch
            break
    
    if target_channel == interaction.channel:
        for ch in guild.text_channels:
            if "모바시" in ch.name:
                target_channel = ch
                break

    target_message = None

    if 키워드:
        if 키워드.isdigit():
            try: target_message = await target_channel.fetch_message(int(키워드))
            except Exception: pass
        if not target_message:
            async for msg in target_channel.history(limit=50):
                if 키워드.strip() in msg.content:
                    target_message = msg; break
    else:
        # 모바시 채널에서 스나 이모지가 달린 가장 최근 메시지 탐색
        async for msg in target_channel.history(limit=30):
            if any(getattr(r.emoji, 'id', None) == TARGET_EMOJI_ID for r in msg.reactions):
                target_message = msg; break

    if not target_message:
        await interaction.followup.send(f"[{target_channel.mention}] 채널에서 스나 이모지가 달린 최근 메시지를 찾지 못했습니다.", ephemeral=True)
        return

    msg_id = target_message.id
    kst = timezone(timedelta(hours=9))
    current_records = reaction_records.get(msg_id, [])
    existing_user_ids = {r['user_id'] for r in current_records}

    active_users = []
    for r in target_message.reactions:
        if getattr(r.emoji, 'id', None) == TARGET_EMOJI_ID:
            async for user in r.users():
                if user.bot: continue
                active_users.append(user)

    active_user_ids = {u.id for u in active_users}

    # 1. 리액션을 뺀 사람은 기록에서 확실히 삭제
    current_records = [r for r in current_records if r['user_id'] in active_user_ids]

    # 2. 메모리에 미처 안 들어간 기존 유저는 안전하게 추가
    for user in active_users:
        if user.id not in existing_user_ids:
            m = guild.get_member(user.id)
            r_name = m.display_name if m else user.name
            c_name = clean_nickname(r_name)
            current_records.append({
                'user_id': user.id,
                'name': c_name if c_name else r_name,
                'time': datetime.now(kst)
            })

    reaction_records[msg_id] = current_records

    if not current_records:
        await interaction.followup.send(f"[{target_channel.mention}] 채널의 최근 메시지에 스나 이모지를 누른 유저가 없습니다.", ephemeral=True)
        return

    # 📌 순서 및 밀리초(시·분·초.밀리초) 포함하여 정렬 출력
    result_lines = []
    for idx, r in enumerate(current_records, 1):
        t_str = r['time'].strftime("%H시%M분%S초") + f".{r['time'].microsecond // 100000:01d}"
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