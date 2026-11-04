
import os
import discord
from discord import app_commands

TOKEN = os.environ["DISCORD_TOKEN"]

# 중개 관리자 역할 ID
ADMIN_ROLE_ID = 1567325646210998313

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


class MiddlemanView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 담당하기",
        style=discord.ButtonStyle.primary,
        custom_id="middleman_claim"
    )
    async def claim(self, interaction: discord.Interaction,
                    button: discord.ui.Button):

        role = interaction.guild.get_role(ADMIN_ROLE_ID)

        if role is None or role not in interaction.user.roles:
            await interaction.response.send_message(
                "중개 관리자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{interaction.user.mention} 님이 중개를 담당합니다."
        )

    @discord.ui.button(
        label="중개 종료",
        style=discord.ButtonStyle.danger,
        custom_id="middleman_close"
    )
    async def close(self, interaction: discord.Interaction,
                    button: discord.ui.Button):

        channel = interaction.channel
        topic = channel.topic or ""

        try:
            requester_id = int(topic.split("requester=")[1])
        except (ValueError, IndexError):
            await interaction.response.send_message(
                "신청자 정보를 확인할 수 없습니다.",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(ADMIN_ROLE_ID)

        is_admin = role is not None and role in interaction.user.roles
        is_requester = interaction.user.id == requester_id

        if not (is_admin or is_requester):
            await interaction.response.send_message(
                "중개 신청자 또는 관리자만 종료할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        requester = interaction.guild.get_member(requester_id)

        if requester:
            await channel.set_permissions(
                requester,
                send_messages=False
            )

        await channel.edit(name=f"closed-{channel.name}")

        await channel.send("중개가 종료되었습니다.")


@tree.command(
    name="middleman",
    description="중개를 신청합니다."
)
@app_commands.describe(reason="중개 신청 내용")
async def middleman(
    interaction: discord.Interaction,
    reason: str
):

    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message(
            "서버에서 사용해 주세요.",
            ephemeral=True
        )
        return

    admin_role = guild.get_role(ADMIN_ROLE_ID)

    if admin_role is None:
        await interaction.response.send_message(
            "중개 관리자 역할을 찾을 수 없습니다.",
            ephemeral=True
        )
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        ),
        admin_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    }

    channel = await guild.create_text_channel(
        name=f"중개-{interaction.user.name}",
        overwrites=overwrites,
        topic=f"requester={interaction.user.id}"
    )

    await channel.send(
        f"{interaction.user.mention} 중개 신청이 접수되었습니다.\n"
        f"**신청 내용:** {reason}\n"
        f"{admin_role.mention}",
        view=MiddlemanView()
    )

    await interaction.response.send_message(
        f"중개 신청이 완료되었습니다: {channel.mention}",
        ephemeral=True
    )


@bot.event
async def on_ready():
    bot.add_view(MiddlemanView())
    await tree.sync()
    print(f"봇 로그인 완료: {bot.user}")


bot.run(TOKEN)
