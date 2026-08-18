import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Select
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict
import time
import asyncio
import random
import string
import json
import traceback
import aiohttp

TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_ID = 1504482964661076098
ADMIN_ROLE_ID = 1516094850628587630
INVITE_LINK = "https://discord.gg/njxxTuMH"
VERIFY_ROLE_ID = 1508785745547235388
VERIFIED_ROLE_ID = 1504503685328146585
VERIFY_MESSAGE_CHANNEL_ID = 1513696689536372736
VERIFY_LOG_CHANNEL_ID = 1513733733184831558
JAIL_ROLE_ID = 1512734205971398676
IMMUNITY_ROLE_ID = 1514879604270305291
TICKET_CATEGORY_ID = 1529642272118014073
GAME_CATEGORY_ID = 1513692080398925824
RULES_CHANNEL_ID = 1514232611600470179
SENIOR_MOD_ROLE_ID = 1504502978374139977
STAFF_LOG_CHANNEL_ID = 1534568211641798717
SPECIAL_BAN_ROLE_ID = 1504502759922077776

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='+', intents=intents, help_command=None)

hardbanned_users = set()
warnings = defaultdict(list)
user_messages = defaultdict(list)
user_warnings = defaultdict(int)
user_message_times = defaultdict(list)
user_violations = defaultdict(list)
verify_running = False
banned_count = 0
verify_message_id = None
verify_channel_id = None
user_roles_backup = {}
afk_users = {}
recently_warned_spam = {}

# Moderation statistics: {moderator_id: {"warned": [{"time": ts, ...}], "banned": [...], ...}}
mod_stats = defaultdict(lambda: defaultdict(list))
case_counter = 0

# Система кулдаунов
command_cooldowns = defaultdict(dict)
COOLDOWN_BAN = 7200
COOLDOWN_MUTE = 7200
COOLDOWN_JAIL = 7200
COOLDOWN_WARN = 7200

ban_usage = defaultdict(list)
mute_usage = defaultdict(list)
warn_usage = defaultdict(list)
jail_usage = defaultdict(list)

BAN_LIMIT = 3
MUTE_LIMIT = 3
WARN_LIMIT = 3
JAIL_LIMIT = 1
TIME_WINDOW = 300

# НАСТРОЙКИ АВТОМОДА
MESSAGE_LIMIT = 5
MESSAGE_WINDOW = 7
SIMILAR_MESSAGE_LIMIT = 4
SIMILAR_MESSAGE_WINDOW = 8
SPAM_WARN_COOLDOWN = 90

MONITORED_USERS = {
    1220374053416599604: [1516094850628587630, 1527291269330505759],
    903474440564801627: [1515363972180869282, 1516192523691884816],
    1430922990706491546: [1508842712542089498]
}

role_map = {
    'retard': 1513440439766876180,
    'tester': 1504503576653856868,
    'known': 1504503401059324055,
    'vip': 1508798935991320767,
    'coolguy': 1508842712542089498,
    'ticketssupport': 1509149262334791791,
    'contentcreator': 1508793047230709932,
    'ticketsadmin': 1509149263123320874,
    'support': 1508782838600830996,
    'mod': 1504503217382232166,
    'senior mod': 1504502978374139977,
    'manager': 1508790828448092211,
    'co-owner': 1508790026518003713,
    'dev': 1504502883872411800,
    'imageperms': 1514869583738175508
}

CHANNELS_TO_LOCK = [
    1513695339167617084,
    1513695434026254438,
    1514945294964359329
]

VOICE_CHANNELS_TO_LOCK = [
    1513692263010799716,
    1513692362931703818,
    1513692441281036348,
    1513692510306963476,
    1513692585682669618
]

STAFF_ROLES = [
    1508782838600830996,
    1504503460740202567,
    1508793047230709932,
    1504503217382232166,
    1504502978374139977,
    1508790828448092211,
    1516192523691884816
]

COMMAND_ROLES = [
    1508782838600830996,
    1504503217382232166,
    1504502978374139977,
    1508790828448092211,
    1516192523691884816,
    1504502759922077776,
    1504502883872411800,
]

JAIL_ROLES = COMMAND_ROLES.copy()
WARN_ROLES = COMMAND_ROLES.copy()
WARN_REMOVE_ROLES = COMMAND_ROLES.copy()
WARN_LIST_ROLES = COMMAND_ROLES.copy()

ADMIN_ROLES = [
    1504502759922077776,
    1516192523691884816,
    1508790828448092211,
    1504502978374139977
]

ALL_STAFF_ROLES = COMMAND_ROLES.copy()

LOCK_ROLES = [SENIOR_MOD_ROLE_ID] + COMMAND_ROLES  # Senior Mod + выше

def can_punish(moderator, target):
    if moderator == target:
        return False, "You cannot punish yourself."
    
    if has_immunity(target):
        return False, f"{target.mention} has immunity from punishments."
    
    # Special role can punish even administrators
    has_special = any(role.id == SPECIAL_BAN_ROLE_ID for role in moderator.roles)
    
    if target.guild_permissions.administrator and not has_special:
        return False, f"{target.mention} has administrator permissions and cannot be punished."
    
    mod_top_role = moderator.top_role
    target_top_role = target.top_role
    
    if not has_special and mod_top_role.position <= target_top_role.position:
        return False, f"You cannot punish {target.mention} because they have the same or higher role than you."
    
    return True, None

def has_command_permission(ctx):
    if ctx.author.guild_permissions.administrator:
        return True
    for role in ctx.author.roles:
        if role.id in COMMAND_ROLES:
            return True
    return False

def generate_warn_code():
    return ''.join(random.choices(string.digits, k=4))

def has_immunity(member):
    if member is None:
        return False
    for role in member.roles:
        if role.id == IMMUNITY_ROLE_ID:
            return True
    return False

def check_cooldown(user_id, command_type, limit, time_window, cooldown_duration):
    current_time = time.time()
    
    if command_type == 'ban':
        usages = ban_usage[user_id]
    elif command_type == 'mute':
        usages = mute_usage[user_id]
    elif command_type == 'warn':
        usages = warn_usage[user_id]
    elif command_type == 'jail':
        usages = jail_usage[user_id]
    else:
        return True, None
    
    usages = [t for t in usages if current_time - t < time_window]
    
    if len(usages) >= limit:
        if command_type in command_cooldowns[user_id]:
            cooldown_end = command_cooldowns[user_id][command_type]
            if current_time < cooldown_end:
                remaining = int(cooldown_end - current_time)
                return False, remaining
        usages = []
    
    if command_type == 'ban':
        ban_usage[user_id] = usages
    elif command_type == 'mute':
        mute_usage[user_id] = usages
    elif command_type == 'warn':
        warn_usage[user_id] = usages
    elif command_type == 'jail':
        jail_usage[user_id] = usages
    
    return True, None

def add_cooldown(user_id, command_type, cooldown_duration):
    current_time = time.time()
    if user_id not in command_cooldowns:
        command_cooldowns[user_id] = {}
    command_cooldowns[user_id][command_type] = current_time + cooldown_duration

def record_usage(user_id, command_type):
    current_time = time.time()
    if command_type == 'ban':
        ban_usage[user_id].append(current_time)
    elif command_type == 'mute':
        mute_usage[user_id].append(current_time)
    elif command_type == 'warn':
        warn_usage[user_id].append(current_time)
    elif command_type == 'jail':
        jail_usage[user_id].append(current_time)

def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{seconds}s"

def format_afk_time(start_time):
    elapsed = int(time.time() - start_time)
    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def save_warnings():
    try:
        warnings_dict = {}
        for key, value in warnings.items():
            warnings_dict[str(key)] = value
        with open('warnings.json', 'w') as f:
            json.dump(warnings_dict, f, indent=4)
        print(f"Warnings saved: {len(warnings_dict)} users")
    except Exception as e:
        print(f"Error saving warnings: {e}")

def load_warnings():
    global warnings, user_warnings
    try:
        if os.path.exists('warnings.json'):
            with open('warnings.json', 'r') as f:
                data = json.load(f)
                for user_id, warns in data.items():
                    warnings[int(user_id)] = warns
                    user_warnings[int(user_id)] = len(warns)
            print(f"Loaded warnings for {len(data)} users")
        else:
            print("No warnings file found, starting fresh")
    except Exception as e:
        print(f"Error loading warnings: {e}")
        print(traceback.format_exc())

def save_hardbanned():
    try:
        with open('hardbanned.json', 'w') as f:
            json.dump(list(hardbanned_users), f)
    except Exception as e:
        print(f"Error saving hardbanned: {e}")

def load_hardbanned():
    global hardbanned_users
    try:
        if os.path.exists('hardbanned.json'):
            with open('hardbanned.json', 'r') as f:
                data = json.load(f)
                hardbanned_users = set(data)
            print(f"Loaded {len(hardbanned_users)} hardbanned users")
    except Exception as e:
        print(f"Error loading hardbanned: {e}")

def save_mod_stats():
    try:
        data = {}
        for mod_id, actions in mod_stats.items():
            data[str(mod_id)] = {k: v for k, v in actions.items()}
        with open('mod_stats.json', 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving mod stats: {e}")

def load_mod_stats():
    global mod_stats
    try:
        if os.path.exists('mod_stats.json'):
            with open('mod_stats.json', 'r') as f:
                data = json.load(f)
                for mod_id, actions in data.items():
                    for action, times in actions.items():
                        mod_stats[int(mod_id)][action] = times
            print(f"Loaded mod stats for {len(data)} moderators")
    except Exception as e:
        print(f"Error loading mod stats: {e}")

def record_mod_action(moderator_id, action):
    """Record a moderation action for statistics. action: warned, kicked, banned, unbanned, timed_out, jailed, unjailed, unmuted"""
    mod_stats[moderator_id][action].append(time.time())
    save_mod_stats()

async def log_staff_action(ctx, action_name, reason="Staff command used"):
    """Log staff action to the log channel with orange color"""
    log_channel = bot.get_channel(STAFF_LOG_CHANNEL_ID)
    if not log_channel:
        return
    embed = discord.Embed(
        description=f"I detected that your staff has doing some weird things (**{reason}**)\n\n**User** {ctx.author.mention}\n**Detected at** {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
        color=discord.Color.from_rgb(255, 140, 0)  # Orange
    )
    try:
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Error logging staff action: {e}")

class DeleteTicketButton(Button):
    def __init__(self):
        super().__init__(label="Delete Ticket", style=discord.ButtonStyle.danger)
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.bot:
            return
        
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                description="You don't have permission to delete this ticket.",
                color=discord.Color.from_rgb(255, 200, 0)
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.send_message("Deleting ticket...", ephemeral=True)
        await asyncio.sleep(1)
        try:
            await interaction.channel.delete()
        except Exception as e:
            print(f"Error deleting channel: {e}")

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.select(
        placeholder="Choose an option...",
        options=[
            discord.SelectOption(label="I want to be staff", description="Apply for staff position", emoji="🛡️"),
            discord.SelectOption(label="I want to be developer", description="Apply for developer position", emoji="💻"),
            discord.SelectOption(label="I found a issue in script", description="Report a script issue", emoji="🐛")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer()
        choice = select.values[0]
        
        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not category:
            await interaction.followup.send("Ticket category not found.", ephemeral=True)
            return
        
        ticket_id = ''.join(random.choices(string.digits, k=3))
        channel_name = f"ticket-{ticket_id}"
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True)
        }
        
        for role_id in ALL_STAFF_ROLES:
            role = interaction.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True)
        
        channel = await interaction.guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )
        
        embed = discord.Embed(
            description=f"{interaction.user.mention}, hello. This is your ticket.",
            color=discord.Color.from_rgb(255, 255, 255)
        )
        
        if choice == "I want to be staff":
            embed.description += f"\n\nThis is ur ticket to be staff. Answer the questions below:\n\n#1 how much u can be active in one day\n#2 are u mobile/pc user\n#3 have you read the staff-info?\n#4 was there any experience in this field?"
            mention = " ".join([f"<@&{role_id}>" for role_id in ADMIN_ROLES])
            await channel.send(f"{mention}")
        elif choice == "I want to be developer":
            embed.description += f'\n\nThis is ur ticket. "I want to be a new dev". Explain ur experience with lua coding below. Show screenshots/videos of your work to get admins respond faster.'
            mention = " ".join([f"<@&{role_id}>" for role_id in [1504502759922077776, 1504502883872411800, 1516192523691884816, 1508790828448092211]])
            await channel.send(f"{mention}")
        else:
            embed.description += f'\n\nThis is ur ticket. "I found a issue in script". Explain it below and wait when moderators answer to u. You can send screenshot or video to get ur problem resolved faster.'
            mention = " ".join([f"<@&{role_id}>" for role_id in ALL_STAFF_ROLES])
            await channel.send(f"{mention}")
        
        embed.color = discord.Color.from_rgb(255, 255, 255)
        await channel.send(embed=embed)
        
        view = View()
        view.add_item(DeleteTicketButton())
        await channel.send("Click the button below to delete this ticket.", view=view)
        
        await interaction.followup.send(f"Ticket created: {channel.mention}", ephemeral=True)

@bot.event
async def on_ready():
    global banned_count, verify_message_id, verify_channel_id
    print(f'Bot {bot.user} is online')
    
    guild = bot.get_guild(SERVER_ID)
    if guild:
        try:
            await guild.me.edit(nick="HollyScriptX")
            print("Nickname changed to HollyScriptX")
        except Exception as e:
            print(f"Could not change nickname: {e}")
    
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name="discord.gg/hsx | +help")
    )
    
    load_warnings()
    load_hardbanned()
    load_mod_stats()
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    
    channel = bot.get_channel(1518832499122507786)
    if channel:
        try:
            async for message in channel.history(limit=None):
                if message.author == bot.user:
                    continue
                banned_count += 1
            print(f"Banned count: {banned_count}")
        except Exception as e:
            print(f"Error counting bans: {e}")
    
    guild = bot.get_guild(SERVER_ID)
    if guild:
        verify_channel = guild.get_channel(VERIFY_MESSAGE_CHANNEL_ID)
        if verify_channel:
            async for message in verify_channel.history(limit=50):
                if message.author == bot.user and message.embeds:
                    verify_message_id = message.id
                    verify_channel_id = message.channel.id
                    print(f'Verification message restored: {verify_message_id}')
                    break

@bot.event
async def on_message(message):
    if message.author == bot.user:
        await bot.process_commands(message)
        return
    
    if message.guild is None or message.guild.id != SERVER_ID:
        await bot.process_commands(message)
        return
    
    # AFK check
    if message.mentions:
        for mentioned in message.mentions:
            if mentioned.id in afk_users:
                afk_data = afk_users[mentioned.id]
                afk_time = format_afk_time(afk_data['time'])
                embed = discord.Embed(
                    description=f"{mentioned.mention} is AFK.\n\n**Reason:** {afk_data['reason']}\n**Duration:** {afk_time}",
                    color=discord.Color.from_rgb(180, 180, 180)
                )
                await message.channel.send(embed=embed)
    
    if message.author.id in afk_users:
        afk_data = afk_users[message.author.id]
        afk_time = format_afk_time(afk_data['time'])
        embed = discord.Embed(
            description=f"{message.author.mention}, you were AFK.\n\n**Reason:** {afk_data['reason']}\n**Duration:** {afk_time}",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await message.channel.send(embed=embed)
        del afk_users[message.author.id]
    
    # ============ АВТОМОД ============
    current_time = time.time()
    user_id = message.author.id
    
    # Skip automod for bots and users with immunity / admin
    if message.author.bot or message.author.guild_permissions.administrator or has_immunity(message.author):
        await bot.process_commands(message)
        return
    
    # Cooldown after recent spam warn
    if user_id in recently_warned_spam:
        if current_time - recently_warned_spam[user_id] < SPAM_WARN_COOLDOWN:
            # Still process commands but skip further spam checks this window
            await bot.process_commands(message)
            return
    
    # Init tracking
    if user_id not in user_message_times:
        user_message_times[user_id] = []
    if user_id not in user_messages:
        user_messages[user_id] = []
    
    # Clean old timestamps
    user_message_times[user_id] = [t for t in user_message_times[user_id] if current_time - t < MESSAGE_WINDOW]
    user_message_times[user_id].append(current_time)
    
    # SPAM: too many messages in short window
    if len(user_message_times[user_id]) >= MESSAGE_LIMIT:
        recently_warned_spam[user_id] = current_time
        try:
            await message.delete()
        except:
            pass
        await warn_user_auto(message, "spamming (too many messages)")
        # Clear tracking after warn
        user_message_times[user_id] = []
        user_messages[user_id] = []
        await bot.process_commands(message)
        return
    
    # SPAM: identical messages
    if message.content and len(message.content.strip()) > 0:
        user_messages[user_id] = [msg for msg in user_messages[user_id] if current_time - msg['time'] < SIMILAR_MESSAGE_WINDOW]
        
        similar_count = sum(1 for msg in user_messages[user_id] if msg['content'] == message.content)
        
        if similar_count >= SIMILAR_MESSAGE_LIMIT - 1:  # -1 because current message will be the limit
            recently_warned_spam[user_id] = current_time
            try:
                await message.delete()
            except:
                pass
            await warn_user_auto(message, "spamming (same message)")
            user_message_times[user_id] = []
            user_messages[user_id] = []
            await bot.process_commands(message)
            return
        
        user_messages[user_id].append({
            'content': message.content,
            'time': current_time
        })
    
    # Messages starting with #
    if message.content and message.content.startswith('#'):
        try:
            await message.delete()
        except:
            pass
        await warn_user_auto(message, "sending messages starting with #")
        await bot.process_commands(message)
        return
    
    # Prohibited content
    if message.content:
        content_lower = message.content.lower()
        if "porn" in content_lower or "loadstring" in content_lower:
            allowed_loadstring = 'loadstring(game:HttpGet("https://raw.githubusercontent.com/saosdkjiqwdjuqjudidw/HollyScriptX/refs/heads/main/main.lua"))()'
            if allowed_loadstring not in message.content:
                try:
                    await message.delete()
                except:
                    pass
                await warn_user_auto(message, "sending prohibited content")
                await bot.process_commands(message)
                return
    
    # Auto-ban channel
    if message.channel.id == 1518832499122507786:
        await auto_ban(message)
        await bot.process_commands(message)
        return
    
    if "zalupa" in message.content.lower():
        await message.reply("**hi!**")
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    if member.id in hardbanned_users:
        try:
            await member.ban(reason="Hardban re-apply: user was hardbanned")
            log_channel = bot.get_channel(STAFF_LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    description=f"I detected a attempt to unban a user that has been hardbanned {member.mention} user banned again and logs has been sent to : <#{STAFF_LOG_CHANNEL_ID}>",
                    color=discord.Color.from_rgb(200, 70, 70)
                )
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Hardban rejoin error: {e}")
        return
    
    if member.id in MONITORED_USERS:
        roles_to_add = MONITORED_USERS[member.id]
        for role_id in roles_to_add:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role)
                except:
                    pass
        
        channel = bot.get_channel(1513695339167617084)
        if channel:
            embed = discord.Embed(
                description=f"{member.mention} I detected your join and restored your roles.",
                color=discord.Color.from_rgb(100, 200, 120)
            )
            await channel.send(embed=embed)

@bot.event
async def on_member_unban(guild, user):
    if user.id in hardbanned_users:
        try:
            await guild.ban(user, reason="Hardban protection: unban attempt blocked")
            log_channel = bot.get_channel(STAFF_LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    description=f"I detected a attempt to unban a user that has been hardbanned {user.mention} user banned again and logs has been sent to : <#{STAFF_LOG_CHANNEL_ID}>",
                    color=discord.Color.from_rgb(200, 70, 70)
                )
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Hardban unban protect error: {e}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    
    if payload.message_id != verify_message_id:
        return
    
    if str(payload.emoji) != "✅":
        return
    
    guild = bot.get_guild(SERVER_ID)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        return
    
    old_role = guild.get_role(VERIFY_ROLE_ID)
    new_role = guild.get_role(VERIFIED_ROLE_ID)
    
    if not old_role or not new_role:
        return
    
    try:
        await member.remove_roles(old_role)
        await member.add_roles(new_role)
        
        log_channel = bot.get_channel(VERIFY_LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                description=f"**HollyScriptX**\n{member.mention} successfully verified.",
                color=discord.Color.from_rgb(100, 200, 120)
            )
            await log_channel.send(embed=embed)
    except Exception as e:
        print(f'Verify error: {e}')

async def warn_user_auto(message, reason, moderator="Auto-Mod"):
    if message.author.guild_permissions.administrator:
        return
    
    if has_immunity(message.author):
        return
    
    warn_code = generate_warn_code()
    user_warnings[message.author.id] += 1
    warn_count = user_warnings[message.author.id]
    
    if message.author.id not in warnings:
        warnings[message.author.id] = []
    
    warnings[message.author.id].append({
        'code': warn_code,
        'reason': reason,
        'moderator': moderator,
        'date': datetime.now().strftime('%m/%d/%Y %I:%M %p')
    })
    
    save_warnings()
    
    try:
        embed_dm = discord.Embed(
            title="Warned",
            description="You have been warned in **HollyScriptX**",
            color=discord.Color.from_rgb(255, 200, 0)  # Yellow bar
        )
        embed_dm.add_field(name="Moderator", value=moderator, inline=True)
        embed_dm.add_field(name="Reason", value=reason, inline=True)
        embed_dm.add_field(name="Warning", value=f"{warn_count}/5", inline=False)
        embed_dm.add_field(name="Code", value=f"`{warn_code}`", inline=False)
        embed_dm.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
        await message.author.send(embed=embed_dm)
    except:
        pass
    
    embed_channel = discord.Embed(
        description=f"{message.author.mention} has been warned for **{reason}**\n\n**Warning:** {warn_count}/5\n**Code:** `{warn_code}`",
        color=discord.Color.from_rgb(255, 200, 0)
    )
    await message.channel.send(embed=embed_channel)
    
    if warn_count >= 5:
        try:
            await message.author.ban(reason="5 warnings - automatic ban")
            
            embed_ban = discord.Embed(
                title="Banned",
                description="You have been **banned** from **HollyScriptX**",
                color=discord.Color.from_rgb(200, 70, 70)
            )
            embed_ban.add_field(name="Moderator", value="Auto-Mod", inline=False)
            embed_ban.add_field(name="Reason", value="5 warnings", inline=False)
            embed_ban.add_field(name="Duration", value="Permanent", inline=False)
            embed_ban.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
            
            try:
                await message.author.send(embed=embed_ban)
            except:
                pass
            
            embed_channel_ban = discord.Embed(
                description=f"{message.author.mention} has been banned for reaching 5 warnings.",
                color=discord.Color.from_rgb(200, 70, 70)
            )
            await message.channel.send(embed=embed_channel_ban)
        except Exception as e:
            print(f'Ban error: {e}')
    
    return warn_code

async def warn_user(target, reason, moderator=None, ctx=None):
    if hasattr(target, 'author'):
        member = target.author
        channel = target.channel
    else:
        member = target
        channel = ctx.channel if ctx else None
    
    if ctx and ctx.author:
        can_punish_result, error_msg = can_punish(ctx.author, member)
        if not can_punish_result:
            if channel:
                embed = discord.Embed(
                    description=error_msg,
                    color=discord.Color.from_rgb(255, 200, 0)
                )
                await channel.send(embed=embed)
            return None
    
    warn_code = generate_warn_code()
    user_warnings[member.id] += 1
    warn_count = user_warnings[member.id]
    
    if member.id not in warnings:
        warnings[member.id] = []
    
    warnings[member.id].append({
        'code': warn_code,
        'reason': reason,
        'moderator': moderator or "Auto-Mod",
        'date': datetime.now().strftime('%m/%d/%Y %I:%M %p')
    })
    
    save_warnings()
    
    embed = discord.Embed(
        title="Warned",
        description="You have been warned in **HollyScriptX**",
        color=discord.Color.from_rgb(255, 200, 0)
    )
    embed.add_field(name="Moderator", value=moderator or "Auto-Mod", inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    embed.add_field(name="Warning", value=f"{warn_count}/5", inline=False)
    embed.add_field(name="Code", value=f"`{warn_code}`", inline=False)
    embed.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
    
    try:
        await member.send(embed=embed)
    except:
        pass
    
    if channel:
        embed_channel = discord.Embed(
            description=f"{member.mention} has been warned for **{reason}**\n\n**Warning:** {warn_count}/5\n**Code:** `{warn_code}`",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await channel.send(embed=embed_channel)
    
    if warn_count >= 5:
        try:
            await member.ban(reason="5 warnings - automatic ban")
            
            embed_ban = discord.Embed(
                title="Banned",
                description="You have been **banned** from **HollyScriptX**",
                color=discord.Color.from_rgb(200, 70, 70)
            )
            embed_ban.add_field(name="Moderator", value="Auto-Mod", inline=False)
            embed_ban.add_field(name="Reason", value="5 warnings", inline=False)
            embed_ban.add_field(name="Duration", value="Permanent", inline=False)
            embed_ban.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
            
            try:
                await member.send(embed=embed_ban)
            except:
                pass
            
            if channel:
                embed_channel_ban = discord.Embed(
                    description=f"{member.mention} has been banned for reaching 5 warnings.",
                    color=discord.Color.from_rgb(200, 70, 70)
                )
                await channel.send(embed=embed_channel_ban)
        except Exception as e:
            print(f'Ban error: {e}')
    
    return warn_code

async def auto_ban(message):
    global banned_count
    try:
        member = message.author
        banned_count += 1
        
        log_channel = bot.get_channel(1518832499122507786)
        if log_channel:
            embed = discord.Embed(
                description=f"{member.mention} has been permanently **banned** from **HollyScriptX**\n\n**Reason:** Scammed Accounts detection 1.0\n**Typed Message:**\n{message.content}",
                color=discord.Color.from_rgb(200, 70, 70)
            )
            await log_channel.send(embed=embed)
        
        try:
            embed = discord.Embed(
                title="Banned",
                description="You have been **banned** from **HollyScriptX**",
                color=discord.Color.from_rgb(200, 70, 70)
            )
            embed.add_field(name="Moderator", value="Auto-Mod", inline=False)
            embed.add_field(name="Reason", value="Auto-ban. Typed in do not type channel (prob hacked account).", inline=False)
            embed.add_field(name="Duration", value="Permanent", inline=False)
            embed.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
            await member.send(embed=embed)
        except:
            pass
        
        await member.ban(reason="Auto-ban. Typed in do not type channel (prob hacked account).")
    except Exception as e:
        print(f'Auto ban error: {e}')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            description="Command not found. Use `+help` for the list of commands.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRole):
        if has_command_permission(ctx):
            await ctx.reinvoke()
        else:
            embed = discord.Embed(
                description="You don't have permission to use this command.",
                color=discord.Color.from_rgb(255, 200, 0)
            )
            await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingAnyRole):
        if has_command_permission(ctx):
            await ctx.reinvoke()
        else:
            embed = discord.Embed(
                description="You don't have permission to use this command.",
                color=discord.Color.from_rgb(255, 200, 0)
            )
            await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = discord.Embed(
            description="User not found. Make sure to mention the user or use a correct ID.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            description=f"Invalid argument: {error}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
    else:
        print(f"Error: {error}")
        print(traceback.format_exc())
        embed = discord.Embed(
            description=f"An error occurred: {error}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)

# ---- КОМАНДЫ ----

@bot.hybrid_command(name="warn", description="Warn a user")
@app_commands.describe(member="The member to warn", reason="Reason for the warning")
@commands.has_any_role(*WARN_ROLES)
async def warn(ctx, member: discord.Member = None, *, reason: str = "No reason provided"):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    
    if member is None:
        embed = discord.Embed(
            description="**Usage**\n`+warn <@Member | ID> [reason]`\n\nMember parameter may be replaced with the author of the replied message.\n\n**Examples**\n`+warn @Member` — empty warning\n`+warn @Member behaves provocatively` — warning with reason",
            color=discord.Color.from_rgb(240, 240, 240)
        )
        await ctx.send(embed=embed)
        return
    
    await warn_user(member, reason, ctx.author.mention, ctx)
    record_mod_action(ctx.author.id, "warned")
    await log_staff_action(ctx, "warn", f"Warned {member.mention} for: {reason}")

@bot.hybrid_command(name="warn-remove", description="Remove a warning by its code", aliases=["warnremove"])
@app_commands.describe(code="The 4-digit warning code")
@commands.has_any_role(*WARN_REMOVE_ROLES)
async def warn_remove(ctx, code: str = None):
    if code is None:
        embed = discord.Embed(
            description="**Usage:** `+warn-remove <code>`\n**Example:** `+warn-remove 1234`",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    found_user = None
    found_warn = None
    
    for user_id, warns in warnings.items():
        for warn in warns:
            if warn['code'] == code:
                found_user = user_id
                found_warn = warn
                break
        if found_user:
            break
    
    if not found_user:
        embed = discord.Embed(
            description=f"Warning code `{code}` not found.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    if found_user == ctx.author.id:
        embed = discord.Embed(
            description="You cannot remove your own warning.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    member = ctx.guild.get_member(found_user)
    if member is None:
        member = await bot.fetch_user(found_user)
    
    warnings[found_user].remove(found_warn)
    user_warnings[found_user] = max(0, user_warnings[found_user] - 1)
    save_warnings()
    
    mention = member.mention if hasattr(member, 'mention') else f'<@{found_user}>'
    embed = discord.Embed(
        description=f"Removed warning `{code}` from {mention}",
        color=discord.Color.from_rgb(100, 200, 120)
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(name="warns", description="Show warnings of a user", aliases=["warns-list", "warnlist"])
@app_commands.describe(member="The member whose warnings to show")
@commands.has_any_role(*WARN_LIST_ROLES)
async def warns(ctx, member: discord.Member = None):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author

    if member is None:
        member = ctx.author
    
    if member.id not in warnings or not warnings[member.id]:
        embed = discord.Embed(
            description=f"{member.mention} has no warnings.",
            color=discord.Color.from_rgb(180, 180, 180)
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title=f"Warnings — {member.display_name}",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    
    for i, warn in enumerate(warnings[member.id], 1):
        embed.add_field(
            name=f"{i}. `{warn['code']}`",
            value=f"**Reason:** {warn['reason']}\n**Moderator:** {warn['moderator']}\n**Date:** {warn['date']}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.hybrid_command(name="jail", description="Jail a user")
@app_commands.describe(member="The member to jail", reason="Reason for jailing")
@commands.has_any_role(*JAIL_ROLES)
async def jail(ctx, member: discord.Member = None, *, reason: str = "No reason provided"):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        await ctx.send("**Usage:** `+jail @user [reason]`")
        return
    
    can_punish_result, error_msg = can_punish(ctx.author, member)
    if not can_punish_result:
        embed = discord.Embed(description=error_msg, color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    can_use, remaining = check_cooldown(ctx.author.id, 'jail', JAIL_LIMIT, TIME_WINDOW, COOLDOWN_JAIL)
    if not can_use:
        embed = discord.Embed(
            description=f"You have reached the jail limit ({JAIL_LIMIT} in 5 minutes). Please wait {format_time(remaining)}.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    record_usage(ctx.author.id, 'jail')
    
    if len(jail_usage[ctx.author.id]) >= JAIL_LIMIT:
        add_cooldown(ctx.author.id, 'jail', COOLDOWN_JAIL)
    
    jail_role = ctx.guild.get_role(JAIL_ROLE_ID)
    if not jail_role:
        await ctx.send("Jail role not found.")
        return
    
    user_roles_backup[member.id] = [role.id for role in member.roles if role.id != JAIL_ROLE_ID]
    
    for role in member.roles:
        if role.id != JAIL_ROLE_ID:
            try:
                await member.remove_roles(role)
            except:
                pass
    
    try:
        await member.add_roles(jail_role)
    except:
        pass
    
    embed = discord.Embed(
        title="Jailed",
        description="You have been jailed in **HollyScriptX**",
        color=discord.Color.from_rgb(200, 70, 70)
    )
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Duration", value="Indefinite", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"If you would like to dispute this punishment, contact a staff member. • {datetime.now().strftime('%m/%d/%Y %I:%M %p')}")
    
    try:
        await member.send(embed=embed)
    except:
        pass
    
    embed_channel = discord.Embed(
        description=f"{member.mention} has been jailed.\n\n**Reason:** {reason}",
        color=discord.Color.from_rgb(200, 70, 70)
    )
    await ctx.send(embed=embed_channel)
    
    record_mod_action(ctx.author.id, "jailed")
    await log_staff_action(ctx, "jail", f"Jailed {member.mention} for: {reason}")

@bot.hybrid_command(name="unjail", description="Unjail a user")
@app_commands.describe(member="The member to unjail")
@commands.has_any_role(*JAIL_ROLES)
async def unjail(ctx, member: discord.Member = None):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        await ctx.send("**Usage:** `+unjail @user`")
        return
    
    jail_role = ctx.guild.get_role(JAIL_ROLE_ID)
    if jail_role:
        try:
            await member.remove_roles(jail_role)
        except:
            pass
    
    if member.id in user_roles_backup:
        for role_id in user_roles_backup[member.id]:
            role = ctx.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role)
                except:
                    pass
        del user_roles_backup[member.id]
    
    # DM to user
    try:
        embed_dm = discord.Embed(
            title="Unjailed",
            description="You have been unjailed in **HollyScriptX**",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        embed_dm.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed_dm.add_field(name="Reason", value="Jail time manually ended early by staff", inline=True)
        embed_dm.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
        await member.send(embed=embed_dm)
    except:
        pass
    
    embed = discord.Embed(
        description=f"{member.mention} has been unjailed.",
        color=discord.Color.from_rgb(100, 200, 120)
    )
    await ctx.send(embed=embed)
    
    record_mod_action(ctx.author.id, "unjailed")
    await log_staff_action(ctx, "unjail", f"Unjailed {member.mention}")

@bot.hybrid_command(name="kick", description="Kick a user")
@app_commands.describe(member="The member to kick", reason="Reason for the kick")
@commands.has_any_role(*COMMAND_ROLES)
async def kick(ctx, member: discord.Member = None, *, reason: str = "No reason provided"):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        await ctx.send("**Usage:** `+kick @user [reason]` or reply to a message with `+kick`")
        return
    
    can_punish_result, error_msg = can_punish(ctx.author, member)
    if not can_punish_result:
        embed = discord.Embed(description=error_msg, color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(
            description=f"{member.mention} has been kicked.\n\n**Reason:** {reason}",
            color=discord.Color.from_rgb(200, 70, 70)
        )
        await ctx.send(embed=embed)
        
        record_mod_action(ctx.author.id, "kicked")
        await log_staff_action(ctx, "kick", f"Kicked {member.mention} for: {reason}")
    except discord.Forbidden:
        await ctx.send("I do not have permission to kick this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error kicking user: {e}")

@bot.hybrid_command(name="ban", description="Ban a user permanently")
@app_commands.describe(member="The member to ban", reason="Reason for the ban")
@commands.has_any_role(*COMMAND_ROLES)
async def ban(ctx, member: discord.Member = None, *, reason: str = "No Reason Provided"):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        embed = discord.Embed(
            title="Command: ban",
            description="Bans the mentioned user",
            color=discord.Color.from_rgb(60, 60, 70)
        )
        embed.add_field(
            name="Syntax",
            value="`+ban (user) [reason]`\n**Example:** `+ban @user Threatening members`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    can_punish_result, error_msg = can_punish(ctx.author, member)
    if not can_punish_result:
        embed = discord.Embed(description=error_msg, color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    can_use, remaining = check_cooldown(ctx.author.id, 'ban', BAN_LIMIT, TIME_WINDOW, COOLDOWN_BAN)
    if not can_use:
        embed = discord.Embed(
            description=f"You have reached the ban limit ({BAN_LIMIT} in 5 minutes). Please wait {format_time(remaining)}.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    record_usage(ctx.author.id, 'ban')
    
    if len(ban_usage[ctx.author.id]) >= BAN_LIMIT:
        add_cooldown(ctx.author.id, 'ban', COOLDOWN_BAN)
    
    try:
        await member.ban(reason=reason)
        
        embed = discord.Embed(
            title="Banned",
            description="You have been **banned** from **HollyScriptX**",
            color=discord.Color.from_rgb(200, 70, 70)
        )
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Duration", value="Permanent", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
        
        try:
            await member.send(embed=embed)
        except:
            pass
        
        embed_channel = discord.Embed(
            description=f"{member.mention} has been banned.\n\n**Reason:** {reason}",
            color=discord.Color.from_rgb(200, 70, 70)
        )
        await ctx.send(embed=embed_channel)
        
        record_mod_action(ctx.author.id, "banned")
        await log_staff_action(ctx, "ban", f"Banned {member.mention} for: {reason}")
    except discord.Forbidden:
        await ctx.send("I do not have permission to ban this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error banning user: {e}")

@bot.hybrid_command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_input="User ID or username to unban")
@commands.has_any_role(*COMMAND_ROLES)
async def unban(ctx, *, user_input: str):
    try:
        user_id = int(user_input)
        user = await bot.fetch_user(user_id)
    except:
        if ctx.message and ctx.message.reference:
            referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            user = referenced.author
        else:
            try:
                user = await commands.UserConverter().convert(ctx, user_input)
            except:
                await ctx.send("**Usage:** `+unban <user_id/username>` or reply to a message with `+unban`")
                return
    
    try:
        await ctx.guild.unban(user)
        embed = discord.Embed(
            description=f"{user.mention} has been unbanned.",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
        
        record_mod_action(ctx.author.id, "unbanned")
        await log_staff_action(ctx, "unban", f"Unbanned {user.mention}")
    except discord.NotFound:
        await ctx.send("User is not banned or not found.")
    except discord.Forbidden:
        await ctx.send("I do not have permission to unban this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error unbanning user: {e}")

@bot.hybrid_command(name="mute", description="Timeout (mute) a user")
@app_commands.describe(member="The member to mute", duration="Duration (1h, 2h, 1d, 2d, 1w, 2w)", reason="Reason for the mute")
@commands.has_any_role(*COMMAND_ROLES)
async def mute(ctx, member: discord.Member = None, duration: str = None, *, reason: str = "Reason not specified"):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        await ctx.send("**Usage:** `+mute @user [duration] [reason]`\n**Example:** `+mute @user 1h Spamming`\n**Durations:** 1h, 2h, 1d, 2d, 1w, 2w")
        return
    
    can_punish_result, error_msg = can_punish(ctx.author, member)
    if not can_punish_result:
        embed = discord.Embed(description=error_msg, color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if duration is None:
        duration = "1h"
    
    duration_map = {
        '1h': 1, '2h': 2, '3h': 3, '4h': 4, '6h': 6, '8h': 8, '12h': 12,
        '1d': 24, '2d': 48, '3d': 72, '4d': 96, '5d': 120, '6d': 144, '1w': 168, '2w': 336
    }
    
    duration_lower = duration.lower()
    if duration_lower not in duration_map:
        await ctx.send("Invalid duration. Use: 1h, 2h, 1d, 2d, 1w, 2w")
        return
    
    hours = duration_map[duration_lower]
    if hours > 336:
        await ctx.send("Maximum mute duration is 2 weeks.")
        return
    
    can_use, remaining = check_cooldown(ctx.author.id, 'mute', MUTE_LIMIT, TIME_WINDOW, COOLDOWN_MUTE)
    if not can_use:
        embed = discord.Embed(
            description=f"You have reached the mute limit ({MUTE_LIMIT} in 5 minutes). Please wait {format_time(remaining)}.",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    record_usage(ctx.author.id, 'mute')
    
    if len(mute_usage[ctx.author.id]) >= MUTE_LIMIT:
        add_cooldown(ctx.author.id, 'mute', COOLDOWN_MUTE)
    
    try:
        timeout = discord.utils.utcnow() + timedelta(hours=hours)
        await member.timeout(timeout, reason=reason)
        
        embed = discord.Embed(
            title="Muted",
            description="You have been **muted** in **HollyScriptX**",
            color=discord.Color.from_rgb(255, 170, 50)
        )
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
        
        try:
            await member.send(embed=embed)
        except:
            pass
        
        embed_channel = discord.Embed(
            description=f"{member.mention} has been muted for **{duration}**.\n\n**Reason:** {reason}",
            color=discord.Color.from_rgb(255, 170, 50)
        )
        await ctx.send(embed=embed_channel)
        
        record_mod_action(ctx.author.id, "timed_out")
        await log_staff_action(ctx, "mute", f"Muted {member.mention} for {duration}: {reason}")
    except discord.Forbidden:
        await ctx.send("I do not have permission to mute this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error muting user: {e}")

@bot.hybrid_command(name="unmute", description="Remove timeout from a user")
@app_commands.describe(member="The member to unmute")
@commands.has_any_role(*COMMAND_ROLES)
async def unmute(ctx, member: discord.Member = None):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        await ctx.send("**Usage:** `+unmute @user` or reply to a message with `+unmute`")
        return
    
    try:
        await member.remove_timeout()
        embed = discord.Embed(
            description=f"{member.mention} has been unmuted.",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
        
        record_mod_action(ctx.author.id, "unmuted")
        await log_staff_action(ctx, "unmute", f"Unmuted {member.mention}")
    except discord.Forbidden:
        await ctx.send("I do not have permission to unmute this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error unmuting user: {e}")

@bot.hybrid_command(name="afk", description="Set your AFK status")
@app_commands.describe(reason="Reason for being AFK")
async def afk(ctx, *, reason: str = "No reason provided"):
    afk_users[ctx.author.id] = {
        'reason': reason,
        'time': time.time()
    }
    embed = discord.Embed(
        description=f"{ctx.author.mention}, your status is now **AFK**.\n\n**Reason:** {reason}",
        color=discord.Color.from_rgb(100, 200, 120)
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(name="giverole", description="Give a role to a user (reply to their message)")
@app_commands.describe(role_name="Name of the role to give")
@commands.has_any_role(*COMMAND_ROLES)
async def giverole(ctx, role_name: str = None):
    if not ctx.message or not ctx.message.reference:
        embed = discord.Embed(
            description=f"**Usage:** Reply to a message with `+giverole <role_name>`\n**Example:** `+giverole support`\n\n**Available roles:** {', '.join(role_map.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    if role_name is None:
        embed = discord.Embed(
            description=f"**Usage:** `+giverole <role_name>`\n**Available roles:** {', '.join(role_map.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    try:
        referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced_msg.author
    except:
        embed = discord.Embed(description="Could not find the user you replied to.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if member.id == ctx.author.id:
        embed = discord.Embed(description="You cannot give roles to yourself.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if has_immunity(member):
        embed = discord.Embed(description=f"{member.mention} has immunity from role changes.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    role_name_lower = role_name.lower()
    if role_name_lower not in role_map:
        embed = discord.Embed(
            description=f"Role `{role_name}` not found.\n**Available:** {', '.join(role_map.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    role_id = role_map[role_name_lower]
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"Role `{role_name}` not found on this server.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if role.position >= ctx.guild.me.top_role.position:
        embed = discord.Embed(description="I cannot give this role because it is above my highest role.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if role.position >= ctx.author.top_role.position:
        embed = discord.Embed(description="You cannot give this role because it is above your highest role.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    try:
        await member.add_roles(role, reason=f"Given by {ctx.author}")
        embed = discord.Embed(
            description=f"Added role {role.mention} to {member.mention}",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(description="I do not have permission to give this role.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
    except discord.HTTPException as e:
        embed = discord.Embed(description=f"Error giving role: {e}", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)

@bot.hybrid_command(name="delrole", description="Remove a role from a user (reply to their message)")
@app_commands.describe(role_name="Name of the role to remove")
@commands.has_any_role(*COMMAND_ROLES)
async def delrole(ctx, role_name: str = None):
    if not ctx.message or not ctx.message.reference:
        embed = discord.Embed(
            description=f"**Usage:** Reply to a message with `+delrole <role_name>`\n**Example:** `+delrole support`\n\n**Available roles:** {', '.join(role_map.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    if role_name is None:
        embed = discord.Embed(
            description=f"**Usage:** `+delrole <role_name>`\n**Available roles:** {', '.join(role_map.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    try:
        referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced_msg.author
    except:
        embed = discord.Embed(description="Could not find the user you replied to.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if has_immunity(member):
        embed = discord.Embed(description=f"{member.mention} has immunity from role changes.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    role_name_lower = role_name.lower()
    if role_name_lower not in role_map:
        embed = discord.Embed(
            description=f"Role `{role_name}` not found.\n**Available:** {', '.join(role_map.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    role_id = role_map[role_name_lower]
    role = ctx.guild.get_role(role_id)
    if not role:
        embed = discord.Embed(description=f"Role `{role_name}` not found on this server.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if role.position >= ctx.guild.me.top_role.position:
        embed = discord.Embed(description="I cannot remove this role because it is above my highest role.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if role.position >= ctx.author.top_role.position:
        embed = discord.Embed(description="You cannot remove this role because it is above your highest role.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    try:
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        embed = discord.Embed(
            description=f"Removed role {role.mention} from {member.mention}",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(description="I do not have permission to remove this role.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
    except discord.HTTPException as e:
        embed = discord.Embed(description=f"Error removing role: {e}", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)

@bot.hybrid_command(name="lockchat", description="Lock the current channel (disable messaging for everyone)")
@commands.has_any_role(SENIOR_MOD_ROLE_ID, *COMMAND_ROLES)
async def lockchat(ctx):
    channel = ctx.channel
    try:
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        
        embed = discord.Embed(
            description=f"Channel {channel.mention} has been **locked**.\nMembers can no longer send messages here.",
            color=discord.Color.from_rgb(200, 70, 70)
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(description=f"Failed to lock channel: {e}", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)

@bot.hybrid_command(name="unlockchat", description="Unlock the current channel")
@commands.has_any_role(SENIOR_MOD_ROLE_ID, *COMMAND_ROLES)
async def unlockchat(ctx):
    channel = ctx.channel
    try:
        await channel.set_permissions(ctx.guild.default_role, overwrite=None)
        
        embed = discord.Embed(
            description=f"Channel {channel.mention} has been **unlocked**.\nMembers can send messages again.",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(description=f"Failed to unlock channel: {e}", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)

@bot.hybrid_command(name="lockchats", description="Lock all configured text and voice channels")
@commands.has_any_role(SENIOR_MOD_ROLE_ID, *COMMAND_ROLES)
async def lockchats(ctx):
    guild = ctx.guild
    locked_channels = []
    
    for channel_id in CHANNELS_TO_LOCK:
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                locked_channels.append(channel.mention)
            except:
                pass
    
    for channel_id in VOICE_CHANNELS_TO_LOCK:
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.connect = False
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                locked_channels.append(channel.mention)
            except:
                pass
    
    if locked_channels:
        embed = discord.Embed(
            description=f"**Locked {len(locked_channels)} channels**\n\n" + ", ".join(locked_channels[:8]) + (f" and {len(locked_channels)-8} more" if len(locked_channels) > 8 else ""),
            color=discord.Color.from_rgb(200, 70, 70)
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("No channels found to lock.")

@bot.hybrid_command(name="unlockchats", description="Unlock all configured text and voice channels")
@commands.has_any_role(SENIOR_MOD_ROLE_ID, *COMMAND_ROLES)
async def unlockchats(ctx):
    guild = ctx.guild
    unlocked_channels = []
    
    for channel_id in CHANNELS_TO_LOCK:
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.set_permissions(guild.default_role, overwrite=None)
                unlocked_channels.append(channel.mention)
            except:
                pass
    
    for channel_id in VOICE_CHANNELS_TO_LOCK:
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.set_permissions(guild.default_role, overwrite=None)
                unlocked_channels.append(channel.mention)
            except:
                pass
    
    if unlocked_channels:
        embed = discord.Embed(
            description=f"**Unlocked {len(unlocked_channels)} channels**\n\n" + ", ".join(unlocked_channels[:8]) + (f" and {len(unlocked_channels)-8} more" if len(unlocked_channels) > 8 else ""),
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("No channels found to unlock.")

@bot.hybrid_command(name="showstafflist", description="Show the list of staff members")
async def showstafflist(ctx):
    guild = ctx.guild
    staff_members = {}
    
    for role_id in STAFF_ROLES:
        role = guild.get_role(role_id)
        if role:
            members = [member for member in guild.members if role in member.roles]
            staff_members[role.name] = members
    
    embed = discord.Embed(
        title="Staff List",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    
    for role_name, members in staff_members.items():
        if members:
            embed.add_field(
                name=role_name,
                value="\n".join([f"{member.mention}" for member in members]) or "None",
                inline=False
            )
        else:
            embed.add_field(name=role_name, value="None", inline=False)
    
    await ctx.send(embed=embed)

@bot.hybrid_command(name="moderatorsinfo", description="Show staff permissions guide")
async def moderatorsinfo(ctx):
    embed = discord.Embed(
        title="Staff Permissions Guide",
        description="""**<@&1516192523691884816> Co-Owner**
Full server control

**<@&1508790828448092211> Manager**
• +giverole (max: **support**)
• All commands below

**<@&1504502978374139977> Senior Mod**
• +giverole / +delrole (max: **support**)
• +lockchat / +lockchats
• Access to audit logs

**<@&1504503217382232166> Mod**
• +giverole / +delrole (max: **support**)
• All commands below

**<@&1508782838600830996> Support**
• +ban, +unban
• +kick
• +mute, +unmute
• +jail, +unjail
• +warn, +warn-remove, +warns
• Access to audit logs

────────────────
**Commands**
`+warn @user [reason]` — Warn a user (5 warns = auto ban)
`+warn-remove <code>` — Remove a warning by code
`+warns @user` — Show user's warnings
`+ban @user [reason]` — Ban permanently
`+unban user_id` — Unban a user
`+kick @user [reason]` — Kick a user
`+jail @user [reason]` — Jail a user
`+unjail @user` — Unjail a user
`+mute @user [duration] [reason]` — Mute (1h, 2h, 1d, 2d, 1w, 2w)
`+unmute @user` — Unmute a user
`+lockchat` — Lock current channel
`+unlockchat` — Unlock current channel""",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(name="invite", description="Get the server invite link")
async def invite(ctx):
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Join Discord", url=INVITE_LINK))
    await ctx.send("Join our Discord!", view=view)

@bot.hybrid_command(name="say", description="Make the bot say something")
@app_commands.describe(message="The message to send")
async def say(ctx, *, message: str):
    try:
        if ctx.message:
            await ctx.message.delete()
    except:
        pass
    await ctx.send(message)

@bot.hybrid_command(name="translate", description="Translate a replied message")
@app_commands.describe(language="Target language code (en, ru, es, fr, de, etc.)")
async def translate_cmd(ctx, language: str = None):
    if language is None:
        embed = discord.Embed(
            title="Translate Command",
            description="Translates the message you reply to.",
            color=discord.Color.from_rgb(100, 180, 255)
        )
        embed.add_field(
            name="Usage",
            value="`+translate <language>`\nExample: `+translate ru`",
            inline=False
        )
        embed.add_field(
            name="Supported Languages",
            value="en, ru, es, fr, de, it, pt, ja, ko, zh, ar, hi, nl, pl, uk",
            inline=False
        )
        embed.add_field(
            name="Tip",
            value="Reply to a message and use `+translate` to translate it.",
            inline=False
        )
        embed.set_footer(text="HollyScriptX")
        await ctx.send(embed=embed)
        return
    
    if not ctx.message or not ctx.message.reference:
        embed = discord.Embed(
            description="You must reply to a message to translate it.\n**Usage:** `+translate <language>`",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    try:
        referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    except:
        embed = discord.Embed(description="Could not find the message you replied to.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    if not referenced_msg.content:
        embed = discord.Embed(description="The message you replied to has no text to translate.", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    supported_languages = {
        'en': 'English', 'ru': 'Russian', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi',
        'nl': 'Dutch', 'pl': 'Polish', 'uk': 'Ukrainian'
    }
    
    target_lang = language.lower()
    if target_lang not in supported_languages:
        embed = discord.Embed(
            description=f"Unsupported language: `{language}`\nSupported: {', '.join(supported_languages.keys())}",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    thinking_msg = await ctx.send("Translating...")
    
    try:
        text = referenced_msg.content
        
        async with aiohttp.ClientSession() as session:
            detect_url = "https://libretranslate.com/detect"
            detect_data = {"q": text}
            
            async with session.post(detect_url, json=detect_data) as resp:
                if resp.status == 200:
                    detect_result = await resp.json()
                    source_lang = detect_result[0]['language'] if detect_result else 'en'
                else:
                    source_lang = 'en'
            
            translate_url = "https://libretranslate.com/translate"
            translate_data = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
                "format": "text"
            }
            
            async with session.post(translate_url, json=translate_data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    translated_text = result['translatedText']
                    
                    embed = discord.Embed(
                        title=f"Translation  {supported_languages.get(source_lang, source_lang)} → {supported_languages[target_lang]}",
                        color=discord.Color.from_rgb(100, 180, 255)
                    )
                    embed.add_field(
                        name=f"Original ({supported_languages.get(source_lang, source_lang)})",
                        value=text[:1024] if len(text) <= 1024 else text[:1021] + "...",
                        inline=False
                    )
                    embed.add_field(
                        name=f"Translated ({supported_languages[target_lang]})",
                        value=translated_text[:1024] if len(translated_text) <= 1024 else translated_text[:1021] + "...",
                        inline=False
                    )
                    embed.set_footer(text=f"Requested by {ctx.author.display_name}  •  HollyScriptX")
                    
                    await thinking_msg.delete()
                    await ctx.send(embed=embed)
                    return
                
                # Fallback
                try:
                    fallback_url = "https://api.mymemory.translated.net/get"
                    params = {"q": text, "langpair": f"{source_lang}|{target_lang}"}
                    
                    async with session.get(fallback_url, params=params) as resp2:
                        if resp2.status == 200:
                            result2 = await resp2.json()
                            if 'responseData' in result2 and 'translatedText' in result2['responseData']:
                                translated_text = result2['responseData']['translatedText']
                                
                                embed = discord.Embed(
                                    title=f"Translation  {supported_languages.get(source_lang, source_lang)} → {supported_languages[target_lang]}",
                                    color=discord.Color.from_rgb(100, 180, 255)
                                )
                                embed.add_field(
                                    name=f"Original ({supported_languages.get(source_lang, source_lang)})",
                                    value=text[:1024] if len(text) <= 1024 else text[:1021] + "...",
                                    inline=False
                                )
                                embed.add_field(
                                    name=f"Translated ({supported_languages[target_lang]})",
                                    value=translated_text[:1024] if len(translated_text) <= 1024 else translated_text[:1021] + "...",
                                    inline=False
                                )
                                embed.set_footer(text=f"Requested by {ctx.author.display_name}  •  HollyScriptX")
                                
                                await thinking_msg.delete()
                                await ctx.send(embed=embed)
                                return
                except:
                    pass
                
                await thinking_msg.delete()
                embed = discord.Embed(description="Failed to translate message. Please try again later.", color=discord.Color.from_rgb(255, 200, 0))
                await ctx.send(embed=embed)
                    
    except Exception as e:
        await thinking_msg.delete()
        embed = discord.Embed(description=f"Translation error: {str(e)[:100]}", color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)

@bot.hybrid_command(name="translatehelp", description="Help for the translate command", aliases=["translations", "tlhelp"])
async def translate_help(ctx):
    embed = discord.Embed(
        title="Translation Help",
        description="Command to translate user messages.",
        color=discord.Color.from_rgb(100, 180, 255)
    )
    embed.add_field(
        name="How to use",
        value="1. Find the message you want to translate\n2. Reply to it\n3. Type `+translate <language>`\n\nExample: `+translate ru`",
        inline=False
    )
    embed.add_field(
        name="Supported languages",
        value="`en` English · `ru` Russian · `es` Spanish · `fr` French · `de` German · `it` Italian · `pt` Portuguese · `ja` Japanese · `ko` Korean · `zh` Chinese · `ar` Arabic · `hi` Hindi · `nl` Dutch · `pl` Polish · `uk` Ukrainian",
        inline=False
    )
    embed.set_footer(text="HollyScriptX  •  Free translation API")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="help", description="Show bot commands", aliases=["help_commands"])
async def help_commands(ctx):
    embed1 = discord.Embed(
        title="Bot Commands (1/3)",
        description="Moderation & utility commands",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    embed1.add_field(name="+warn @user [reason]", value="Warn a user", inline=False)
    embed1.add_field(name="+warn-remove <code>", value="Remove a warning by code", inline=False)
    embed1.add_field(name="+warns @user", value="Show user's warnings", inline=False)
    embed1.add_field(name="+ban @user [reason]", value="Ban a user permanently", inline=False)
    embed1.add_field(name="+unban <user_id>", value="Unban a user", inline=False)
    embed1.add_field(name="+kick @user [reason]", value="Kick a user", inline=False)
    embed1.add_field(name="+mute @user [duration] [reason]", value="Mute a user (1h, 2h, 1d, 2d, 1w, 2w)", inline=False)
    embed1.add_field(name="+unmute @user", value="Unmute a user", inline=False)
    embed1.add_field(name="+jail @user [reason]", value="Jail a user", inline=False)
    embed1.add_field(name="+unjail @user", value="Unjail a user", inline=False)
    
    embed2 = discord.Embed(
        title="Bot Commands (2/3)",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    embed2.add_field(name="+lockchat", value="Lock the current channel", inline=False)
    embed2.add_field(name="+unlockchat", value="Unlock the current channel", inline=False)
    embed2.add_field(name="+lockchats", value="Lock all configured channels", inline=False)
    embed2.add_field(name="+unlockchats", value="Unlock all configured channels", inline=False)
    embed2.add_field(name="+giverole <role>", value="Give a role (reply to message)", inline=False)
    embed2.add_field(name="+delrole <role>", value="Remove a role (reply to message)", inline=False)
    embed2.add_field(name="+afk [reason]", value="Set AFK status", inline=False)
    embed2.add_field(name="+say <message>", value="Make the bot say something", inline=False)
    embed2.add_field(name="+translate <lang>", value="Translate a replied message", inline=False)
    embed2.add_field(name="+invite", value="Get server invite", inline=False)
    embed2.add_field(name="+scriptguide", value="Send ink game script guide (reply)", inline=False)
    embed2.add_field(name="+statistics [@user]", value="Show moderation statistics", inline=False)
    embed2.add_field(name="+purge <amount>", value="Delete messages (alias +clear)", inline=False)
    
    embed3 = discord.Embed(
        title="Bot Commands (3/3)",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    embed3.add_field(name="+showstafflist", value="Show all staff members", inline=False)
    embed3.add_field(name="+moderatorsinfo", value="Show staff permissions", inline=False)
    embed3.add_field(name="+help", value="Show this help message", inline=False)
    embed3.add_field(name="Available Roles", value=", ".join(role_map.keys()), inline=False)
    embed3.set_footer(text="Most commands also work as slash commands (/)")
    
    await ctx.send(embed=embed1)
    await ctx.send(embed=embed2)
    await ctx.send(embed=embed3)

@bot.hybrid_command(name="scriptguide", description="Send ink game script guide to a replied user")
@commands.has_any_role(*COMMAND_ROLES)
async def scriptguide(ctx):
    if not ctx.message or not ctx.message.reference:
        embed = discord.Embed(
            description="You must reply to a message to use this command.\n**Usage:** Reply to a user and type `+scriptguide`",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    
    try:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        target = referenced.author
    except:
        await ctx.send("Could not find the message you replied to.")
        return
    
    global case_counter
    case_counter += 1
    case_num = case_counter
    
    text = f"""Case #{case_num} {target.mention} "How to get ink game script" first join at channel <#1513695025836593243> and complete keysystem, after you done copy your key and press "Redeem Key" and paste your key, and after this press "Get Script" and you get your script with key so you dont need to put key in loader everytime
Make sure u **NOT** using xeno, solara or other bad executors. They can be unsupported with our script, also read <#1526840056898125904>"""
    
    await ctx.send(text)
    await log_staff_action(ctx, "scriptguide", f"Sent script guide to {target.mention}")

@bot.hybrid_command(name="statistics", description="Show moderation statistics for a user", aliases=["statisctics", "stats", "modstats"])
@app_commands.describe(member="The staff member to show stats for")
@commands.has_any_role(*COMMAND_ROLES)
async def statistics(ctx, member: discord.Member = None):
    if member is None and ctx.message and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        member = ctx.author
    
    now = time.time()
    day7 = now - 7 * 86400
    day14 = now - 14 * 86400
    
    actions = mod_stats.get(member.id, {})
    
    def count_since(action_list, since):
        return sum(1 for t in action_list if t >= since)
    
    warned_7 = count_since(actions.get("warned", []), day7)
    warned_14 = count_since(actions.get("warned", []), day14)
    warned_all = len(actions.get("warned", []))
    
    kicked_7 = count_since(actions.get("kicked", []), day7)
    kicked_14 = count_since(actions.get("kicked", []), day14)
    kicked_all = len(actions.get("kicked", []))
    
    banned_7 = count_since(actions.get("banned", []), day7)
    banned_14 = count_since(actions.get("banned", []), day14)
    banned_all = len(actions.get("banned", []))
    
    unbanned_7 = count_since(actions.get("unbanned", []), day7)
    unbanned_14 = count_since(actions.get("unbanned", []), day14)
    unbanned_all = len(actions.get("unbanned", []))
    
    timed_7 = count_since(actions.get("timed_out", []), day7)
    timed_14 = count_since(actions.get("timed_out", []), day14)
    timed_all = len(actions.get("timed_out", []))
    
    jailed_7 = count_since(actions.get("jailed", []), day7)
    jailed_14 = count_since(actions.get("jailed", []), day14)
    jailed_all = len(actions.get("jailed", []))
    
    embed = discord.Embed(
        title=f"Moderation Statistics for {member.display_name}",
        color=discord.Color.from_rgb(60, 60, 70)
    )
    
    embed.add_field(
        name="7 days",
        value=f"Warned: {warned_7}\nKicked: {kicked_7}\nBanned: {banned_7}\nUnbanned: {unbanned_7}\nTimed Out: {timed_7}\nJailed: {jailed_7}",
        inline=True
    )
    embed.add_field(
        name="14 days",
        value=f"Warned: {warned_14}\nKicked: {kicked_14}\nBanned: {banned_14}\nUnbanned: {unbanned_14}\nTimed Out: {timed_14}\nJailed: {jailed_14}",
        inline=True
    )
    embed.add_field(
        name="All time",
        value=f"Warned: {warned_all}\nKicked: {kicked_all}\nBanned: {banned_all}\nUnbanned: {unbanned_all}\nTimed Out: {timed_all}\nJailed: {jailed_all}",
        inline=True
    )
    
    embed.set_footer(text="HollyScriptX")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="purge", description="Delete messages in the channel", aliases=["clear"])
@app_commands.describe(amount="Number of messages to delete (max 1000)")
@commands.has_any_role(*ADMIN_ROLES)
async def purge(ctx, amount: int = None):
    if amount is None:
        embed = discord.Embed(
            description="**Usage:** `+purge <amount>`\n**Example:** `+purge 50`",
            color=discord.Color.from_rgb(255, 200, 0)
        )
        await ctx.send(embed=embed)
        return
    if amount <= 0:
        await ctx.send("Please specify a positive number.")
        return
    if amount > 1000:
        await ctx.send("Cannot delete more than 1000 messages at once.")
        return
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"Deleted {len(deleted) - 1} messages")
        await msg.delete(delay=3)
        await log_staff_action(ctx, "purge", f"Purged {len(deleted) - 1} messages in {ctx.channel.mention}")
    except Exception as e:
        await ctx.send(f"Error: {e}")

# ========== ADMIN ONLY (prefix only, no slash) ==========

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def rename(ctx, *, name: str):
    try:
        await ctx.guild.edit(name=name)
        embed = discord.Embed(description=f"Server renamed to: **{name}**", color=discord.Color.from_rgb(100, 200, 120))
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error renaming server: {e}")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def createnewsupportedgame(ctx, *, name: str):
    category = ctx.guild.get_channel(GAME_CATEGORY_ID)
    if not category:
        category = ctx.channel.category
    
    try:
        channel = await ctx.guild.create_voice_channel(f"{name}: 🔵", category=category)
        embed = discord.Embed(description=f"Created voice channel: {channel.mention}", color=discord.Color.from_rgb(100, 200, 120))
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error creating channel: {e}")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def ticketscreate(ctx):
    embed = discord.Embed(description="Press the button below to create your ticket.", color=discord.Color.from_rgb(240, 240, 240))
    await ctx.send(embed=embed, view=TicketView())

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def down(ctx, game: str = None):
    if game is None:
        await ctx.send("**Usage:** `+down (InkGame / MurderMystery2 / Doors / ALL)`")
        return
    
    if game.lower() == "all":
        await down(ctx, "InkGame")
        await down(ctx, "MurderMystery2")
        await down(ctx, "Doors")
        return
    
    channel_map = {
        "inkgame": {"id": 1513692263010799716, "name": "Ink Game: 🔴"},
        "murder mystery 2": {"id": 1513692362931703818, "name": "Murder Mystery 2: 🔴"},
        "murder mystery2": {"id": 1513692362931703818, "name": "Murder Mystery 2: 🔴"},
        "murder": {"id": 1513692362931703818, "name": "Murder Mystery 2: 🔴"},
        "doors": {"id": 1513692441281036348, "name": "Doors: 🔴"}
    }
    
    game_lower = game.lower()
    if game_lower not in channel_map:
        await ctx.send("Invalid game. Options: InkGame, MurderMystery2, Doors, ALL")
        return
    
    channel_id = channel_map[game_lower]["id"]
    new_name = channel_map[game_lower]["name"]
    
    channel = ctx.guild.get_channel(channel_id)
    if channel:
        try:
            await channel.edit(name=new_name)
            embed = discord.Embed(description=f"**{game}** marked as down.", color=discord.Color.from_rgb(200, 70, 70))
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error changing channel name: {e}")
    else:
        await ctx.send("Channel not found.")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def undetected(ctx, game: str = None):
    if game is None:
        await ctx.send("**Usage:** `+undetected (InkGame / MurderMystery2 / Doors / ALL)`")
        return
    
    if game.lower() == "all":
        await undetected(ctx, "InkGame")
        await undetected(ctx, "MurderMystery2")
        await undetected(ctx, "Doors")
        return
    
    channel_map = {
        "inkgame": {"id": 1513692263010799716, "name": "Ink Game: 🟢"},
        "murder mystery 2": {"id": 1513692362931703818, "name": "Murder Mystery 2: 🟢"},
        "murder mystery2": {"id": 1513692362931703818, "name": "Murder Mystery 2: 🟢"},
        "murder": {"id": 1513692362931703818, "name": "Murder Mystery 2: 🟢"},
        "doors": {"id": 1513692441281036348, "name": "Doors: 🟢"}
    }
    
    game_lower = game.lower()
    if game_lower not in channel_map:
        await ctx.send("Invalid game. Options: InkGame, MurderMystery2, Doors, ALL")
        return
    
    channel_id = channel_map[game_lower]["id"]
    new_name = channel_map[game_lower]["name"]
    
    channel = ctx.guild.get_channel(channel_id)
    if channel:
        try:
            await channel.edit(name=new_name)
            embed = discord.Embed(description=f"**{game}** marked as undetected.", color=discord.Color.from_rgb(100, 200, 120))
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error changing channel name: {e}")
    else:
        await ctx.send("Channel not found.")

# clear command moved to hybrid +purge / +clear

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def hardban(ctx, member: discord.Member = None, *, reason="Not specified"):
    if member is None and ctx.message.reference:
        referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced.author
    if member is None:
        await ctx.send("**Usage:** `+hardban @user [reason]`")
        return
    
    can_punish_result, error_msg = can_punish(ctx.author, member)
    if not can_punish_result:
        embed = discord.Embed(description=error_msg, color=discord.Color.from_rgb(255, 200, 0))
        await ctx.send(embed=embed)
        return
    
    try:
        hardbanned_users.add(member.id)
        save_hardbanned()
        
        # Remove all roles
        for role in member.roles:
            if role != ctx.guild.default_role:
                try:
                    await member.remove_roles(role)
                except:
                    pass
        
        # Deny access to all channels
        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(member, view_channel=False, send_messages=False)
            except:
                pass
        
        # Ban the user
        try:
            await member.ban(reason=f"Hardban: {reason}")
        except:
            pass
        
        embed = discord.Embed(
            title="Hard Banned",
            description="You have been **hard-banned** from **HollyScriptX**",
            color=discord.Color.from_rgb(200, 70, 70)
        )
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Duration", value="Permanent", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=datetime.now().strftime('%m/%d/%Y %I:%M %p'))
        
        try:
            await member.send(embed=embed)
        except:
            pass
        
        embed_channel = discord.Embed(
            description=f"{member.mention} has been hard-banned.\n\n**Reason:** {reason}",
            color=discord.Color.from_rgb(200, 70, 70)
        )
        await ctx.send(embed=embed_channel)
        
        await log_staff_action(ctx, "hardban", f"Hardbanned {member.mention} for: {reason}")
        
    except discord.Forbidden:
        await ctx.send("I do not have permission to hard-ban this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error hard-banning user: {e}")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def unhardban(ctx, *, user_input):
    try:
        user_id = int(user_input)
        member = ctx.guild.get_member(user_id)
        if member is None:
            member = await bot.fetch_user(user_id)
    except:
        if ctx.message.reference:
            referenced = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            member = referenced.author
        else:
            try:
                member = await commands.UserConverter().convert(ctx, user_input)
            except:
                await ctx.send("**Usage:** `+unhardban <user_id/username>`")
                return
    
    try:
        if member.id in hardbanned_users:
            hardbanned_users.remove(member.id)
        
        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(member, overwrite=None)
            except:
                pass
        
        embed = discord.Embed(
            description=f"{member.mention} has been unhard-banned.",
            color=discord.Color.from_rgb(100, 200, 120)
        )
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I do not have permission to unhard-ban this user.")
    except discord.HTTPException as e:
        await ctx.send(f"Error unhard-banning user: {e}")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def verifyall(ctx):
    global verify_running
    
    if verify_running:
        await ctx.send("Verification process is already running.")
        return
    
    guild = ctx.guild
    old_role = guild.get_role(VERIFY_ROLE_ID)
    new_role = guild.get_role(VERIFIED_ROLE_ID)
    
    if not old_role:
        await ctx.send(f"Role with ID {VERIFY_ROLE_ID} not found.")
        return
    if not new_role:
        await ctx.send(f"Role with ID {VERIFIED_ROLE_ID} not found.")
        return
    
    members = [member for member in guild.members if old_role in member.roles]
    if not members:
        await ctx.send("No members found with the specified role.")
        return
    
    verify_running = True
    unverified_msg = await ctx.send(f"Unverified Users: {len(members)}")
    progress_msg = await ctx.send("Starting verification...")
    
    success = 0
    fail = 0
    total = len(members)
    
    for index, member in enumerate(members, 1):
        if not verify_running:
            break
        try:
            await member.remove_roles(old_role)
            await member.add_roles(new_role)
            success += 1
            await progress_msg.edit(content=f"Verified: {member.mention} ({index}/{total})")
        except:
            fail += 1
        await asyncio.sleep(0.5)
    
    verify_running = False
    await unverified_msg.edit(content=f"Unverified Users: {total - success - fail}")
    await progress_msg.edit(content=f"Verification completed. Success: {success}, Failed: {fail}")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def stopverify(ctx):
    global verify_running
    if not verify_running:
        await ctx.send("Verification process is not running.")
        return
    verify_running = False
    await ctx.send("Verification process stopped.")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def join(ctx):
    voice_channel = ctx.guild.get_channel(1513692263010799716)
    if not voice_channel:
        await ctx.send("Voice channel not found.")
        return
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
    await voice_channel.connect()
    await ctx.send("Connected to voice channel.")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def unjoin(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Left voice channel.")
    else:
        await ctx.send("Not in a voice channel.")

@bot.command()
async def saysomething(ctx, *, message: str):
    try:
        await ctx.message.delete()
    except:
        pass
    
    channel = bot.get_channel(1513695339167617084)
    if channel:
        await channel.send(message)

@bot.command()
async def typeinchannel(ctx):
    global banned_count
    channel = bot.get_channel(1518832499122507786)
    if channel:
        embed = discord.Embed(
            description="**DON'T SEND ANY MESSAGES IN THIS CHANNEL**\n\nThis channel is only used to catch spam bots and hacked accounts. Sending anything here will result in an immediate ban from HollyScriptX.\n\n**Banned users:** " + str(banned_count),
            color=discord.Color.from_rgb(240, 240, 240)
        )
        await channel.send(embed=embed)
        await ctx.send("Message sent to the channel.", delete_after=3)

@bot.command()
async def sendverifyshit(ctx):
    global verify_message_id, verify_channel_id
    try:
        await ctx.message.delete()
    except:
        pass
    
    channel = bot.get_channel(VERIFY_MESSAGE_CHANNEL_ID)
    if not channel:
        await ctx.send("Verify channel not found.", delete_after=3)
        return
    
    embed = discord.Embed(
        description="**HollyScriptX**\nClick the reaction below to verify",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    
    message = await channel.send(embed=embed)
    await message.add_reaction("✅")
    
    verify_message_id = message.id
    verify_channel_id = channel.id
    
    await ctx.send("Verification message sent.", delete_after=3)

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def setstatus(ctx, status: str = None, *, game: str = None):
    if status is None:
        await ctx.send("**Usage:** `+setstatus (online/idle/dnd/invisible) [game]`")
        return
    
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible
    }
    
    if status.lower() not in status_map:
        await ctx.send("Invalid status. Use: online, idle, dnd, invisible")
        return
    
    activity = None
    if game:
        activity = discord.Game(name=game)
    
    await bot.change_presence(status=status_map[status.lower()], activity=activity)
    await ctx.send(f"Status changed to: {status}")

@bot.command()
@commands.has_role(ADMIN_ROLE_ID)
async def rules(ctx):
    channel = bot.get_channel(RULES_CHANNEL_ID)
    if not channel:
        await ctx.send("Rules channel not found.")
        return
    
    embed = discord.Embed(
        title="SERVER RULES",
        color=discord.Color.from_rgb(240, 240, 240)
    )
    
    rules_text = """1. Spam not allowed | **warn**
2. Scam in any form (like scam images and other) | **warn**
3. Criticize **OUR** scripts **(except for some bugs)** | If the critize is not severe, punishment - **warn**
4. Sending malicious files not allowed | **warn**
5. Alts accounts on discord server not allowed | **permanent ban**
6. Sexual gifs, images or videos not allowed | **warn**
7. Self promoting and advertising is strictly forbidden unless you have permission by a server admin. If u dont have permission and still advertise or promote something u **will be warned**
8. Not write suggestions for other games that we dont support, we have a new game channel. | **warn**
9. Dont talk about other scripts. **Result will be in a warn or ban.**
10. 1 Key, 1 computer. Key-sharing is strictly prohibited.
11. No "insiding" — any attempt to reverse engineer, or to help a developer of another product figure out how a feature works or test upon it, is strictly prohibited.
12. Purposefully putting out media to defame the product instead of submitting a bug-report / ticket is prohibited. Use the proper channels.

-# If you got banned for violate point 2 (u got hacked or smth) u can get unbanned through our support server but not guaranteed.
-# You can get unbanned only once, if u got banned in discord server twice = you gone.
-# if you got 3 warns - permanent ban (appealable in our support server)
-# if you talking in any other language but not English in general chat, you will be warned, we have non English channel.
-# If u have staff role like and you will punish users for no reason, u will be demoted immediately with no exception"""
    
    embed.description = rules_text
    await channel.send(embed=embed)
    await ctx.send(f"Rules sent to {channel.mention}", delete_after=3)

if __name__ == "__main__":
    if TOKEN is None:
        print("ERROR: DISCORD_TOKEN environment variable is not set!")
    else:
        bot.run(TOKEN)
