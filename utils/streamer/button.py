from __future__ import annotations

import discord
import re


__all__ = (
    "ViewCloseDynamicButton",
)


class ViewCloseDynamicButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r'closure:detail_msg:user:(?P<id>[0-9]+)'
):
    def __init__(self, owner_id : int = 0):
            
        super().__init__(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.red,
                custom_id=f"closure:detail_msg:user:{owner_id}"
            )
        )
        
        self.owner_id = owner_id
    
    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        owner_id = int(match['id'])
        return cls(owner_id)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the user who created the button to interact with it.
        if not self.owner_id or interaction.user.id == self.owner_id:
            return True
        
        await interaction.response.send_message("This message is not granted for you", ephemeral=True)
        return False
    
    async def callback(self, interaction : discord.Interaction):
        await interaction.response.defer()
        await interaction.delete_original_response()
        
        view = self.view
        if view is not None:
            view.stop()