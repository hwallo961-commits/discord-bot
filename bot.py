
import os
import discord

TOKEN = os.environ["DISCORD_TOKEN"]

ADMIN_ROLE_ID = 1567743560055263292
TICKET_CHANNEL_ID = 1567747285365039114

intents = discord.Intents.default()
bot = discord.Client(intents=intents)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 종료 및 채널 삭제",
        style=discord.ButtonStyle.danger,
        custom_id="middleman_close"
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        topic = channel.topic or ""

        try:
            data = dict(item.split("=", 1) for item in topic.split(";"))
            requester_id = int(data["requester"])
            buyer_id = int(data["buyer"])
            seller_id = int(data["seller"])
        except (ValueError, KeyError):
            await interaction.response.send_message(
                "중개 정보를 확인할 수 없습니다.",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(ADMIN_ROLE_ID)
        is_admin = role is not None and role in interaction.user.roles
        is_participant = interaction.user.id in [
            requester_id, buyer_id, seller_id
        ]

        if not (is_admin or is_participant):
            await interaction.response.send_message(
                "중개 참여자 또는 관리자만 종료할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "중개가 종료되어 채널을 삭제합니다.",
            ephemeral=True
        )

        await channel.delete(reason="중개 종료")


class TicketModal(discord.ui.Modal, title="중개 신청"):
    price = discord.ui.TextInput(
        label="거래 가격",
        placeholder="예: 50000원",
        max_length=50
    )

    buyer_id = discord.ui.TextInput(
        label="구매자 디스코드 ID",
        placeholder="구매자의 숫자 ID",
        max_length=20
    )

    seller_id = discord.ui.TextInput(
        label="판매자 디스코드 ID",
        placeholder="판매자의 숫자 ID",
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "서버에서 신청해 주세요.",
                ephemeral=True
            )
            return

        try:
            buyer = await guild.fetch_member(int(self.buyer_id.value))
            seller = await guild.fetch_member(int(self.seller_id.value))
        except (ValueError, discord.NotFound):
            await interaction.response.send_message(
                "구매자 또는 판매자 ID를 확인해 주세요. 두 사람 모두 서버에 가입해야 합니다.",
                ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "사용자 정보를 불러오지 못했습니다. 다시 시도해 주세요.",
                ephemeral=True
            )
            return

        if buyer.id == seller.id:
            await interaction.response.send_message(
                "구매자와 판매자는 서로 달라야 합니다.",
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

        await interaction.response.defer(ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            ),
            buyer: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            ),
            seller: discord.PermissionOverwrite(
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
            name=f"중개-{buyer.name}",
            overwrites=overwrites,
            topic=(
                f"requester={interaction.user.id};"
                f"buyer={buyer.id};"
                f"seller={seller.id}"
            )
        )

        embed = discord.Embed(
            title="🤝 중개 신청 접수",
            description="거래 정보를 확인해 주세요.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="거래 가격",
            value=self.price.value,
            inline=False
        )

        embed.add_field(
            name="구매자",
            value=f"{buyer.mention}\nID: `{buyer.id}`",
            inline=True
        )

        embed.add_field(
            name="판매자",
            value=f"{seller.mention}\nID: `{seller.id}`",
            inline=True
        )

        await channel.send(
            content=f"{interaction.user.mention} {admin_role.mention}",
            embed=embed,
            view=TicketCloseView()
        )

        await interaction.followup.send(
            f"중개 티켓이 생성되었습니다: {channel.mention}",
            ephemeral=True
        )


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 티켓 열기",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="open_middleman_ticket"
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(TicketModal())


@bot.event
async def on_ready():
    print(f"봇 로그인 완료: {bot.user}")

    ticket_channel = bot.get_channel(TICKET_CHANNEL_ID)

    if ticket_channel is None:
        print("중개 티켓 채널을 찾을 수 없습니다.")
        return

    marker = "중개 티켓 안내 패널"

    async for message in ticket_channel.history(limit=50):
        if message.author == bot.user and marker in message.content:
            return

    embed = discord.Embed(
        title="🤝 중개 티켓",
        description=(
            "안전한 거래를 위해 중개 티켓을 이용해 주세요.\n\n"
            "아래 버튼을 눌러 거래 정보를 입력하면\n"
            "구매자, 판매자, 중개 관리자만 볼 수 있는\n"
            "전용 중개 채널이 생성됩니다."
        ),
        color=discord.Color.blue()
    )

    await ticket_channel.send(
        content=marker,
        embed=embed,
        view=TicketPanelView()
    )


bot.add_view(TicketPanelView())
bot.add_view(TicketCloseView())

bot.run(TOKEN)
