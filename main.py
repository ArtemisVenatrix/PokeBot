# main
import datetime
import io
import os
from dotenv import load_dotenv
from discord.ext import commands
import discord
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

scheduler = AsyncIOScheduler()


"""
# Event handler for when the bot has finished startup sequence
# In this handler we have implemented a function that handles one of the two cases under which a new guild will have
# to be registered with the bot side database
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
            # Iterate through all guilds the bot is a member of and compare each of them to the ones registered in the
            # db. If any are not found in the db they are queued in the 'discordGuilds' array to be sent to the
            # registering function.
            for guild in bot.guilds:
                stmt = select(Guild.id).filter(Guild.id.in_([guild.id]))
                result = session.execute(stmt).fetchone()
                if result is None:
                    discordGuilds.append(guild)
        except Exception as e:
            print(e)
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
    register_guild(guild)


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



async def push_reminder():
    try:
        with Session() as session:
            stmt = select(ArtStreak).filter(ArtStreak.active)
            result = session.execute(stmt).all()
            for streak in result:
                streakObj = streak[0]
                yesterday = datetime.date.today() - datetime.timedelta(1)
                stmt = select(ArtStreakSubmission).join(ArtStreak, ArtStreakSubmission.art_streak_id == streakObj.id) \
                    .order_by(ArtStreakSubmission.creation_date.desc())
                submissionResults = session.execute(stmt).all()
                streakFulfilled = False
                for submissionResult in submissionResults:
                    submissionResultObj = submissionResult[0]
                    if submissionResultObj.creation_date == yesterday or submissionResultObj.creation_date == datetime.date.today():
                        streakFulfilled = True
                        break
                    else:
                        break
                if not streakFulfilled:
                    stmt = select(Guild).filter(Guild.id == streakObj.guild_id)
                    guildObj = session.execute(stmt).fetchone()[0]
                    artChannel = await bot.fetch_channel(guildObj.art_channel_id)
                    await artChannel.send(f"<@{streakObj.user_id}> still needs to submit art today and is a cringe, gay baby for not doing so already.")
    except Exception as e:
        print(e)


async def check_streaks():
    try:
        with Session() as session:
            persistentVars = session.query(PersistentVars).all()[0]
            if persistentVars.last_streak_check_date == datetime.date.today():
                return
            persistentVars.last_streak_check_date = datetime.date.today()
            session.commit()
            stmt = select(ArtStreak).filter(ArtStreak.active)
            result = session.execute(stmt).all()
            for streak in result:
                # renews freezes on sunday
                if datetime.datetime.today().weekday() == 6:
                    streak[0].freezes = 2
                yesterday = datetime.date.today() - datetime.timedelta(1)
                stmt = select(ArtStreakSubmission).join(ArtStreak, ArtStreakSubmission.art_streak_id == streak[0].id)\
                    .order_by(ArtStreakSubmission.creation_date.desc())
                submissionResults = session.execute(stmt).all()
                streakFulfilled = False
                for submissionResult in submissionResults:
                    if submissionResult[0].creation_date == yesterday or submissionResult[0].creation_date == datetime.date.today():
                        streakFulfilled = True
                        break
                    else:
                        break
                if not streakFulfilled:
                    if streak[0].freezes == 0:
                        await terminate_streak(streak[0].id, 1)
                    else:
                        streak[0].freezes -= 1
                        stmt = select(Guild).filter(Guild.id == streak[0].guild_id)
                        guildObj = session.execute(stmt).fetchone()[0]
                        artChannel = await bot.fetch_channel(guildObj.art_channel_id)
                        await artChannel.send(f"<@{streak[0].user_id}> failed to fulfill yesterday's streak requirement and has lost a freeze.")
            session.commit()
    except Exception as e:
        print(e)


# reason uses ints as error code type bits. 0 = cancelled by user; 1 = failure to meet streak requirements
async def terminate_streak(streak_id: int, reason: int):
    try:
        with Session() as session:
            stmt = select(ArtStreak).filter(ArtStreak.id == streak_id)
            artStreak = session.execute(stmt).fetchone()[0]
            artStreak.active = False
            artStreak.end_date = datetime.date.today()
            session.commit()
            if reason == 0:
                reasonStr = "The streak was cancelled by the user."
            elif reason == 1:
                reasonStr = "The streak parameters were not fulfilled in time."
            stmt = select(Guild).filter(Guild.id == artStreak.guild_id)
            guildObj = session.execute(stmt).fetchone()[0]
            artChannel = await bot.fetch_channel(guildObj.art_channel_id)
            artStreakDuration = (datetime.date.today() - artStreak.creation_date).days + 1
            await artChannel.send(f"<@{artStreak.user_id}>'s art streak of {artStreakDuration} days has ended.\nReason: {reasonStr}")
    except Exception as e:
        print(e)


"""
# Test command that honestly needs to be removed. It accepts a single argument as a string and repeats it in its reply.
# @Params:
# msg; Expected Type: str - message to be echoed
"""
@bot.tree.command(name="echo", description="repeats a message")
async def echo(interaction: discord.Interaction, msg: str) -> None:
    print("Echoing...")
    await interaction.response.send_message(msg)
    print("Echo complete!")


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
            stmt = select(Subscriber).join(Guild, Subscriber.parent_guild_id == Guild.id)\
                .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id))
            result = session.execute(stmt).fetchone()
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
            stmt = select(Subscriber).join(Guild, Subscriber.parent_guild_id == Guild.id)\
                .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id))
            result = session.execute(stmt).fetchone()
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
            stmt = select(Subscriber).join(Guild, Subscriber.parent_guild_id == Guild.id)\
                .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id))
            result = session.execute(stmt).fetchone()
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


@bot.tree.command(name="submitart", description="Submit art for an art streak. Only accepts image files."
                                                " Starts art streak if one isn't active")
async def submit_art(interaction: discord.Interaction, attachment: discord.Attachment):
    if attachment.content_type.__contains__("image"):
        try:
            with Session() as session:
                stmt = select(ArtStreak).join(Guild, ArtStreak.guild_id == Guild.id)\
                    .filter(and_(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == interaction.user.id), ArtStreak.active))
                result = session.execute(stmt).fetchone()
                if result is None:
                    stmt = select(Guild).filter(Guild.id == interaction.guild_id)
                    guildObj: Guild = session.execute(stmt).fetchone()[0]
                    if Guild.art_channel_id is None:
                        await interaction.response.send_message("This guild has not designated an art channel!")
                        raise Exception("Art channel not designated on this guild!")
                    result = ArtStreak(guild_id=interaction.guild_id
                                          , user_id=interaction.user.id
                                          , creation_date=datetime.date.today())
                    guildObj.art_streaks.append(result)
                    session.add(result)
                else:
                    result = result[0]
                submissionObj = ArtStreakSubmission(art_streak_id=result.id, creation_date=datetime.date.today(), user_id=interaction.user.id)
                result.submissions.append(submissionObj)
                async with aiohttp.ClientSession() as aioSession:
                    async with aioSession.get(attachment.url) as resp:
                        img = await resp.read()
                        with io.BytesIO(img) as file:
                            await interaction.response\
                                .send_message(content=f"Day {(datetime.date.today() - result.creation_date).days + 1} art"
                                                      f" streak submission by <@{interaction.user.id}>."
                                                , file=discord.File(file, attachment.filename))
                message = await interaction.original_response()
                submissionObj.message_link = message.jump_url
                session.add(submissionObj)
                session.commit()
        except Exception as e:
            print(e)
    else:
        await interaction.response.send_message("That is not an image. Please Submit an image.")


# stats to display per user: number of streaks, total art submitted, longest streak, days since last streak if ended
@bot.tree.command(name="streakstats", description="View the stats of your current art streak.")
async def streak_stats(interaction: discord.Interaction, user: discord.User):
    try:
        with Session() as session:
            streaksList = session.query(ArtStreak) \
                .join(Guild, ArtStreak.guild_id == interaction.guild_id) \
                .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)) \
                .order_by(ArtStreak.get_duration.desc()) \
                .all()
            if len(streaksList) != 0:
                numstreaks = session.query(func.count(ArtStreak.id))\
                    .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                    .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id))\
                    .scalar()
                print(f"num_streaks: {numstreaks}")
                totalart = session.query(func.count(ArtStreakSubmission.id))\
                    .filter(and_(ArtStreakSubmission.user_id == user.id, ArtStreakSubmission.art_streak.has(guild_id=interaction.guild_id)))\
                    .scalar()
                print(f"total_art: {totalart}")
                # needs to be narrowed to local guild
                print(f"longest_streak: {streaksList[0].get_duration.days}")
                hasActiveStreak = session.query(ArtStreak)\
                    .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                    .filter(and_(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)), ArtStreak.active)\
                    .all()
                if hasActiveStreak is None:
                    mostRecentStreak = session.query(ArtStreak.end_date)\
                        .join(Guild, ArtStreak.guild_id == interaction.guild_id)\
                        .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id))\
                        .order_by(ArtStreak.end_date.desc())\
                        .all()
                else:
                    mostRecentStreak = hasActiveStreak[0]
                if mostRecentStreak.active:
                    mostRecentStreakOut = "user currently has a running streak"
                else:
                    mostRecentStreakOut = f"User's last streak was {(datetime.date.today() - mostRecentStreak.creation_date).days} days ago."
                # need to write a proper output
                await interaction.response.send_message(f"<@{user.id}>'s streak stats:"
                                                        f"\nNumber of streaks: {numstreaks}"
                                                        f"\nTotal art submissions: {totalart}"
                                                        f"\nLongest streak: {streaksList[0].get_duration.days}"
                                                        f"\nMost recent streak: {mostRecentStreakOut}")
            else:
                await interaction.response.send_message(f"<@{user.id}> has no streaks archived on the local guild.")
    except Exception as e:
        print(e)


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
            print("VC is now active!")
            # Open session with local db
            with Session() as session:
                try:
                    # This statement retrieves all user ids of subscribers affiliated with the local guild
                    stmt = select(Subscriber.user_id).join(Guild).filter(Guild.id == guild.id)
                    result = session.execute(stmt).all()
                    # Iterate through the list of subscriber user ids and dm them each a notification about activity in
                    # the guild
                    for id in result:
                        user = discord.utils.get(guild.members, id=id[0])
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
# guild; Expected Type: None - We have no idea why but it started crashing when we removed the parameter that no longer
# does anything
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
    scheduler.add_job(push_reminder, 'cron', minute='57')


@bot.command(description="Designates art channel where art streaks are handled in the guild. "
                         "Requires guild admin to use.")
@commands.has_permissions(administrator=True)
async def designate_art_channel(ctx: commands.Context):
    with Session() as session:
        stmt = select(Guild).filter(Guild.id == ctx.guild.id)
        guildObj = session.execute(stmt).fetchone()[0]
        guildObj.art_channel_id = ctx.channel.id
        session.commit()
    await ctx.interaction.send_message("This channel has been designated as the art channel.")


# Starting call to entrypoint function
asyncio.run(main())
