
import os
import re
import asyncio
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

# =========================
# 기본 설정
# =========================

TOKEN = os.environ["DISCORD_TOKEN"]

ADMIN_ROLE_ID = 1567743560055263292
PANEL_CHANNEL_ID = 1567747285365039114
COMPLETED_CHANNEL_ID = 1567768667913977977

KST = timezone(timedelta(hours=9))

# 기존 패널 색상에 맞춰 필요하면 이 값만 변경
PANEL_COLOR = discord.Color.blurple()

claim_lock = asyncio.Lock()


# =========================
# 공통 함수
# =========================

def get_topic_data(topic):
    data = {}
    for item in (topic or "").split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            data[key] = value
    return data


def make_topic(buyer_id, seller_id, requester_id, amount, mediator_id=0):
    return (
        f"buyer={buyer_id};"
        f"seller={seller_id};"
        f"requester={requester_id};"
        f"amount={amount};"
        f"mediator={mediator_id}"
    )


def parse_amount(value):
    digits = re.sub(r"[^0-9]", "", value)
    if not digits:
        return None
    amount = int(digits)
    if amount <= 0:
        return None
    return amount


async def find_member(guild, username):
    username = username.strip().lstrip("@").casefold()

    async for member in guild.fetch_members(limit=None):
        names = [
            member.name,
            member.display_name,
            member.global_name or ""
        ]

        if any(name.casefold() == username for name in names):
            return member

    return None


async def send_dm(member, embed, view=None):
    try:
        await member.send(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        pass


def is_admin(member):
    return any(role.id == ADMIN_ROLE_ID for role in member.roles)


def is_assigned_mediator(channel, member):
    data = get_topic_data(channel.topic)
    return data.get("mediator") == str(member.id)


# =========================
# 중개 완료 익명 선택 화면
# =========================

class CompletionView(discord.ui.View):
    def __init__(self, channel):
        super().__init__(timeout=840)
        self.channel = channel
        self.buyer_anonymous = False
        self.seller_anonymous = False

        self.add_item(AnonymousSelect(self, "buyer"))
        self.add_item(AnonymousSelect(self, "seller"))

    @discord.ui.button(
        label="거래 완료 확정",
        style=discord.ButtonStyle.success,
        custom_id="confirm_trade_completion"
    )
    async def confirm(self, interaction, button):
        if not is_assigned_mediator(
            self.channel, interaction.user
        ):
            await interaction.response.send_message(
                "담당 중개자만 완료할 수 있습니다.",
                ephemeral=True
            )
            return

        data = get_topic_data(self.channel.topic)

        buyer_id = int(data["buyer"])
        seller_id = int(data["seller"])
        amount = int(data["amount"])

        guild = self.channel.guild

        buyer = guild.get_member(buyer_id)
        seller = guild.get_member(seller_id)

        if buyer is None:
            try:
                buyer = await guild.fetch_member(buyer_id)
            except discord.HTTPException:
                buyer = None

        if seller is None:
            try:
                seller = await guild.fetch_member(seller_id)
            except discord.HTTPException:
                seller = None

        log_channel = guild.get_channel(COMPLETED_CHANNEL_ID)

        if log_channel is None:
            await interaction.response.send_message(
                "거래완료 채널을 찾을 수 없습니다. 채널 ID와 봇 권한을 확인해 주세요.",
                ephemeral=True
            )
            return

        buyer_name = (
            "익명"
            if self.buyer_anonymous
            else buyer.mention if buyer else "확인 불가"
        )

        seller_name = (
            "익명"
            if self.seller_anonymous
            else seller.mention if seller else "확인 불가"
        )

        date_text = datetime.now(KST).strftime(
            "%Y년 %m월 %d일"
        )

        embed = discord.Embed(
            title=f"{amount:,}KRW",
            color=discord.Color.green()
        )

        embed.add_field(
            name="구매자",
            value=buyer_name,
            inline=False
        )

        embed.add_field(
            name="판매자",
            value=seller_name,
            inline=False
        )

        embed.add_field(
            name="거래 날짜",
            value=date_text,
            inline=False
        )

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            await interaction.response.send_message(
                "거래 완료 기록을 올리지 못했습니다. 봇의 채널 권한을 확인해 주세요.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "거래 완료 기록이 등록되었습니다. 티켓을 종료합니다.",
            ephemeral=True
        )

        try:
            await self.channel.delete(
                reason="담당 중개자가 거래 완료 처리"
            )
        except discord.HTTPException:
            pass

        self.stop()


class AnonymousSelect(discord.ui.Select):
    def __init__(self, parent, target):
        self.parent_view = parent
        self.target = target

        label = "구매자 공개 여부" if target == "buyer" else "판매자 공개 여부"

        options = [
            discord.SelectOption(
                label="공개",
                value="public",
                description="거래완료 로그에 계정을 표시합니다."
            ),
            discord.SelectOption(
                label="익명",
                value="anonymous",
                description="거래완료 로그에 익명으로 표시합니다."
            )
        ]

        super().__init__(
            placeholder=label,
            options=options,
            min_values=1,
            max_values=1,
            custom_id=f"anonymous_{target}"
        )

    async def callback(self, interaction):
        anonymous = self.values[0] == "anonymous"

        if self.target == "buyer":
            self.parent_view.buyer_anonymous = anonymous
        else:
            self.parent_view.seller_anonymous = anonymous

        await interaction.response.send_message(
            "설정이 변경되었습니다.",
            ephemeral=True
        )


# =========================
# 티켓 내부 버튼
# =========================

class TicketControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="중개 담당하기",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_claim"
    )
    async def claim(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "중개 관리자만 담당할 수 있습니다.",
                ephemeral=True
            )
            return

        channel = interaction.channel

        async with claim_lock:
            data = get_topic_data(channel.topic)

            if data.get("mediator", "0") != "0":
                await interaction.response.send_message(
                    "이미 다른 중개자가 담당하고 있습니다.",
                    ephemeral=True
                )
                return

            data["mediator"] = str(interaction.user.id)

            new_topic = ";".join(
                f"{key}={value}" for key, value in data.items()
            )

            try:
                await channel.edit(topic=new_topic)
                await channel.set_permissions(
                    interaction.user,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            except discord.HTTPException:
                await interaction.response.send_message(
                    "담당자 배정에 실패했습니다. 봇의 채널 관리 권한을 확인해 주세요.",
                    ephemeral=True
                )
                return

        # 담당 버튼 제거
        for item in self.children:
            if getattr(item, "custom_id", None) == "ticket_claim":
                item.disabled = True

        await interaction.response.edit_message(view=self)

        await channel.send(
            embed=discord.Embed(
                title="중개 담당자 배정 완료",
                description=f"{interaction.user.mention} 님이 담당 중개자로 배정되었습니다.",
                color=PANEL_COLOR
            )
        )

        # 담당 중개자에게만 보이는 개인 완료 버튼
        await interaction.followup.send(
            "담당자 배정이 완료되었습니다. 거래가 끝나면 아래 버튼을 눌러 주세요.",
            view=PrivateCompletionButton(channel),
            ephemeral=True
        )

        # 구매자와 판매자에게 배정 DM
        guild = channel.guild

        for key in ("buyer", "seller"):
            member = guild.get_member(int(data[key]))
            if member:
                embed = discord.Embed(
                    title="중개 담당자 배정 안내",
                    description=(
                        f"담당 중개자가 배정되었습니다.\n"
                        f"담당자: {interaction.user.mention}\n"
                        f"티켓: {channel.mention}"
                    ),
                    color=PANEL_COLOR
                )
                await send_dm(member, embed)

    @discord.ui.button(
        label="티켓 삭제",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_close"
    )
    async def close(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "중개 관리자만 티켓을 삭제할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "티켓을 삭제합니다.",
            ephemeral=True
        )

        await interaction.channel.delete(
            reason="중개 관리자에 의한 티켓 삭제"
        )


# =========================
# 개인 완료 버튼
# =========================

class PrivateCompletionButton(discord.ui.View):
    def __init__(self, channel):
        super().__init__(timeout=840)
        self.channel = channel

    @discord.ui.button(
        label="중개 완료",
        style=discord.ButtonStyle.success,
        custom_id="private_complete"
    )
    async def complete(self, interaction, button):
        if not is_assigned_mediator(
            self.channel, interaction.user
        ):
            await interaction.response.send_message(
                "담당 중개자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "구매자와 판매자의 표시 방식을 각각 선택해 주세요.",
            view=CompletionView(self.channel),
            ephemeral=True
        )


# =========================
# 티켓 신청 모달
# =========================

class TicketModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="중개 신청")

        self.amount = discord.ui.TextInput(
            label="거래 금액",
            placeholder="예: 1000000",
            required=True,
            max_length=20
        )

        self.buyer = discord.ui.TextInput(
            label="구매자 디스코드 사용자명",
            placeholder="예: username",
            required=True,
            max_length=100
        )

        self.seller = discord.ui.TextInput(
            label="판매자 디스코드 사용자명",
            placeholder="예: username",
            required=True,
            max_length=100
        )

        self.add_item(self.amount)
        self.add_item(self.buyer)
        self.add_item(self.seller)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        amount = parse_amount(str(self.amount))

        if amount is None:
            await interaction.followup.send(
                "올바른 거래 금액을 입력해 주세요.",
                ephemeral=True
            )
            return

        buyer = await find_member(guild, str(self.buyer))
        seller = await find_member(guild, str(self.seller))

        if buyer is None or seller is None:
            await interaction.followup.send(
                "구매자 또는 판매자를 찾을 수 없습니다. 사용자명을 확인해 주세요.",
                ephemeral=True
            )
            return

        if buyer.id == seller.id:
            await interaction.followup.send(
                "구매자와 판매자는 서로 다른 사람이어야 합니다.",
                ephemeral=True
            )
            return

        if interaction.user.id not in (buyer.id, seller.id):
            await interaction.followup.send(
                "신청자는 구매자 또는 판매자 중 한 명이어야 합니다.",
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

        bot_member = guild.me

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
            ),

            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True
            )
        }

        topic = make_topic(
            buyer.id,
            seller.id,
            interaction.user.id,
            amount
        )

        safe_name = re.sub(
            r"[^a-zA-Z0-9가-힣-]",
            "-",
            buyer.name
        )[:20]

        try:
            channel = await guild.create_text_channel(
                name=f"중개-{safe_name}",
                overwrites=overwrites,
                topic=topic
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "티켓 생성에 실패했습니다. 봇의 채널 관리 권한을 확인해 주세요.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="중개 신청 접수",
            description="중개 담당자가 배정될 때까지 기다려 주세요.",
            color=PANEL_COLOR
        )

        embed.add_field(
            name="거래 금액",
            value=f"{amount:,}KRW",
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

        embed.add_field(
            name="신청자",
            value=interaction.user.mention,
            inline=False
        )

        await channel.send(
            content=f"{buyer.mention} {seller.mention} {admin_role.mention}",
            embed=embed,
            view=TicketControlsView(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True
            )
        )

        await interaction.followup.send(
            f"중개 티켓이 생성되었습니다: {channel.mention}",
            ephemeral=True
        )

        dm_embed = discord.Embed(
            title="중개 신청 접수 완료",
            description=(
                f"거래 금액: {amount:,}KRW\n"
                f"티켓: {channel.mention}"
            ),
            color=PANEL_COLOR
        )

        await send_dm(buyer, dm_embed)
        await send_dm(seller, dm_embed)


# =========================
# 패널
# =========================

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="티켓 열기",
        style=discord.ButtonStyle.primary,
        custom_id="open_mediation_ticket"
    )
    async def open_ticket(self, interaction, button):
        await interaction.response.send_modal(TicketModal())


# =========================
# 봇 실행
# =========================

class MediationBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(TicketPanelView())
        self.add_view(TicketControlsView())


intents = discord.Intents.default()
intents.members = True

bot = MediationBot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"봇 로그인 완료: {bot.user}")

    channel = bot.get_channel(PANEL_CHANNEL_ID)

    if channel is None:
        print("패널 채널을 찾을 수 없습니다.")
        return

    async for message in channel.history(limit=100):
        if (
            message.author.id == bot.user.id
            and message.embeds
            and message.embeds[0].title == "중개 - Brokerage robot"
        ):
            return

    embed = discord.Embed(
        title="중개 - Brokerage robot",
        description=(
            "- 안전하게 당신의 계정을 중개로 지키세요\n"
            "- 중개 수수료 : 100,000₩ / 1,000₩"
        ),
        color=PANEL_COLOR
    )

    await channel.send(
        embed=embed,
        view=TicketPanelView()
    )


bot.run(TOKEN)
