import logging
import sqlite3
import random
import re
import asyncio
import os
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8834781488:AAFGY0h5QLvDd9rU_WiqeGfYsgpP5GEVq8Q"
ADMIN_IDS = [6691026525, 8128047950]
CHANNEL_ID = -1003993806005

LINK, PRIZE, TASK, NOTICE, CONFIRM = range(5)

def get_db_connection():
    conn = sqlite3.connect('giveaway.db', timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS giveaways (
            giveaway_id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            chat_id INTEGER,
            prize TEXT,
            task TEXT,
            link TEXT,
            notice TEXT,
            status TEXT DEFAULT 'active',
            main_post_id INTEGER,
            counter_post_id INTEGER,
            winner_id INTEGER,
            winner_username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            giveaway_id INTEGER,
            user_id INTEGER,
            username TEXT,
            proof_message_id INTEGER,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (giveaway_id, user_id)
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update) or update.effective_chat.type != "private":
        await update.message.reply_text("❌ You are not authorized.")
        return
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🎁 Create Giveaway", callback_data="panel_create")],
        [InlineKeyboardButton("📊 Statistics", callback_data="panel_stats")],
        [InlineKeyboardButton("🎯 Draw Winner", callback_data="panel_draw")],
        [InlineKeyboardButton("🔍 Test Channel", callback_data="test_channel")],
        [InlineKeyboardButton("❌ Cancel", callback_data="panel_cancel")]
    ]
    await update.message.reply_text(
        "👋 Welcome to Giveaway Bot!\n\n📌 Channel: @SabbirGA\nSelect an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def start_creation_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text("🔗 Step 1/4: Send the Giveaway Link:")
    return LINK

async def reg_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ga_link'] = update.message.text.strip()
    await update.message.reply_text("💰 Step 2/4: Enter Prize Amount:")
    return PRIZE

async def reg_prize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ga_prize'] = update.message.text.strip()
    await update.message.reply_text("🎖️ Step 3/4: Enter Tasks:")
    return TASK

async def reg_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ga_task'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("⏩ Skip Notice", callback_data="skip_notice")]]
    await update.message.reply_text(
        "📢 Step 4/4 (Optional): Send notice or skip.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return NOTICE

def compile_main_post(user_data):
    link = user_data.get('ga_link', '')
    prize = user_data.get('ga_prize', '')
    task = user_data.get('ga_task', '')
    notice = user_data.get('ga_notice', '')
    main_post = (
        f"🎁 **{prize} | FAST GIVEAWAY** 🦋\n\n"
        f"**📋 Complete these tasks:**\n"
        f"— {task}\n"
        f"{link}\n\n"
        f"**📸 How to Enter:**\n"
        f"1️⃣ Complete all tasks\n"
        f"2️⃣ Click 'Submit Proof' below\n"
        f"3️⃣ Send your proof screenshot\n\n"
    )
    if notice:
        main_post += f"‼️ *{notice}* ‼️\n\n"
    main_post += "Do the task & click participate so your entries count 😍"
    return main_post

def compile_counter_post(giveaway_id, prize):
    return f"Entries: 0\n\nClick below to participate! 👇"

async def handle_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ga_notice'] = update.message.text.strip()
    preview_text = compile_main_post(context.user_data)
    context.user_data['ga_main_post'] = preview_text
    keyboard = [
        [InlineKeyboardButton("🚀 Publish Both Posts", callback_data="publish_now")],
        [InlineKeyboardButton("❌ Cancel", callback_data="panel_cancel")]
    ]
    msg = f"👀 Main Post Preview:\n\n{'─' * 20}\n{preview_text}\n{'─' * 20}\n\nClick 'Publish Both Posts' to proceed."
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CONFIRM

async def skip_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['ga_notice'] = ""
    preview_text = compile_main_post(context.user_data)
    context.user_data['ga_main_post'] = preview_text
    keyboard = [
        [InlineKeyboardButton("🚀 Publish Both Posts", callback_data="publish_now")],
        [InlineKeyboardButton("❌ Cancel", callback_data="panel_cancel")]
    ]
    msg = f"👀 Main Post Preview:\n\n{'─' * 20}\n{preview_text}\n{'─' * 20}\n\nClick 'Publish Both Posts' to proceed."
    await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CONFIRM

async def publish_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prize_val = context.user_data.get('ga_prize', 'Giveaway')
    main_post_text = context.user_data.get('ga_main_post', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO giveaways (prize, task, link, notice) VALUES (?, ?, ?, ?)",
            (prize_val, context.user_data.get('ga_task', ''), context.user_data.get('ga_link', ''), context.user_data.get('ga_notice', '')))
        giveaway_id = cursor.lastrowid
        conn.commit()
        main_keyboard = [[InlineKeyboardButton("📸 Submit Proof", callback_data=f"submit_proof_{giveaway_id}")]]
        main_msg = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=main_post_text,
            reply_markup=InlineKeyboardMarkup(main_keyboard),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        counter_text = compile_counter_post(giveaway_id, prize_val)
        counter_keyboard = [[InlineKeyboardButton("🎉 Participate! 🎉", callback_data=f"join_{giveaway_id}")]]
        counter_msg = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=counter_text,
            reply_markup=InlineKeyboardMarkup(counter_keyboard),
            parse_mode="Markdown"
        )
        cursor.execute("UPDATE giveaways SET message_id = ?, chat_id = ?, main_post_id = ?, counter_post_id = ? WHERE giveaway_id = ?",
            (main_msg.message_id, main_msg.chat_id, main_msg.message_id, counter_msg.message_id, giveaway_id))
        conn.commit()
        success_msg = f"✅ Success! Both posts published!\n\n🆔 Giveaway ID: `{giveaway_id}`\n📝 Main Post: https://t.me/SabbirGA/{main_msg.message_id}\n📊 Counter Post: https://t.me/SabbirGA/{counter_msg.message_id}"
        await query.message.reply_text(success_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error publishing giveaway: {e}")
        await query.message.reply_text(f"❌ Failed to publish: {str(e)}")
    finally:
        conn.close()
        context.user_data.clear()
    return ConversationHandler.END

async def update_participant_counter(chat_id, message_id, giveaway_id, context):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as count FROM participants WHERE giveaway_id = ?", (giveaway_id,))
        count_row = cursor.fetchone()
        participant_count = count_row['count'] if count_row else 0
        new_text = f"Entries: {participant_count}\n\nClick below to participate! 👇"
        keyboard = [[InlineKeyboardButton("🎉 Participate! 🎉", callback_data=f"join_{giveaway_id}")]]
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=new_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to update participant counter: {e}")
        return False
    finally:
        conn.close()

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data.startswith("join_"):
        giveaway_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
        username = query.from_user.username or query.from_user.first_name
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT status, counter_post_id, chat_id FROM giveaways WHERE giveaway_id = ?", (giveaway_id,))
            ga = cursor.fetchone()
            if not ga or ga['status'] != 'active':
                await query.answer("❌ This giveaway has ended!", show_alert=True)
                return
            cursor.execute("SELECT * FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
            existing = cursor.fetchone()
            if existing:
                await query.answer("⚠️ You've already participated!", show_alert=True)
                return
            cursor.execute("INSERT INTO participants (giveaway_id, user_id, username) VALUES (?, ?, ?)", 
                (giveaway_id, user_id, username))
            conn.commit()
            await query.answer("✅ Successfully entered!", show_alert=False)
            await update_participant_counter(ga['chat_id'], ga['counter_post_id'], giveaway_id, context)
        except Exception as e:
            logger.error(f"Error adding participant: {e}")
            await query.answer("❌ Error joining", show_alert=True)
        finally:
            conn.close()
    elif query.data.startswith("submit_proof_"):
        giveaway_id = int(query.data.split("_")[2])
        await query.answer("📸 Please send your proof screenshot as a photo message.", show_alert=True)
        context.user_data['submitting_proof'] = giveaway_id

async def handle_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'submitting_proof' not in context.user_data:
        return
    giveaway_id = context.user_data['submitting_proof']
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    if not update.message.photo:
        await update.message.reply_text("❌ Please send a photo as proof.")
        return
    photo = update.message.photo[-1]
    file_id = photo.file_id
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
        participant = cursor.fetchone()
        if not participant:
            await update.message.reply_text("❌ You haven't participated yet! Click 'Participate' first.")
            return
        cursor.execute("UPDATE participants SET proof_message_id = ? WHERE giveaway_id = ? AND user_id = ?",
            (file_id, giveaway_id, user_id))
        conn.commit()
        await update.message.reply_text(f"✅ Proof Submitted!\n\n📸 Your proof has been submitted for Giveaway #{giveaway_id}.")
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📸 New Proof Submission!\n\n👤 User: @{username}\n🆔 Giveaway: #{giveaway_id}",
                    parse_mode="Markdown"
                )
                await update.message.forward(chat_id=admin_id)
            except:
                pass
        context.user_data.pop('submitting_proof', None)
    except Exception as e:
        logger.error(f"Error handling proof: {e}")
        await update.message.reply_text("❌ Error submitting proof.")
    finally:
        conn.close()

async def draw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT g.giveaway_id, g.prize, COUNT(p.user_id) as entry_count FROM giveaways g LEFT JOIN participants p ON g.giveaway_id = p.giveaway_id WHERE g.status = 'active' GROUP BY g.giveaway_id ORDER BY g.giveaway_id DESC")
        giveaways = cursor.fetchall()
        if not giveaways:
            await query.message.reply_text("❌ No active giveaways found.")
            return
        keyboard = []
        for g in giveaways:
            if g['entry_count'] > 0:
                keyboard.append([InlineKeyboardButton(f"🎯 #{g['giveaway_id']} - {g['prize']} ({g['entry_count']} entries)", callback_data=f"draw_now_{g['giveaway_id']}")])
        if not keyboard:
            await query.message.reply_text("❌ No participants in any active giveaway.")
            return
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="panel_back")])
        await query.message.reply_text("🎯 Select a giveaway to draw winner:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in draw menu: {e}")
        await query.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        conn.close()

async def draw_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giveaway_id = int(query.data.split("_")[2])
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM giveaways WHERE giveaway_id = ? AND status = 'active'", (giveaway_id,))
        giveaway = cursor.fetchone()
        if not giveaway:
            await query.message.reply_text("❌ Giveaway not found or already ended.")
            return
        cursor.execute("SELECT user_id, username FROM participants WHERE giveaway_id = ?", (giveaway_id,))
        participants = cursor.fetchall()
        if not participants:
            await query.message.reply_text("❌ No participants in this giveaway!")
            return
        winner = random.choice(participants)
        cursor.execute("UPDATE giveaways SET status = 'ended', winner_id = ?, winner_username = ? WHERE giveaway_id = ?",
            (winner['user_id'], winner['username'] or str(winner['user_id']), giveaway_id))
        conn.commit()
        winner_mention = f"[{winner['username']}](tg://user?id={winner['user_id']})" if winner['username'] else f"User {winner['user_id']}"
        announce_text = (
            f"🎉 GIVEAWAY WINNER ANNOUNCEMENT! 🎉\n\n"
            f"🏆 Giveaway #{giveaway_id}\n"
            f"🎁 Prize: {giveaway['prize']}\n"
            f"👥 Total Participants: {len(participants)}\n\n"
            f"🎊 Congratulations!\n{winner_mention}\n\nPlease contact @SABBIRXDM to claim your prize! 🎁"
        )
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=announce_text, parse_mode="Markdown")
            await query.message.reply_text(f"✅ Winner Drawn!\n\n🏆 Giveaway #{giveaway_id}\n👤 Winner: {winner_mention}", parse_mode="Markdown")
        except Exception as e:
            await query.message.reply_text(f"❌ Failed to announce: {str(e)}")
    except Exception as e:
        logger.error(f"Error drawing winner: {e}")
        await query.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        conn.close()

async def view_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT g.giveaway_id, g.prize, g.status, COUNT(p.user_id) as entry_count, COUNT(CASE WHEN p.proof_message_id IS NOT NULL THEN 1 END) as proof_count, g.winner_id, g.winner_username FROM giveaways g LEFT JOIN participants p ON g.giveaway_id = p.giveaway_id GROUP BY g.giveaway_id ORDER BY g.giveaway_id DESC LIMIT 10")
        rows = cursor.fetchall()
        if not rows:
            await query.message.reply_text("📭 No giveaways found.")
            return
        stats_text = "📊 Giveaway Statistics\n\n"
        for r in rows:
            status_icon = "🟢" if r['status'] == 'active' else "🔴"
            winner_text = f"🏆 Winner: {r['winner_username'] or 'Not Drawn'}" if r['winner_id'] else "🎯 Not Drawn"
            stats_text += f"🆔 `{r['giveaway_id']}` | {r['prize']}\nStatus: {status_icon} `{r['status']}`\n👥 Entries: **{r['entry_count']}** | 📸 Proofs: **{r['proof_count']}**\n{winner_text}\n\n"
        keyboard = [
            [InlineKeyboardButton("🎯 Draw Winner", callback_data="panel_draw")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="panel_back")]
        ]
        await query.message.reply_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error viewing statistics: {e}")
        await query.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        conn.close()

async def test_channel_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        test_msg = await context.bot.send_message(chat_id=CHANNEL_ID, text="✅ Bot Connection Test!\n\nChannel connection successful!", parse_mode="Markdown")
        await query.message.reply_text(f"✅ Connection Successful!\n\n📌 Bot can send messages to @SabbirGA")
        await asyncio.sleep(5)
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=test_msg.message_id)
    except Exception as e:
        await query.message.reply_text(f"❌ Connection Failed!\n\nError: `{str(e)}`")

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🎁 Create Giveaway", callback_data="panel_create")],
        [InlineKeyboardButton("📊 Statistics", callback_data="panel_stats")],
        [InlineKeyboardButton("🎯 Draw Winner", callback_data="panel_draw")],
        [InlineKeyboardButton("🔍 Test Channel", callback_data="test_channel")],
        [InlineKeyboardButton("❌ Cancel", callback_data="panel_cancel")]
    ]
    await query.message.edit_text(
        "👋 Welcome to Giveaway Bot!\n\n📌 Channel: @SabbirGA\nSelect an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text("❌ Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

async def main():
    """Start the bot with proper async handling for python-telegram-bot v20+"""
    try:
        init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"Database init error: {e}")
        return
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("✅ Application built")
    except Exception as e:
        logger.error(f"Application build error: {e}")
        return

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_creation_flow, pattern="^panel_create$")],
        states={
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_link)],
            PRIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_prize)],
            TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_task)],
            NOTICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_notice), CallbackQueryHandler(skip_notice, pattern="^skip_notice$")],
            CONFIRM: [CallbackQueryHandler(publish_giveaway, pattern="^publish_now$")]
        },
        fallbacks=[CallbackQueryHandler(cancel_flow, pattern="^panel_cancel$"), CommandHandler("start", start)]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(view_statistics, pattern="^panel_stats$"))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern="^panel_back$"))
    application.add_handler(CallbackQueryHandler(cancel_flow, pattern="^panel_cancel$"))
    application.add_handler(CallbackQueryHandler(button_click, pattern="^(join_|submit_proof_)"))
    application.add_handler(CallbackQueryHandler(draw_menu, pattern="^panel_draw$"))
    application.add_handler(CallbackQueryHandler(draw_winner, pattern="^draw_now_"))
    application.add_handler(CallbackQueryHandler(test_channel_connection, pattern="^test_channel$"))
    application.add_handler(MessageHandler(filters.PHOTO, handle_proof))
    
    logger.info("=" * 50)
    logger.info("✅ Giveaway Bot is running!")
    logger.info("=" * 50)
    logger.info(f"👥 Admin IDs: {ADMIN_IDS}")
    logger.info(f"📢 Channel: @SabbirGA")
    logger.info("=" * 50)
    
    async with application:
        await application.start()
        await application.updater.start_polling()
        logger.info("Bot is polling...")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        finally:
            await application.updater.stop()
            await application.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped")
    except Exception as e:
        print(f"Error: {e}")
        logger.exception("Fatal error occurred")
