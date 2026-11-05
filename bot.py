
import os
import re
import discord
from discord.ext import commands

# =========================
# 기본 설정
# =========================

TOKEN = os.environ["DISCORD_TOKEN"]

ADMIN_ROLE_ID = 1567743560055263292
TICKET_CHANNEL_ID = 1567747285365039114

PANEL_MARKER = "중개 티켓 안내 패널"

# =========================
# 봇 권한 설정
# =========================

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# 사용자 검색
# =========================

async def find_member(guild, value):
    value = value.strip()

    # 실제 멘션 형식도 지원
    mention_match = re.fullmatch(r"<@!?(\d+)>", value)

    if mention_match:
        member_id = int(mention_match.group(1))

        try:
            return await guild.fetch_member(member_id)
        except discord.NotFound:
            return None

    # @ 기호 제거
    username = value.removeprefix("@").strip().casefold()

    if not username:
        return None

    exact_username = []
    display_matches = []

    async for member in guild.fetch_members(limit=None):
        if member.bot:
            continue

        if member.name.casefold() == username:
            exact_username.append(member)

        elif (
            member.display_name.casefold() == username
            or (
                member.global_name is not None
                and member.global_name.casefold() == username
            )
        ):
            display_matches.append(member)

    # 실제 Discord 사용자명 우선
    matches = exact_username if exact_username else display_matches

    # 중복 제거
    unique_matches = {
        member.id: member
        for member in matches
    }

    if len(unique_matches) == 1:
        return list(unique_matches.values())[0]

    return None


# =========================
# 중개 종료 버튼
# =========================

class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

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

        # 관리자만 종료 가능
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
            reason=f"중개 종료 - 관리자: {interaction.user}"
        )


# =========================
# 중개 신청 모달
# =========================

class TicketModal(discord.ui.Modal):

    def __init__(self):
        super().__init__(title="중개 신청")

        self.price = discord.ui.TextInput(
            label="거래 가격",
            placeholder="예: 50000원",
            max_length=50,
            required=True
        )

        self.buyer_name = discord.ui.TextInput(
            label="구매자 사용자명",
            placeholder="예: @buyer123",
            max_length=100,
            required=True
        )

        self.seller_name = discord.ui.TextInput(
            label="판매자 사용자명",
            placeholder="예: @seller456",
            max_length=100,
            required=True
        )

        self.add_item(self.price)
        self.add_item(self.buyer_name)
        self.add_item(self.seller_name)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        # 처리 시간이 길어져도 응답 시간 초과 방지
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        guild = interaction.guild

        if guild is None:
            await interaction.followup.send(
                "서버에서만 신청할 수 있습니다.",
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

        # 구매자 검색
        buyer = await find_member(
            guild,
            self.buyer_name.value
        )

        # 판매자 검색
        seller = await find_member(
            guild,
            self.seller_name.value
        )

        if buyer is None:
            await interaction.followup.send(
                "구매자를 찾을 수 없거나 사용자명이 중복됩니다. "
                "서버의 정확한 사용자명을 입력해 주세요.",
                ephemeral=True
            )
            return

        if seller is None:
            await interaction.followup.send(
                "판매자를 찾을 수 없거나 사용자명이 중복됩니다. "
                "서버의 정확한 사용자명을 입력해 주세요.",
                ephemeral=True
            )
            return

        if buyer.id == seller.id:
            await interaction.followup.send(
                "구매자와 판매자는 서로 다른 사람이어야 합니다.",
                ephemeral=True
            )
            return

        requester = interaction.user

        # 신청자는 구매자 또는 판매자여야 함
        if requester.id not in [buyer.id, seller.id]:
            await interaction.followup.send(
                "신청자는 구매자 또는 판매자 중 한 명이어야 합니다.",
                ephemeral=True
            )
            return

        # 거래 채널 권한 설정
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),

            requester: discord.PermissionOverwrite(
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
                read_message_history=True,
                manage_channels=True
            )
        }

        # 봇 본인 권한
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True
            )

        # 채널 이름 생성
        channel_name = (
            f"중개-{buyer.display_name[:12]}-{seller.display_name[:12]}"
        )

        channel_name = re.sub(
            r"[^a-zA-Z0-9가-힣_-]",
            "-",
            channel_name
        )

        # 거래 정보 저장
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

        # 거래 정보 표시
        embed = discord.Embed(
            title="중개 신청 완료",
            description="중개 거래가 접수되었습니다.",
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

        embed.add_field(
            name="신청자",
            value=requester.mention,
            inline=False
        )

        embed.set_footer(
            text="중개 관리자만 중개 종료 버튼을 사용할 수 있습니다."
        )

        await ticket_channel.send(
            content=f"{buyer.mention} {seller.mention} {admin_role.mention}",
            embed=embed,
            view=TicketCloseView()
        )

        await interaction.followup.send(
            f"중개 채널이 생성되었습니다: {ticket_channel.mention}",
            ephemeral=True
        )


# =========================
# 중개 티켓 생성 버튼
# =========================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 신청하기",
        style=discord.ButtonStyle.success,
        custom_id="open_middleman_ticket"
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            TicketModal()
        )


# =========================
# 봇 시작 시 설정
# =========================

class MediationBot(commands.Bot):

    async def setup_hook(self):

        # 버튼을 재시작 후에도 유지
        self.add_view(TicketPanelView())
        self.add_view(TicketCloseView())


bot = MediationBot(
    command_prefix="!",
    intents=intents
)


# =========================
# 중개 티켓 안내 패널
# =========================

panel_created = False


@bot.event
async def on_ready():

    global panel_created

    print(f"봇 로그인 완료: {bot.user}")

    if panel_created:
        return

    panel_channel = bot.get_channel(TICKET_CHANNEL_ID)

    if panel_channel is None:
        print("중개 티켓 채널을 찾을 수 없습니다.")
        return

    try:
        # 기존 패널 확인
        async for message in panel_channel.history(limit=50):

            if (
                message.author.id == bot.user.id
                and PANEL_MARKER in message.content
            ):
                panel_created = True
                print("기존 중개 티켓 패널 확인 완료")
                return

        # 새 패널 생성
        embed = discord.Embed(
            title="중개 티켓",
            description=(
                "아래 버튼을 눌러 중개를 신청해 주세요.\n\n"
                "거래 가격, 구매자, 판매자 정보를 입력하면 "
                "전용 중개 채널이 생성됩니다."
            ),
            color=discord.Color.blue()
        )

        await panel_channel.send(
            content=PANEL_MARKER,
            embed=embed,
            view=TicketPanelView()
        )

        panel_created = True

        print("중개 티켓 패널 생성 완료")

    except discord.Forbidden:
        print("중개 티켓 채널 권한을 확인해 주세요.")

    except Exception as error:
        print(f"패널 생성 오류: {error}")


# =========================
# 봇 실행
# =========================

bot.run(TOKEN)
