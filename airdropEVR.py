import os
import logging
from dotenv import load_dotenv
from openai import OpenAI
import discord
from discord.ext import commands

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize the OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Define the intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Specific channel IDs
ALLOWED_CHANNEL_IDS = [1261814430291722410]

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if message.channel.id not in ALLOWED_CHANNEL_IDS:
        return
    
    # Check if the bot is mentioned in the message
    if bot.user.mentioned_in(message):
        logging.info(f"Bot mentioned in allowed channel {message.channel.id}: {message.content}")
        
        try:
            # Remove the bot's mention from the message content
            clean_content = message.content.replace(f'<@{bot.user.id}>', '').strip()
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are Satori, the helpful AI assistant."},
                    {"role": "user", "content": clean_content}
                ]
            )
            response_text = response.choices[0].message.content.strip()
            logging.info(f"Generated response: {response_text[:50]}...")  # Log first 50 chars
            await message.channel.send(response_text)
        except Exception as e:
            logging.error(f"Error in OpenAI API call: {e}", exc_info=True)
            await message.channel.send("Sorry, I encountered an error while processing your request.")
    else:
        logging.info(f"Message in allowed channel, but bot not mentioned: {message.content}")
    
    await bot.process_commands(message)

@bot.event
async def on_error(event, *args, **kwargs):
    logging.error(f"Unhandled error in {event}", exc_info=True)

try:
    bot.run(os.getenv('DISCORD_TOKEN'))
except Exception as e:
    logging.critical(f"Failed to start the bot: {e}", exc_info=True)