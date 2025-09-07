import discord
from discord.ext import commands
import requests
import sqlite3
import os

TOKEN = os.getenv("DISCORD_TOKEN")
BC_TOKEN = os.getenv("BLOCKCYPHER_TOKEN")
NETWORK = "ltc"  # REAL Litecoin mainnet

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =================
# Database
# =================
conn = sqlite3.connect("balances.db")
cur = conn.cursor()
cur.execute(
    "CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, address TEXT, balance REAL)"
)
conn.commit()

def get_or_create_address(user_id):
    cur.execute("SELECT address FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row:
        return row[0]

    url = f"https://api.blockcypher.com/v1/ltc/{NETWORK}/addrs?token={BC_TOKEN}"
    r = requests.post(url).json()
    address = r["address"]

    cur.execute("INSERT INTO users (user_id, address, balance) VALUES (?, ?, ?)", (user_id, address, 0))
    conn.commit()
    return address

def get_balance(user_id):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0

def update_balance(user_id, new_balance):
    cur.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
    conn.commit()

# =================
# Deposit Button View
# =================
class DepositView(discord.ui.View):
    def __init__(self, user_id, address):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.address = address

    @discord.ui.button(label="Check Funds", style=discord.ButtonStyle.green)
    async def check_funds(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = f"https://api.blockcypher.com/v1/ltc/{NETWORK}/addrs/{self.address}/balance?token={BC_TOKEN}"
        r = requests.get(url).json()
        confirmed = r.get("balance", 0) / 1e8

        current_bal = get_balance(self.user_id)
        if confirmed > current_bal:
            update_balance(self.user_id, confirmed)
            await interaction.response.send_message(
                f"✅ Deposit confirmed! Balance updated to {confirmed} LTC.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⚠️ No new confirmed deposits yet. Try again later.", ephemeral=True
            )

# =================
# Modals (Forms)
# =================
class SendTipModal(discord.ui.Modal, title="🎁 Send Tip"):
    user_id = discord.ui.TextInput(label="User ID (Discord @mention ID)", placeholder="1234567890", required=True)
    amount = discord.ui.TextInput(label="Amount (LTC)", placeholder="0.01", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        sender = str(interaction.user.id)
        receiver = str(self.user_id.value.strip())
        amount = float(self.amount.value)

        if get_balance(sender) < amount:
            await interaction.response.send_message("❌ Not enough balance.", ephemeral=True)
            return

        get_or_create_address(receiver)

        update_balance(sender, get_balance(sender) - amount)
        update_balance(receiver, get_balance(receiver) + amount)

        await interaction.response.send_message(
            f"🎉 You tipped {amount} LTC to <@{receiver}>!", ephemeral=True
        )

class WithdrawModal(discord.ui.Modal, title="💸 Withdraw"):
    ltc_address = discord.ui.TextInput(label="Litecoin Address", placeholder="Lg123abc...", required=True)
    amount = discord.ui.TextInput(label="Amount (LTC)", placeholder="0.05", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user = str(interaction.user.id)
        amount = float(self.amount.value)

        if get_balance(user) < amount:
            await interaction.response.send_message("❌ Not enough balance.", ephemeral=True)
            return

        update_balance(user, get_balance(user) - amount)

        tx_url = f"https://api.blockcypher.com/v1/ltc/{NETWORK}/txs/micro?token={BC_TOKEN}"
        tx_data = {
            "to_address": self.ltc_address.value,
            "value_satoshis": int(amount * 1e8)
        }
        r = requests.post(tx_url, json=tx_data)

        if r.status_code == 201:
            await interaction.response.send_message(f"✅ Withdrawal of {amount} LTC sent to `{self.ltc_address.value}`", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Withdrawal error: {r.text}", ephemeral=True)

# =================
# Menu View
# =================
class MenuView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="📥 Deposit", style=discord.ButtonStyle.blurple)
    async def deposit(self, interaction: discord.Interaction, button: discord.ui.Button):
        addr = get_or_create_address(self.user_id)
        view = DepositView(self.user_id, addr)
        await interaction.response.send_message(
            f"💰 Deposit LTC to:\n`{addr}`\n\nClick **Check Funds** after confirmation.",
            view=view, ephemeral=True
        )

    @discord.ui.button(label="💰 Balance", style=discord.ButtonStyle.green)
    async def balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.user_id)
        await interaction.response.send_message(f"💳 Your Balance: **{bal} LTC**", ephemeral=True)

    @discord.ui.button(label="🎁 Send Tip", style=discord.ButtonStyle.gray)
    async def send_tip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SendTipModal())

    @discord.ui.button(label="💸 Withdraw", style=discord.ButtonStyle.red)
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WithdrawModal())

# =================
# Commands
# =================
@bot.event
async def on_ready():
    print(f"Bot online as {bot.user}")

@bot.command()
async def menu(ctx):
    """Opens main menu with buttons"""
    view = MenuView(str(ctx.author.id))
    await ctx.send("🔹 **Litecoin Tip Bot Menu** — choose an action:", view=view)

bot.run(TOKEN)
