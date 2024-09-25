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
#  - TODO: fix redundant streak reminders bug
#
#  TODO for future releases:
#
#  - TODO: make setup initialize a .env file
#  - TODO: fix setup.sh
#  - TODO: add a config file that determines whether setup has been done before
#  - TODO: rebuild models around a dedicated user table
#  - TODO: add per user config options that allow setting timezone for things like reminders
#  - TODO: modify the 'push_reminder' function so that the message provided is different at random
#  - TODO: rewrite all of the sql statements to use the newer 'query' syntax
#  - TODO: setup proper error logging
#
# ////////////////////////////////////////////



import datetime
import io
import os
import typing
import json

from dotenv import load_dotenv
from discord.ext import commands
import discord
from discord import app_commands
from sqlalchemy import select, delete, create_engine, and_, func
from models import Subscriber, Guild, ArtStreak, ArtStreakSubmission, PersistentVars
from sqlalchemy.orm import sessionmaker
import asyncio
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Create database engine from the engine factory and instantiate the session factory based on the persistent engine
engine = create_engine("sqlite:///poke_bot.db", echo=True)
Session = sessionmaker(bind=engine)

# set discords special permission requests, in this case viewing message content, and initialize the bot object
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# load environmental variables and retrieve the bot token from them
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# initialize the scheduler object
scheduler = AsyncIOScheduler()


"""
# Event handler for when the bot has finished startup sequence
# In this handler we have implemented a function that handles one of the two cases under which a new guild will have
# to be registered with the bot side database and one of two cases in which a guild should be removed from the local db
# @Params:
# NONE
"""
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    await check_streaks()
    scheduler.add_job(check_streaks, 'cron', hour='0')
    scheduler.add_job(push_reminder, 'cron', hour='9,12,15,18,21')
    scheduler.start()
    discordGuilds = []
    # open a session with the database
    with Session() as session:
        try:
            # Iterate through all guild entries stored on local db and compare them with guilds that the bot is
            # currently a member of. If any are in the db that the bot is no longer a member of, then send them to the
            # 'unregister_guild' function for removal.
            guilds = session.query(Guild).all()
            guildsToDelete = []
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
            print(e)
    # If the queue of guild entries to be removed has anything in it, send it off to the 'unregister_guild' function.
    if len(guildsToDelete) > 0:
        unregister_guild(guildsToDelete)
    # If the queue of new guilds to be registered has anything in it, send it off to the 'register_guild' function.
    if len(discordGuilds) > 0:
        register_guild(discordGuilds)


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
    print("Unregistering guilds...")
    with Session() as session:
        try:
            for guild in guilds:
                session.query(Guild).filter(Guild.id == guild.id).delete()
            session.commit()
        except Exception as e:
            print(e)


"""
# Private function for handling the registration of new guilds in the bot side database.
# @Params: 
# guilds; Expected Type: [discord.Guild] - list of guilds to register
"""
def register_guild(guilds: [discord.Guild]):
    print("Registering new guilds...")
    # Start a session with the bot side database
    with Session() as session:
        try:
            for guild in guilds:
                guildObj = Guild(id=guild.id)
                session.add(guildObj)
                print(f"Adding guild: \"{guild.name}\" to session...")
            session.commit()
            print("Guilds committed!")
        except Exception as e:
            print(e)


"""
# Entry point function for the entire application.
# @Params:
# NONE
"""
async def main():
    # Initialize async functions and launch the bot's built in event loop.
    async with bot:
        await bot.start(TOKEN)



"""
# Scheduler call back function that handles the firing off of reminders for art streaks to all users with currently
# active art streaks in respective guilds.
# It uses a lot of copied code from the 'check_streaks' function which has already caused problems. Both functions could
# probably be optimized and need a closer look in the future.
# @Params:
# NONE
"""
async def push_reminder():
    try:
        with Session() as session:
            # Pull a list of all active art streaks from local db
            result = session.query(ArtStreak).filter(ArtStreak.active).all()
            # Iterate through list
            for streak in result:
                # For some reason the iterator needs to be subscripted, or it won't work.
                streakObj = streak[0]
                # Pull a list of all art streak submissions registered under the current art streak.
                submissionResults = session.query(ArtStreakSubmission)\
                    .join(ArtStreak, ArtStreakSubmission.art_streak_id == streakObj.id)\
                    .order_by(ArtStreakSubmission.creation_date.desc())\
                    .all()
                streakFulfilled = False
                # Iterate through said art streak list. If there has been a submission to this art streak today, then do
                # nothing. Otherwise, send a reminder to the art streak's user.
                for submissionResult in submissionResults:
                    # For some reason the iterator needs to be subscripted, or it won't work.
                    submissionResultObj = submissionResult[0]
                    if submissionResultObj.creation_date == datetime.date.today():
                        streakFulfilled = True
                        break
                    else:
                        break
                if not streakFulfilled:
                    guildObj = session.query(Guild).filter(Guild.id == streakObj.guild_id).first()
                    artChannel = await bot.fetch_channel(guildObj.art_channel_id)
                    await artChannel.send(f"<@{streakObj.user_id}> still needs to submit art today and is a cringe, gay baby for not doing so already.")
    except Exception as e:
        print(e)


"""
# Helper function that handles the job of iterating through all active streaks in the database and checking whether they
# had a submission today or yesterday. If not then a freeze is subtracted. If no freezes remain then the streak is 
# terminated and the helper function 'terminate_streak' is dispatched.
# @Params:
# NONE
"""
async def check_streaks():
    try:
        print("Checking streaks...")
        with Session() as session:
            # Pull the persistent vars entry in the db.
            persistentVars = session.query(PersistentVars).first()
            # If persistent vars has no entry then make one.
            if persistentVars is None:
                print("No 'PersistentVars' entry found. Creating entry...")
                persistentVars = PersistentVars()
                persistentVars.last_streak_check_date = datetime.date.today() - datetime.timedelta(1)
                session.add(persistentVars)
            else:
                print(f"Streaks were last checked on: {persistentVars.last_streak_check_date}")
            # If persistent vars says that the bot has not checked streaks yet today, then do so.
            if persistentVars.last_streak_check_date == datetime.date.today():
                print("Streaks have already been checked today. Skipping rest of function...")
                return
            # Update the entry detailing the last time streaks have been checked.
            persistentVars.last_streak_check_date = datetime.date.today()
            session.commit()
            # Pulls a list of active art steaks.
            result = session.query(ArtStreak).filter(ArtStreak.active).all()
            # Iterates through said list.
            for streak in result:
                streakObj = streak[0]
                # Renews freezes on sunday
                if datetime.datetime.today().weekday() == 6:
                   streakObj.freezes = 2
                # Calculates yesterday's date.
                yesterday = datetime.date.today() - datetime.timedelta(1)
                # Pulls a list of all submissions for the current art steak.
                submissionResults = session.query(ArtStreakSubmission)\
                    .join(ArtStreak, ArtStreakSubmission.art_streak_id == streakObj.id)\
                    .order_by(ArtStreakSubmission.creation_date.desc())\
                    .all()
                streakFulfilled = False
                # Iterates through all the submissions and determines if a submission has been given yesterday or
                # today. If one hasn't, then remove a freeze from the streak. If the streak is out of freezes, then
                # terminate the streak.
                for submissionResult in submissionResults:
                    if submissionResult[0].creation_date == yesterday or submissionResult[0].creation_date == datetime.date.today():
                        streakFulfilled = True
                        break
                    else:
                        break
                if not streakFulfilled:
                    if streakObj.freezes == 0:
                        await terminate_streak(streakObj.id, 1)
                    else:
                        streakObj.freezes -= 1
                        guildObj = session.query(Guild).filter(Guild.id == streakObj.guild_id).first()
                        artChannel = await bot.fetch_channel(guildObj.art_channel_id)
                        await artChannel.send(f"<@{streakObj.user_id}> failed to fulfill yesterday's streak requirement and has lost a freeze.")
            session.commit()
            print("Streaks checked successfully!")
    except Exception as e:
        print(e)


"""
# Helper function that handles the termination of art streaks.
# Deals with setting an art streak to inactive in the db, setting the end date of the art streak, and announcing on the
# art channel that the streak in question has ended.
# @Params:
# streak_id; Expected Type: int - the id for the streak to be ended
# reason; Expected Type: int - the numeric code for the reason to provide in the announcement for why the streak was terminated
"""
# reason uses ints as error code type bits. 0 = cancelled by user; 1 = failure to meet streak requirements
async def terminate_streak(streak_id: int, reason: int):
    try:
        print(f"Terminating streak: {streak_id}...")
        with Session() as session:
            # Pull the requested art streak.
            artStreak = session.query(ArtStreak).filter(ArtStreak.id == streak_id).first()
            # Set it to inactive and set its end date.
            artStreak.active = False
            artStreak.end_date = datetime.date.today()
            session.commit()
            # Initialize the str for the corresponding termination reason numeric code.
            if reason == 0:
                reasonStr = "The streak was cancelled by the user."
            elif reason == 1:
                reasonStr = "The streak parameters were not fulfilled in time."
            print(f"Termination reason: {reasonStr}")
            # Pull the guild that the art streak belongs to.
            guildObj = session.query(Guild).filter(Guild.id == artStreak.guild_id).first()
            # Pull the designated art channel for said guild.
            artChannel = await bot.fetch_channel(guildObj.art_channel_id)
            # Send the announcement for the art streak's termination.
            await artChannel.send(f"<@{artStreak.user_id}>'s art streak of {artStreak.get_duration()} days has ended."
                                  f"\nReason: {reasonStr}")
            print("Streak terminated successfully!")
    except Exception as e:
        print(e)


"""
# Command that allows the user to check the bot's local db if they are signed up for vc notifs on the local guild.
# @Params:
# NONE
"""
@bot.tree.command(name="amisubscribed", description="Tells you if you're subscribed for vc notifs or not.")
async def am_i_subscribed(interaction: discord.Interaction) -> None:
    # Open session with local db
    with Session() as session:
        try:
            # The following sql statement looks through the list of notif subscribers registered to the local guild and
            # returns the one that matches with the user requesting the query if such an entry exists.
            result = session.query(Subscriber)\
                .join(Guild, Subscriber.parent_guild_id == Guild.id)\
                .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id))\
                .first()
            if result is None:
                await interaction.response.send_message("You are not subscribed")
            else:
                await interaction.response.send_message("You are subscribed")
        except Exception as e:
            print(e)
            await interaction.response.send_message("An error has occurred. Go bug Artemis.")


"""
# Command that allows a user to enroll themselves for vc notifs on the local guild.
# @Params:
# NONE
"""
@bot.tree.command(name="subscribe", description="Subscribes you to vc notifs.")
async def subscribe(interaction: discord.Interaction) -> None:
    # Open session with the local db.
    with Session() as session:
        try:
            # The following sql statement looks through the list of notif subscribers registered to the local guild and
            # returns the one that matches with the user requesting the query if such an entry exists.
            result = session.query(Subscriber)\
                .join(Guild, Subscriber.parent_guild_id == Guild.id)\
                .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id))\
                .first()
            # If the query failed to return a result then the user hasn't already been subscribed and should be
            # immediately
            if result is None:
                subscriber = Subscriber(user_id=interaction.user.id)
                guild = session.get(Guild, interaction.guild.id)
                guild.member_subs.append(subscriber)
                session.add(subscriber)
                session.commit()
                await interaction.response.send_message("You have been subscribed.")
            # Otherwise notify the user they have already been subscribed in this guild
            else:
                await interaction.response.send_message("You are already subscribed.")
        except Exception as e:
            print(e)
            await interaction.response.send_message("An error has occurred. Go bug Artemis.")


"""
# Command that allows users to un-enroll from the local guild's vc notifs.
# @Params:
# NONE
"""
@bot.tree.command(name="unsubscribe", description="Unsubscribes you from vc notifs.")
async def unsubscribe(interaction: discord.Interaction) -> None:
    with Session() as session:
        try:
            # The following sql statement looks through the list of notif subscribers registered to the local guild and
            # returns the one that matches with the user requesting the query if such an entry exists.
            result = session.query(Subscriber)\
                .join(Guild, Subscriber.parent_guild_id == Guild.id)\
                .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id))\
                .first()
            # if the query succeeded in returning a result then the user is still subscribed and should be removed from
            # this guild's subscriber list immediately.
            if result is not None:
                stmt = delete(Subscriber).where(Subscriber.id == result[0].id)
                session.execute(stmt)
                session.commit()
                await interaction.response.send_message("You have been unsubscribed.")
            # Otherwise, inform the user that they are not currently subscribed.
            else:
                await interaction.response.send_message("You aren't subscribed to begin with.")
        except Exception as e:
            print(e)
            await interaction.response.send_message("An error has occurred. Go bug Artemis.")


"""
# Command that allows the user to submit art which either adds to their active art streak on the local guild or starts
# a new one if there isn't one already. Accepts image and audio files as valid media formats. Handles the backend work
# for initializing a new streak and adding new submissions to streaks in the data base and the frontend work of sending
# responses to discord that display the submission file and a mention of the author and the day of the streak the 
# submission was posted on.
# @Params:
# interaction; Expected Type: discord.Interaction - the interaction object discord passes for all tree commands 
#                                                        (mainly handles meta data and a bunch of async call back stuff)
# attachment; Expected Type: discord.Attachment - tells discord to require someone provide an attachment with the
#                                                                                      command and passes it to the code                                
"""
@bot.tree.command(name="submitart", description="Submit art for an art streak. Only accepts image and audio files.")
async def submit_art(interaction: discord.Interaction, attachment: discord.Attachment):
    # check if the attachment is a valid file type (currently only allows audio or image)
    if attachment.content_type.__contains__("image") or attachment.content_type.__contains__("audio"):
        try:
            with Session() as session:
                # query all active art streaks linked to the local guild
                result = session.query(ArtStreak)\
                    .join(Guild, ArtStreak.guild_id == Guild.id)\
                    .filter(and_(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == interaction.user.id), ArtStreak.active))\
                    .first()
                # if none exist then create a new one
                if result is None:
                    guildObj: Guild = session.query(Guild).filter(Guild.id == interaction.guild_id).first()
                    # if guild has not designated an art channel then raise exception and inform user
                    if guildObj.art_channel_id is None:
                        await interaction.response.send_message("This guild has not designated an art channel!")
                        raise Exception("Art channel not designated on this guild!")
                    # initialize new art streak and add to session
                    result = ArtStreak(guild_id=interaction.guild_id
                                          , user_id=interaction.user.id
                                          , creation_date=datetime.date.today())
                    guildObj.art_streaks.append(result)
                    session.add(result)
                else:
                    result = result[0]
                # initialize submission and add it to the art streak
                submissionObj = ArtStreakSubmission(art_streak_id=result.id, creation_date=datetime.date.today(), user_id=interaction.user.id)
                result.submissions.append(submissionObj)
                # Parse the byte stream of the attachment object provided by discord and turn it back into a file so it
                # can be posted by the bot in the response
                async with aiohttp.ClientSession() as aioSession:
                    async with aioSession.get(attachment.url) as resp:
                        img = await resp.read()
                        with io.BytesIO(img) as file:
                            await interaction.response\
                                .send_message(content=f"Day {(datetime.date.today() - result.creation_date).days + 1} art"
                                                      f" streak submission by <@{interaction.user.id}>."
                                                , file=discord.File(file, attachment.filename))
                # retrieve object of the response just sent and log its message link in the database entry for the
                # submission so the db can refer back to the corresponding message
                message = await interaction.original_response()
                submissionObj.message_link = message.jump_url
                session.add(submissionObj)
                session.commit()
        except Exception as e:
            print(e)
    else:
        # inform the user they have entered an invalid media format
        await interaction.response\
            .send_message("That is not an accepted media format. Please Submit an image or audio file.")


"""
# Command that allows users to see an array of art streak related stats for any requested user. The stats tracked and
# shown are as follows: the number of art streaks a user has had on the guild, the total amount of submissions made on
# the local guild across all streaks, the duration of a user's longest local streak, and the days passed since their 
# last streak. The command handles retrieving all of said stats from the database and serving them to the user.
# @Params:
# interaction; Expected Type: discord.Interaction - required context object for all bot.tree commands
# user; Expected Type: discord.User - tells discord to require the input of a user to retrieve stats on
"""
@bot.tree.command(name="streakstats", description="View the stats of your current art streak.")
async def streak_stats(interaction: discord.Interaction, user: discord.User):
    try:
        with Session() as session:
            # Get list of all the specified user's streaks on the local guild.
            streaksList = session.query(ArtStreak)\
                .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id))\
                .order_by(ArtStreak.get_duration.desc())\
                .all()
            # Check if the user has any streaks on the local guild. If yes: then proceed, otherwise: inform command
            # submitter that the requested user has no streaks locally.
            if len(streaksList) != 0:
                # Retrieve number of streaks a user has made on the local guild.
                numstreaks = session.query(func.count(ArtStreak.id))\
                    .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                    .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id))\
                    .scalar()
                # Retrieve number of total submission on the local guild across all streaks.
                totalart = session.query(func.count(ArtStreakSubmission.id))\
                    .filter(and_(ArtStreakSubmission.user_id == user.id, ArtStreakSubmission.art_streak.has(guild_id=interaction.guild_id)))\
                    .scalar()
                # Pull the currently active art streak on the guild for the requested user if one exists.
                hasActiveStreak = session.query(ArtStreak)\
                    .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                    .filter(
                    and_(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)), ArtStreak.active)\
                    .first()
                # If the user does not have a currently active streak: then retrieve the most recent one and assign it
                # to the 'mostRecentStreak' variable.
                if hasActiveStreak is None:
                    mostRecentStreak = session.query(ArtStreak.end_date)\
                        .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                        .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id))\
                        .order_by(ArtStreak.end_date.desc())\
                        .first()
                # Otherwise: assign the result of the 'hasActiveStreak' query to 'mostRecentStreak'.
                else:
                    mostRecentStreak = hasActiveStreak
                # Check if the most recent streak is currently active. If yes: set the output string to say so;
                # Otherwise: set the output string to tell how many days ago the most recent streak was.
                if mostRecentStreak.active:
                    mostRecentStreakOut = "user currently has a running streak"
                else:
                    mostRecentStreakOut = f"User's last streak was " \
                                          f"{(datetime.date.today() - mostRecentStreak.end_date).days} days ago."
                # Serve the response with all the requested data in it.
                await interaction.response.send_message(f"<@{user.id}>'s streak stats:"
                                                        f"\nNumber of streaks: {numstreaks}"
                                                        f"\nTotal art submissions: {totalart}"
                                                        f"\nLongest streak: {streaksList[0].get_duration.days}"
                                                        f"\nMost recent streak: {mostRecentStreakOut}")
            else:
                # Inform the command submitter that the requested user has no streaks on the local guild.
                await interaction.response.send_message(f"<@{user.id}> has no streaks archived on the local guild.")
    except Exception as e:
        print(e)


"""
# Command that responds with a description of what features are available on the bot and how to use them.
# The bot just returns the tutorial in string form in its response.
# @Params:
# NONE
"""
@bot.tree.command(description="Responds with a written introduction to the features of the bot and how to use them.")
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
        print(e)


"""
# Test command for testing whatever snippet of code I'm working on.
# It's only usable by the bot owner.
# @Params:
# NONE
"""
@bot.command(name="pushReminderTest", description="Test the notifs")
@commands.is_owner()
async def push_reminder_test(ctx: commands.Context):
    await push_reminder()


"""
# Event handler for when a voice state is updated in any guild the bot is apart of. The logic in this handler
# specifically filters for the event of someone going from not connected to any voice channels on that guild to being in
# one. Then it further filters for whether they have brought the summed population of all the guild's voice channels
# from zero to one. If so, the bot requests a list of users subscribed to vc notifs on the local guild from the db and
# iterates through them to send each a dm about the guild's VCs gaining population.
# @Params:
# member; Expected Type: discord.Member - user whom precipitated the change
# before; Expected Type: discord.VoiceState - voice state before change
# after; Expected Type: discord.VoiceState - voice state after change
"""
@bot.event
async def on_voice_state_update(member, before, after):
    # Filter for user going from no voice channel connection to a voice channel connection
    if before.channel is None and after.channel is not None:
        # Retrieve the guild in which the change happened
        guild: discord.Guild = after.channel.guild
        # Retrieve a list of all voice channels except the afk channel
        channels = [i for i in guild.voice_channels if i is not guild.afk_channel]
        # Sum up all chatters in all VCs
        totalChatters = 0
        for channel in channels:
            totalChatters += len(channel.members)
        # If the total chatters out of ever voice channel is one, then begin notifying those subscribed to notifs
        if totalChatters == 1:
            print(f"The VC in {guild.name} now active!")
            # Open session with local db
            with Session() as session:
                try:
                    # This statement retrieves all user ids of subscribers affiliated with the local guild
                    result = session.query(Subscriber.user_id).join(Guild).filter(Guild.id == guild.id).all()
                    # Iterate through the list of subscriber user ids and dm them each a notification about activity in
                    # the guild
                    for id in result:
                        user = discord.utils.get(guild.members, id=id[0])
                        # Avoid messaging the user who just joined the vc.
                        if id[0] != member.id:
                            # If the bot does not have an active dm with a user, create one before notifying them.
                            if user.dm_channel is None:
                                await bot.create_dm(user)
                            await user.dm_channel.send(f"The VC in {guild.name} is now active!")
                except Exception as e:
                    print(e)


"""
# Command to sync all of the slash commands with discord's servers.
# Requires the user invoking it to be the owner of the bot.
# @Params:
# ctx; Expected Type: commands.Context - standard non-tree bot command context object (See discord docs for more info).
"""
@bot.command(description="Syncs commands for the bot globally. Only usable by Artemis.")
@commands.is_owner()
async def sync(ctx: commands.Context):
    try:
        print("Syncing...")
        synced = await bot.tree.sync()
        print(synced)
        print("Syncing complete!")
    except Exception as e:
        print(e)


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
    await check_streaks()


"""
# Command that sets whatever channel the command was issued in to the local guild's designated art channel.
# One should note that this command works via a chat prefix and the slash tree and has its use restricted to guild 
# administrators.
# @Params:
# ctx; Expected Type: commands.Context - standard non-tree bot command context object (See discord docs for more info).
"""
@bot.command(description="Designates art channel where art streaks are handled in the guild. "
                         "Requires guild admin to use.")
@commands.has_permissions(administrator=True)
async def designate_art_channel(ctx: commands.Context):
    try:
        with Session() as session:
            # Retrieve db entry for the guild the command was issued on.
            guildObj = session.query(Guild).filter(Guild.id == ctx.guild.id).first()
            # Set the guild entry's 'art_channel_id' field to the id of the channel the command was issued from.
            guildObj.art_channel_id = ctx.channel.id
            session.commit()
        # Inform the command submitter that the art channel has been designated.
        await ctx.channel.send("This channel has been designated as the art channel.")
    except Exception as e:
        print(e)


# Starting call to entrypoint function
asyncio.run(main())
