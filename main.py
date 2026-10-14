import io
import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from urllib.parse import quote
import asyncio
from PIL import Image, ImageDraw, ImageFont

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
LAUNCHER_URL = os.getenv('LAUNCHER_URL')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='n!', intents=intents)

KNIGHTLIES_FILE = Path('knightlies.json')


@dataclass
class Knightly:
    name: str
    url: str
    order: int
    consistent: bool = False


def load_knightlies() -> list[Knightly]:
    if not KNIGHTLIES_FILE.exists():
        return []
    with open(KNIGHTLIES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return sorted((Knightly(**k) for k in data), key=lambda k: k.order)


def save_knightlies(knightlies: list[Knightly]) -> None:
    for i, k in enumerate(knightlies, start=1):
        k.order = i
    with open(KNIGHTLIES_FILE, 'w', encoding='utf-8') as f:
        json.dump([asdict(k) for k in knightlies], f, indent=2)


def normalize_url(url: str) -> str:
    return url if url.startswith(('http://', 'https://')) else 'https://' + url


@bot.event
async def on_ready():
    print("OH yea")


@bot.command(name='add')
async def add_knightly(ctx, name: str, url: str, order: int = None):
    """n!add "Game Name" https://example.com [order]"""
    knightlies = load_knightlies()

    if any(k.name.lower() == name.lower() for k in knightlies):
        await ctx.send(f"**{name}** is already in the list.")
        return

    new = Knightly(name=name, url=normalize_url(url), order=0)

    if order is None or order > len(knightlies):
        knightlies.append(new)
    else:
        knightlies.insert(max(order, 1) - 1, new)

    save_knightlies(knightlies)
    await ctx.send(f"Added **{name}** at position {knightlies.index(new) + 1}.")


@bot.command(name='remove')
async def remove_knightly(ctx, *, name: str):
    """n!remove Game Name"""
    knightlies = load_knightlies()
    remaining = [k for k in knightlies if k.name.lower() != name.lower()]

    if len(remaining) == len(knightlies):
        await ctx.send(f"Couldn't find **{name}**.")
        return

    save_knightlies(remaining)
    await ctx.send(f"Removed **{name}**.")

@bot.command(name='consistent')
async def set_consistent(ctx, name: str, value: bool):
    """n!consistent "Game Name" true/false"""
    knightlies = load_knightlies()
    match = next((k for k in knightlies if k.name.lower() == name.lower()), None)

    if match is None:
        await ctx.send(f"Couldn't find **{name}**.")
        return

    match.consistent = value
    save_knightlies(knightlies)
    await ctx.send(f"**{match.name}** is now {'a nightly regular' if value else 'in the game bank'}.")

@bot.command(name='see')
async def see_knightlies(ctx):
    """n!see"""
    knightlies = load_knightlies()
    if not knightlies:
        await ctx.send("No knightlies yet. Add one with `n!add \"Name\" url`.")
        return

    def fmt(group):
        return "\n".join(f"{k.order}. **{k.name}**: <{k.url}>" for k in group) or "*none*"

    consistent = [k for k in knightlies if k.consistent]
    bank = [k for k in knightlies if not k.consistent]
    await ctx.send(f"**Consistent**\n{fmt(consistent)}\n\n**Knightly bank**\n{fmt(bank)}")


@bot.command(name='start')
async def start_knightlies(ctx, x: int = 0):
    """n!start [x] - consistent games plus x random games from the bank"""
    knightlies = load_knightlies()
    consistent = [k for k in knightlies if k.consistent]
    bank = [k for k in knightlies if not k.consistent]

    if not consistent and not bank:
        await ctx.send("No knightlies to start.")
        return

    note = ""
    if x > len(bank):
        note = f"\n*(Only {len(bank)} games in the bank, so I picked all of them.)*"
    x = max(0, min(x, len(bank)))

    picked = sorted(random.sample(bank, x), key=lambda k: k.order)
    tonight = consistent + picked 

    payload = quote(json.dumps([k.url for k in tonight]), safe='')
    link = f"{LAUNCHER_URL}#{payload}"

    lines = [f"{i}. {k.name}" + (" FLEX: " if k in picked else "") for i, k in enumerate(tonight, start=1)]
    await ctx.send(
        f"{ctx.author.mention} tonight's knightlies:\n"
        + "\n".join(lines)
        + f"{note}\n\nOH yea:\n<{link}>"
    )

async def try_dm(member: discord.Member, message: str) -> bool:
    """Returns True if the DM was delivered, False if the user has DMs closed."""
    try:
        await member.send(message)
        return True
    except discord.Forbidden:
        return False


DAN_ID = 496261987697688576
ASH_ID = 486549134162001938
JESSE_ID = 458132159228674049

MSG1 = "Sir Dan, you've been summoned for Knightlies personally since you're a bum with server @s turned off. Geegee.!"
MSG2 = "come scran, Dagwood."


@bot.command(name='bums')
async def dm_two(ctx, scope: str = "Both"):
    results = []
    if scope =="Dan":
        try:
            user = await bot.fetch_user(DAN_ID)
            await user.send(MSG1)
            results.append((user.display_name, True))
        except (discord.Forbidden, discord.NotFound):
            results.append((str(user_id), False))
    elif scope == "Jesse":
        try:
            user = await bot.fetch_user(JESSE_ID)
            await user.send(MSG2)
            results.append((user.display_name, True))
        except (discord.Forbidden, discord.NotFound):
            results.append((str(user_id), False))        
    else:
        for user_id, msg in ((DAN_ID, MSG1), (JESSE_ID, MSG2)):
            try:
                user = await bot.fetch_user(user_id)
                await user.send(msg)
                results.append((user.display_name, True))
            except (discord.Forbidden, discord.NotFound):
                results.append((str(user_id), False))

    failed = [name for name, ok in results if not ok]
    if failed:
        await ctx.send(f"Couldn't DM: {', '.join(failed)}")
    else:
        await ctx.send("Bums summoned.")

CRUCIVERBALIST_ROLE_ID = 1542620117903609896
import random
CRUCIVERBALIST_REPLY = ["Let's Larp.", "Yippee, yippee! Daddy can't wait to solve some puzzles!","You cannot fucking say that in 2026.",
                        "Gee Whiz I love crosswords!", "Yet another night I am cuckholded by the Washington Post.", "Not really feelin it 2nite :/"]
NO_PB_REPLY = "Nothing ever happens."
YES_PB_REPLY = "Billions must glom."


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if f"<@&{CRUCIVERBALIST_ROLE_ID}>" in message.content:
        await message.reply(CRUCIVERBALIST_REPLY[random.randint(0,len(CRUCIVERBALIST_REPLY)-1)])

    if bot.user in message.mentions:
        text = message.content
        for mention in (f"<@{bot.user.id}>", f"<@!{bot.user.id}>"):
            text = text.replace(mention, "")
        if text.strip().lower() == "no pb tonight":
            await message.reply(NO_PB_REPLY)
        elif text.strip().lower() == "pb tonight":
            await message.reply(YES_PB_REPLY)

    await bot.process_commands(message)

ASSETS = Path('assets')
BASE_IMAGE = ASSETS / 'base.png'
FONT_PATH = ASSETS / 'gg sans Regular.ttf'
BOLDFONT_PATH = ASSETS / 'gg sans Semibold.ttf'
CARD_POSITION = (40, 200) 
CARD_MAX_WIDTH = 350        


def load_font(size: int):
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default(size)
    
def load_boldfont(size: int):
    try:
        return ImageFont.truetype(str(BOLDFONT_PATH), size)
    except OSError:
        return ImageFont.load_default(size)


def wrap_text(text: str, font, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.split('\n'):
        current = ''
        for word in paragraph.split(' '):
            test = f"{current} {word}".strip()
            if not current or font.getlength(test) <= max_width:
                current = test
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def render_card(avatar_bytes: bytes, name: str, name_color, text: str) -> Image.Image:
    pad, avatar_size, gap, line_h = 16, 44, 12, 24
    name_font, text_font = load_boldfont(20), load_font(18)

    text_max = CARD_MAX_WIDTH - pad * 2 - avatar_size - gap
    lines = wrap_text(text or "[Not pastin allat 🙏]", text_font, text_max)

    content_w = max(max(text_font.getlength(l) for l in lines), name_font.getlength(name))
    width = int(pad * 2 + avatar_size + gap + content_w)
    height = max(int(pad * 2 + 26 + line_h * len(lines)), pad * 2 + avatar_size)

    card = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=12, fill=(49, 51, 56, 255))

    avatar = Image.open(io.BytesIO(avatar_bytes)).convert('RGBA').resize((avatar_size, avatar_size))
    mask = Image.new('L', avatar.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
    card.paste(avatar, (pad, pad), mask)

    x = pad + avatar_size + gap
    draw.text((x, pad - 2), name, font=name_font, fill=name_color)
    y = pad + 26
    for line in lines:
        draw.text((x, y), line, font=text_font, fill=(219, 222, 225))
        y += line_h
    return card


def composite(card: Image.Image) -> io.BytesIO:
    base = Image.open(BASE_IMAGE).convert('RGBA')
    base.paste(card, CARD_POSITION, card)
    buf = io.BytesIO()
    base.save(buf, 'PNG')
    buf.seek(0)
    return buf


@bot.command(name='winArgument')
async def quote_image(ctx):
    """Reply to a message, then run n!winArgument"""
    ref = ctx.message.reference
    if ref is None or ref.message_id is None:
        await ctx.send("Bro's debating no one 😭.")
        return

    try:
        target = ref.resolved if isinstance(ref.resolved, discord.Message) \
            else await ctx.channel.fetch_message(ref.message_id)
    except discord.NotFound:
        await ctx.send("Bro's debating a message that doesnt exist 😭.")
        return

    author = target.author
    avatar_bytes = await author.display_avatar.replace(size=128, format='png').read()

    color = author.color.to_rgb() if getattr(author, 'color', None) and author.color.value else (242, 243, 245)

    def build():
        card = render_card(avatar_bytes, author.display_name, color, target.clean_content)
        return composite(card)

    buf = await asyncio.to_thread(build)
    await ctx.reply(file=discord.File(buf, filename='quote.png'), mention_author=False)

bot.run(token, log_handler=handler, log_level=logging.DEBUG)