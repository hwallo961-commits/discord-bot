
import os
import re
import asyncio
import discord
from discord.ext import commands

# =========================
# 기본 설정
# =========================

TOKEN = os.environ["DISCORD_TOKEN"]

ADMIN_ROLE_ID = 1567743560055263292
TICKET_CHANNEL_ID = 1567747285365039114

PANEL_MARKER = "중개 티켓 안내 패널"

# 담당자 중복 배정 방지
claim_lock = asyncio.Lock()


# =========================
# 봇 설정
# =========================

intents = discord.Intents.default()
intents.members = True


class MediationBot(commands.Bot):

    async def setup_hook(self):
        self.add_view(TicketPanelView())
        self.add_view(TicketControlsView())


bot = MediationBot(
    command_prefix="!",
    intents=intents
)


# =========================
# 사용자 검색
# =========================

async def find_member(guild, value):
    value = value.strip()

    mention = re.fullmatch(r"<@!?(\d+)>", value)

    if mention:
        try:
            return await guild.fetch_member(int(mention.group(1)))
        except discord.NotFound:
            return None

    username = value.removeprefix("@").strip().casefold()

    if not username:
        return None

    exact = []
    display = []

    async for member in guild.fetch_members(limit=None):
        if member.bot:
            continue

        if member.name.casefold() == username:
            exact.append(member)
        elif (
            member.display_name.casefold() == username
            or (
                member.global_name
                and member.global_name.casefold() == username
            )
        ):
            display.append(member)

    matches = exact if exact else display

    unique = {member.id: member for member in matches}

    if len(unique) == 1:
        return list(unique.values())[0]

    return None


# =========================
# 중개 담당 및 종료 버튼
# =========================

class TicketControlsView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 담당하기",
        style=discord.ButtonStyle.success,
        custom_id="middleman_claim"
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        role = interaction.guild.get_role(ADMIN_ROLE_ID)

        if role is None or role not in interaction.user.roles:
            await interaction.response.send_message(
                "중개 관리자만 담당할 수 있습니다.",
                ephemeral=True
            )
            return

        async with claim_lock:

            channel = interaction.channel
            topic = channel.topic or ""

            if "mediator=" in topic:
                await interaction.response.send_message(
                    "이미 다른 중개자가 담당하고 있습니다.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            try:
                # 담당자에게 대화 권한 부여
                await channel.set_permissions(
                    interaction.user,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

                # 담당자 정보 저장
                new_topic = (
                    topic + f";mediator={interaction.user.id}"
                )

                await channel.edit(topic=new_topic)

                # 담당 버튼 비활성화
                button.disabled = True
                button.label = f"{interaction.user.display_name} 담당 중"

                embed = discord.Embed(
                    title="중개 담당자 배정 완료",
                    description=(
                        f"{interaction.user.mention} 님이 "
                        "이번 중개를 담당합니다.\n\n"
                        "이제 담당 중개자만 대화할 수 있습니다."
                    ),
                    color=discord.Color.green()
                )

                await interaction.message.edit(
                    embed=embed,
                    view=self
                )

                await interaction.followup.send(
                    "중개 담당자로 배정되었습니다.",
                    ephemeral=True
                )

            except discord.Forbidden:
                await interaction.followup.send(
                    "채널 권한을 변경할 수 없습니다. "
                    "봇의 채널 관리 권한을 확인해 주세요.",
                    ephemeral=True
                )

    @discord.ui.button(
        label="중개 종료 및 채널 삭제",
        style=discord.ButtonStyle.danger,
        custom_id="middleman_close"
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        role = interaction.guild.get_role(ADMIN_ROLE_ID)

        is_admin = (
            role is not None
            and role in interaction.user.roles
        )

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

        await interaction.channel.delete(
            reason=f"중개 종료 - {interaction.user}"
        )


# =========================
# 중개 신청 입력창
# =========================

class TicketModal(discord.ui.Modal):

    def __init__(self):
        super().__init__(title="중개 신청")

        self.price = discord.ui.TextInput(
            label="거래 가격",
            placeholder="예: 50000원",
            max_length=50
        )

        self.buyer_name = discord.ui.TextInput(
            label="구매자 사용자명",
            placeholder="예: @buyer123",
            max_length=100
        )

        self.seller_name = discord.ui.TextInput(
            label="판매자 사용자명",
            placeholder="예: @seller456",
            max_length=100
        )

        self.add_item(self.price)
        self.add_item(self.buyer_name)
        self.add_item(self.seller_name)

    async def on_submit(self, interaction):

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        if guild is None:
            await interaction.followup.send(
                "서버에서 신청해 주세요.",
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

        buyer = await find_member(
            guild, self.buyer_name.value
        )

        seller = await find_member(
            guild, self.seller_name.value
        )

        if buyer is None or seller is None:
            await interaction.followup.send(
                "구매자 또는 판매자를 찾을 수 없습니다. "
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

        requester = interaction.user

        if requester.id not in [buyer.id, seller.id]:
            await interaction.followup.send(
                "신청자는 구매자 또는 판매자여야 합니다.",
                ephemeral=True
            )
            return

        # 기본적으로 중개 관리자 역할은 읽기만 가능
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
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
                send_messages=False,
                read_message_history=True
            )
        }

        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True
            )

        channel_name = (
            f"중개-{buyer.display_name[:12]}-{seller.display_name[:12]}"
        )

        channel_name = re.sub(
            r"[^a-zA-Z0-9가-힣_-]",
            "-",
            channel_name
        )

        topic = (
            f"requester={requester.id};"
            f"buyer={buyer.id};"
            f"seller={seller.id}"
        )

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name[:100],
                overwrites=overwrites,
                topic=topic,
                reason="새로운 중개 신청"
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "봇에 채널 생성 권한이 없습니다.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="중개 신청 접수",
            description=(
                "아직 담당 중개자가 배정되지 않았습니다.\n"
                "중개 관리자 중 한 명이 담당 버튼을 눌러야 합니다."
            ),
            color=discord.Color.blue()
        )

        embed.add_field(
            name="거래 가격",
            value=self.price.value,
            inline=False
        )

        embed.add_field(
            name="구매자",
            value=buyer.mention,
            inline=True
        )

        embed.add_field(
            name="판매자",
            value=seller.mention,
            inline=True
        )

        await ticket_channel.send(
            content=(
                f"{buyer.mention} {seller.mention} "
                f"{admin_role.mention}"
            ),
            embed=embed,
            view=TicketControlsView()
        )

        await interaction.followup.send(
            f"중개 채널이 생성되었습니다: {ticket_channel.mention}",
            ephemeral=True
        )


# =========================
# 티켓 생성 버튼
# =========================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 신청하기",
        style=discord.ButtonStyle.success,
        custom_id="open_middleman_ticket"
    )
    async def open_ticket(self, interaction, button):

        await interaction.response.send_modal(
            TicketModal()
        )


# =========================
# 봇 시작
# =========================

panel_created = False


@bot.event
async def on_ready():

    global panel_created

    print(f"봇 로그인 완료: {bot.user}")

    if panel_created:
        return

    channel = bot.get_channel(TICKET_CHANNEL_ID)

    if channel is None:
        print("중개 티켓 채널을 찾을 수 없습니다.")
        return

    try:
        async for message in channel.history(limit=50):

            if (
                message.author.id == bot.user.id
                and PANEL_MARKER in message.content
            ):
                panel_created = True
                print("기존 중개 티켓 패널 확인 완료")
                return

        embed = discord.Embed(
            title="중개 티켓",
            description=(
                "아래 버튼을 눌러 중개를 신청해 주세요.\n\n"
                "거래 가격, 구매자, 판매자 정보를 입력하면 "
                "전용 중개 채널이 생성됩니다."
            ),
            color=discord.Color.blue()
        )

        await channel.send(
            content=PANEL_MARKER,
            embed=embed,
            view=TicketPanelView()
        )

        panel_created = True
        print("중개 티켓 패널 생성 완료")

    except Exception as error:
        print(f"패널 생성 오류: {error}")


bot.run(TOKEN)
