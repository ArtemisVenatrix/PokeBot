from discord.ext import commands
import discord
from models import Subscriber, Guild
from sqlalchemy import and_, delete

class VcNotifier(commands.cog):

    def __init__(self, bot):
        self.bot = bot


    """
    # Command that allows the user to check the bot's local db if they are signed up for vc notifs on the local guild.
    # @Params:
    # NONE
    """
    @commands.command(name="amisubscribed", description="Tells you if you're subscribed for vc notifs or not.")
    async def am_i_subscribed(self, interaction: discord.Interaction) -> None:
        # Open session with local db
        with self.bot.Session() as session:
            try:
                # The following sql statement looks through the list of notif subscribers registered to the local guild and
                # returns the one that matches with the user requesting the query if such an entry exists.
                result = session.query(Subscriber) \
                    .join(Guild, Subscriber.parent_guild_id == Guild.id) \
                    .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id)) \
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
    @commands.command(name="subscribe", description="Subscribes you to vc notifs.")
    async def subscribe(self, interaction: discord.Interaction) -> None:
        # Open session with the local db.
        with self.bot.Session() as session:
            try:
                # The following sql statement looks through the list of notif subscribers registered to the local guild and
                # returns the one that matches with the user requesting the query if such an entry exists.
                result = session.query(Subscriber) \
                    .join(Guild, Subscriber.parent_guild_id == Guild.id) \
                    .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id)) \
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
    @commands.command(name="unsubscribe", description="Unsubscribes you from vc notifs.")
    async def unsubscribe(self, interaction: discord.Interaction) -> None:
        with self.bot.Session() as session:
            try:
                # The following sql statement looks through the list of notif subscribers registered to the local guild and
                # returns the one that matches with the user requesting the query if such an entry exists.
                result = session.query(Subscriber) \
                    .join(Guild, Subscriber.parent_guild_id == Guild.id) \
                    .filter(and_(Guild.id == interaction.guild.id, Subscriber.user_id == interaction.user.id)) \
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
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
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
                with self.bot.Session() as session:
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
                                    await self.bot.create_dm(user)
                                await user.dm_channel.send(f"The VC in {guild.name} is now active!")
                    except Exception as e:
                        print(e)