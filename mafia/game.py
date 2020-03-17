import asyncio
import random
from typing import List, Set

import discord
from redbot.core import commands
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

from .player import Player
from .role import Role, TownRole, MafiaRole

class Game:
    """
    Class to run a game of Rocket League Mafia
    """

    roles: List[Role]
    players: List[Player]
    join_queue: List[discord.Member]
    leave_queue: List[discord.Member]

    def __init__(self, guild: discord.Guild):
        self.guild = guild

        self.roles = []
        self.players = []
        self.join_queue = []
        self.leave_queue = []

        self.vote_totals = {}

        self.started = False
        self.game_over = False

        self.game_role = None
        self.channel_category = None
        self.village_channel = None
        self.game_type = None     

    async def start(self, ctx: commands.Context):
        """
        Setup
        1. Add New Players
        2. Assign Discord Roles
        3. Create Channels
            a. Channel Permissions
        4. Assign Game Roles
        5. Start Game
            a. Send Roles
            b. Await Game End
            c. Vote on Mafia
            d. Tally Points
        6. Remove Leaving Players
        """
        # Assign Players in join_queue
        self.game_over = False
        
        if not await self._add_queued_players(ctx):
            return False            
            
        if len(self.players) == 0:
            await ctx.send("No players to start the game!\nJoin the game with `[p]mafia join`")
            return True
        
        self.started = True

        # Create and Assign Discord Role
        if self.game_role is None:
            if not await self._create_discord_role(ctx):
                return False

        if not await self.assign_all_discord_role(ctx, self.game_role):
            return False
        
        # Create Channels and their permissions
        if self.channel_category is None:
            if not await self._create_category(ctx):
                return False

        if self.village_channel is None:
            if not await self._create_channel(ctx):
                return False
    
        # Create and Assign Game Roles
        if not await self._set_roles():
            return False

        if not await self._assign_roles(self.roles):
            return False

        # Game Itself
        await self._start_round() # Send players the DM

        await self._wait_for_game(ctx) # Wait for RL Game to Finish

        await self._vote_mafia(ctx) # Vote on Mafia

        await self._end_round(ctx) # Display Mafia and Tally Points 
        
        self.started = False

        # Remove Leaving Players
        if not await self._remove_leaving_players(ctx):
            return False
        
        if await self._prompt_new_game(ctx):
            await self.start(ctx)
        else:
            await self.cleanup()

        return True

    async def join(self, member: discord.Member, channel: discord.TextChannel):
        """
        Have a member join a game
        """
        player = await self.get_player_by_member(member)

        if player is not None:
            embed = discord.Embed(description=player.mention+" is already in the game!")
            await channel.send(embed=embed)
            return

        if self.started:
            embed = discord.Embed(description="Game has already started. "+member.mention+" will be added at the start of the next round")
            await channel.send(embed=embed)
            self.join_queue.append(member)
            return

        await self._join(member, channel)

    async def leave(self, member: discord.Member, channel: discord.TextChannel = None):
        """
        Have a member quit a game
        """
        player = await self.get_player_by_member(member)

        if player is None:
            embed = discord.Embed(description=member.mention+" isn't in the game")
            await channel.send(embed=embed)
            return

        if self.started:
            embed = discord.Embed(description="Game is in progress.\n"+player.mention+" will be removed at the end of the round")
            await channel.send(embed=embed)
            self.leave_queue.append(member)
            return
        
        await self._leave(member, channel)

        embed = discord.Embed(description=player.mention+" has left the game")
        await channel.send(embed=embed)
        
    async def get_player_by_member(self, member):
        """
        Return Player by member
        """
        for player in self.players:
            if player.member == member:
                return player
        return None

    async def assign_all_discord_role(self, ctx, role: discord.Role):
        try:
            for player in self.players:
                if role not in player.member.roles:
                    await player.member.add_roles(*[role])
        except discord.Forbidden:
            await ctx.send("Unable to add role **{}**\nBot is missing `manage_roles` permissions".format(role.name))
            return False
        return True

    async def assign_member_discord_role(self, member, channel, role: discord.Role):
        try:
            if role not in member.roles:
                await member.add_roles(*[role])
        except discord.Forbidden:
            await channel.send("Unable to add role **{}**\nBot is missing `manage_roles` permissions".format(role.name))
            return False
        return True

    async def cleanup(self):
        # Delete Discord stuff
        await self.game_role.delete(reason="(BOT) Mafia Game Has Ended")
        await self.village_channel.delete(reason="(BOT) Mafia Game Has Ended")
        await self.channel_category.delete(reason="(BOT) Mafia Game Has Ended")

        # Reset Variables
        self.roles = []
        self.players = []
        self.join_queue = []
        self.leave_queue = []

        self.vote_totals = {}

        self.started = False

        self.game_role = None
        self.channel_category = None
        self.village_channel = None
        self.game_type = None

    async def _leave(self, member, channel):
        """
        Remove Roles and Permisions
        """
        player = await self.get_player_by_member(member)
        
        self.players = [player for player in self.players if player.member != member]

        if self.game_role is not None:
            await member.remove_roles(*[self.game_role])

    async def _join(self, member, channel):
        """
        Add Roles and add to game
        """
        self.players.append(Player(member))
        
        if self.game_role is not None:
            await self.assign_member_discord_role(member, channel, self.game_role) 
        
        embed = discord.Embed(description=member.mention+" has joined the game")
        await channel.send(embed=embed)

    async def _create_game_roles(self, game_type=None):
        """
        If no game_type game creates the roles based on number of players
        """
        self.roles = []

        if game_type is None:
            for player_index in range(len(self.players)):
                if player_index == len(self.players) - 1:
                    self.roles.append(MafiaRole())
                else:
                    self.roles.append(TownRole())
        return True

    async def _assign_roles(self, roles):
        random.shuffle(roles)
        self.players.sort(key=lambda player: player.member.display_name.lower())

        if len(roles) != len(self.players):
            await self.village_channel.send("Unhandled error - players!=roles")
            return False

        for index, player in enumerate(self.players):
            await self.players[index].assign_role(roles[index])

            await player.assign_id(index)
        return True

    async def _add_queued_players(self, ctx):
        if len(self.join_queue) > 0:
            for member in self.join_queue:
                if self.village_channel is not None:
                    await self._join(member, self.village_channel)
                else:
                    await self._join(member, ctx.channel)
            self.join_queue = []
        return True

    async def _remove_leaving_players(self, ctx):
        if len(self.leave_queue) > 0:
            for member in self.leave_queue:
                if self.village_channel is not None:
                    await self._leave(member, self.village_channel)
                else:
                    await self._leave(member, ctx.channel)
            self.leave_queue = []
        return True
    
    async def _create_discord_role(self, ctx):
        for role in ctx.guild.roles:
            if "Mafia Players" == role.name:
                self.game_role = role
                
                try:
                    await self.game_role.edit(mentionable=True,
                                        reason="(BOT)Mafia Game Role")
                    return True
                except (discord.Forbidden, discord.HTTPException):
                    await ctx.send("Unable to edit discord role\nBot is missing `manage_roles` permisions")
                    return False
        
        try:
            self.game_role = await ctx.guild.create_role(name="Mafia Players",
                                                        mentionable=True,
                                                        reason="(BOT)Mafia Game Role")
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("Unable to create discord role\nBot is missing `manage_roles` permisions")
            return False  
        return True

    async def _create_category(self, ctx):
        overwrite = {
            self.guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False,
                                                                 add_reactions=False),
            self.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, add_reactions=True,
                                                       manage_messages=True, manage_channels=True,
                                                       manage_roles=True, read_message_history=True),
            self.game_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        for category in ctx.guild.categories:
            if "Rocket League Mafia" == category.name:
                self.channel_category = category

                try:
                    await self.channel_category.edit(overwrites=overwrite, reason="(BOT) New Mafia Game")
                    return True
                except discord.Forbidden:
                    await ctx.send("Unable to modify category **{}**\n"
                                    "Bot is missing `manage_channels` permissions".format(self.channel_category.name))
                    return False     

        try:
            self.channel_category = await self.guild.create_category("Rocket League Mafia",
                                                                    overwrites=overwrite,
                                                                    reason="(BOT)New Mafia game")
        except discord.Forbidden:
            await ctx.send("Unable to add category **{}**\n"
                            "Bot is missing `manage_channels` permissions".format(self.channel_category.name))
            return False           
        return True

    async def _create_channel(self, ctx):
        overwrite = {
            self.guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False,
                                                                 add_reactions=False),
            self.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, add_reactions=True,
                                                       manage_messages=True, manage_channels=True,
                                                       manage_roles=True, read_message_history=True),
            self.game_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        for channel in ctx.guild.text_channels:
            if "village" == channel.name:
                self.village_channel = channel
                
                try:
                    await self.village_channel.edit(overwrites=overwrite, reason="(BOT) New Mafia Game")
                    return True
                except discord.Forbidden:
                    await ctx.send("Unable to modify category **{}**\n"
                                    "Bot is missing `manage_channels` permissions".format(self.channel_category.name))
                    return False

        try:
            self.village_channel = await self.guild.create_text_channel("Village",
                                                                        overwrites=overwrite,
                                                                        reason="(BOT) New Mafia Game",
                                                                        category=self.channel_category)
        except discord.Forbidden:
            await ctx.send("Unable to add channel **{}**\n"
                                "Bot is missing `manage_channels` permissions".format(self.channel_category.name))
            return False
        return True

    async def _prompt_new_game(self, ctx):
        embed = discord.Embed(title="Would you like to continue?")
        embed.add_field(name="Select an Option",value="Click ✅ for yes\nClick ❎ for no")

        msg = await self.village_channel.send(embed=embed)
        start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

        pred = ReactionPredicate.yes_or_no(msg)
        await ctx.bot.wait_for("reaction_add", check=pred)
        
        await msg.delete()

        return pred.result

    async def _check_game_over_status(self):
        if self.game_over:
            await self.cleanup()
    
    async def _start_round(self):
        embed = discord.Embed(title="Welcome To Rocket League Mafia")
        embed.add_field(name="Town's Objective", value="Find the mafia player", inline=False)
        embed.add_field(name="Mafia's Objective", value="Lose the game without getting caught", inline=False)

        await self.village_channel.send(self.game_role.mention, embed=embed)
        await asyncio.sleep(5)

        tasks = []
        for player in self.players:
            tasks.append(asyncio.create_task(player._start_round()))
        
        await asyncio.gather(*tasks)

    async def _wait_for_game(self, ctx):
        # TODO: Seperate Teams

        embed = discord.Embed(title="Respond with the 🏁 when the game is done")

        msg = await self.village_channel.send(embed=embed)
        start_adding_reactions(msg, "🏁")

        pred = ReactionPredicate.with_emojis(emojis="🏁", message=msg)
        await ctx.bot.wait_for("reaction_add", check=pred)
 
        await msg.delete()

    async def _vote_mafia(self, ctx):
        embed = discord.Embed(title="Who do you think is mafia?",
                             description="Vote for who you think it is with the corresponding emoji")
        
        player_list = " "
        emoji_list = []
        for index, player in enumerate(self.players):
            player_list = player_list + str(index + 1) + ". " + player.mention + "\n"
            if index < 9:
                emoji_list.append(ReactionPredicate.NUMBER_EMOJIS[index+1])

        embed.add_field(name="Players", value=player_list, inline=True)
        embed.add_field(name="You have 15 seconds to vote: ", value="15", inline=False)

        msg = await self.village_channel.send(embed=embed)

        start_adding_reactions(msg, emoji_list)

        for time in range(14, -1, -1):
            await asyncio.sleep(1)
            embed.remove_field(1)
            embed.insert_field_at(1, name="You have 15 seconds to vote: ", value=str(time), inline=False)
            await msg.edit(embed=embed)

        # TODO: Total up Reactions   

    async def _end_round(self, ctx):
        mafia_players = await self._get_mafia_players()
        player_mention = " "

        for player in mafia_players:
            player_mention = player_mention + player.mention + " "
        
        embed = discord.Embed(title="The Mafia Was...",
                              description=player_mention)

        await self.village_channel.send(embed=embed)

        # TODO: Score Points and Display

    async def _get_mafia_players(self):
        mafia_players = []
        for player in self.players:
            if player.role.alignment == 2:
                mafia_players.append(player)
        return mafia_players