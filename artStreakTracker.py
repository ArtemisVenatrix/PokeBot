import datetime
import aiohttp
import io

from discord.ext import commands, tasks
import discord

from sqlalchemy import and_, func
from models import ArtStreak, ArtStreakSubmission, Guild, PersistentVars


class ArtStreakTracker(commands.Cog):
    # Declare time values for task scheduling.
    # Definition of mountain time
    mtn = datetime.timezone(datetime.timedelta(hours=-6), name="Mountain Time")
    # Time definitions
    streak_check_time = datetime.time(hour=0, tzinfo=mtn)
    streak_reminder_times = [
        datetime.time(hour=9, tzinfo=mtn),
        datetime.time(hour=12, tzinfo=mtn),
        datetime.time(hour=15, tzinfo=mtn),
        datetime.time(hour=18, tzinfo=mtn)
    ]


    def __init__(self, bot):
        self.bot = bot


    @commands.Cog.listener()
    async def on_ready(self):
        self.check_streaks.start()
        self.push_reminder.start()
        await self.check_streaks()


    """
    # Scheduler call back function that handles the firing off of reminders for art streaks to all users with currently
    # active art streaks in respective guilds.
    # It uses a lot of copied code from the 'check_streaks' function which has already caused problems. Both functions could
    # probably be optimized and need a closer look in the future.
    # @Params:
    # NONE
    """
    @tasks.loop(time=streak_reminder_times)
    async def push_reminder(self):
        try:
            with self.bot.Session() as session:
                # Pull a list of all active art streaks from local db
                result = session.query(ArtStreak).filter(ArtStreak.active).all()
                # Iterate through list
                for streak in result:
                    # Pull a list of all art streak submissions registered under the current art streak.
                    submissionResults = session.query(ArtStreakSubmission) \
                        .join(ArtStreak, ArtStreakSubmission.art_streak_id == streak.id) \
                        .order_by(ArtStreakSubmission.creation_date.desc()) \
                        .all()
                    streakFulfilled = False
                    # Iterate through said art streak list. If there has been a submission to this art streak today, then do
                    # nothing. Otherwise, send a reminder to the art streak's user.
                    for submissionResult in submissionResults:
                        if submissionResult.creation_date == datetime.date.today():
                            streakFulfilled = True
                            break
                        else:
                            break
                    if not streakFulfilled:
                        guildObj = session.query(Guild).filter(Guild.id == streak.guild_id).first()
                        artChannel = await self.bot.fetch_channel(guildObj.art_channel_id)
                        await artChannel.send(
                            f"<@{streak.user_id}> still needs to submit art today and is a cringe, gay baby for not doing so already.")
        except Exception as e:
            print(e)

    """
    # Helper function that handles the job of iterating through all active streaks in the database and checking whether they
    # had a submission today or yesterday. If not then a freeze is subtracted. If no freezes remain then the streak is 
    # terminated and the helper function 'terminate_streak' is dispatched.
    # @Params:
    # NONE
    """
    @tasks.loop(time=streak_check_time)
    async def check_streaks(self, force=False):
        try:
            print("Checking streaks...")
            with self.bot.Session() as session:
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
                if persistentVars.last_streak_check_date == datetime.date.today() and not force:
                    print("Streaks have already been checked today. Skipping rest of function...")
                    return
                # Update the entry detailing the last time streaks have been checked.
                persistentVars.last_streak_check_date = datetime.date.today()
                session.commit()
                # Pulls a list of active art steaks.
                result = session.query(ArtStreak).filter(ArtStreak.active).all()
                # Iterates through said list.
                for streak in result:
                    # Renews freezes on sunday
                    if datetime.datetime.today().weekday() == 6:
                        streak.freezes = 2
                    # Calculates yesterday's date.
                    yesterday = datetime.date.today() - datetime.timedelta(1)
                    # Pulls a list of all submissions for the current art steak.
                    submissionResults = session.query(ArtStreakSubmission) \
                        .join(ArtStreak, ArtStreakSubmission.art_streak_id == streak.id) \
                        .order_by(ArtStreakSubmission.creation_date.desc()) \
                        .all()
                    streakFulfilled = False
                    # Iterates through all the submissions and determines if a submission has been given yesterday or
                    # today. If one hasn't, then remove a freeze from the streak. If the streak is out of freezes, then
                    # terminate the streak.
                    for submissionResult in submissionResults:
                        if submissionResult.creation_date == yesterday or submissionResult.creation_date == datetime.date.today():
                            streakFulfilled = True
                            break
                        else:
                            break
                    if not streakFulfilled:
                        if streak.freezes == 0:
                            await self.terminate_streak(streak.id, 1)
                        else:
                            streak.freezes -= 1
                            guildObj = session.query(Guild).filter(Guild.id == streak.guild_id).first()
                            artChannel = await self.bot.fetch_channel(guildObj.art_channel_id)
                            await artChannel.send(
                                f"<@{streak.user_id}> failed to fulfill yesterday's streak requirement and has lost a freeze.")
                session.commit()
                print("Streaks checked successfully!")
        except Exception as e:
            print(e)


    async def terminate_user_streak(self, guild, user):
        try:
            with (self.bot.Session() as session):
                result = session.query(ArtStreak.id)\
                    .join(Guild, ArtStreak.guild_id == guild.id)\
                    .filter(and_(ArtStreak.active, ArtStreak.user_id == user.id))\
                    .first()
                await self.terminate_streak(result, 0)
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
    async def terminate_streak(self, streak_id: int, reason: int):
        try:
            print(f"Terminating streak: {streak_id}...")
            with self.bot.Session() as session:
                # Pull the requested art streak.
                artStreak = session.query(ArtStreak).filter(ArtStreak.id == streak_id).first()
                # Set it to inactive and set its end date.
                artStreak.active = False
                artStreak.end_date = datetime.date.today()
                session.commit()
                # Initialize the str for the corresponding termination reason numeric code.
                if reason == 0:
                    reasonStr = "The streak was cancelled by the user or an administrator."
                elif reason == 1:
                    reasonStr = "The streak parameters were not fulfilled in time."
                print(f"Termination reason: {reasonStr}")
                # Pull the guild that the art streak belongs to.
                guildObj = session.query(Guild).filter(Guild.id == artStreak.guild_id).first()
                # Pull the designated art channel for said guild.
                artChannel = await self.bot.fetch_channel(guildObj.art_channel_id)
                # Send the announcement for the art streak's termination.
                await artChannel.send(
                    f"<@{artStreak.user_id}>'s art streak of {artStreak.get_duration()} days has ended."
                    f"\nReason: {reasonStr}")
                print("Streak terminated successfully!")
        except Exception as e:
            print(e)


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
    @commands.command(name="submitart", description="Submit art for an art streak. Only accepts image and audio files.")
    async def submit_art(self, interaction: discord.Interaction, attachment: discord.Attachment):
        # check if the attachment is a valid file type (currently only allows audio or image)
        if attachment.content_type.__contains__("image") or attachment.content_type.__contains__("audio"):
            try:
                with self.bot.Session() as session:
                    # query all active art streaks linked to the local guild
                    result = session.query(ArtStreak) \
                        .join(Guild, ArtStreak.guild_id == Guild.id) \
                        .filter(and_(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == interaction.user.id),
                                     ArtStreak.active)) \
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
                    submissionObj = ArtStreakSubmission(art_streak_id=result.id, creation_date=datetime.date.today(),
                                                        user_id=interaction.user.id)
                    result.submissions.append(submissionObj)
                    # Parse the byte stream of the attachment object provided by discord and turn it back into a file so it
                    # can be posted by the bot in the response
                    async with aiohttp.ClientSession() as aioSession:
                        async with aioSession.get(attachment.url) as resp:
                            img = await resp.read()
                            with io.BytesIO(img) as file:
                                await interaction.response \
                                    .send_message(
                                    content=f"Day {(datetime.date.today() - result.creation_date).days + 1} art"
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
            await interaction.response \
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
    @commands.command(name="streakstats", description="View the stats of your current art streak.")
    async def streak_stats(self, interaction: discord.Interaction, user: discord.User):
        try:
            with self.bot.Session() as session:
                # Get list of all the specified user's streaks on the local guild.
                streaksList = session.query(ArtStreak) \
                    .join(Guild, ArtStreak.guild_id == interaction.guild_id) \
                    .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)) \
                    .order_by(ArtStreak.get_duration.desc()) \
                    .all()
                # Check if the user has any streaks on the local guild. If yes: then proceed, otherwise: inform command
                # submitter that the requested user has no streaks locally.
                if len(streaksList) != 0:
                    # Retrieve number of streaks a user has made on the local guild.
                    numstreaks = session.query(func.count(ArtStreak.id)) \
                        .join(Guild, ArtStreak.guild_id == interaction.guild_id) \
                        .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)) \
                        .scalar()
                    # Retrieve number of total submission on the local guild across all streaks.
                    totalart = session.query(func.count(ArtStreakSubmission.id)) \
                        .filter(and_(ArtStreakSubmission.user_id == user.id,
                                     ArtStreakSubmission.art_streak.has(guild_id=interaction.guild_id))) \
                        .scalar()
                    # Pull the currently active art streak on the guild for the requested user if one exists.
                    hasActiveStreak = session.query(ArtStreak) \
                        .join(Guild, ArtStreak.guild_id == interaction.guild_id) \
                        .filter(
                        and_(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)), ArtStreak.active) \
                        .first()
                    # If the user does not have a currently active streak: then retrieve the most recent one and assign it
                    # to the 'mostRecentStreak' variable.
                    if hasActiveStreak is None:
                        mostRecentStreak = session.query(ArtStreak.end_date) \
                            .join(Guild, ArtStreak.guild_id == interaction.guild_id) \
                            .filter(and_(Guild.id == interaction.guild_id, ArtStreak.user_id == user.id)) \
                            .order_by(ArtStreak.end_date.desc()) \
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
    # Command that sets whatever channel the command was issued in to the local guild's designated art channel.
    # One should note that this command works via a chat prefix and the slash tree and has its use restricted to guild 
    # administrators.
    # @Params:
    # ctx; Expected Type: commands.Context - standard non-tree bot command context object (See discord docs for more info).
    """
    @commands.command(description="Designates art channel where art streaks are handled in the guild. "
                             "Requires guild admin to use.")
    @commands.has_permissions(administrator=True)
    async def designate_art_channel(self, ctx: commands.Context):
        try:
            with self.bot.Session() as session:
                # Retrieve db entry for the guild the command was issued on.
                guildObj = session.query(Guild).filter(Guild.id == ctx.guild.id).first()
                # Set the guild entry's 'art_channel_id' field to the id of the channel the command was issued from.
                guildObj.art_channel_id = ctx.channel.id
                session.commit()
            # Inform the command submitter that the art channel has been designated.
            await ctx.channel.send("This channel has been designated as the art channel.")
        except Exception as e:
            print(e)