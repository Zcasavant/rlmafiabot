class Role:
    alignment = 0  # 1: Town, 2: Mafia
    name = "Default"
    color = 9807270 # Grey
    game_start_message = (
        "Your role is **Default**\n"
        "You win by testing the game\n"
        "Lynch players during the day with `[p]ww vote <ID>`"
    )
    description = (
        "This is the basic role\n"
        "All roles are based on this Class\n"
        "Has no special significance"
    )

    def __init__(self):
        self.player = None

    async def _at_game_start(self, data=None):
        await self.player.send_dm(self.game_start_message)

# Town Roles
class TownRole(Role):
    alignment = 1  # 1: Town, 2: Mafia
    color = 3066993 # Green
    name = "Town"
    game_start_message = (
        "Your role is **Villager**\n"
        "You win by determining who is the mafia\n"
        "Be on the lookout for mafia players they will be trying to throw the game"
    )

    def __init__(self):
        super().__init__()

# Mafia Roles
class MafiaRole(Role):
    alignment = 2  # 1: Town, 2: Mafia
    color = 15158332 # Red
    name = "Mafia"
    game_start_message = (
        "Your role is **Mafia**\n"
        "You win by purposefully losing the game\n"
        "Don't let town know you are trying to throw the game"
    )

    def __init__(self):
        super().__init__()
