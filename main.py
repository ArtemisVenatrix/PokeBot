# main

# /////////////////////////////////////////
# TODO for v1.1 patch:
#
#  - DONE: make 'designate_art_channel' send a status response in discord
#  - DONE: add support for audio files in 'submitart'
#  - DONE: make persistent vars initialize its own entry on setup so it wont crash 'check_streaks'
#  - DONE: setup test bot
#  - DONE: have bot remove guild from local db when removed and check for removed guilds on startup
#  - DONE: update code comments
#  - DONE: add a help function for the slash commands that explains how the features work
#  - DONE: Fix bug where reminders arent sent if there was a streak submission yesterday
#  - DONE: make it so vc notifs don't message the user who just joined the vc
#
# TODO for v1.2 hotfix:
#
#  - DONE: fix designate_art_channel command
#  - DONE: migrate scheduled functions to discord's internal scheduler
#  - DONE: fix redundant streak reminders bug
#
# TODO for v1.3 hotfix:
#
#  - DONE: fix subscription commands with new db structure
#  - DONE: try to recover old db file
#
# TODO for v2 release:
#
#  - DONE: setup proper error logging
#  - DONE: organize features into discord.py's 'cog' extension
#  - TODO: Finnish info logging setup in cogs
#  - TODO: Make the user tracking update on events and startup rather than when checking a user
#  - TODO: rebuild models around a dedicated user table
#
#  TODO for future releases:
#
#  - TODO: make setup initialize a .env file
#  - TODO: fix setup.sh
#  - TODO: add a config file that determines whether setup has been done before
#  - TODO: add per user config options that allow setting timezone for things like reminders
#  - TODO: modify the 'push_reminder' function so that the message provided is different at random
#  - DONE: rewrite all of the sql statements to use the newer 'query' syntax
#
# ////////////////////////////////////////////


import os
import typing
import json
import logging.handlers
import traceback

from dotenv import load_dotenv
from discord.ext import commands
import discord
from discord import app_commands
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Guild
from myBot import MyBot


# Create database engine from the engine factory and instantiate the session factory based on the persistent engine
engine = create_engine("sqlite:///poke_bot.db", echo=False)
Session = sessionmaker(bind=engine)

# set discords special permission requests, in this case viewing message content, and initialize the bot object
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = MyBot('!', intents, Session)
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
logging.getLogger('discord.http').setLevel(logging.INFO)
logging.getLogger("discord.exception").setLevel(logging.ERROR)

handler = logging.handlers.RotatingFileHandler(
    'poke_bot.log',
    encoding='utf-8',
    maxBytes=32 * 1024, #32 KiB
    backupCount=5, # rotate through five log files
    mode='w'
)
dt_fmt = '%Y-%m-%d %H:%M:%S'
formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style="{")
handler.setFormatter(formatter)
logger.addHandler(handler)

# load environmental variables and retrieve the bot token from them
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')


"""
# Event handler for when the bot has finished startup sequence
# In this handler we have implemented a function that handles one of the two cases under which a new guild will have
# to be registered with the bot side database and one of two cases in which a guild should be removed from the local db
# @Params:
# NONE
"""
@bot.event
async def on_ready():
    bot.logInfo(f"Logged in as {bot.user}")
    discordGuilds = []
    # open a session with the database
    with Session() as session:
        try:
            # Iterate through all guild entries stored on local db and compare them with guilds that the bot is
            # currently a member of. If any are in the db that the bot is no longer a member of, then send them to the
            # 'unregister_guild' function for removal.
            guilds = session.query(Guild).all()
            guildsToDelete = []
            print(guildsToDelete[4])
            for guild in guilds:
                discordGuildObj = discord.utils.get(bot.guilds, id=guild.id)
                if discordGuildObj is None:
                    guildsToDelete.append(guild)
            # Iterate through all guilds the bot is a member of and compare each of them to the ones registered in the
            # db. If any are not found in the db they are queued in the 'discordGuilds' array to be sent to the
            # registering function.
            for guild in bot.guilds:
                result = session.query(Guild.id).filter(Guild.id.in_([guild.id])).first()
                if result is None:
                    discordGuilds.append(guild)
        except Exception as e:
            bot.logError(e)
    # If the queue of guild entries to be removed has anything in it, send it off to the 'unregister_guild' function.
    if len(guildsToDelete) > 0:
        unregister_guild(guildsToDelete)
    # If the queue of new guilds to be registered has anything in it, send it off to the 'register_guild' function.
    if len(discordGuilds) > 0:
        register_guild(discordGuilds)


@bot.event
async def setup_hook() -> None:
    bot.logInfo("Loading Cogs")
    for filename in os.listdir('cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')
            bot.logInfo(f"Loaded Cog: {filename[:-3]}")
        else:
            bot.logWarning("Unable to load pycache folder.")


"""
# Event handler for when the bot joins a guild while running.
# All that's embedded in this handler is a call to the same 'register_guild' function used in 'on_ready' that just
# passes along the guild just joined.
# @Params:
# guild; Expected Type: discord.Guild - guild that was joined
"""
@bot.event
async def on_guild_join(guild):
    register_guild([guild])


"""
# Event handler for when the bot is removed from a guild while running.
# The only thing embedded in this handler is a call to the same 'unregister_guild' function used in 'on_ready' that
# passes along the guild just removed.
# @Params:
# guild; Expected Type: discord.Guild - guild that was just removed
"""
@bot.event
async def on_guild_remove(guild):
    unregister_guild([guild])


"""
# Helper function that handles the removal of guild entries from the local db.
# Iterates through the provided list of guilds and removes from the local db.
# @Params:
# guilds; Expected Type: [discord.Guild] - list of guilds to remove from local db
"""
def unregister_guild(guilds: [discord.Guild]):
    bot.logInfo("Unregistering Guilds...")
    with Session() as session:
        try:
            for guild in guilds:
                session.query(Guild).filter(Guild.id == guild.id).delete()
                bot.logInfo(f"Removing guild: \"{guild.name}\" from session...")
            session.commit()
            bot.logInfo("Changes Committed! Unregistration successful.")
        except Exception as e:
            bot.logError(e)


"""
# Private function for handling the registration of new guilds in the bot side database.
# @Params: 
# guilds; Expected Type: [discord.Guild] - list of guilds to register
"""
def register_guild(guilds: [discord.Guild]):
    bot.logInfo("Registering New Guilds...")
    # Start a session with the bot side database
    with Session() as session:
        try:
            for guild in guilds:
                guildObj = Guild(id=guild.id)
                session.add(guildObj)
                bot.logInfo(f"Adding guild: \"{guild.name}\" to session...")
            session.commit()
            bot.logInfo("Guilds committed! Registration Successful.")
        except Exception as e:
            bot.logError(e)


"""
# Command that responds with a description of what features are available on the bot and how to use them.
# The bot just returns the tutorial in string form in its response.
# @Params:
# NONE
"""
@bot.tree.command(
    description="Responds with a written introduction to the features of the bot and how to use them.")
@app_commands.describe(entry="Choose the manual entry you want to view. Leave blank for the main page.")
@app_commands.choices(entry=[
    app_commands.Choice(name="Voice Chat Notifications", value="vc"),
    app_commands.Choice(name="Art Streaks", value="as")
])
async def help(interaction: discord.Interaction, entry: typing.Optional[app_commands.Choice[str]]):
    try:
        if entry is None:
            entry = "mn"
        else:
            entry = entry.value
        with open("manual_entries.json", 'r') as f:
            manual = json.load(f)
        entryStr = manual[entry]
        await interaction.response.send_message(entryStr)
    except Exception as e:
        bot.logError(e)


"""
# Command to sync all of the slash commands with discord's servers.
# Requires the user invoking it to be the owner of the bot.
# @Params:
# ctx; Expected Type: commands.Context - standard non-tree bot command context object (See discord docs for more info).
"""
@bot.command()
async def sync(ctx : commands.Context):
    try:
        bot.logInfo("Syncing Commands...")
        synced = await bot.tree.sync()
        bot.logInfo(f"The following commands were successfully synced: {synced}")
    except Exception as e:
        bot.logError(e)


"""
# List of test cases to run:
# Check streak stats while user has active streak on guild in question
# check streak stats while user has deactivated streaks and no active on guild in question
# check streak stats while user has streaks active on other guilds
# check streak stats while user has deactivated streaks on other guilds
# run testing for scheduling streak checks
# run testing for the streak check function itself
# run testing for the freeze decrease and replenishment feature
# run streak stats while user has no streaks
"""
@bot.command(description="Trigger a test function for debugging")
@commands.is_owner()
async def run_test(ctx: commands.Context, *args):
    try:
        artCog = bot.get_cog("ArtStreakChecker")
        if (args[0] == "check_streaks"):
            func =  getattr(artCog, "check_streaks")
            if (args[1:].__contains__("--force") or args[1:].__contains__("-f")):
                await func(force=True)
            else:
                await func()
        elif (args[0] == "push_reminder"):
            func = getattr(artCog, "push_reminder")
            await func()
        elif (args[0] == "terminate_streak"):
            if (len(args[1:]) < 1 or len(args[:1]) > 1):
                await ctx.channel.send("The debug command 'terminate_streak' requires 1 argument (user id)")
                return
            func = getattr(artCog, "terminate_user_streak")
            user = bot.get_user(args[1])
            await func(ctx.guild, user)
        else:
            await ctx.channel.send(f"{args[0]} is not a recognized debug command.")
    except Exception as e:
        bot.logError(e)


"""
# Entry point function for the entire application.
# @Params:
# NONE
"""
def main():
    bot.run(TOKEN, log_handler=None)


main()
