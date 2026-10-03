import io
import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

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


# ---------- storage ----------

def load_knightlies() -> list[Knightly]:
    if not KNIGHTLIES_FILE.exists():
        return []
    with open(KNIGHTLIES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return sorted((Knightly(**k) for k in data), key=lambda k: k.order)


def save_knightlies(knightlies: list[Knightly]) -> None:
    # Renumber so orders are always 1..N with no gaps
    for i, k in enumerate(knightlies, start=1):
        k.order = i
    with open(KNIGHTLIES_FILE, 'w', encoding='utf-8') as f:
        json.dump([asdict(k) for k in knightlies], f, indent=2)


def normalize_url(url: str) -> str:
    return url if url.startswith(('http://', 'https://')) else 'https://' + url


# ---------- commands ----------

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


@bot.command(name='see')
async def see_knightlies(ctx):
    """n!see"""
    knightlies = load_knightlies()
    if not knightlies:
        await ctx.send("No knightlies yet. Add one with `n!add \"Name\" url`.")
        return

    # <url> stops Discord from generating a preview embed for every link
    lines = [f"{k.order}. **{k.name}**: <{k.url}>" for k in knightlies]
    await ctx.send("**Tonight's Knightlies**\n" + "\n".join(lines))


LAUNCHER_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Knightlies Launcher</title></head>
<body style="font-family:sans-serif;text-align:center;margin-top:80px">
  <h1>Ready to start the knightlies?</h1>
  <p>{count} tabs will open. Allow pop-ups if your browser asks.</p>
  <button style="font-size:1.5em;padding:12px 32px" onclick="launch()">Open all</button>
  <script>
    const urls = {urls};
    function launch() {{ urls.forEach(u => window.open(u, '_blank')); }}
  </script>
</body>
</html>
"""


@bot.command(name='start')
async def start_knightlies(ctx):
    """n!start - sends a one-click launcher file"""
    knightlies = load_knightlies()
    if not knightlies:
        await ctx.send("No knightlies to start.")
        return

    html = LAUNCHER_HTML.format(
        count=len(knightlies),
        urls=json.dumps([k.url for k in knightlies]),
    )
    file = discord.File(io.BytesIO(html.encode('utf-8')), filename='start_knightlies.html')
    await ctx.send(
        f"{ctx.author.mention} download this, open it, and click the button:",
        file=file,
    )


bot.run(token, log_handler=handler, log_level=logging.DEBUG)