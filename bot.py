
import os
import re
import discord

TOKEN = os.environ["DISCORD_TOKEN"]

ADMIN_ROLE_ID = 1567743560055263292
TICKET_CHANNEL_ID = 1567747285365039114

intents = discord.Intents.default()
intents.members = True

bot = discord.Client(intents=intents)


async def find_member(guild, value):
    value = value.strip()

    # 실제 디스코드 멘션 형식도 지원
    match = re.fullmatch(r"<@!?(\d+)>", value)
    if match:
        try:
            return await guild.fetch_member(int(match.group(1)))
        except discord.NotFound:
            return None

    # @를 붙여 입력해도 검색 가능
    username = value.lstrip("@").casefold()

    matches = []

    async for member in guild.fetch_members(limit=None):
        possible_names = {
            member.name.casefold(),
            member.display_name.casefold()
        }

        if member.global_name:
            possible_names.add(member.global_name.casefold())

        if username in possible_names:
            matches.append(member)

    if len(matches) == 1:
        return matches[0]

    return None


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 종료 및 채널 삭제",
        style=discord.ButtonStyle.danger,
        custom_id="middleman_close"
    )
    async def close(self, interaction, button):
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

if not is_admin:
    await interaction.response.send_message(
        "중개 관리자만 채널을 종료할 수 있습니다.",
        ephemeral=True
    )
    return

await interaction.response.send_message(
            "중개 종료! 채널을 삭제합니다.",
            ephemeral=True
        )

await channel.delete(reason="중개 종료")


class TicketModal(discord.ui.Modal, title="중개 신청"):
    price = discord.ui.TextInput(
        label="거래 가격",
        placeholder="예: 50000원",
        max_length=50
    )

    buyer_name = discord.ui.TextInput(
        label="구매자 사용자명",
        placeholder="예: @buyer123",
        max_length=100
    )

    seller_name = discord.ui.TextInput(
        label="판매자 사용자명",
        placeholder="예: @seller456",
        max_length=100
    )

    async def on_submit(self, interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "서버에서 신청해 주세요.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        buyer = await find_member(guild, self.buyer_name.value)
        seller = await find_member(guild, self.seller_name.value)

        if buyer is None or seller is None:
            await interaction.followup.send(
                "사용자를 찾을 수 없거나 동일한 이름이 여러 명 있습니다. "
                "정확한 사용자명을 확인해 주세요.",
                ephemeral=True
            )
            return

        if buyer.id == seller.id:
            await interaction.followup.send(
                "구매자와 판매자는 서로 달라야 합니다.",
                ephemeral=True
            )
            return

        if interaction.user.id not in [buyer.id, seller.id]:
            await interaction.followup.send(
                "신청자는 구매자 또는 판매자여야 합니다.",
                ephemeral=True
            )
            return

        admin_role = guild.get_role(ADMIN_ROLE_ID)

        if admin_role is None:
            await interaction.followup.send(
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
            f"중개 티켓 생성 완료: {channel.mention}",
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
    async def open_ticket(self, interaction, button):
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
            "안전한 거래를 위해 중개를 신청해 주세요.\n\n"
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
